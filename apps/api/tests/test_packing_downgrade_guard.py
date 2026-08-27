"""CMP-015 downgrade-guard proof tests.

Unlike CMP-014's own guard (which only blocks on genuinely unreconstructible
data), CMP-015's guard blocks on the mere *existence* of any packing history
— packing events, input lines, finished-goods lots, or packing_consumption
ledger debits are all independent operational facts, not projections of
older data, so downgrading past CMP-015 while any exists would silently
discard them. This file also proves the v2 ledger insert-integrity trigger
attachment cleanly replaces (not supplements) CMP-014's own, and that a
clean downgrade restores the exact original CMP-014 attachment."""
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
from app.services import packing_service
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, require_cmp_test

API_ROOT = Path(__file__).resolve().parent.parent
# Specific, historically fixed migration under test — the target this test
# downgrades to — is safe to hardcode; "current head" is not.
_PRE_CMP015_REVISION = "de82132ef837"


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


def _pack_one(scenario, db) -> None:
    packing_service.record_packing(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), pack_specification_version_id=scenario["pack_specification_version_id"],
        effective_time=_now(),
        finished_goods_lot_code=f"FG-{scenario['suffix']}", package_count=1,
        packed_output_weight_kg=Decimal("2.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("2.000"), "consumed_whole_unit_count": None, "note": None}],
    )


@pytest.mark.integration
def test_downgrade_blocked_when_packing_history_exists(test_engine, alembic_head_restore) -> None:
    # CARRIER-CONFIG-001A: packing history existence is unrelated to
    # carrier type -- grow_bag keeps the scenario free of a
    # carrier_specifications row, which would otherwise unconditionally
    # block via e5b8c3a72f04's own, earlier-in-chain guard before this
    # guard is ever reached.
    #
    # POSTHARVEST-OPS-001E: real packing history is now GPL-input, which
    # trips POSTHARVEST-OPS-001E's OWN downgrade guard (in d8f4a1c92b57)
    # before the cascade ever reaches CMP-015's original guard further
    # down the chain -- 001E's migration sits directly above CMP-015's own
    # and blocks unconditionally on the same packing_events/
    # packing_input_lines existence check. This test now proves that
    # outer guard; CMP-015's own guard remains independently in place for
    # a downgrade that starts already below 001E.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    _pack_one(scenario, session)
    # Release any implicit post-commit transaction before triggering a
    # downgrade cascade from another connection — the same lesson learned
    # from CMP-014's own harvest_downgrade_guard fix.
    session.commit()
    session.close()
    conn.close()

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP015_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_clean_downgrade_and_reupgrade_restores_original_cmp014_trigger(test_engine, alembic_head_restore) -> None:
    require_cmp_test(test_engine)

    with test_engine.connect() as conn:
        v2_before = conn.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'produce_lot_ledger_entries'::regclass "
                "AND tgname = 'produce_lot_ledger_entries_enforce_insert_integrity_v2'"
            )
        ).scalar_one()
        assert v2_before == 1, "the v2 trigger must be attached at head"
        original_before = conn.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'produce_lot_ledger_entries'::regclass "
                "AND tgname = 'produce_lot_ledger_entries_enforce_insert_integrity'"
            )
        ).scalar_one()
        assert original_before == 0, "the v2 trigger must replace, not supplement, CMP-014's own attachment"

    command.downgrade(_cfg(), _PRE_CMP015_REVISION)
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _PRE_CMP015_REVISION
        v2_after_downgrade = conn.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'produce_lot_ledger_entries'::regclass "
                "AND tgname = 'produce_lot_ledger_entries_enforce_insert_integrity_v2'"
            )
        ).scalar_one()
        assert v2_after_downgrade == 0
        original_after_downgrade = conn.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'produce_lot_ledger_entries'::regclass "
                "AND tgname = 'produce_lot_ledger_entries_enforce_insert_integrity'"
            )
        ).scalar_one()
        assert original_after_downgrade == 1, "clean downgrade must restore the exact original CMP-014 trigger attachment"
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name IN ('packing_events', 'packing_input_lines', 'finished_goods_lots')"
            )
        ).scalars().all()
        assert tables == []

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _resolve_head_revision(_cfg())
        v2_after_reupgrade = conn.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'produce_lot_ledger_entries'::regclass "
                "AND tgname = 'produce_lot_ledger_entries_enforce_insert_integrity_v2'"
            )
        ).scalar_one()
        assert v2_after_reupgrade == 1, "re-upgrade must reattach the v2 trigger"


@pytest.mark.integration
def test_downgrade_blocked_when_only_packing_event_and_ledger_debit_remain(test_engine, alembic_head_restore) -> None:
    """Direct-SQL defense: even a partially-torn-down packing history (input
    lines and the finished-goods lot removed, leaving only the event and its
    ledger debit — the debit's own composite FK to packing_events means the
    event can never be removed while the debit remains) still blocks
    downgrade, proving the guard does not depend on every row existing
    together. The CMP-016 opening receipt is removed along with its lot
    (both are torn down here as one unit) so this remains a proof of the
    unconditional guard specifically — without it, the orphaned receipt
    left behind would trip CMP-016's own (correct, and separately proven
    in test_finished_goods_ledger_downgrade_guard.py) orphan-receipt guard
    first, since CMP-016 now sits above CMP-015 in the downgrade cascade.

    POSTHARVEST-OPS-001E: the remaining bare `packing_events` row alone
    already trips 001E's OWN downgrade guard (in d8f4a1c92b57), which sits
    directly above CMP-015's own guard in the cascade and fires first."""
    # CARRIER-CONFIG-001A: packing history existence is unrelated to
    # carrier type -- grow_bag keeps the scenario free of a
    # carrier_specifications row, which would otherwise unconditionally
    # block via e5b8c3a72f04's own, earlier-in-chain guard before this
    # guard is ever reached.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    _pack_one(scenario, session)
    session.commit()

    require_cmp_test(test_engine)
    conn2 = test_engine.connect()
    trans = conn2.begin()
    try:
        conn2.execute(text("SET session_replication_role = replica"))
        conn2.execute(text("DELETE FROM finished_goods_ledger_entries WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]})
        conn2.execute(text("DELETE FROM packing_input_lines WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]})
        conn2.execute(text("DELETE FROM finished_goods_lots WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]})
        conn2.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    except Exception:
        trans.rollback()
        conn2.execute(text("SET session_replication_role = DEFAULT"))
        conn2.commit()
        raise
    finally:
        conn2.close()

    session.close()
    conn.close()

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP015_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])
