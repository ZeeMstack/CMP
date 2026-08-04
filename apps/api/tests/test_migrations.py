from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.settings import settings

API_ROOT = Path(__file__).resolve().parent.parent


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _assert_operating_on_cmp_test_database(test_engine) -> None:
    """Every test in this file runs a destructive schema downgrade/upgrade
    cycle. Before any of them touch the database, confirm — by literal
    database name, not just by the pre-existing
    `test_database_url != database_url` distinctness check in conftest.py —
    that the connection genuinely points at `cmp_test`. Never run a
    destructive reset against anything else."""
    with test_engine.connect() as conn:
        current_db = conn.execute(text("SELECT current_database()")).scalar_one()
    assert current_db == "cmp_test", (
        f"refusing destructive migration downgrade/upgrade against database {current_db!r} — "
        "expected exactly 'cmp_test'"
    )


@pytest.mark.integration
def test_migration_downgrade_then_upgrade_on_test_database(test_engine) -> None:
    command.downgrade(_cfg(), "base")
    command.upgrade(_cfg(), "head")


@pytest.mark.integration
def test_migration_downgrade_removes_classification_trigger_and_function(test_engine) -> None:
    command.downgrade(_cfg(), "471bdd408a33")
    with test_engine.connect() as conn:
        trigger_exists = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgname = 'locations_enforce_greenhouse_classification'"
            )
        ).first()
        function_exists = conn.execute(
            text("SELECT 1 FROM pg_proc WHERE proname = 'enforce_location_greenhouse_classification'")
        ).first()
    assert trigger_exists is None
    assert function_exists is None

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        trigger_exists = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgname = 'locations_enforce_greenhouse_classification'"
            )
        ).first()
    assert trigger_exists is not None


@pytest.mark.integration
def test_migration_downgrade_removes_asset_carrier_triggers_and_functions(test_engine) -> None:
    command.downgrade(_cfg(), "3cbaeceee9dc")
    with test_engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN ("
                "'asset_positions_enforce_structure', 'assets_no_delete', "
                "'carriers_no_delete', 'asset_positions_no_delete')"
            )
        ).all()
        functions = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN "
                "('enforce_asset_position_structure', 'reject_hard_delete')"
            )
        ).all()
    assert triggers == []
    assert functions == []

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        trigger_exists = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'asset_positions_enforce_structure'")
        ).first()
    assert trigger_exists is not None


@pytest.mark.integration
def test_migration_downgrade_removes_crop_workflow_triggers_and_functions(test_engine) -> None:
    command.downgrade(_cfg(), "8a2c6f1e9d33")
    with test_engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN ("
                "'workflows_enforce_identity_immutable', 'workflow_transitions_enforce_draft_only', "
                "'workflow_stages_enforce_draft_only', 'workflow_versions_no_delete_when_published', "
                "'workflow_versions_enforce_transition')"
            )
        ).all()
        functions = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN ("
                "'enforce_workflow_identity_immutable', 'enforce_workflow_transition_draft_only', "
                "'enforce_workflow_stage_draft_only', 'reject_non_draft_workflow_version_delete', "
                "'enforce_workflow_version_transition')"
            )
        ).all()
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN ("
                "'crops', 'varieties', 'production_systems', 'workflows', 'workflow_versions', "
                "'workflow_stages', 'workflow_transitions')"
            )
        ).all()
    assert triggers == []
    assert functions == []
    assert tables == []

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        trigger_exists = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'workflows_enforce_identity_immutable'")
        ).first()
    assert trigger_exists is not None


@pytest.mark.integration
def test_migration_downgrade_removes_crop_batch_triggers_functions_and_additive_constraints(
    test_engine,
) -> None:
    command.downgrade(_cfg(), "b2f6c9d3e178")
    with test_engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN ("
                "'crop_batches_enforce_lifecycle', 'crop_batches_no_delete', "
                "'batch_stage_runs_enforce_closure_only', 'batch_stage_runs_enforce_insert_integrity', "
                "'batch_stage_runs_no_delete', 'batch_stage_transitions_enforce_version_match', "
                "'batch_stage_transitions_no_update', 'batch_stage_transitions_no_delete')"
            )
        ).all()
        functions = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN ("
                "'enforce_crop_batch_lifecycle', 'enforce_batch_stage_run_closure_only', "
                "'enforce_batch_stage_run_insert_integrity', "
                "'enforce_batch_stage_transition_version_match', 'reject_append_only_mutation')"
            )
        ).all()
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN ("
                "'crop_batches', 'batch_stage_runs', 'batch_stage_transitions')"
            )
        ).all()
        additive_constraints = conn.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conname IN ("
                "'uq_farms_tenant_id_id', 'uq_workflow_versions_tenant_workflow_id', "
                "'uq_workflow_transitions_tenant_version_id')"
            )
        ).all()
        prior_ticket_constraint = conn.execute(
            text("SELECT 1 FROM pg_indexes WHERE indexname = 'ux_farms_tenant_code_lower'")
        ).first()
    assert triggers == []
    assert functions == []
    assert tables == []
    assert additive_constraints == []
    assert prior_ticket_constraint is not None, "prior-ticket farms schema must remain intact"

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        trigger_exists = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'crop_batches_enforce_lifecycle'")
        ).first()
        constraint_exists = conn.execute(
            text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_farms_tenant_id_id'")
        ).first()
    assert trigger_exists is not None
    assert constraint_exists is not None


@pytest.mark.integration
def test_migration_downgrade_removes_seed_sowing_triggers_functions_and_additive_constraints(
    test_engine,
) -> None:
    command.downgrade(_cfg(), "c48f21a6b3d9")
    with test_engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN ("
                "'seed_lots_no_delete', 'sowing_events_enforce_insert_integrity', "
                "'sowing_events_no_update', 'sowing_events_no_delete', "
                "'batch_carrier_assignments_enforce_insert_integrity', "
                "'batch_carrier_assignments_no_update', 'batch_carrier_assignments_no_delete', "
                "'sowing_event_lines_enforce_insert_integrity', 'sowing_event_lines_no_update', "
                "'sowing_event_lines_no_delete')"
            )
        ).all()
        functions = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN ("
                "'enforce_sowing_event_insert_integrity', "
                "'enforce_batch_carrier_assignment_insert_integrity', "
                "'enforce_sowing_event_line_insert_integrity')"
            )
        ).all()
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN ("
                "'seed_lots', 'sowing_events', 'batch_carrier_assignments', 'sowing_event_lines')"
            )
        ).all()
        additive_constraints = conn.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conname IN ("
                "'uq_carriers_tenant_farm_id', 'uq_batch_stage_runs_tenant_farm_batch_id')"
            )
        ).all()
        prior_ticket_constraint = conn.execute(
            text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_crop_batches_tenant_farm_id'")
        ).first()
        shared_function_still_present = conn.execute(
            text("SELECT 1 FROM pg_proc WHERE proname = 'reject_append_only_mutation'")
        ).first()
    assert triggers == []
    assert functions == []
    assert tables == []
    assert additive_constraints == []
    assert prior_ticket_constraint is not None, "prior-ticket crop_batches schema must remain intact"
    assert shared_function_still_present is not None, "reject_append_only_mutation is shared with CMP-008"

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        trigger_exists = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'sowing_events_enforce_insert_integrity'")
        ).first()
        constraint_exists = conn.execute(
            text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_carriers_tenant_farm_id'")
        ).first()
    assert trigger_exists is not None
    assert constraint_exists is not None


@pytest.mark.integration
def test_migration_downgrade_removes_observation_quality_triggers_functions_and_tables(test_engine) -> None:
    command.downgrade(_cfg(), "d17a4e2f9c86")
    with test_engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN ("
                "'observation_definitions_enforce_status_only_update', 'observation_definitions_no_delete', "
                "'observation_events_enforce_insert_integrity', 'observation_events_no_update', "
                "'observation_events_no_delete', 'observation_values_enforce_insert_integrity', "
                "'observation_values_no_update', 'observation_values_no_delete', "
                "'germination_checks_enforce_insert_integrity', 'germination_checks_no_update', "
                "'germination_checks_no_delete', 'quality_holds_enforce_insert_integrity', "
                "'quality_holds_no_update', 'quality_holds_no_delete', "
                "'quality_hold_releases_enforce_insert_integrity', 'quality_hold_releases_no_update', "
                "'quality_hold_releases_no_delete', 'batch_stage_transitions_enforce_no_open_hold')"
            )
        ).all()
        functions = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN ("
                "'enforce_observation_definition_status_only_update', "
                "'enforce_observation_event_insert_integrity', "
                "'enforce_observation_value_insert_integrity', "
                "'enforce_germination_check_insert_integrity', "
                "'enforce_quality_hold_insert_integrity', "
                "'enforce_quality_hold_release_insert_integrity', "
                "'enforce_no_open_quality_hold')"
            )
        ).all()
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN ("
                "'observation_definitions', 'observation_events', 'observation_values', "
                "'germination_checks', 'quality_holds', 'quality_hold_releases')"
            )
        ).all()
        shared_function_still_present = conn.execute(
            text("SELECT 1 FROM pg_proc WHERE proname = 'reject_append_only_mutation'")
        ).first()
        prior_ticket_table_intact = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'batch_stage_transitions'")
        ).first()
        prior_ticket_constraint_intact = conn.execute(
            text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_sowing_events_tenant_farm_id'")
        ).first()
    assert triggers == []
    assert functions == []
    assert tables == []
    assert shared_function_still_present is not None, "reject_append_only_mutation is shared with CMP-008/009"
    assert prior_ticket_table_intact is not None, "prior-ticket batch_stage_transitions must remain intact"
    assert prior_ticket_constraint_intact is not None, "prior-ticket sowing_events schema must remain intact"

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        trigger_exists = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'observation_events_enforce_insert_integrity'")
        ).first()
        hold_block_trigger_exists = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'batch_stage_transitions_enforce_no_open_hold'")
        ).first()
    assert trigger_exists is not None
    assert hold_block_trigger_exists is not None


@pytest.mark.integration
def test_migration_downgrade_removes_occupancy_and_movement_triggers_and_functions(test_engine) -> None:
    command.downgrade(_cfg(), "5f3a9c2d1b44")
    with test_engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN ("
                "'occupancies_enforce_insert_integrity', 'occupancies_enforce_closure_only', "
                "'occupancies_no_delete', 'movements_no_update', 'movements_no_delete')"
            )
        ).all()
        functions = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN "
                "('enforce_occupancy_insert_integrity', 'enforce_occupancy_closure_only', "
                "'reject_movement_mutation')"
            )
        ).all()
    assert triggers == []
    assert functions == []

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        trigger_exists = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'occupancies_enforce_insert_integrity'")
        ).first()
    assert trigger_exists is not None


# --- CMP-011: carrier release and transplantation ---------------------------
#
# The two "blocked downgrade" guard tests live in their own file,
# test_transplant_downgrade_guard.py. They commit real
# transplant/transplanting-stage rows via dedicated connections, but — like
# test_transplant_concurrency.py and test_transplant_rollback.py's deferred
# tests — they clean up everything they commit in a `finally` block, scoped
# to their own tenant, using the same `session_replication_role = replica`
# bypass technique. That is what keeps this test's assumption below valid
# regardless of execution order: no CMP-011 test is meant to leave
# transplant history, transplant-created assignments, or a
# transplanting-category workflow stage behind for another test to observe.
# This test does not itself rely on running before or after any other file —
# it relies only on every other CMP-011 test cleaning up after itself, which
# is verified separately by the repeated/randomized-order runs in the
# correction report.
#
# The downgrade/upgrade cycle below is destructive schema DDL, so it first
# confirms it is genuinely operating against `cmp_test`, and guarantees head
# is restored in `finally` even if an assertion below fails mid-test — a
# failed assertion here must never leave the database downgraded for
# whichever test runs next.


@pytest.mark.integration
def test_migration_downgrade_removes_transplant_triggers_functions_tables_and_restores_cmp009_shape(
    test_engine,
) -> None:
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), "e29b5c1a7d43")
    try:
        _assert_downgraded_transplant_schema_removed(test_engine)
    finally:
        command.upgrade(_cfg(), "head")
    _assert_upgraded_transplant_schema_restored(test_engine)


def _assert_downgraded_transplant_schema_removed(test_engine) -> None:
    with test_engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN ("
                "'transplant_events_enforce_insert_integrity', 'transplant_events_no_update', "
                "'transplant_events_no_delete', 'transplant_source_lines_enforce_insert_integrity', "
                "'transplant_source_lines_no_update', 'transplant_source_lines_no_delete', "
                "'transplant_destination_lines_enforce_insert_integrity', "
                "'transplant_destination_lines_no_update', 'transplant_destination_lines_no_delete', "
                "'transplant_allocations_no_update', 'transplant_allocations_no_delete', "
                "'transplant_events_enforce_reconciliation', 'transplant_source_lines_enforce_reconciliation', "
                "'transplant_destination_lines_enforce_reconciliation', "
                "'transplant_allocations_enforce_reconciliation', "
                "'batch_carrier_assignments_enforce_reconciliation_on_open', "
                "'batch_carrier_assignments_enforce_reconciliation_on_release', "
                "'batch_carrier_assignments_enforce_origin_insert_integrity', "
                "'batch_carrier_assignments_enforce_closure_only')"
            )
        ).all()
        functions = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN ("
                "'enforce_transplant_event_insert_integrity', "
                "'enforce_transplant_source_line_insert_integrity', "
                "'enforce_transplant_destination_line_insert_integrity', "
                "'enforce_transplant_reconciliation', "
                "'enforce_batch_carrier_assignment_origin_insert_integrity', "
                "'enforce_batch_carrier_assignment_closure_only')"
            )
        ).all()
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN ("
                "'transplant_events', 'transplant_source_lines', 'transplant_destination_lines', "
                "'transplant_allocations')"
            )
        ).all()
        assignment_columns = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'batch_carrier_assignments' "
                "AND column_name IN ('opening_transplant_event_id', 'released_by_transplant_event_id')"
            )
        ).all()
        opening_sowing_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'batch_carrier_assignments' "
                "AND column_name = 'opening_sowing_event_id'"
            )
        ).scalar_one()
        category_check_def = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_workflow_stages_category_allowed'"
            )
        ).scalar_one()
        # CMP-009's original function and trigger must have been restored
        # untouched — never dropped, only re-attached.
        cmp009_trigger = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgname = 'batch_carrier_assignments_enforce_insert_integrity'"
            )
        ).first()
        cmp009_function = conn.execute(
            text("SELECT 1 FROM pg_proc WHERE proname = 'enforce_batch_carrier_assignment_insert_integrity'")
        ).first()
        cmp009_update_trigger = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'batch_carrier_assignments_no_update'")
        ).first()
        shared_function_still_present = conn.execute(
            text("SELECT 1 FROM pg_proc WHERE proname = 'reject_append_only_mutation'")
        ).first()
        prior_ticket_constraint_intact = conn.execute(
            text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_sowing_events_tenant_farm_id'")
        ).first()
    assert triggers == []
    assert functions == []
    assert tables == []
    assert assignment_columns == []
    assert opening_sowing_nullable == "NO"
    assert "transplanting" not in category_check_def
    assert cmp009_trigger is not None
    assert cmp009_function is not None
    assert cmp009_update_trigger is not None
    assert shared_function_still_present is not None, "reject_append_only_mutation is shared with CMP-008/009/010"
    assert prior_ticket_constraint_intact is not None, "prior-ticket sowing_events schema must remain intact"


def _assert_upgraded_transplant_schema_restored(test_engine) -> None:
    with test_engine.connect() as conn:
        trigger_exists = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'transplant_events_enforce_insert_integrity'")
        ).first()
        deferred_trigger_exists = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgname = "
                "'batch_carrier_assignments_enforce_reconciliation_on_release'"
            )
        ).first()
        category_check_def = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_workflow_stages_category_allowed'"
            )
        ).scalar_one()
    assert trigger_exists is not None
    assert deferred_trigger_exists is not None
    assert "transplanting" in category_check_def
