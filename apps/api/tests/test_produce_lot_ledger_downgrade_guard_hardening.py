"""CMP-016A: produce-lot ledger downgrade-guard hardening proof tests.

`de82132ef837` (CMP-014) is never edited: its own `downgrade()` only checks
for missing/mismatched harvest receipts, not orphaned or duplicated ones.
CMP-016A closes this gap two ways: a marker migration (`dd4e6fab718a`) that
validates on its own upgrade/downgrade, and — the durable half — a
pre-migration guard in `migrations/env.py` that runs on *every* Alembic
invocation, before any destructive step, using the current database
contents rather than which migrations happen to be in history. This file
proves both the one-shot downgrade path (single command, head all the way
past CMP-014) and the staged path (a first command down to CMP-016A's own
revision — clean data, always succeeds — then a *separate*, later command
further down, after which CMP-016A's own marker is no longer present in
the database's history at all) are both blocked for every malformed state,
and that legitimate CMP-015 `packing_consumption` history is never treated
as malformed except at the exact point it would be silently discarded."""
import importlib.util
import threading
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
from app.services import harvest_service, packing_service
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, require_cmp_test

API_ROOT = Path(__file__).resolve().parent.parent
NEW_REVISION = "dd4e6fab718a"
PRODUCE_LOT_LEDGER_REVISION = "de82132ef837"


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_head_revision(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_current_head()


def _pre_cmp014_revision(cfg: Config) -> str:
    """Never hardcoded: derived from the live revision graph, exactly the
    correction this file exists to prove was applied."""
    return ScriptDirectory.from_config(cfg).get_revision(PRODUCE_LOT_LEDGER_REVISION).down_revision


def _now():
    return datetime.now(timezone.utc)


def _assert_at(test_engine, expected: str) -> None:
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert current == expected


def _plv():
    path = API_ROOT / "migrations" / "_produce_lot_ledger_validation.py"
    spec = importlib.util.spec_from_file_location("cmp_produce_lot_ledger_validation_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pack_one(scenario, db) -> None:
    """Records a legitimate CMP-015 packing_consumption debit against
    lot_a — real, valid, non-corrupted data."""
    packing_service.record_packing(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), effective_time=_now(),
        finished_goods_lot_code=f"FG-{scenario['suffix']}", package_count=1,
        packed_output_weight_kg=Decimal("2.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"harvested_produce_lot_id": scenario["lot_a_id"], "consumed_weight_kg": Decimal("2.000"), "consumed_whole_unit_count": None, "note": None}],
    )


def _snapshot(test_engine, lot_id):
    with test_engine.connect() as c:
        return dict(
            c.execute(
                text(
                    "SELECT tenant_id, farm_id, harvest_event_id, weight_delta_kg, whole_unit_count_delta, "
                    "effective_time, recorded_time, actor_user_id "
                    "FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid AND entry_kind = 'harvest_receipt'"
                ),
                {"lid": lot_id},
            ).mappings().one()
        )


def _replica_update(test_engine, lot_id, column: str, value) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(
        text(f"UPDATE produce_lot_ledger_entries SET {column} = :val WHERE produce_lot_id = :lid AND entry_kind = 'harvest_receipt'"),
        {"val": value, "lid": lot_id},
    )
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()


# --- corruption appliers: (test_engine, scenario) -> restore_info -----------
# --- restorers: (test_engine, scenario, restore_info) -> None ---------------

def _reconstruct_receipt(test_engine, lot_id) -> None:
    """Deletes whatever (missing/malformed) harvest_receipt currently
    exists for `lot_id`, if any, and inserts the one deterministically
    correct row — the same projection the backfill/live-creation code
    uses. Used to heal a lot back to a valid state before an interim
    re-upgrade in staged tests, so the *next* corruption under test is
    the only thing being proven, not leftover damage from this one."""
    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid AND entry_kind = 'harvest_receipt'"), {"lid": lot_id})
    conn.execute(
        text(
            "INSERT INTO produce_lot_ledger_entries "
            "(id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, "
            "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
            "SELECT lot.id, lot.tenant_id, lot.farm_id, lot.id, lot.harvest_event_id, 'harvest_receipt', "
            "lot.total_harvested_weight_kg, lot.total_whole_unit_count, lot.effective_time, lot.recorded_at, "
            "event.actor_user_id, NULL "
            "FROM harvested_produce_lots lot JOIN harvest_events event ON event.id = lot.harvest_event_id "
            "WHERE lot.id = :lid"
        ),
        {"lid": lot_id},
    )
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()


def _apply_missing(test_engine, scenario):
    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid"), {"lid": scenario["lot_a_id"]})
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()
    return None


def _restore_missing(test_engine, scenario, info):
    _reconstruct_receipt(test_engine, scenario["lot_a_id"])


def _restore_noop(test_engine, scenario, info):
    pass


def _apply_orphan_missing_lot(test_engine, scenario):
    snap = _snapshot(test_engine, scenario["lot_a_id"])
    bogus_lot_id = uuid.uuid4()
    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(
        text(
            "INSERT INTO produce_lot_ledger_entries "
            "(id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, "
            "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
            "VALUES (:id, :tid, :fid, :id, :eid, 'harvest_receipt', 1.000, NULL, :eff, :rec, :uid, NULL)"
        ),
        {
            "id": bogus_lot_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
            "eid": uuid.uuid4(), "eff": snap["effective_time"], "rec": snap["recorded_time"], "uid": snap["actor_user_id"],
        },
    )
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()
    return bogus_lot_id


def _restore_orphan_missing_lot(test_engine, scenario, bogus_lot_id):
    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE id = :bid"), {"bid": bogus_lot_id})
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()


def _apply_orphan_missing_event(test_engine, scenario):
    """Uses lot_b as a real, bare (receipt-less) lot, then inserts a
    receipt for it pointing at a nonexistent harvest event."""
    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid"), {"lid": scenario["lot_b_id"]})
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()
    snap_a = _snapshot(test_engine, scenario["lot_a_id"])  # borrow plausible field values
    bogus_event = uuid.uuid4()
    conn2 = test_engine.connect()
    trans2 = conn2.begin()
    conn2.execute(text("SET session_replication_role = replica"))
    conn2.execute(
        text(
            "INSERT INTO produce_lot_ledger_entries "
            "(id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, "
            "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
            "SELECT id, tenant_id, farm_id, id, :eid, 'harvest_receipt', total_harvested_weight_kg, "
            "total_whole_unit_count, effective_time, recorded_at, :uid, NULL "
            "FROM harvested_produce_lots WHERE id = :lid"
        ),
        {"eid": bogus_event, "uid": snap_a["actor_user_id"], "lid": scenario["lot_b_id"]},
    )
    conn2.execute(text("SET session_replication_role = DEFAULT"))
    trans2.commit()
    conn2.close()
    return None


def _restore_orphan_missing_event(test_engine, scenario, info):
    _reconstruct_receipt(test_engine, scenario["lot_b_id"])


def _apply_duplicate_lot(test_engine, scenario):
    duplicate_id = uuid.uuid4()
    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(text("ALTER TABLE produce_lot_ledger_entries DROP CONSTRAINT produce_lot_ledger_entries_pkey"))
    conn.execute(text("ALTER TABLE produce_lot_ledger_entries DROP CONSTRAINT uq_produce_lot_ledger_entries_tenant_farm_id"))
    conn.execute(text("DROP INDEX ux_produce_lot_ledger_entries_lot_harvest_receipt"))
    conn.execute(text("DROP INDEX ux_produce_lot_ledger_entries_event_harvest_receipt"))
    conn.execute(
        text(
            "INSERT INTO produce_lot_ledger_entries "
            "(id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, "
            "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
            "SELECT :did, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, "
            "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note "
            "FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid AND entry_kind = 'harvest_receipt'"
        ),
        {"did": duplicate_id, "lid": scenario["lot_a_id"]},
    )
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()
    return duplicate_id


def _restore_duplicate_lot(test_engine, scenario, duplicate_id):
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE id = :did"), {"did": duplicate_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.execute(text("ALTER TABLE produce_lot_ledger_entries ADD CONSTRAINT produce_lot_ledger_entries_pkey PRIMARY KEY (id)"))
        conn.execute(text("ALTER TABLE produce_lot_ledger_entries ADD CONSTRAINT uq_produce_lot_ledger_entries_tenant_farm_id UNIQUE (tenant_id, farm_id, id)"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX ux_produce_lot_ledger_entries_lot_harvest_receipt "
                "ON produce_lot_ledger_entries (produce_lot_id) WHERE entry_kind = 'harvest_receipt'"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX ux_produce_lot_ledger_entries_event_harvest_receipt "
                "ON produce_lot_ledger_entries (harvest_event_id) WHERE entry_kind = 'harvest_receipt'"
            )
        )
    except Exception:
        trans.rollback()
        raise
    else:
        trans.commit()
    finally:
        conn.close()


def _apply_duplicate_event(test_engine, scenario):
    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(text("DROP INDEX ux_produce_lot_ledger_entries_event_harvest_receipt"))
    conn.execute(
        text("UPDATE produce_lot_ledger_entries SET harvest_event_id = :eid WHERE produce_lot_id = :lid AND entry_kind = 'harvest_receipt'"),
        {"eid": scenario["harvest_a_id"], "lid": scenario["lot_b_id"]},
    )
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()
    return None


def _restore_duplicate_event(test_engine, scenario, info):
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(
            text("UPDATE produce_lot_ledger_entries SET harvest_event_id = :eid WHERE produce_lot_id = :lid AND entry_kind = 'harvest_receipt'"),
            {"eid": scenario["harvest_b_id"], "lid": scenario["lot_b_id"]},
        )
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX ux_produce_lot_ledger_entries_event_harvest_receipt "
                "ON produce_lot_ledger_entries (harvest_event_id) WHERE entry_kind = 'harvest_receipt'"
            )
        )
    except Exception:
        trans.rollback()
        raise
    else:
        trans.commit()
    finally:
        conn.close()


def _apply_id_mismatch(test_engine, scenario):
    bogus_id = uuid.uuid4()
    _replica_update(test_engine, scenario["lot_a_id"], "id", bogus_id)
    return bogus_id


def _restore_id_mismatch(test_engine, scenario, bogus_id):
    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(text("UPDATE produce_lot_ledger_entries SET id = :lid WHERE id = :bid"), {"lid": scenario["lot_a_id"], "bid": bogus_id})
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()


def _apply_note(test_engine, scenario):
    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(text("ALTER TABLE produce_lot_ledger_entries DROP CONSTRAINT ck_produce_lot_ledger_entries_receipt_note_null"))
    conn.execute(
        text("UPDATE produce_lot_ledger_entries SET note = 'not allowed' WHERE produce_lot_id = :lid AND entry_kind = 'harvest_receipt'"),
        {"lid": scenario["lot_a_id"]},
    )
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()
    return None


def _restore_note(test_engine, scenario, info):
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(
            text("UPDATE produce_lot_ledger_entries SET note = NULL WHERE produce_lot_id = :lid AND entry_kind = 'harvest_receipt'"),
            {"lid": scenario["lot_a_id"]},
        )
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.execute(
            text(
                "ALTER TABLE produce_lot_ledger_entries ADD CONSTRAINT ck_produce_lot_ledger_entries_receipt_note_null "
                "CHECK (entry_kind <> 'harvest_receipt' OR note IS NULL)"
            )
        )
    except Exception:
        trans.rollback()
        raise
    else:
        trans.commit()
    finally:
        conn.close()


def _apply_extra_receipt(test_engine, scenario):
    """State 2, genuinely distinct from orphan/duplicate/id-mismatch: an
    ADDITIONAL committed row for a real, previously-bare lot (lot_b, its
    own correct receipt removed first) whose harvest_event_id is a REAL,
    existing event — just not lot_b's own. Both foreign keys resolve to
    genuine rows (nothing fabricated, unlike orphan); this is a bijection-
    pairing violation on a lot that had zero receipts before this insert
    (not a second row for an already-receipted lot, unlike duplicate)."""
    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid"), {"lid": scenario["lot_b_id"]})
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()

    # lot_a's real event already has its own receipt (lot_a's), so the
    # event-scoped partial unique index must be dropped first -- restored
    # in _restore_extra_receipt before cleanup, same discipline as
    # _apply_duplicate_event.
    snap_a = _snapshot(test_engine, scenario["lot_a_id"])  # borrow plausible actor value
    conn2 = test_engine.connect()
    trans2 = conn2.begin()
    conn2.execute(text("SET session_replication_role = replica"))
    conn2.execute(text("DROP INDEX ux_produce_lot_ledger_entries_event_harvest_receipt"))
    conn2.execute(
        text(
            "INSERT INTO produce_lot_ledger_entries "
            "(id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, "
            "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
            "SELECT id, tenant_id, farm_id, id, :eid, 'harvest_receipt', total_harvested_weight_kg, "
            "total_whole_unit_count, effective_time, recorded_at, :uid, NULL "
            "FROM harvested_produce_lots WHERE id = :lid"
        ),
        {"eid": scenario["harvest_a_id"], "uid": snap_a["actor_user_id"], "lid": scenario["lot_b_id"]},
    )
    conn2.execute(text("SET session_replication_role = DEFAULT"))
    trans2.commit()
    conn2.close()
    return None


def _restore_extra_receipt(test_engine, scenario, info):
    _reconstruct_receipt(test_engine, scenario["lot_b_id"])
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX ux_produce_lot_ledger_entries_event_harvest_receipt "
                "ON produce_lot_ledger_entries (harvest_event_id) WHERE entry_kind = 'harvest_receipt'"
            )
        )
    except Exception:
        trans.rollback()
        raise
    else:
        trans.commit()
    finally:
        conn.close()


def _mk_field_mismatch(column, mutate, *, needs_event_index_drop=False):
    def _apply(test_engine, scenario):
        snap = _snapshot(test_engine, scenario["lot_a_id"])
        original = snap[column]
        if needs_event_index_drop:
            # The new value (a real, different event) already has its own
            # receipt, so the event-scoped partial unique index must be
            # dropped first -- CHECK/append-only triggers alone don't
            # cover this, since a unique index isn't a trigger.
            conn = test_engine.connect()
            trans = conn.begin()
            conn.execute(text("SET session_replication_role = replica"))
            conn.execute(text("DROP INDEX ux_produce_lot_ledger_entries_event_harvest_receipt"))
            conn.execute(
                text(
                    "UPDATE produce_lot_ledger_entries SET harvest_event_id = :val "
                    "WHERE produce_lot_id = :lid AND entry_kind = 'harvest_receipt'"
                ),
                {"val": mutate(snap, scenario), "lid": scenario["lot_a_id"]},
            )
            conn.execute(text("SET session_replication_role = DEFAULT"))
            trans.commit()
            conn.close()
        else:
            _replica_update(test_engine, scenario["lot_a_id"], column, mutate(snap, scenario))
        return original

    def _restore(test_engine, scenario, original):
        _replica_update(test_engine, scenario["lot_a_id"], column, original)
        if needs_event_index_drop:
            conn = test_engine.connect()
            trans = conn.begin()
            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX ux_produce_lot_ledger_entries_event_harvest_receipt "
                        "ON produce_lot_ledger_entries (harvest_event_id) WHERE entry_kind = 'harvest_receipt'"
                    )
                )
            except Exception:
                trans.rollback()
                raise
            else:
                trans.commit()
            finally:
                conn.close()

    return _apply, _restore


_FIELD_MISMATCH_CASES = [
    pytest.param("tenant_id", lambda snap, scenario: uuid.uuid4(), False, id="tenant_mismatch"),
    pytest.param("farm_id", lambda snap, scenario: uuid.uuid4(), False, id="farm_mismatch"),
    # A real-but-wrong event (lot_b's own), not a fabricated one -- a pure
    # field mismatch (state 10), distinct from orphan_missing_event
    # (state 4, a genuinely nonexistent event reference). It already has
    # its own receipt, so this needs the event-scoped index dropped.
    pytest.param("harvest_event_id", lambda snap, scenario: scenario["harvest_b_id"], True, id="harvest_event_mismatch"),
    pytest.param("weight_delta_kg", lambda snap, scenario: Decimal("999.000"), False, id="weight_mismatch"),
    pytest.param("whole_unit_count_delta", lambda snap, scenario: 999999, False, id="whole_unit_count_mismatch"),
    pytest.param("effective_time", lambda snap, scenario: snap["effective_time"] - timedelta(days=1), False, id="effective_time_mismatch"),
    pytest.param("recorded_time", lambda snap, scenario: snap["recorded_time"] - timedelta(days=1), False, id="recorded_time_mismatch"),
    pytest.param("actor_user_id", lambda snap, scenario: uuid.uuid4(), False, id="actor_mismatch"),
]

_DEDICATED_STATES = [
    pytest.param(_apply_missing, _restore_missing, "lot_missing_harvest_receipt", id="missing_receipt"),
    pytest.param(_apply_extra_receipt, _restore_extra_receipt, "extra_harvest_receipt", id="extra_receipt"),
    pytest.param(_apply_orphan_missing_lot, _restore_orphan_missing_lot, "orphan_harvest_receipt_missing_lot", id="orphan_missing_lot"),
    pytest.param(_apply_orphan_missing_event, _restore_orphan_missing_event, "orphan_harvest_receipt_missing_event", id="orphan_missing_event"),
    pytest.param(_apply_duplicate_lot, _restore_duplicate_lot, "duplicate_harvest_receipt_by_lot", id="duplicate_by_lot"),
    pytest.param(_apply_duplicate_event, _restore_duplicate_event, "duplicate_harvest_receipt_by_event", id="duplicate_by_event"),
    pytest.param(_apply_id_mismatch, _restore_id_mismatch, "harvest_receipt_projection_mismatch", id="deterministic_id_mismatch"),
    pytest.param(_apply_note, _restore_note, "harvest_receipt_projection_mismatch", id="non_null_note"),
]


def _new_scenario(test_engine):
    return build_committed_scenario(test_engine, lot_a_count=None, lot_b_count=None)


@pytest.mark.integration
@pytest.mark.parametrize("apply_fn, restore_fn, match", _DEDICATED_STATES)
def test_one_shot_downgrade_blocked(test_engine, apply_fn, restore_fn, match) -> None:
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)
    info = apply_fn(test_engine, scenario)
    try:
        with pytest.raises(RuntimeError, match=match):
            command.downgrade(_cfg(), _pre_cmp014_revision(_cfg()))
        _assert_at(test_engine, _resolve_head_revision(_cfg()))
    finally:
        restore_fn(test_engine, scenario, info)
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
@pytest.mark.parametrize("column, mutate, needs_event_index_drop", _FIELD_MISMATCH_CASES)
def test_one_shot_downgrade_blocked_field_mismatch(test_engine, column, mutate, needs_event_index_drop) -> None:
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)
    apply_fn, restore_fn = _mk_field_mismatch(column, mutate, needs_event_index_drop=needs_event_index_drop)
    original = apply_fn(test_engine, scenario)
    try:
        with pytest.raises(RuntimeError, match="harvest_receipt_projection_mismatch"):
            command.downgrade(_cfg(), _pre_cmp014_revision(_cfg()))
        _assert_at(test_engine, _resolve_head_revision(_cfg()))
    finally:
        restore_fn(test_engine, scenario, original)
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
@pytest.mark.parametrize("apply_fn, restore_fn, match", _DEDICATED_STATES)
def test_staged_downgrade_blocked(test_engine, apply_fn, restore_fn, match) -> None:
    """Stage 1 (head -> CMP-016A's own down_revision) always succeeds on
    clean data; corruption is introduced only after CMP-016A's own marker
    is no longer present in the database's history; stage 2 (a separate,
    later command) must still be blocked by env.py alone."""
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)
    try:
        command.downgrade(_cfg(), "b3f6e9a2d174")
        _assert_at(test_engine, "b3f6e9a2d174")

        info = apply_fn(test_engine, scenario)
        try:
            with pytest.raises(RuntimeError, match=match):
                command.downgrade(_cfg(), _pre_cmp014_revision(_cfg()))
            _assert_at(test_engine, "b3f6e9a2d174")
        finally:
            restore_fn(test_engine, scenario, info)
    finally:
        command.upgrade(_cfg(), "head")
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
@pytest.mark.parametrize("column, mutate, needs_event_index_drop", _FIELD_MISMATCH_CASES)
def test_staged_downgrade_blocked_field_mismatch(test_engine, column, mutate, needs_event_index_drop) -> None:
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)
    apply_fn, restore_fn = _mk_field_mismatch(column, mutate, needs_event_index_drop=needs_event_index_drop)
    try:
        command.downgrade(_cfg(), "b3f6e9a2d174")
        _assert_at(test_engine, "b3f6e9a2d174")

        original = apply_fn(test_engine, scenario)
        try:
            with pytest.raises(RuntimeError, match="harvest_receipt_projection_mismatch"):
                command.downgrade(_cfg(), _pre_cmp014_revision(_cfg()))
            _assert_at(test_engine, "b3f6e9a2d174")
        finally:
            restore_fn(test_engine, scenario, original)
    finally:
        command.upgrade(_cfg(), "head")
        cleanup_scenario(test_engine, scenario["tenant_id"])


# --- state 11: legitimate packing_consumption at the crossing boundary ------

@pytest.mark.integration
def test_packing_consumption_does_not_block_cmp016a_upgrade_or_downgrade(test_engine) -> None:
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    _pack_one(scenario, session)
    session.commit()
    session.close()
    conn.close()

    try:
        command.downgrade(_cfg(), "b3f6e9a2d174")
        _assert_at(test_engine, "b3f6e9a2d174")
        command.upgrade(_cfg(), "head")
        _assert_at(test_engine, _resolve_head_revision(_cfg()))
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_packing_consumption_blocks_crossing_below_cmp014_one_shot(test_engine) -> None:
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    _pack_one(scenario, session)
    session.commit()
    session.close()
    conn.close()
    try:
        with pytest.raises(RuntimeError, match="unsupported_entry_kind_at_crossing"):
            command.downgrade(_cfg(), _pre_cmp014_revision(_cfg()))
        _assert_at(test_engine, _resolve_head_revision(_cfg()))
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_packing_consumption_blocks_crossing_below_cmp014_staged(test_engine) -> None:
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    _pack_one(scenario, session)
    session.commit()
    session.close()
    conn.close()
    try:
        command.downgrade(_cfg(), "b3f6e9a2d174")
        _assert_at(test_engine, "b3f6e9a2d174")
        with pytest.raises(RuntimeError, match="unsupported_entry_kind_at_crossing"):
            command.downgrade(_cfg(), _pre_cmp014_revision(_cfg()))
        _assert_at(test_engine, "b3f6e9a2d174")
    finally:
        command.upgrade(_cfg(), "head")
        cleanup_scenario(test_engine, scenario["tenant_id"])


def _walk_down_revisions(cfg: Config, steps: int) -> list[str]:
    """[head, head-1, head-2, ..., head-steps], derived by walking
    `down_revision` from the live script graph -- never a hardcoded
    assumption about which specific revision is "current head"."""
    script = ScriptDirectory.from_config(cfg)
    revs = [script.get_current_head()]
    for _ in range(steps):
        revs.append(script.get_revision(revs[-1]).down_revision)
    return revs


@pytest.mark.integration
def test_staged_downgrade_head_through_cmp014_each_leg_legal(test_engine) -> None:
    """CMP-017 verification pass: an explicit, single-step-at-a-time walk
    head (CMP-017) -> CMP-016A -> CMP-016 -> CMP-015 -> CMP-014, with no
    dispatch or packing history at all, proving every individual leg is
    legal on its own (not just as part of a larger multi-step jump) --
    and that CMP-016A's own env.py guard does not block any of them.
    Revisions are resolved dynamically from the live graph; only the
    number of steps (4, matching CMP-017/CMP-016A/CMP-016/CMP-015) is
    fixed, since that is a structural fact about this linear history, not
    a "current head" assumption."""
    require_cmp_test(test_engine)
    head, cmp016a, cmp016, cmp015, cmp014 = _walk_down_revisions(_cfg(), 4)

    command.downgrade(_cfg(), cmp016a)
    _assert_at(test_engine, cmp016a)
    command.downgrade(_cfg(), cmp016)
    _assert_at(test_engine, cmp016)
    command.downgrade(_cfg(), cmp015)
    _assert_at(test_engine, cmp015)
    command.downgrade(_cfg(), cmp014)
    _assert_at(test_engine, cmp014)

    command.upgrade(_cfg(), "head")
    _assert_at(test_engine, head)


# --- clean paths, ambiguity, upgrades, boundaries ----------------------------

@pytest.mark.integration
def test_clean_receipts_allow_one_shot_downgrade(test_engine) -> None:
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)
    try:
        command.downgrade(_cfg(), _pre_cmp014_revision(_cfg()))
        _assert_at(test_engine, _pre_cmp014_revision(_cfg()))
        command.upgrade(_cfg(), "head")
        _assert_at(test_engine, _resolve_head_revision(_cfg()))
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_clean_receipts_allow_staged_downgrade(test_engine) -> None:
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)
    try:
        command.downgrade(_cfg(), "b3f6e9a2d174")
        _assert_at(test_engine, "b3f6e9a2d174")
        command.downgrade(_cfg(), _pre_cmp014_revision(_cfg()))
        _assert_at(test_engine, _pre_cmp014_revision(_cfg()))
        command.upgrade(_cfg(), "head")
        _assert_at(test_engine, _resolve_head_revision(_cfg()))
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_clean_downgrade_with_no_produce_lots(test_engine) -> None:
    require_cmp_test(test_engine)
    command.downgrade(_cfg(), _pre_cmp014_revision(_cfg()))
    _assert_at(test_engine, _pre_cmp014_revision(_cfg()))
    command.upgrade(_cfg(), "head")
    _assert_at(test_engine, _resolve_head_revision(_cfg()))


@pytest.mark.integration
def test_current_head_resolution_is_dynamic(test_engine) -> None:
    # NEW_REVISION ("dd4e6fab718a") is CMP-016A's own marker migration, not
    # necessarily "head" — CMP-020 ("68215f964ca9") now sits above it, so
    # this asserts against the true current head directly rather than
    # reusing that older, unrelated constant.
    assert _resolve_head_revision(_cfg()) == "68215f964ca9"
    assert _pre_cmp014_revision(_cfg()) == "c7f14b8e29a3"


@pytest.mark.integration
def test_upgrade_is_unaffected_by_the_guard(test_engine) -> None:
    require_cmp_test(test_engine)
    command.downgrade(_cfg(), "a91f4c7b2e58")
    command.upgrade(_cfg(), "head")
    _assert_at(test_engine, _resolve_head_revision(_cfg()))


@pytest.mark.integration
def test_downgrade_remaining_above_cmp014_is_unaffected(test_engine) -> None:
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)
    try:
        command.downgrade(_cfg(), "a91f4c7b2e58")
        _assert_at(test_engine, "a91f4c7b2e58")
        with test_engine.connect() as c:
            still_present = c.execute(
                text("SELECT count(*) FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid"),
                {"lid": scenario["lot_a_id"]},
            ).scalar_one()
        assert still_present == 1, "a downgrade that never crosses CMP-014 must leave the ledger untouched"
        command.upgrade(_cfg(), "head")
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_cmp015_and_cmp016_downgrade_behavior_unchanged(test_engine) -> None:
    """CMP-015's own unconditional-block guard and CMP-016's own
    reconstructible-projection guard are untouched by this ticket."""
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    _pack_one(scenario, session)
    session.commit()
    session.close()
    conn.close()
    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past CMP-015"):
            command.downgrade(_cfg(), "de82132ef837")
        _assert_at(test_engine, _resolve_head_revision(_cfg()))
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_offline_downgrade_crossing_cmp014_fails_closed(test_engine) -> None:
    """Offline (--sql) mode has no live connection to validate against, so
    a downgrade path that crosses CMP-014 must fail closed rather than
    emit unvalidated destructive SQL."""
    with pytest.raises(RuntimeError, match="Perform this downgrade online"):
        command.downgrade(_cfg(), f"{_resolve_head_revision(_cfg())}:c7f14b8e29a3", sql=True)


@pytest.mark.integration
def test_offline_downgrade_above_cmp014_is_unaffected_by_the_guard(test_engine) -> None:
    """The guard itself must not intervene for a path that never reaches
    CMP-014. (Whether SQL generation completes end-to-end for these
    revisions is a separate, pre-existing characteristic of this
    migration chain — every revision from CMP-013 onward reads live data
    for its own backfill/reconciliation validation inside upgrade()/
    downgrade(), which is fundamentally incompatible with --sql's mock
    connection; this predates and is out of scope for CMP-016A. This test
    only proves our own crossing message is never raised here.)"""
    try:
        command.downgrade(_cfg(), f"{_resolve_head_revision(_cfg())}:a91f4c7b2e58", sql=True)
    except RuntimeError as e:
        assert "Cannot generate offline downgrade SQL past CMP-014" not in str(e)
    except Exception:
        pass  # pre-existing, unrelated offline-mode limitation; not this guard's concern


@pytest.mark.integration
def test_ambiguous_script_heads_fail_safely(test_engine) -> None:
    """Two script-directory heads (a temporary branch, constructed only in
    a throwaway tmp copy of migrations/ -- the real migrations/versions/
    is never touched) must refuse to evaluate the crossing guard rather
    than silently pick one lineage. The real cmp_test schema is never
    reached: the guard raises before context.run_migrations()."""
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    try:
        mig_dst = tmp / "migrations"
        shutil.copytree(API_ROOT / "migrations", mig_dst, ignore=shutil.ignore_patterns("__pycache__"))
        head = _resolve_head_revision(_cfg())
        for suffix in ("a", "b"):
            (mig_dst / "versions" / f"zzzz_test_branch_{suffix}.py").write_text(
                f'revision = "zzzzbranch{suffix}"\n'
                f'down_revision = "{head}"\n'
                "branch_labels = None\n"
                "depends_on = None\n\n"
                "def upgrade(): pass\n"
                "def downgrade(): pass\n"
            )
        ini_path = tmp / "alembic.ini"
        ini_path.write_text((API_ROOT / "alembic.ini").read_text())
        branched_cfg = Config(str(ini_path))
        branched_cfg.set_main_option("script_location", str(mig_dst))
        branched_cfg.set_main_option("sqlalchemy.url", settings.test_database_url)

        assert len(ScriptDirectory.from_config(branched_cfg).get_heads()) == 2

        with pytest.raises(RuntimeError, match="ambiguous Alembic head state"):
            command.downgrade(branched_cfg, head)
        # The real database must be untouched -- still at the real head.
        _assert_at(test_engine, head)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- lock behavior --------------------------------------------------------

@pytest.mark.integration
def test_concurrent_writer_first_guard_waits_then_validates_committed_state(test_engine) -> None:
    """Writer opens a transaction and writes relevant ledger state first;
    the crossing downgrade starts only after the writer's write is
    visible (though still uncommitted); the guard's own LOCK TABLE call
    must block until the writer commits, then validate the resulting
    committed (clean) state and let the downgrade proceed. Uses events and
    bounded waits throughout, never an arbitrary sleep."""
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)

    writer_ready = threading.Event()
    writer_may_commit = threading.Event()
    writer_done = threading.Event()

    def writer() -> None:
        conn = test_engine.connect()
        trans = conn.begin()
        conn.execute(text("SET session_replication_role = replica"))
        # A genuine row lock on the guarded table, zero semantic change.
        conn.execute(
            text(
                "UPDATE produce_lot_ledger_entries SET note = note "
                "WHERE produce_lot_id = :lid AND entry_kind = 'harvest_receipt'"
            ),
            {"lid": scenario["lot_a_id"]},
        )
        writer_ready.set()
        writer_may_commit.wait(timeout=15)
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
        conn.close()
        writer_done.set()

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    assert writer_ready.wait(timeout=10), "writer must acquire its row lock before the guard starts"

    downgrade_done = threading.Event()
    downgrade_outcome: dict = {}

    def downgrade_runner() -> None:
        try:
            command.downgrade(_cfg(), _pre_cmp014_revision(_cfg()))
            downgrade_outcome["ok"] = True
        except Exception as exc:  # pragma: no cover
            downgrade_outcome["error"] = exc
        downgrade_done.set()

    downgrade_thread = threading.Thread(target=downgrade_runner)
    downgrade_thread.start()

    assert not downgrade_done.wait(timeout=2), (
        "the guard's LOCK TABLE must block while the writer's transaction is still open, "
        "not validate a stale pre-write snapshot"
    )

    writer_may_commit.set()
    assert writer_done.wait(timeout=15)
    assert downgrade_done.wait(timeout=20)
    writer_thread.join(timeout=5)
    downgrade_thread.join(timeout=5)

    assert "error" not in downgrade_outcome, downgrade_outcome.get("error")
    assert downgrade_outcome.get("ok") is True

    try:
        _assert_at(test_engine, _pre_cmp014_revision(_cfg()))
        command.upgrade(_cfg(), "head")
        _assert_at(test_engine, _resolve_head_revision(_cfg()))
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_lock_holder_blocks_concurrent_writer_until_released(test_engine) -> None:
    """The guard acquires locks first; a writer then attempts a relevant
    INSERT and must block until the lock-holding transaction completes —
    proving no write can slip between validation and migration execution.
    Simulates the exact primitive env.py's guard uses (same three tables,
    same ACCESS EXCLUSIVE mode, same deterministic alphabetical order) in
    a controlled thread rather than the real command.downgrade() call,
    since validation itself completes in milliseconds and cannot be
    paused without adding test-only hooks to production code; this proves
    the locking mechanism itself is sufficient, deterministically, with
    bounded waits and no arbitrary sleeps."""
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)

    lock_acquired = threading.Event()
    release_lock = threading.Event()
    lock_released = threading.Event()

    def lock_holder() -> None:
        conn = test_engine.connect()
        trans = conn.begin()
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        for table_name in _plv().GUARDED_TABLES:
            conn.execute(text(f"LOCK TABLE {table_name} IN ACCESS EXCLUSIVE MODE"))
        lock_acquired.set()
        release_lock.wait(timeout=15)
        trans.commit()
        conn.close()
        lock_released.set()

    holder_thread = threading.Thread(target=lock_holder)
    holder_thread.start()
    assert lock_acquired.wait(timeout=10), "the lock holder must acquire all three locks first"

    writer_done = threading.Event()
    writer_outcome: dict = {}

    def writer() -> None:
        conn = test_engine.connect()
        trans = conn.begin()
        try:
            conn.execute(text("SET session_replication_role = replica"))
            conn.execute(
                text(
                    "INSERT INTO produce_lot_ledger_entries "
                    "(id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, "
                    "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "SELECT gen_random_uuid(), tenant_id, farm_id, gen_random_uuid(), gen_random_uuid(), "
                    "'harvest_receipt', weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, "
                    "actor_user_id, NULL "
                    "FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid AND entry_kind = 'harvest_receipt'"
                ),
                {"lid": scenario["lot_a_id"]},
            )
            conn.execute(text("SET session_replication_role = DEFAULT"))
            trans.commit()
            writer_outcome["ok"] = True
        except Exception as exc:  # pragma: no cover
            trans.rollback()
            writer_outcome["error"] = exc
        finally:
            conn.close()
        writer_done.set()

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()

    assert not writer_done.wait(timeout=2), "the writer's INSERT must block while the lock is held"

    release_lock.set()
    assert lock_released.wait(timeout=15)
    assert writer_done.wait(timeout=15)
    holder_thread.join(timeout=5)
    writer_thread.join(timeout=5)

    assert writer_outcome.get("ok") is True, writer_outcome.get("error")
    cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_rejection_releases_locks_and_preserves_malformed_data(test_engine) -> None:
    """When validation rejects a malformed state: the migration
    transaction rolls back; every table lock it held is released; a fresh
    connection can immediately read and write the test-owned rows; the
    database revision is unchanged; and the malformed data itself is
    preserved (not silently repaired) until the test's own cleanup."""
    require_cmp_test(test_engine)
    scenario = _new_scenario(test_engine)
    _apply_missing(test_engine, scenario)  # a real, reachable malformed state

    try:
        with pytest.raises(RuntimeError, match="lot_missing_harvest_receipt"):
            command.downgrade(_cfg(), _pre_cmp014_revision(_cfg()))
        _assert_at(test_engine, _resolve_head_revision(_cfg()))

        # A fresh connection must be able to read the still-malformed,
        # preserved data (the lot has zero receipts) and write freely --
        # no lock survives the rejected migration's rollback.
        fresh = test_engine.connect()
        try:
            receipt_count = fresh.execute(
                text("SELECT count(*) FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid"),
                {"lid": scenario["lot_a_id"]},
            ).scalar_one()
            assert receipt_count == 0, "the malformed (missing-receipt) state must be preserved for inspection"

            fresh.execute(text("SET session_replication_role = replica"))
            fresh.execute(
                text("UPDATE harvested_produce_lots SET code = code WHERE id = :lid"),
                {"lid": scenario["lot_a_id"]},
            )
            fresh.execute(text("SET session_replication_role = DEFAULT"))
            fresh.commit()
        finally:
            fresh.close()
    finally:
        _restore_missing(test_engine, scenario, None)
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_final_restoration_to_head(test_engine) -> None:
    _assert_at(test_engine, _resolve_head_revision(_cfg()))
