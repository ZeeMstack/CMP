"""POSTHARVEST-OPS-001C migration proofs: sole head, clean downgrade/
re-upgrade, the unconditional downgrade guard when persisted GradingEvent /
GradedProduceLot / graded ledger / grading_consumption history exists, and
exact restoration of the prior (HARVEST-OPS-001) produce_lot_ledger_entries
trigger/check shape on downgrade -- mirrors test_pack_specification_
migration.py's own conventions exactly."""
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.settings import settings
from tests._grading_scenario import build_committed_scenario, cleanup_scenario
from tests.test_grading import _grade, _output, _session

API_ROOT = Path(__file__).resolve().parent.parent
_THIS_REVISION = "f2c8a5d1e793"
_PARENT_REVISION = "e8d5f3a2b6c1"


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_head_revision(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_current_head()


def _assert_at_head(test_engine) -> None:
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    expected_head = _resolve_head_revision(_cfg())
    assert current == expected_head, "a blocked downgrade must leave the database at Alembic head"


@pytest.mark.integration
def test_migration_upgrades_from_prior_revision() -> None:
    script = ScriptDirectory.from_config(_cfg())
    this_revision = script.get_revision(_THIS_REVISION)
    assert this_revision.down_revision == _PARENT_REVISION


@pytest.mark.integration
def test_this_revision_remains_the_sole_chains_direct_ancestor() -> None:
    """POSTHARVEST-OPS-001D (`c3f7a29d5e64`) now sits on top of this
    migration -- `f2c8a5d1e793` is no longer itself the head, but must
    remain part of the one single, unambiguous chain leading to it, never
    orphaned by a competing branch. `test_migrations.py`'s own
    `test_alembic_script_graph_resolves_single_unambiguous_head` proves
    the "exactly one head" half generically for every revision; this test
    keeps this ticket's own local proof that its specific revision is
    still on that one chain, updated for whichever ticket currently sits
    on top of it."""
    cfg = _cfg()
    script = ScriptDirectory.from_config(cfg)
    rev = script.get_revision(_resolve_head_revision(cfg))
    ancestors = set()
    while rev is not None:
        ancestors.add(rev.revision)
        rev = script.get_revision(rev.down_revision) if rev.down_revision else None
    assert _THIS_REVISION in ancestors


@pytest.mark.integration
def test_downgrade_blocked_when_grading_event_exists_with_zero_outputs(test_engine, alembic_head_restore) -> None:
    """A GradingEvent with zero saleable outputs (fully rejected/lost/
    sampled) still creates no GradedProduceLot at all -- the guard must
    still fire on GradingEvent existence alone."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="10.000", rejected="5.000", loss="3.000", sample="2.000",
            remainder="0", outputs=[],
        )
        session.commit()
        with test_engine.connect() as verify_conn:
            assert verify_conn.execute(text("SELECT count(*) FROM graded_produce_lots")).scalar_one() == 0
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001C"):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_when_graded_produce_lot_exists(test_engine, alembic_head_restore) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000")],
        )
        session.commit()
        with test_engine.connect() as verify_conn:
            assert verify_conn.execute(text("SELECT count(*) FROM graded_produce_lots")).scalar_one() >= 1
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001C"):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_when_graded_ledger_entry_exists(test_engine, alembic_head_restore) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000")],
        )
        session.commit()
        with test_engine.connect() as verify_conn:
            assert verify_conn.execute(
                text("SELECT count(*) FROM graded_produce_lot_ledger_entries WHERE entry_kind = 'grading_receipt'")
            ).scalar_one() >= 1
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001C"):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_when_grading_consumption_history_exists(test_engine, alembic_head_restore) -> None:
    """Even a zero-output GradingEvent (no GradedProduceLot at all) still
    leaves a `grading_consumption` debit on `produce_lot_ledger_entries` --
    the guard must fire on that history alone, independent of the other
    three counts."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _grade(
            scenario, db=session, input_presented="10.000", rejected="10.000", loss="0", sample="0",
            remainder="0", outputs=[],
        )
        session.commit()
        with test_engine.connect() as verify_conn:
            assert verify_conn.execute(
                text("SELECT count(*) FROM produce_lot_ledger_entries WHERE entry_kind = 'grading_consumption'")
            ).scalar_one() >= 1
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001C"):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_clean_downgrade_and_reupgrade_restores_prior_ledger_shape(test_engine, alembic_head_restore) -> None:
    expected_tables = ["grading_events", "graded_produce_lots", "graded_produce_lot_ledger_entries"]
    with test_engine.connect() as conn:
        tables_before = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name = ANY(:names)"
            ),
            {"names": expected_tables},
        ).scalars().all()
        assert sorted(tables_before) == sorted(expected_tables)
        assert conn.execute(text("SELECT count(*) FROM grading_events")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM graded_produce_lots")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM graded_produce_lot_ledger_entries")).scalar_one() == 0
        assert conn.execute(
            text("SELECT count(*) FROM produce_lot_ledger_entries WHERE entry_kind = 'grading_consumption'")
        ).scalar_one() == 0
        ledger_body_before = conn.execute(
            text("SELECT pg_get_functiondef(oid) FROM pg_proc WHERE proname = "
                 "'enforce_produce_lot_ledger_entry_insert_integrity_v2'")
        ).scalar_one()
        assert "grading_consumption" in ledger_body_before
        assert "packing_consumption" in ledger_body_before

    command.downgrade(_cfg(), _PARENT_REVISION)
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _PARENT_REVISION
        tables_after_downgrade = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name = ANY(:names)"
            ),
            {"names": expected_tables},
        ).scalars().all()
        assert tables_after_downgrade == []

        functions_after_downgrade = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN "
                "('enforce_grading_event_insert_integrity', 'enforce_graded_produce_lot_insert_integrity', "
                " 'enforce_graded_produce_lot_ledger_entry_insert_integrity', 'enforce_grading_reconciliation', "
                " 'enforce_graded_produce_lot_ledger_reconciliation')"
            )
        ).scalars().all()
        assert functions_after_downgrade == [], "downgrade must drop every function it created"

        # --- item 87: prior ProduceLot ledger trigger/check shape restored exactly ---
        ledger_body_after = conn.execute(
            text("SELECT pg_get_functiondef(oid) FROM pg_proc WHERE proname = "
                 "'enforce_produce_lot_ledger_entry_insert_integrity_v2'")
        ).scalar_one()
        assert "grading_consumption" not in ledger_body_after
        assert "packing_consumption" in ledger_body_after, "restoring the prior shape must not regress Packing"
        assert "harvest_adjustment" in ledger_body_after

        trigger_row = conn.execute(
            text(
                "SELECT tgname, tgrelid::regclass::text FROM pg_trigger "
                "WHERE tgfoid = 'enforce_produce_lot_ledger_entry_insert_integrity_v2()'::regprocedure "
                "AND NOT tgisinternal"
            )
        ).one()
        assert trigger_row[1] == "produce_lot_ledger_entries"

        allowed_kinds = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_produce_lot_ledger_entries_kind_allowed'"
            )
        ).scalar_one()
        assert "grading_consumption" not in allowed_kinds
        for kind in ("harvest_receipt", "packing_consumption", "harvest_adjustment"):
            assert kind in allowed_kinds

        column_exists = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_name = 'produce_lot_ledger_entries' "
                "AND column_name = 'grading_event_id'"
            )
        ).scalar_one()
        assert column_exists == 0

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _resolve_head_revision(_cfg())
        tables_after_reupgrade = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name = ANY(:names)"
            ),
            {"names": expected_tables},
        ).scalars().all()
        assert sorted(tables_after_reupgrade) == sorted(expected_tables)

        trigger_count = conn.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgname IN "
                "('grading_events_no_delete', 'grading_events_no_update', "
                " 'graded_produce_lots_no_delete', 'graded_produce_lots_no_update', "
                " 'graded_produce_lot_ledger_entries_no_delete', 'graded_produce_lot_ledger_entries_no_update', "
                " 'grading_events_enforce_insert_integrity', 'graded_produce_lots_enforce_insert_integrity', "
                " 'graded_produce_lot_ledger_entries_enforce_insert_integrity', "
                " 'grading_events_enforce_reconciliation', 'graded_produce_lots_enforce_grading_reconciliation', "
                " 'produce_lot_ledger_entries_enforce_grading_reconciliation', "
                " 'graded_produce_lots_enforce_ledger_reconciliation', "
                " 'graded_produce_lot_ledger_entries_enforce_reconciliation')"
            )
        ).scalar_one()
        assert trigger_count == 14, "re-upgrade must recreate every trigger this migration owns"

        ledger_body_reupgraded = conn.execute(
            text("SELECT pg_get_functiondef(oid) FROM pg_proc WHERE proname = "
                 "'enforce_produce_lot_ledger_entry_insert_integrity_v2'")
        ).scalar_one()
        assert "grading_consumption" in ledger_body_reupgraded
        assert "packing_consumption" in ledger_body_reupgraded
