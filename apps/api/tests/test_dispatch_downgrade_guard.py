"""CMP-017 downgrade-guard proof tests.

Dispatch history follows CMP-015's own unconditional-block model, not
CMP-016's reconstructible-projection one: a dispatch event/line/issue is
independent operational data (nothing else in the schema can rebuild it),
so downgrade past CMP-017 is blocked while ANY of it exists — the guard
never tries to "reconstruct and verify" a dispatch the way CMP-016 does
for a packing receipt. This file also proves the v2 ledger insert-
integrity trigger attachment cleanly replaces (not supplements) CMP-016's
own, that a clean downgrade restores the byte-exact original CMP-016
CHECK constraints and trigger attachment, that every packing receipt
survives the round trip untouched, and that CMP-016A's own env.py guard
(a different, unrelated revision) is unaffected."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from tests._dispatch_scenario import dispatch_one, pack_one
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, require_cmp_test

API_ROOT = Path(__file__).resolve().parent.parent
# Specific, historically fixed migration under test — the target this test
# downgrades to — is safe to hardcode; "current head" is not.
_PRE_CMP017_REVISION = "dd4e6fab718a"

_CMP016_KIND_ALLOWED_DEF = "CHECK (((entry_kind)::text = 'packing_receipt'::text))"
_CMP016_DETERMINISTIC_ID_DEF = "CHECK ((id = finished_goods_lot_id))"
_CMP016_WEIGHT_ENVELOPE_DEF = (
    "CHECK (((weight_delta_kg > (0)::numeric) AND (weight_delta_kg = trunc(weight_delta_kg, 3)) "
    "AND (weight_delta_kg < ('100000000000'::bigint)::numeric)))"
)
_CMP016_COUNT_POSITIVE_DEF = "CHECK ((package_count_delta > 0))"


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


def _build_dispatched_scenario(test_engine):
    s = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(s, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
    event = dispatch_one(s, session, finished_goods_lot_id=fg_lot_id, dispatched_weight_kg=Decimal("2.000"), dispatched_package_count=2)
    event_id = event.id
    line_id = session.execute(
        text("SELECT id FROM dispatch_lines WHERE dispatch_event_id = :eid"), {"eid": event_id}
    ).scalar_one()
    session.commit()
    session.close()
    conn.close()
    s["fg_lot_id"] = fg_lot_id
    s["dispatch_event_id"] = event_id
    s["dispatch_line_id"] = line_id
    return s


@pytest.mark.integration
def test_downgrade_blocked_by_dispatch_event(test_engine) -> None:
    s = _build_dispatched_scenario(test_engine)
    try:
        with pytest.raises(RuntimeError, match="dispatch_events contains history"):
            command.downgrade(_cfg(), _PRE_CMP017_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, s["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_by_dispatch_line_only(test_engine) -> None:
    """The event alone is bypass-deleted (its own line remains, orphaned
    by FK enforcement bypass) — proving the guard's second clause fires
    independently once the first (event) count is zero."""
    s = _build_dispatched_scenario(test_engine)
    require_cmp_test(test_engine)
    bypass_conn = test_engine.connect()
    trans = bypass_conn.begin()
    bypass_conn.execute(text("SET session_replication_role = replica"))
    bypass_conn.execute(text("DELETE FROM dispatch_events WHERE id = :eid"), {"eid": s["dispatch_event_id"]})
    bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    bypass_conn.close()

    try:
        with pytest.raises(RuntimeError, match="dispatch_lines contains history"):
            command.downgrade(_cfg(), _PRE_CMP017_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, s["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_by_dispatch_issue_only(test_engine) -> None:
    """Both the event and its line are bypass-deleted, leaving only the
    orphaned dispatch_issue ledger row — proving the guard's third clause
    fires independently once both the event and line counts are zero."""
    s = _build_dispatched_scenario(test_engine)
    require_cmp_test(test_engine)
    bypass_conn = test_engine.connect()
    trans = bypass_conn.begin()
    bypass_conn.execute(text("SET session_replication_role = replica"))
    bypass_conn.execute(text("DELETE FROM dispatch_lines WHERE id = :lid"), {"lid": s["dispatch_line_id"]})
    bypass_conn.execute(text("DELETE FROM dispatch_events WHERE id = :eid"), {"eid": s["dispatch_event_id"]})
    bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    bypass_conn.close()

    try:
        with pytest.raises(RuntimeError, match="contains dispatch_issue rows"):
            command.downgrade(_cfg(), _PRE_CMP017_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, s["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_by_unknown_future_kind(test_engine) -> None:
    """An entry_kind this migration does not recognize (neither
    packing_receipt nor dispatch_issue) must block downgrade even though
    no dispatch_events/dispatch_lines/dispatch_issue rows exist at all —
    constructed against an ordinary CMP-016 receipt row, with the three
    kind-dependent CHECKs temporarily dropped to allow the mutation."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=1, packed_output_weight_kg=Decimal("1.000"))
    session.commit()
    session.close()
    conn.close()
    require_cmp_test(test_engine)

    dropped_checks = [
        "ck_finished_goods_ledger_entries_kind_allowed",
        "ck_finished_goods_ledger_entries_deterministic_id",
        "ck_finished_goods_ledger_entries_typed_source_shape",
        "ck_finished_goods_ledger_entries_weight_envelope",
        "ck_finished_goods_ledger_entries_count_signed",
    ]
    try:
        bypass_conn = test_engine.connect()
        trans = bypass_conn.begin()
        bypass_conn.execute(text("SET session_replication_role = replica"))
        for name in dropped_checks:
            bypass_conn.execute(text(f"ALTER TABLE finished_goods_ledger_entries DROP CONSTRAINT {name}"))
        bypass_conn.execute(
            text("UPDATE finished_goods_ledger_entries SET entry_kind = 'future_kind' WHERE finished_goods_lot_id = :lid"),
            {"lid": fg_lot_id},
        )
        bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
        bypass_conn.close()

        with pytest.raises(RuntimeError, match="entry kind this migration does not recognize"):
            command.downgrade(_cfg(), _PRE_CMP017_REVISION)
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


@pytest.mark.integration
def test_downgrade_blocked_by_dangling_dispatch_line_id_with_manipulated_kind(test_engine) -> None:
    """A row with entry_kind manipulated back to 'packing_receipt' but a
    still-non-null dispatch_line_id (an internally-inconsistent state,
    unreachable through normal operation) must independently block
    downgrade — proving the guard does not merely trust entry_kind once
    the dispatch_events/dispatch_lines/dispatch_issue counts are all
    zero."""
    s = _build_dispatched_scenario(test_engine)
    require_cmp_test(test_engine)

    try:
        bypass_conn = test_engine.connect()
        trans = bypass_conn.begin()
        bypass_conn.execute(text("SET session_replication_role = replica"))
        # Tear down the owning dispatch_event/dispatch_line first so the
        # first two guard clauses both read zero.
        bypass_conn.execute(text("DELETE FROM dispatch_lines WHERE id = :lid"), {"lid": s["dispatch_line_id"]})
        bypass_conn.execute(text("DELETE FROM dispatch_events WHERE id = :eid"), {"eid": s["dispatch_event_id"]})
        bypass_conn.execute(
            text("ALTER TABLE finished_goods_ledger_entries DROP CONSTRAINT ck_finished_goods_ledger_entries_deterministic_id")
        )
        bypass_conn.execute(
            text("ALTER TABLE finished_goods_ledger_entries DROP CONSTRAINT ck_finished_goods_ledger_entries_typed_source_shape")
        )
        bypass_conn.execute(
            text("ALTER TABLE finished_goods_ledger_entries DROP CONSTRAINT ck_finished_goods_ledger_entries_weight_envelope")
        )
        bypass_conn.execute(
            text("ALTER TABLE finished_goods_ledger_entries DROP CONSTRAINT ck_finished_goods_ledger_entries_count_signed")
        )
        # The mutated row's finished_goods_lot_id already owns a genuine
        # packing_receipt (from pack_one) — flipping this row to
        # entry_kind='packing_receipt' would collide with CMP-016's own
        # per-lot partial unique index, so it is dropped here too and
        # restored afterward alongside the CHECKs.
        bypass_conn.execute(text("DROP INDEX ux_finished_goods_ledger_entries_lot_packing_receipt"))
        bypass_conn.execute(
            text(
                "UPDATE finished_goods_ledger_entries SET entry_kind = 'packing_receipt', "
                "weight_delta_kg = -weight_delta_kg, package_count_delta = -package_count_delta "
                "WHERE dispatch_line_id = :lid"
            ),
            {"lid": s["dispatch_line_id"]},
        )
        bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
        bypass_conn.close()

        with pytest.raises(RuntimeError, match="non-null dispatch_line_id"):
            command.downgrade(_cfg(), _PRE_CMP017_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, s["tenant_id"])
        restore_conn = test_engine.connect()
        restore_trans = restore_conn.begin()
        try:
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
            restore_conn.execute(
                text(
                    "CREATE UNIQUE INDEX ux_finished_goods_ledger_entries_lot_packing_receipt "
                    "ON finished_goods_ledger_entries (finished_goods_lot_id) WHERE entry_kind = 'packing_receipt'"
                )
            )
        except Exception:
            restore_trans.rollback()
            raise
        else:
            restore_trans.commit()
        finally:
            restore_conn.close()


@pytest.mark.integration
def test_clean_downgrade_with_no_dispatch_history_reupgrade_restores_exact_cmp016_state(test_engine) -> None:
    """No dispatch history at all: downgrade must succeed, drop the
    dispatch tables/triggers, restore the byte-exact original CMP-016
    CHECK bodies and trigger attachment, preserve every existing packing
    receipt untouched, and re-upgrade must reattach the v2 trigger."""
    require_cmp_test(test_engine)
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=3, packed_output_weight_kg=Decimal("2.000"))
    session.commit()

    def _receipt_snapshot():
        with test_engine.connect() as c:
            return dict(
                c.execute(
                    text(
                        "SELECT id, tenant_id, farm_id, finished_goods_lot_id, packing_event_id, entry_kind, "
                        "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note "
                        "FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = :lid"
                    ),
                    {"lid": fg_lot_id},
                ).mappings().one()
            )

    receipt_before = _receipt_snapshot()
    session.close()
    conn.close()

    with test_engine.connect() as c:
        # CMP-018 sits above CMP-017 at "head", so the currently-attached
        # function is v3 (which supersedes v2's attachment), not v2 itself
        # -- see test_finished_goods_storage_downgrade_guard.py for CMP-018's
        # own dedicated downgrade/re-upgrade proof.
        v3_before = c.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                "AND tgfoid = 'enforce_finished_goods_ledger_entry_insert_integrity_v3'::regproc"
            )
        ).scalar_one()
        assert v3_before == 1, "the v3 trigger must be attached at head"

    try:
        command.downgrade(_cfg(), _PRE_CMP017_REVISION)
        with test_engine.connect() as c:
            current = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == _PRE_CMP017_REVISION

            tables = c.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                    "AND table_name IN ('dispatch_events', 'dispatch_lines')"
                )
            ).scalars().all()
            assert tables == [], "downgrade must drop both dispatch tables"

            checks = dict(
                c.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid = 'finished_goods_ledger_entries'::regclass AND conname = ANY(:names)"
                    ),
                    {
                        "names": [
                            "ck_finished_goods_ledger_entries_kind_allowed",
                            "ck_finished_goods_ledger_entries_deterministic_id",
                            "ck_finished_goods_ledger_entries_weight_envelope",
                            "ck_finished_goods_ledger_entries_count_positive",
                        ]
                    },
                ).all()
            )
            assert checks["ck_finished_goods_ledger_entries_kind_allowed"] == _CMP016_KIND_ALLOWED_DEF
            assert checks["ck_finished_goods_ledger_entries_deterministic_id"] == _CMP016_DETERMINISTIC_ID_DEF
            assert checks["ck_finished_goods_ledger_entries_weight_envelope"] == _CMP016_WEIGHT_ENVELOPE_DEF
            assert checks["ck_finished_goods_ledger_entries_count_positive"] == _CMP016_COUNT_POSITIVE_DEF

            packing_event_nullable = c.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'finished_goods_ledger_entries' AND column_name = 'packing_event_id'"
                )
            ).scalar_one()
            assert packing_event_nullable == "NO", "downgrade must restore packing_event_id NOT NULL"

            # Downgrade must have dropped the v2 function entirely, so a
            # direct `'...'::regproc` cast here would itself raise
            # UndefinedFunction — `to_regproc` is the NULL-safe variant,
            # returning NULL (never matching tgfoid) when the function is
            # genuinely absent.
            v2_after_downgrade = c.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                    "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                    "AND tgfoid = to_regproc('enforce_finished_goods_ledger_entry_insert_integrity_v2')"
                )
            ).scalar_one()
            assert v2_after_downgrade == 0
            v2_function_exists = c.execute(
                text("SELECT to_regproc('enforce_finished_goods_ledger_entry_insert_integrity_v2') IS NOT NULL")
            ).scalar_one()
            assert v2_function_exists is False, "clean downgrade must drop the v2 function entirely"
            original_after_downgrade = c.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                    "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                    "AND tgfoid = 'enforce_finished_goods_ledger_entry_insert_integrity'::regproc"
                )
            ).scalar_one()
            assert original_after_downgrade == 1, "clean downgrade must restore the exact original CMP-016 trigger attachment"

            receipt_still_present = c.execute(
                text(
                    "SELECT id, tenant_id, farm_id, finished_goods_lot_id, packing_event_id, entry_kind, "
                    "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note "
                    "FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = :lid"
                ),
                {"lid": fg_lot_id},
            ).mappings().one()
            assert dict(receipt_still_present) == receipt_before, "the existing packing receipt must survive untouched"

        command.upgrade(_cfg(), "head")
        with test_engine.connect() as c:
            current = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == _resolve_head_revision(_cfg())
            # CMP-018 sits above CMP-017 at "head", so re-upgrading here also
            # reattaches its own v3 trigger (superseding v2's attachment).
            v3_after_reupgrade = c.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                    "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                    "AND tgfoid = 'enforce_finished_goods_ledger_entry_insert_integrity_v3'::regproc"
                )
            ).scalar_one()
            assert v3_after_reupgrade == 1, "re-upgrade must reattach the v3 trigger"
            receipt_after_reupgrade = dict(
                c.execute(
                    text(
                        "SELECT id, tenant_id, farm_id, finished_goods_lot_id, packing_event_id, entry_kind, "
                        "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note "
                        "FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = :lid"
                    ),
                    {"lid": fg_lot_id},
                ).mappings().one()
            )
            assert receipt_after_reupgrade == receipt_before, "re-upgrade must leave the receipt byte-identical"
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])
