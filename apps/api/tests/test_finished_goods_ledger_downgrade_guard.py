"""CMP-016 downgrade-guard proof tests.

Unlike CMP-015's own guard (which blocks on the mere existence of any
packing history), CMP-016's guard follows CMP-014's own model: every
`packing_receipt` is a deterministic, reconstructible projection of
already-immutable CMP-015 data, so downgrade is allowed even while
finished-goods lots/packing events exist, as long as every receipt is
exactly reconstructible. The guard blocks on genuinely unreconstructible
state: an unknown `entry_kind`, a missing/field-mismatched receipt, an
orphaned receipt (no matching lot/event), or more than one receipt for one
lot/event — none reachable through normal packing operation, so every
scenario below is deliberately constructed via direct SQL with
`session_replication_role = replica` (and, where a same-row CHECK would
otherwise block the state outright, a temporary constraint drop), guarded
by the same `cmp_test` + explicit `DEFAULT` restore discipline used
throughout this test suite. Each of the 16 malformed states CMP-016
hardening identified is proven independently — none are collapsed into one
generic mismatch test."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.services import packing_service
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, require_cmp_test

API_ROOT = Path(__file__).resolve().parent.parent
# Specific, historically fixed migration under test — the target this test
# downgrades to — is safe to hardcode; "current head" is not.
_PRE_CMP016_REVISION = "a91f4c7b2e58"


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_head_revision(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_current_head()


def _now():
    return datetime.now(timezone.utc)


def _assert_at_head(test_engine) -> None:
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    expected_head = _resolve_head_revision(_cfg())
    assert current == expected_head, "a blocked downgrade must leave the database at Alembic head"


def _pack_one(scenario, db) -> uuid.UUID:
    event = packing_service.record_packing(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), pack_specification_version_id=scenario["pack_specification_version_id"],
        effective_time=_now(),
        finished_goods_lot_code=f"FG-{scenario['suffix']}", package_count=6,
        packed_output_weight_kg=Decimal("2.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("2.000"), "consumed_whole_unit_count": None, "note": None}],
    )
    detail = packing_service.get_packing_event(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=event.id
    )
    return detail.finished_goods_lot.id


def _pack_two(scenario, db) -> dict:
    """Packs both lot_a and lot_b into two independent finished-goods lots.
    Requires `build_committed_scenario(..., lot_a_count=None, lot_b_count=None)`
    — both source lots must be count-free for a NULL `consumed_whole_unit_count`
    to be valid under CMP-015's count-mode compatibility rule."""
    event_a = packing_service.record_packing(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), pack_specification_version_id=scenario["pack_specification_version_id"],
        effective_time=_now(),
        finished_goods_lot_code=f"FGA-{scenario['suffix']}", package_count=6,
        packed_output_weight_kg=Decimal("2.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("2.000"), "consumed_whole_unit_count": None, "note": None}],
    )
    event_b = packing_service.record_packing(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), pack_specification_version_id=scenario["pack_specification_version_id"],
        effective_time=_now(),
        finished_goods_lot_code=f"FGB-{scenario['suffix']}", package_count=4,
        packed_output_weight_kg=Decimal("1.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"graded_produce_lot_id": scenario["gpl_b_id"], "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": None, "note": None}],
    )
    lot_a = packing_service.get_packing_event(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=event_a.id
    ).finished_goods_lot.id
    lot_b = packing_service.get_packing_event(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=event_b.id
    ).finished_goods_lot.id
    return {"lot_a": lot_a, "event_a": event_a.id, "lot_b": lot_b, "event_b": event_b.id}


def _snapshot(test_engine, fg_lot_id) -> dict:
    with test_engine.connect() as c:
        return dict(
            c.execute(
                text(
                    "SELECT tenant_id, farm_id, packing_event_id, weight_delta_kg, package_count_delta, "
                    "effective_time, recorded_time, actor_user_id "
                    "FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = :lid"
                ),
                {"lid": fg_lot_id},
            ).mappings().one()
        )


def _replica_update(test_engine, fg_lot_id, column: str, value) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(
        text(f"UPDATE finished_goods_ledger_entries SET {column} = :val WHERE finished_goods_lot_id = :lid"),
        {"val": value, "lid": fg_lot_id},
    )
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()


@pytest.mark.integration
def test_clean_downgrade_with_wellformed_history_reupgrade_reproduces_identical_receipt(test_engine, alembic_head_restore) -> None:
    """Pre-POSTHARVEST-OPS-001E, this proved: downgrade succeeds even while
    finished_goods_lots/packing_events data exists, as long as the receipt
    is well-formed -- the CMP-014 reconstructible-projection model, not
    CMP-015's unconditional block.

    POSTHARVEST-OPS-001E: any real packing_events row (GPL-input Packing
    is now independent, never-reconstructible operational history) now
    unconditionally blocks downgrade past 001E -- in d8f4a1c92b57, which
    sits directly above CMP-016 in the chain -- before the cascade could
    ever reach CMP-016's own reconstructible-projection check. This test
    now proves that outer guard fires even for a well-formed receipt;
    CMP-016's own reconstruction logic remains independently in place in
    the migration itself (and its OWN malformed-state guards below remain
    independently correct) for a downgrade that starts already below
    001E."""
    require_cmp_test(test_engine)
    # CARRIER-CONFIG-001A: this guard is about CMP-016 ledger
    # reconstructibility, unrelated to carrier type -- grow_bag keeps the
    # scenario free of a carrier_specifications row, which would otherwise
    # unconditionally block via e5b8c3a72f04's own, earlier-in-chain guard
    # before this guard is ever reached.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    _pack_one(scenario, session)
    session.commit()
    session.close()
    conn.close()

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP016_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- state 1: finished-goods lot missing its receipt ------------------------

@pytest.mark.integration
def test_downgrade_blocked_by_missing_receipt(test_engine, alembic_head_restore) -> None:
    """A finished-goods lot whose receipt was hard-deleted (bypassing the
    append-only trigger via `replica`) must block downgrade — the lot ->
    receipt LEFT JOIN finds no matching row (`r.id IS NULL`)."""
    # CARRIER-CONFIG-001A: this guard is about CMP-016 ledger
    # reconstructibility, unrelated to carrier type -- grow_bag keeps the
    # scenario free of a carrier_specifications row, which would otherwise
    # unconditionally block via e5b8c3a72f04's own, earlier-in-chain guard
    # before this guard is ever reached.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id = _pack_one(scenario, session)
    session.commit()
    session.close()
    conn.close()
    require_cmp_test(test_engine)

    bypass_conn = test_engine.connect()
    trans = bypass_conn.begin()
    bypass_conn.execute(text("SET session_replication_role = replica"))
    bypass_conn.execute(
        text("DELETE FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = :lid"), {"lid": fg_lot_id}
    )
    bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    bypass_conn.close()

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP016_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- state 2: extra receipt not corresponding to a valid lot ----------------

@pytest.mark.integration
def test_downgrade_blocked_by_extra_receipt_without_valid_lot(test_engine, alembic_head_restore) -> None:
    """A receipt-shaped row whose `finished_goods_lot_id` matches no real
    finished-goods lot at all is invisible to the lot-driven LEFT JOIN
    (there is no lot row to walk it from) and can only be caught by the
    dedicated receipt -> lot orphan check added during CMP-016 hardening."""
    # CARRIER-CONFIG-001A: this guard is about CMP-016 ledger
    # reconstructibility, unrelated to carrier type -- grow_bag keeps the
    # scenario free of a carrier_specifications row, which would otherwise
    # unconditionally block via e5b8c3a72f04's own, earlier-in-chain guard
    # before this guard is ever reached.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id = _pack_one(scenario, session)
    session.commit()
    real = session.execute(
        text(
            "SELECT actor_user_id, effective_time, recorded_time "
            "FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = :lid"
        ),
        {"lid": fg_lot_id},
    ).mappings().one()
    session.close()
    conn.close()
    require_cmp_test(test_engine)

    # Both id/finished_goods_lot_id and packing_event_id are fresh, unlinked
    # UUIDs — a genuinely orphaned row, not merely a duplicate of the real
    # receipt's own event.
    bogus_lot_id = uuid.uuid4()
    bogus_event_id = uuid.uuid4()
    bypass_conn = test_engine.connect()
    trans = bypass_conn.begin()
    bypass_conn.execute(text("SET session_replication_role = replica"))
    bypass_conn.execute(
        text(
            "INSERT INTO finished_goods_ledger_entries "
            "(id, tenant_id, farm_id, finished_goods_lot_id, packing_event_id, entry_kind, "
            "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note) "
            "VALUES (:id, :tid, :fid, :id, :eid, 'packing_receipt', 1.000, 1, :eff, :rec, :uid, NULL)"
        ),
        {
            "id": bogus_lot_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
            "eid": bogus_event_id, "eff": real["effective_time"], "rec": real["recorded_time"],
            "uid": real["actor_user_id"],
        },
    )
    bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    bypass_conn.close()

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP016_REVISION)
        _assert_at_head(test_engine)
    finally:
        # tenant_id/farm_id are the real scenario's own, so cleanup_scenario's
        # tenant-scoped delete removes this bogus row too.
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- state 3: orphan receipt referencing a missing packing event ------------

@pytest.mark.integration
def test_downgrade_blocked_by_orphan_receipt_missing_packing_event(test_engine, alembic_head_restore) -> None:
    """A receipt whose `finished_goods_lot_id` names a real lot but whose
    `packing_event_id` does not match that lot's own event is an orphan on
    the event side. It is still visible to the lot-driven LEFT JOIN (its
    finished_goods_lot_id resolves), so it is caught there as a packing-
    event field mismatch — proving the same real-world state (a receipt
    that cannot be tied back to a genuine packing event) is blocked
    regardless of which specific guard clause fires."""
    # CARRIER-CONFIG-001A: see comment on the other build_committed_scenario
    # calls in this file -- grow_bag avoids masking this guard.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, lot_b_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    ids = _pack_two(scenario, session)
    session.commit()
    session.close()
    conn.close()
    require_cmp_test(test_engine)

    bogus_event_id = uuid.uuid4()
    _replica_update(test_engine, ids["lot_b"], "packing_event_id", bogus_event_id)

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP016_REVISION)
        _assert_at_head(test_engine)
    finally:
        _replica_update(test_engine, ids["lot_b"], "packing_event_id", ids["event_b"])
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- state 4: duplicate receipt for one lot ----------------------------------

@pytest.mark.integration
def test_downgrade_blocked_by_duplicate_receipt_for_lot(test_engine, alembic_head_restore) -> None:
    """Two receipt rows for the same finished-goods lot is unreachable
    through normal operation: the deterministic-id CHECK ties a receipt's
    id to its lot's id, so a genuine duplicate collides with the primary
    key first, and the partial unique index on finished_goods_lot_id is a
    second, independent barrier. Both are dropped here to construct a
    literal duplicate (byte-identical to the original, so the field-
    mismatch predicate stays silent), isolating the dedicated per-lot
    cardinality check added during CMP-016 hardening."""
    # CARRIER-CONFIG-001A: this guard is about CMP-016 ledger
    # reconstructibility, unrelated to carrier type -- grow_bag keeps the
    # scenario free of a carrier_specifications row, which would otherwise
    # unconditionally block via e5b8c3a72f04's own, earlier-in-chain guard
    # before this guard is ever reached.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id = _pack_one(scenario, session)
    session.commit()
    session.close()
    conn.close()
    require_cmp_test(test_engine)

    bypass_conn = test_engine.connect()
    trans = bypass_conn.begin()
    bypass_conn.execute(text("SET session_replication_role = replica"))
    bypass_conn.execute(text("ALTER TABLE finished_goods_ledger_entries DROP CONSTRAINT finished_goods_ledger_entries_pkey"))
    bypass_conn.execute(text("ALTER TABLE finished_goods_ledger_entries DROP CONSTRAINT uq_finished_goods_ledger_entries_tenant_farm_id"))
    bypass_conn.execute(text("DROP INDEX ux_finished_goods_ledger_entries_lot_packing_receipt"))
    bypass_conn.execute(text("DROP INDEX ux_finished_goods_ledger_entries_event_packing_receipt"))
    bypass_conn.execute(
        text(
            "INSERT INTO finished_goods_ledger_entries "
            "(id, tenant_id, farm_id, finished_goods_lot_id, packing_event_id, entry_kind, "
            "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note) "
            "SELECT id, tenant_id, farm_id, finished_goods_lot_id, packing_event_id, entry_kind, "
            "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note "
            "FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = :lid"
        ),
        {"lid": fg_lot_id},
    )
    bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    bypass_conn.close()

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP016_REVISION)
        _assert_at_head(test_engine)
    finally:
        restore_conn = test_engine.connect()
        restore_trans = restore_conn.begin()
        try:
            restore_conn.execute(text("SET session_replication_role = replica"))
            # Both surviving rows are byte-identical; ctid disambiguates
            # which physical copy to drop before uniqueness is restored.
            restore_conn.execute(
                text(
                    "DELETE FROM finished_goods_ledger_entries WHERE ctid IN ("
                    "  SELECT ctid FROM finished_goods_ledger_entries "
                    "  WHERE finished_goods_lot_id = :lid ORDER BY ctid LIMIT 1"
                    ")"
                ),
                {"lid": fg_lot_id},
            )
            restore_conn.execute(text("SET session_replication_role = DEFAULT"))
            restore_conn.execute(
                text("ALTER TABLE finished_goods_ledger_entries ADD CONSTRAINT finished_goods_ledger_entries_pkey PRIMARY KEY (id)")
            )
            restore_conn.execute(
                text(
                    "ALTER TABLE finished_goods_ledger_entries ADD CONSTRAINT "
                    "uq_finished_goods_ledger_entries_tenant_farm_id UNIQUE (tenant_id, farm_id, id)"
                )
            )
            restore_conn.execute(
                text(
                    "CREATE UNIQUE INDEX ux_finished_goods_ledger_entries_lot_packing_receipt "
                    "ON finished_goods_ledger_entries (finished_goods_lot_id) WHERE entry_kind = 'packing_receipt'"
                )
            )
            restore_conn.execute(
                text(
                    "CREATE UNIQUE INDEX ux_finished_goods_ledger_entries_event_packing_receipt "
                    "ON finished_goods_ledger_entries (packing_event_id) WHERE entry_kind = 'packing_receipt'"
                )
            )
        except Exception:
            restore_trans.rollback()
            raise
        else:
            restore_trans.commit()
        finally:
            restore_conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- state 5: duplicate receipt for one packing event ------------------------

@pytest.mark.integration
def test_downgrade_blocked_by_duplicate_receipt_for_packing_event(test_engine, alembic_head_restore) -> None:
    """Two distinct lots' receipts sharing one packing_event_id (after
    dropping the event-scoped partial unique index) is inherently also a
    packing-event field mismatch for whichever lot does not really own
    that event — proving the same real-world state (one event, two
    receipts) is blocked, alongside the dedicated per-event cardinality
    check added during CMP-016 hardening."""
    # CARRIER-CONFIG-001A: see comment on the other build_committed_scenario
    # calls in this file -- grow_bag avoids masking this guard.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, lot_b_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    ids = _pack_two(scenario, session)
    session.commit()
    session.close()
    conn.close()
    require_cmp_test(test_engine)

    bypass_conn = test_engine.connect()
    trans = bypass_conn.begin()
    bypass_conn.execute(text("SET session_replication_role = replica"))
    bypass_conn.execute(text("DROP INDEX ux_finished_goods_ledger_entries_event_packing_receipt"))
    bypass_conn.execute(
        text("UPDATE finished_goods_ledger_entries SET packing_event_id = :eid WHERE finished_goods_lot_id = :lid"),
        {"eid": ids["event_a"], "lid": ids["lot_b"]},
    )
    bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    bypass_conn.close()

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP016_REVISION)
        _assert_at_head(test_engine)
    finally:
        restore_conn = test_engine.connect()
        restore_trans = restore_conn.begin()
        try:
            restore_conn.execute(text("SET session_replication_role = replica"))
            restore_conn.execute(
                text("UPDATE finished_goods_ledger_entries SET packing_event_id = :eid WHERE finished_goods_lot_id = :lid"),
                {"eid": ids["event_b"], "lid": ids["lot_b"]},
            )
            restore_conn.execute(text("SET session_replication_role = DEFAULT"))
            restore_conn.execute(
                text(
                    "CREATE UNIQUE INDEX ux_finished_goods_ledger_entries_event_packing_receipt "
                    "ON finished_goods_ledger_entries (packing_event_id) WHERE entry_kind = 'packing_receipt'"
                )
            )
        except Exception:
            restore_trans.rollback()
            raise
        else:
            restore_trans.commit()
        finally:
            restore_conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- state 6: deterministic ID mismatch --------------------------------------

@pytest.mark.integration
def test_downgrade_blocked_by_deterministic_id_mismatch(test_engine, alembic_head_restore) -> None:
    """`id` diverging from `finished_goods_lot_id` is unreachable without
    dropping the deterministic-id CHECK first — the same "drop CHECK,
    mutate, restore" discipline the unknown-entry-kind test below uses."""
    # CARRIER-CONFIG-001A: this guard is about CMP-016 ledger
    # reconstructibility, unrelated to carrier type -- grow_bag keeps the
    # scenario free of a carrier_specifications row, which would otherwise
    # unconditionally block via e5b8c3a72f04's own, earlier-in-chain guard
    # before this guard is ever reached.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id = _pack_one(scenario, session)
    session.commit()
    session.close()
    conn.close()
    require_cmp_test(test_engine)

    bogus_id = uuid.uuid4()
    bypass_conn = test_engine.connect()
    trans = bypass_conn.begin()
    bypass_conn.execute(text("SET session_replication_role = replica"))
    bypass_conn.execute(
        text("ALTER TABLE finished_goods_ledger_entries DROP CONSTRAINT ck_finished_goods_ledger_entries_deterministic_id")
    )
    bypass_conn.execute(
        text("UPDATE finished_goods_ledger_entries SET id = :bid WHERE finished_goods_lot_id = :lid"),
        {"bid": bogus_id, "lid": fg_lot_id},
    )
    bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    bypass_conn.close()

    try:
        # CMP-017 now sits above CMP-016 in the migration chain and, as
        # part of its own downgrade, validates every remaining ledger row
        # against the exact CMP-016 shape being restored (including
        # `id = finished_goods_lot_id`) before CMP-016's own downgrade()
        # ever runs — so its guard fires first, making CMP-016's own
        # "does not exactly reconstruct" message unreachable via a single
        # multi-step downgrade from head for this specific malformed state.
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP016_REVISION)
        _assert_at_head(test_engine)
    finally:
        restore_conn = test_engine.connect()
        restore_trans = restore_conn.begin()
        try:
            restore_conn.execute(text("SET session_replication_role = replica"))
            restore_conn.execute(
                text("UPDATE finished_goods_ledger_entries SET id = :lid WHERE id = :bid"),
                {"lid": fg_lot_id, "bid": bogus_id},
            )
            restore_conn.execute(text("SET session_replication_role = DEFAULT"))
            restore_conn.execute(
                text(
                    "ALTER TABLE finished_goods_ledger_entries ADD CONSTRAINT "
                    "ck_finished_goods_ledger_entries_deterministic_id CHECK (id = finished_goods_lot_id)"
                )
            )
        except Exception:
            restore_trans.rollback()
            raise
        else:
            restore_trans.commit()
        finally:
            restore_conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- states 7-14: same-row field mismatches against lot/event ---------------

_SIMPLE_MISMATCH_CASES = [
    pytest.param("tenant_id", lambda snap: uuid.uuid4(), id="tenant_mismatch"),
    pytest.param("farm_id", lambda snap: uuid.uuid4(), id="farm_mismatch"),
    pytest.param("packing_event_id", lambda snap: uuid.uuid4(), id="packing_event_mismatch"),
    pytest.param("weight_delta_kg", lambda snap: Decimal("999.000"), id="weight_mismatch"),
    pytest.param("package_count_delta", lambda snap: 999999, id="package_count_mismatch"),
    pytest.param("effective_time", lambda snap: snap["effective_time"] - timedelta(days=1), id="effective_time_mismatch"),
    pytest.param("recorded_time", lambda snap: snap["recorded_time"] - timedelta(days=1), id="recorded_time_mismatch"),
    pytest.param("actor_user_id", lambda snap: uuid.uuid4(), id="actor_mismatch"),
]


@pytest.mark.integration
@pytest.mark.parametrize("column, mutate", _SIMPLE_MISMATCH_CASES)
def test_downgrade_blocked_by_field_mismatch(test_engine, column, mutate, alembic_head_restore) -> None:
    """States 7-14: tenant, farm, packing-event, weight, package-count,
    effective-time, recorded-time, and actor mismatches, each proven as an
    independently-run, independently-reported case (not one generic test)
    via pytest's own parametrize identity. None of these columns are
    guarded by a same-row CHECK, so a plain `replica`-bypassed UPDATE is
    enough to construct each state — no constraint needs dropping."""
    # CARRIER-CONFIG-001A: this guard is about CMP-016 ledger
    # reconstructibility, unrelated to carrier type -- grow_bag keeps the
    # scenario free of a carrier_specifications row, which would otherwise
    # unconditionally block via e5b8c3a72f04's own, earlier-in-chain guard
    # before this guard is ever reached.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id = _pack_one(scenario, session)
    session.commit()
    session.close()
    conn.close()
    require_cmp_test(test_engine)

    snap = _snapshot(test_engine, fg_lot_id)
    original_value = snap[column]
    new_value = mutate(snap)
    _replica_update(test_engine, fg_lot_id, column, new_value)

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP016_REVISION)
        _assert_at_head(test_engine)
    finally:
        _replica_update(test_engine, fg_lot_id, column, original_value)
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- state 15: non-null note -------------------------------------------------

@pytest.mark.integration
def test_downgrade_blocked_by_non_null_note(test_engine, alembic_head_restore) -> None:
    """`note` diverging from NULL is unreachable without dropping the
    note-null CHECK first."""
    # CARRIER-CONFIG-001A: this guard is about CMP-016 ledger
    # reconstructibility, unrelated to carrier type -- grow_bag keeps the
    # scenario free of a carrier_specifications row, which would otherwise
    # unconditionally block via e5b8c3a72f04's own, earlier-in-chain guard
    # before this guard is ever reached.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id = _pack_one(scenario, session)
    session.commit()
    session.close()
    conn.close()
    require_cmp_test(test_engine)

    bypass_conn = test_engine.connect()
    trans = bypass_conn.begin()
    bypass_conn.execute(text("SET session_replication_role = replica"))
    bypass_conn.execute(
        text("ALTER TABLE finished_goods_ledger_entries DROP CONSTRAINT ck_finished_goods_ledger_entries_note_null")
    )
    bypass_conn.execute(
        text("UPDATE finished_goods_ledger_entries SET note = 'not allowed' WHERE finished_goods_lot_id = :lid"),
        {"lid": fg_lot_id},
    )
    bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    bypass_conn.close()

    try:
        # See test_downgrade_blocked_by_deterministic_id_mismatch above:
        # CMP-017's own downgrade guard fires first now that it sits above
        # CMP-016, making CMP-016's own message unreachable here too.
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP016_REVISION)
        _assert_at_head(test_engine)
    finally:
        restore_conn = test_engine.connect()
        restore_trans = restore_conn.begin()
        try:
            restore_conn.execute(text("SET session_replication_role = replica"))
            restore_conn.execute(
                text("UPDATE finished_goods_ledger_entries SET note = NULL WHERE finished_goods_lot_id = :lid"),
                {"lid": fg_lot_id},
            )
            restore_conn.execute(text("SET session_replication_role = DEFAULT"))
            restore_conn.execute(
                text(
                    "ALTER TABLE finished_goods_ledger_entries ADD CONSTRAINT "
                    "ck_finished_goods_ledger_entries_note_null CHECK (note IS NULL)"
                )
            )
        except Exception:
            restore_trans.rollback()
            raise
        else:
            restore_trans.commit()
        finally:
            restore_conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- state 16: unknown entry kind --------------------------------------------

@pytest.mark.integration
def test_downgrade_blocked_by_unknown_entry_kind(test_engine, alembic_head_restore) -> None:
    # CARRIER-CONFIG-001A: this guard is about CMP-016 ledger
    # reconstructibility, unrelated to carrier type -- grow_bag keeps the
    # scenario free of a carrier_specifications row, which would otherwise
    # unconditionally block via e5b8c3a72f04's own, earlier-in-chain guard
    # before this guard is ever reached.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id = _pack_one(scenario, session)
    session.commit()
    session.close()
    conn.close()
    require_cmp_test(test_engine)

    # CMP-017 widened kind_allowed, deterministic_id, typed_source_shape,
    # weight_envelope, and count_signed all to be kind-aware, branching on
    # entry_kind IN ('packing_receipt', 'dispatch_issue') — 'future_kind'
    # now satisfies none of those branches either, so all five must be
    # dropped here (not just kind_allowed) to construct this state, and
    # restored afterward in their exact CMP-017 (not CMP-016) bodies, since
    # this test never actually leaves head.
    bypass_conn = test_engine.connect()
    trans = bypass_conn.begin()
    bypass_conn.execute(text("SET session_replication_role = replica"))
    for name in [
        "ck_finished_goods_ledger_entries_kind_allowed",
        "ck_finished_goods_ledger_entries_deterministic_id",
        "ck_finished_goods_ledger_entries_typed_source_shape",
        "ck_finished_goods_ledger_entries_weight_envelope",
        "ck_finished_goods_ledger_entries_count_signed",
    ]:
        bypass_conn.execute(text(f"ALTER TABLE finished_goods_ledger_entries DROP CONSTRAINT {name}"))
    bypass_conn.execute(
        text("UPDATE finished_goods_ledger_entries SET entry_kind = 'future_kind' WHERE finished_goods_lot_id = :lid"),
        {"lid": fg_lot_id},
    )
    bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    bypass_conn.close()

    try:
        # CMP-017's own downgrade guard checks for an unrecognized entry
        # kind before CMP-016's own downgrade() ever runs, so its message
        # fires first now that it sits above CMP-016 in the chain.
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP016_REVISION)
        _assert_at_head(test_engine)
    finally:
        # Restore order matters: delete the tenant's bad row *before*
        # re-adding the CHECKs, since Postgres validates all existing rows
        # against a newly added CHECK unless declared NOT VALID.
        cleanup_scenario(test_engine, scenario["tenant_id"])
        restore_conn = test_engine.connect()
        restore_trans = restore_conn.begin()
        try:
            restore_conn.execute(
                text(
                    "ALTER TABLE finished_goods_ledger_entries ADD CONSTRAINT "
                    "ck_finished_goods_ledger_entries_kind_allowed "
                    "CHECK (entry_kind IN ('packing_receipt', 'dispatch_issue'))"
                )
            )
            restore_conn.execute(
                text(
                    "ALTER TABLE finished_goods_ledger_entries ADD CONSTRAINT "
                    "ck_finished_goods_ledger_entries_deterministic_id CHECK ("
                    "(entry_kind = 'packing_receipt' AND id = finished_goods_lot_id) "
                    "OR (entry_kind = 'dispatch_issue' AND id = dispatch_line_id))"
                )
            )
            restore_conn.execute(
                text(
                    "ALTER TABLE finished_goods_ledger_entries ADD CONSTRAINT "
                    "ck_finished_goods_ledger_entries_typed_source_shape CHECK ("
                    "(entry_kind = 'packing_receipt' AND packing_event_id IS NOT NULL AND dispatch_line_id IS NULL) "
                    "OR (entry_kind = 'dispatch_issue' AND packing_event_id IS NULL AND dispatch_line_id IS NOT NULL))"
                )
            )
            restore_conn.execute(
                text(
                    "ALTER TABLE finished_goods_ledger_entries ADD CONSTRAINT "
                    "ck_finished_goods_ledger_entries_weight_envelope CHECK ("
                    "weight_delta_kg = trunc(weight_delta_kg, 3) AND ("
                    "  (entry_kind = 'packing_receipt' AND weight_delta_kg > 0 AND weight_delta_kg < 100000000000)"
                    "  OR (entry_kind = 'dispatch_issue' AND weight_delta_kg < 0 AND weight_delta_kg > -100000000000)"
                    "))"
                )
            )
            restore_conn.execute(
                text(
                    "ALTER TABLE finished_goods_ledger_entries ADD CONSTRAINT "
                    "ck_finished_goods_ledger_entries_count_signed CHECK ("
                    "(entry_kind = 'packing_receipt' AND package_count_delta > 0 "
                    "  AND package_count_delta <= 9223372036854775807)"
                    "OR (entry_kind = 'dispatch_issue' AND package_count_delta < 0 "
                    "  AND package_count_delta >= -9223372036854775807))"
                )
            )
        except Exception:
            restore_trans.rollback()
            raise
        else:
            restore_trans.commit()
        finally:
            restore_conn.close()
