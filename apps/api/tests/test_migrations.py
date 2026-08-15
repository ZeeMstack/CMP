from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.settings import settings

API_ROOT = Path(__file__).resolve().parent.parent


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_head_revision(cfg: Config) -> str:
    """Never hardcode "current head" in a test — resolve it dynamically from
    the Alembic script graph so tests that assert "at head" stay correct as
    later tickets add revisions on top of whichever one is head today."""
    return ScriptDirectory.from_config(cfg).get_current_head()


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
def test_migration_downgrade_then_upgrade_on_test_database(test_engine, alembic_head_restore) -> None:
    command.downgrade(_cfg(), "base")
    command.upgrade(_cfg(), "head")


@pytest.mark.integration
def test_alembic_script_graph_resolves_single_unambiguous_head() -> None:
    """Guards against a future migration accidentally creating a second,
    divergent head (e.g. a bad down_revision) — every downgrade-guard test
    in this suite that resolves "current head" dynamically depends on there
    being exactly one."""
    script = ScriptDirectory.from_config(_cfg())
    heads = script.get_heads()
    assert len(heads) == 1, f"expected exactly one Alembic head, found {heads}"


@pytest.mark.integration
def test_migration_upgrade_head_matches_dynamically_resolved_alembic_head(test_engine) -> None:
    """Proves the dynamic head-resolution helper actually tracks whichever
    migration is current head (CMP-012 today) without any test hardcoding
    its revision string — the same helper test_transplant_downgrade_guard.py
    and test_batch_derivation_downgrade_guard.py use."""
    _assert_operating_on_cmp_test_database(test_engine)
    command.upgrade(_cfg(), "head")
    expected_head = _resolve_head_revision(_cfg())
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert current == expected_head


@pytest.mark.integration
def test_migration_downgrade_removes_classification_trigger_and_function(test_engine, alembic_head_restore) -> None:
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
def test_migration_downgrade_removes_asset_carrier_triggers_and_functions(test_engine, alembic_head_restore) -> None:
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
def test_migration_downgrade_removes_crop_workflow_triggers_and_functions(test_engine, alembic_head_restore) -> None:
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
    test_engine, alembic_head_restore,
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
        # Not `crop_batches_enforce_lifecycle` itself: CMP-012 supersedes
        # that trigger attachment with `crop_batches_enforce_lifecycle_v2`
        # (same pattern CMP-011 already used for CMP-009's
        # `batch_carrier_assignments_enforce_insert_integrity`), so this
        # smoke check uses a CMP-008 trigger no later ticket has touched.
        trigger_exists = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'batch_stage_transitions_enforce_version_match'")
        ).first()
        constraint_exists = conn.execute(
            text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_farms_tenant_id_id'")
        ).first()
    assert trigger_exists is not None
    assert constraint_exists is not None


@pytest.mark.integration
def test_migration_downgrade_removes_seed_sowing_triggers_functions_and_additive_constraints(
    test_engine, alembic_head_restore,
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
def test_migration_downgrade_removes_observation_quality_triggers_functions_and_tables(test_engine, alembic_head_restore) -> None:
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
def test_migration_downgrade_removes_occupancy_and_movement_triggers_and_functions(test_engine, alembic_head_restore) -> None:
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
    test_engine, alembic_head_restore,
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


# --- CMP-012: crop-batch split and merge lineage foundation -----------------------
#
# Isolation here follows the same self-cleaning discipline as CMP-011's own
# section: no test in this file assumes a particular collection order, and
# no committed-connection scenario is built here — this file only exercises
# the migration's own downgrade/upgrade DDL cycle, never real derivation
# data (that lives in test_batch_derivation_downgrade_guard.py, which cleans
# up after itself).


@pytest.mark.integration
def test_migration_downgrade_removes_derivation_triggers_functions_tables_and_restores_cmp011_shape(
    test_engine, alembic_head_restore,
) -> None:
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), "f3a8c2e1b975")
    try:
        _assert_downgraded_derivation_schema_removed(test_engine)
    finally:
        command.upgrade(_cfg(), "head")
    _assert_upgraded_derivation_schema_restored(test_engine)


def _assert_downgraded_derivation_schema_removed(test_engine) -> None:
    with test_engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN ("
                "'batch_derivation_events_no_update', 'batch_derivation_events_no_delete', "
                "'batch_derivation_sources_no_update', 'batch_derivation_sources_no_delete', "
                "'batch_derivation_outputs_no_update', 'batch_derivation_outputs_no_delete', "
                "'batch_assignment_transfers_enforce_insert_integrity', "
                "'batch_assignment_transfers_no_update', 'batch_assignment_transfers_no_delete', "
                "'batch_derivation_events_enforce_reconciliation', "
                "'batch_derivation_sources_enforce_reconciliation', "
                "'batch_derivation_outputs_enforce_reconciliation', "
                "'batch_assignment_transfers_enforce_reconciliation', "
                "'crop_batches_enforce_derivation_reconciliation_on_create', "
                "'crop_batches_enforce_derivation_reconciliation_on_supersede', "
                "'batch_stage_transitions_enforce_derivation_reconciliation', "
                "'batch_stage_runs_enforce_derivation_reconciliation', "
                "'batch_carrier_assignments_enforce_reconcile_bde_on_open', "
                "'batch_carrier_assignments_enforce_reconcile_bde_on_release', "
                "'batch_carrier_assignments_enforce_origin_insert_integrity_v2', "
                "'batch_carrier_assignments_enforce_closure_only_v2', "
                "'crop_batches_enforce_lifecycle_v2')"
            )
        ).all()
        functions = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN ("
                "'enforce_batch_assignment_transfer_insert_integrity', "
                "'enforce_batch_derivation_reconciliation', "
                "'enforce_batch_carrier_assignment_origin_insert_integrity_v2', "
                "'enforce_batch_carrier_assignment_closure_only_v2', "
                "'enforce_crop_batch_lifecycle_v2')"
            )
        ).all()
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN ("
                "'batch_derivation_events', 'batch_derivation_sources', 'batch_derivation_outputs', "
                "'batch_assignment_transfers')"
            )
        ).all()
        crop_batches_columns = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'crop_batches' "
                "AND column_name IN ('superseded_effective_time', 'superseded_by_batch_derivation_event_id', "
                "'created_by_batch_derivation_event_id')"
            )
        ).all()
        client_command_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'crop_batches' "
                "AND column_name = 'client_command_id'"
            )
        ).scalar_one()
        transition_columns = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'batch_stage_transitions' "
                "AND column_name = 'batch_derivation_event_id'"
            )
        ).all()
        transition_client_command_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'batch_stage_transitions' "
                "AND column_name = 'client_command_id'"
            )
        ).scalar_one()
        assignment_columns = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'batch_carrier_assignments' "
                "AND column_name IN ('opening_batch_derivation_event_id', 'released_by_batch_derivation_event_id')"
            )
        ).all()
        state_check_def = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_crop_batches_state'")
        ).scalar_one()
        command_kind_check_def = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_batch_stage_transitions_command_kind'"
            )
        ).scalar_one()
        # CMP-011's and CMP-008's original functions/triggers must have been
        # restored untouched — never dropped, only re-attached.
        cmp011_closure_trigger = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'batch_carrier_assignments_enforce_closure_only'")
        ).first()
        cmp011_origin_trigger = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgname = "
                "'batch_carrier_assignments_enforce_origin_insert_integrity'"
            )
        ).first()
        cmp008_lifecycle_trigger = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'crop_batches_enforce_lifecycle'")
        ).first()
        cmp008_lifecycle_function = conn.execute(
            text("SELECT 1 FROM pg_proc WHERE proname = 'enforce_crop_batch_lifecycle'")
        ).first()
        prior_ticket_constraint_intact = conn.execute(
            text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_transplant_events_tenant_farm_id'")
        ).first()
    assert triggers == []
    assert functions == []
    assert tables == []
    assert crop_batches_columns == []
    assert client_command_nullable == "NO"
    assert transition_columns == []
    assert transition_client_command_nullable == "NO"
    assert assignment_columns == []
    assert "superseded" not in state_check_def
    assert "derivation_entry" not in command_kind_check_def
    assert cmp011_closure_trigger is not None
    assert cmp011_origin_trigger is not None
    assert cmp008_lifecycle_trigger is not None
    assert cmp008_lifecycle_function is not None
    assert prior_ticket_constraint_intact is not None, "prior-ticket transplant schema must remain intact"


def _assert_upgraded_derivation_schema_restored(test_engine) -> None:
    with test_engine.connect() as conn:
        trigger_exists = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'batch_derivation_events_no_update'")
        ).first()
        deferred_trigger_exists = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgname = "
                "'batch_carrier_assignments_enforce_reconcile_bde_on_release'"
            )
        ).first()
        state_check_def = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_crop_batches_state'")
        ).scalar_one()
    assert trigger_exists is not None
    assert deferred_trigger_exists is not None
    assert "superseded" in state_check_def


# --- CMP-013: harvest event and harvested produce lot foundation ------------------


@pytest.mark.integration
def test_migration_downgrade_removes_harvest_triggers_functions_tables_and_restores_cmp012_shape(
    test_engine, alembic_head_restore,
) -> None:
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), "a4d92f7c1e6b")
    try:
        _assert_downgraded_harvest_schema_removed(test_engine)
    finally:
        command.upgrade(_cfg(), "head")
    _assert_upgraded_harvest_schema_restored(test_engine)


def _assert_downgraded_harvest_schema_removed(test_engine) -> None:
    with test_engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN ("
                "'harvest_events_enforce_insert_integrity', 'harvest_events_no_update', "
                "'harvest_events_no_delete', 'harvest_source_lines_enforce_insert_integrity', "
                "'harvest_source_lines_no_update', 'harvest_source_lines_no_delete', "
                "'harvested_produce_lots_enforce_insert_integrity', 'harvested_produce_lots_no_update', "
                "'harvested_produce_lots_no_delete', 'harvest_events_enforce_reconciliation', "
                "'harvest_source_lines_enforce_reconciliation', "
                "'harvested_produce_lots_enforce_reconciliation')"
            )
        ).all()
        functions = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN ("
                "'enforce_harvest_event_insert_integrity', 'enforce_harvest_source_line_insert_integrity', "
                "'enforce_harvested_produce_lot_insert_integrity', 'enforce_harvest_reconciliation')"
            )
        ).all()
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN ("
                "'harvest_events', 'harvest_source_lines', 'harvested_produce_lots')"
            )
        ).all()
        category_check_def = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_workflow_stages_category_allowed'"
            )
        ).scalar_one()
        # Shared functions must remain present (used by other tickets' tables).
        shared_functions_still_present = conn.execute(
            text(
                "SELECT count(*) FROM pg_proc WHERE proname IN "
                "('reject_append_only_mutation', 'reject_hard_delete')"
            )
        ).scalar_one()
        prior_ticket_constraint_intact = conn.execute(
            text("SELECT 1 FROM pg_constraint WHERE conname = 'uq_batch_derivation_events_tenant_farm_id'")
        ).first()
    assert triggers == []
    assert functions == []
    assert tables == []
    assert "harvesting" not in category_check_def
    assert "harvest_ready" in category_check_def
    assert shared_functions_still_present == 2
    assert prior_ticket_constraint_intact is not None, "prior-ticket batch-derivation schema must remain intact"


def _assert_upgraded_harvest_schema_restored(test_engine) -> None:
    with test_engine.connect() as conn:
        trigger_exists = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'harvest_events_enforce_insert_integrity'")
        ).first()
        deferred_trigger_exists = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgname = 'harvested_produce_lots_enforce_reconciliation'"
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
    assert "harvesting" in category_check_def


# --- CMP-014: produce lot opening receipt ledger ----------------------------------


@pytest.mark.integration
def test_migration_downgrade_removes_ledger_triggers_functions_table_and_restores_cmp013_shape(
    test_engine, alembic_head_restore,
) -> None:
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), "c7f14b8e29a3")
    try:
        _assert_downgraded_ledger_schema_removed(test_engine)
    finally:
        command.upgrade(_cfg(), "head")
    _assert_upgraded_ledger_schema_restored(test_engine)


def _assert_downgraded_ledger_schema_removed(test_engine) -> None:
    with test_engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN ("
                "'produce_lot_ledger_entries_enforce_insert_integrity', "
                "'produce_lot_ledger_entries_no_update', 'produce_lot_ledger_entries_no_delete', "
                "'produce_lot_ledger_entries_enforce_reconciliation', "
                "'harvested_produce_lots_enforce_ledger_reconciliation')"
            )
        ).all()
        functions = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN ("
                "'enforce_produce_lot_ledger_entry_insert_integrity', "
                "'enforce_produce_lot_ledger_reconciliation')"
            )
        ).all()
        table_exists = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'produce_lot_ledger_entries'")
        ).first()
        # CMP-013's own reconciliation trigger on harvested_produce_lots
        # must remain untouched — only CMP-014's second, distinctly-named
        # trigger on that same table is dropped.
        cmp013_lot_trigger_intact = conn.execute(
            text("SELECT 1 FROM pg_trigger WHERE tgname = 'harvested_produce_lots_enforce_reconciliation'")
        ).first()
        shared_functions_still_present = conn.execute(
            text(
                "SELECT count(*) FROM pg_proc WHERE proname IN "
                "('reject_append_only_mutation', 'reject_hard_delete')"
            )
        ).scalar_one()
    assert triggers == []
    assert functions == []
    assert table_exists is None
    assert cmp013_lot_trigger_intact is not None, "CMP-013's own lot reconciliation trigger must remain intact"
    assert shared_functions_still_present == 2


def _assert_upgraded_ledger_schema_restored(test_engine) -> None:
    with test_engine.connect() as conn:
        # Since CMP-015, head's own insert-integrity trigger on this table
        # is named `..._v2` (CMP-015 replaces, rather than modifies,
        # CMP-014's original attachment — see test_packing_downgrade_guard.py).
        # Match by prefix so this assertion stays correct for whichever
        # revision is head, instead of hardcoding one specific trigger name.
        trigger_exists = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgrelid = 'produce_lot_ledger_entries'::regclass "
                "AND tgname LIKE 'produce_lot_ledger_entries_enforce_insert_integrity%'"
            )
        ).first()
        deferred_trigger_exists = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgname = 'harvested_produce_lots_enforce_ledger_reconciliation'"
            )
        ).first()
        table_exists = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'produce_lot_ledger_entries'")
        ).first()
    assert trigger_exists is not None
    assert deferred_trigger_exists is not None
    assert table_exists is not None


def _cleanup_ledger_migration_scenario(test_engine, tenant_id) -> None:
    _assert_operating_on_cmp_test_database(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvested_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_event_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_carrier_assignments WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM seed_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_runs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crop_batches WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_stages WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_versions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflows WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM production_systems WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM varieties WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crops WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    except Exception:
        trans.rollback()
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        raise
    else:
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_migration_backfill_matches_pre_existing_lot_and_survives_downgrade_reupgrade(test_engine, alembic_head_restore) -> None:
    """Simulates data that already existed under CMP-013 before CMP-014
    ever ran: a harvest event/lot/source-line triple is built directly via
    SQL (mirroring exactly what `harvest_service.record_harvest` produced
    before this ticket amended it) while the database is downgraded to
    CMP-013 — the current `harvest_service` code cannot be used for this
    step, since it now unconditionally inserts a ledger row that would not
    exist at CMP-013 schema. Upgrading to CMP-014 must then backfill one
    receipt whose every field exactly matches the lot/event, and a
    downgrade-then-re-upgrade cycle must reproduce an identical row."""
    import uuid
    from datetime import datetime, timezone
    from decimal import Decimal

    from sqlalchemy.orm import Session

    from app.services import (
        carrier_service,
        crop_batch_service,
        crop_service,
        farm_service,
        membership_service,
        production_system_service,
        sowing_service,
        tenant_service,
        user_service,
        workflow_service,
    )

    def now():
        return datetime.now(timezone.utc)

    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), "c7f14b8e29a3")

    suffix = uuid.uuid4().hex[:8]
    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant = tenant_service.create_tenant(session, code=f"ledger-mig-{suffix}", name="Ledger Migration Tenant")
    user = user_service.create_user(
        session, oidc_issuer="ledger-mig", oidc_subject=suffix, email=f"ledger-mig-{suffix}@example.com",
        display_name="Migration User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Migration Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"var-{suffix}",
        name="Variety", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ps-{suffix}", name="System", description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"wf-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    harvesting = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="HARVESTING", name="Harvesting", display_order=1, stage_category="harvesting",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=harvesting.id, code="ADV-1", name="Advance 1",
    )
    workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=harvesting.id, to_stage_id=complete.id, code="ADV-2", name="Advance 2",
    )
    workflow_service.publish_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"batch-{suffix}", workflow_id=workflow.id, effective_time=now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"lot-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    carrier = carrier_service.register_carrier(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, carrier_type_code="seed_tray",
        code=f"tray-{suffix}", issued_date=None,
    )
    # NURSERY-OPS-001 added `seeding_station_id`/`seeding_machine_id` to
    # `sowing_events` -- absent at this deliberately-downgraded (CMP-013)
    # schema level, so the CURRENT `sowing_service.sow_batch` (whose ORM
    # model always selects/inserts those columns) cannot be used here,
    # exactly like `harvest_service` below it. Built directly via SQL
    # instead, mirroring that same established pattern -- the pre-existing
    # seeding stage run (before the harvesting transition) is captured
    # first since `crop_batch_service.transition_stage` below closes it.
    seeding_run_id = session.execute(
        text("SELECT id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"),
        {"bid": batch.id},
    ).scalar_one()
    sowing_event_id = uuid.uuid4()
    assignment_id = uuid.uuid4()
    sow_effective_time = now()
    session.execute(
        text(
            "INSERT INTO sowing_events "
            "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
            "client_command_id, request_fingerprint, note) VALUES "
            "(:id, :tid, :fid, :bid, :run_id, :eff, :uid, :cmd, :fp, NULL)"
        ),
        {
            "id": sowing_event_id, "tid": tenant.id, "fid": farm.id, "bid": batch.id, "run_id": seeding_run_id,
            "eff": sow_effective_time, "uid": user.id, "cmd": uuid.uuid4(), "fp": "pre-existing-cmp013-schema-sowing",
        },
    )
    session.execute(
        text(
            "INSERT INTO batch_carrier_assignments "
            "(id, tenant_id, farm_id, batch_id, carrier_id, batch_stage_run_id, assigned_effective_time, "
            "released_effective_time, opening_sowing_event_id, actor_user_id) VALUES "
            "(:id, :tid, :fid, :bid, :cid, :run_id, :eff, NULL, :eid, :uid)"
        ),
        {
            "id": assignment_id, "tid": tenant.id, "fid": farm.id, "bid": batch.id, "cid": carrier.id,
            "run_id": seeding_run_id, "eff": sow_effective_time, "eid": sowing_event_id, "uid": user.id,
        },
    )
    session.execute(
        text(
            "INSERT INTO sowing_event_lines "
            "(id, tenant_id, farm_id, sowing_event_id, batch_carrier_assignment_id, carrier_id, seed_lot_id, "
            "sown_site_count, seed_count, line_note) VALUES "
            "(:id, :tid, :fid, :eid, :aid, :cid, :lid, :site, :seed, NULL)"
        ),
        {
            "id": uuid.uuid4(), "tid": tenant.id, "fid": farm.id, "eid": sowing_event_id, "aid": assignment_id,
            "cid": carrier.id, "lid": seed_lot.id, "site": 20, "seed": 20,
        },
    )
    assignment = type("_Assignment", (), {"id": assignment_id})()
    crop_batch_service.transition_stage(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=now(), reason=None,
    )
    active_run_id = session.execute(
        text("SELECT id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"),
        {"bid": batch.id},
    ).scalar_one()

    # Build the harvest event/line/lot directly via SQL — exactly what
    # harvest_service produced before this ticket amended it — since the
    # database is currently at CMP-013 schema (no ledger table exists yet).
    event_id = uuid.uuid4()
    event_effective_time = now()
    session.execute(
        text(
            "INSERT INTO harvest_events "
            "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
            "client_command_id, request_fingerprint, note) VALUES "
            "(:id, :tid, :fid, :bid, :run_id, :eff, :uid, :cmd, :fp, NULL)"
        ),
        {
            "id": event_id, "tid": tenant.id, "fid": farm.id, "bid": batch.id, "run_id": active_run_id,
            "eff": event_effective_time, "uid": user.id, "cmd": uuid.uuid4(), "fp": "pre-existing-cmp013-data",
        },
    )
    session.execute(
        text(
            "INSERT INTO harvest_source_lines "
            "(id, tenant_id, farm_id, harvest_event_id, batch_carrier_assignment_id, carrier_id, "
            "harvested_weight_kg, whole_unit_count, note) VALUES "
            "(:id, :tid, :fid, :eid, :aid, :cid, :w, :c, NULL)"
        ),
        {
            "id": uuid.uuid4(), "tid": tenant.id, "fid": farm.id, "eid": event_id, "aid": assignment.id,
            "cid": carrier.id, "w": Decimal("6.750"), "c": 22,
        },
    )
    lot_id = uuid.uuid4()
    session.execute(
        text(
            "INSERT INTO harvested_produce_lots "
            "(id, tenant_id, farm_id, code, harvest_event_id, batch_id, workflow_id, workflow_version_id, "
            "crop_id, variety_id, total_harvested_weight_kg, total_whole_unit_count, effective_time) VALUES "
            "(:id, :tid, :fid, :code, :eid, :bid, :wf, :wfv, :crop, :variety, :w, :c, :eff)"
        ),
        {
            "id": lot_id, "tid": tenant.id, "fid": farm.id, "code": f"PREEXIST-{suffix}", "eid": event_id,
            "bid": batch.id, "wf": workflow.id, "wfv": version.id, "crop": crop.id, "variety": variety.id,
            "w": Decimal("6.750"), "c": 22, "eff": event_effective_time,
        },
    )
    session.commit()
    lot_recorded_at = session.execute(
        text("SELECT recorded_at FROM harvested_produce_lots WHERE id = :id"), {"id": lot_id}
    ).scalar_one()
    tenant_id, farm_id, user_id = tenant.id, farm.id, user.id
    session.close()
    conn.close()

    try:
        command.upgrade(_cfg(), "head")

        def _receipt_snapshot():
            with test_engine.connect() as verify_conn:
                return verify_conn.execute(
                    text(
                        "SELECT id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, "
                        "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, "
                        "note FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid"
                    ),
                    {"lid": lot_id},
                ).mappings().all()

        first_backfill = _receipt_snapshot()
        assert len(first_backfill) == 1
        row = first_backfill[0]
        assert row["id"] == lot_id
        assert row["tenant_id"] == tenant_id
        assert row["farm_id"] == farm_id
        assert row["produce_lot_id"] == lot_id
        assert row["harvest_event_id"] == event_id
        assert row["entry_kind"] == "harvest_receipt"
        assert row["weight_delta_kg"] == Decimal("6.750")
        assert row["whole_unit_count_delta"] == 22
        assert row["effective_time"] == event_effective_time
        assert row["recorded_time"] == lot_recorded_at
        assert row["actor_user_id"] == user_id
        assert row["note"] is None

        command.downgrade(_cfg(), "c7f14b8e29a3")
        with test_engine.connect() as verify_conn:
            table_exists = verify_conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'produce_lot_ledger_entries'")
            ).first()
            lot_still_present = verify_conn.execute(
                text("SELECT count(*) FROM harvested_produce_lots WHERE id = :id"), {"id": lot_id}
            ).scalar_one()
        assert table_exists is None, "downgrade must drop the ledger table"
        assert lot_still_present == 1, "downgrade must leave the underlying CMP-013 lot untouched"

        command.upgrade(_cfg(), "head")
        second_backfill = _receipt_snapshot()
        assert second_backfill == first_backfill, "re-upgrade must reproduce an identical receipt row"
    finally:
        _cleanup_ledger_migration_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_migration_downgrade_removes_packing_triggers_functions_tables_and_restores_cmp014_shape(
    test_engine, alembic_head_restore,
) -> None:
    """CMP-015's clean downgrade (no packing history) must remove every new
    table/trigger/function it introduced and restore produce_lot_ledger_entries
    and harvested_produce_lots to their exact CMP-014 shape — verified here
    by comparing CHECK constraint bodies byte-for-byte via
    pg_get_constraintdef, not just by name."""
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), "de82132ef837")
    try:
        _assert_downgraded_packing_schema_removed(test_engine)
    finally:
        command.upgrade(_cfg(), "head")
    _assert_upgraded_packing_schema_restored(test_engine)


def _assert_downgraded_packing_schema_removed(test_engine) -> None:
    with test_engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN "
                "('packing_events', 'packing_input_lines', 'finished_goods_lots')"
            )
        ).scalars().all()
        assert tables == []

        functions = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN ("
                "'enforce_packing_event_insert_integrity', 'enforce_packing_input_line_insert_integrity', "
                "'enforce_finished_goods_lot_insert_integrity', "
                "'enforce_produce_lot_ledger_entry_insert_integrity_v2', 'enforce_packing_reconciliation')"
            )
        ).all()
        assert functions == [], "every CMP-015 function, including the v2 ledger function, must be dropped"

        # CMP-014's own function must be untouched — never modified, never dropped.
        cmp014_function_intact = conn.execute(
            text("SELECT 1 FROM pg_proc WHERE proname = 'enforce_produce_lot_ledger_entry_insert_integrity'")
        ).first()
        assert cmp014_function_intact is not None

        original_trigger = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgrelid = 'produce_lot_ledger_entries'::regclass "
                "AND tgname = 'produce_lot_ledger_entries_enforce_insert_integrity'"
            )
        ).first()
        assert original_trigger is not None, "downgrade must restore the exact original CMP-014 trigger attachment"

        columns = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'produce_lot_ledger_entries' "
                "AND column_name = 'packing_event_id'"
            )
        ).first()
        assert columns is None, "the packing_event_id column must be dropped on downgrade"

        harvest_event_id_nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'produce_lot_ledger_entries' "
                "AND column_name = 'harvest_event_id'"
            )
        ).scalar_one()
        assert harvest_event_id_nullable == "NO", "harvest_event_id must be restored to NOT NULL"

        check_bodies = dict(
            conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'produce_lot_ledger_entries'::regclass AND contype = 'c' "
                    "AND conname IN ('ck_produce_lot_ledger_entries_kind_allowed', "
                    "'ck_produce_lot_ledger_entries_weight_envelope', 'ck_produce_lot_ledger_entries_count_positive')"
                )
            ).all()
        )
        assert check_bodies["ck_produce_lot_ledger_entries_kind_allowed"] == (
            "CHECK (((entry_kind)::text = 'harvest_receipt'::text))"
        )
        assert "packing_consumption" not in check_bodies["ck_produce_lot_ledger_entries_weight_envelope"]
        assert "packing_consumption" not in check_bodies["ck_produce_lot_ledger_entries_count_positive"]

        harvested_produce_lots_composite_unique = conn.execute(
            text(
                "SELECT 1 FROM pg_constraint WHERE conrelid = 'harvested_produce_lots'::regclass "
                "AND conname = 'uq_harvested_produce_lots_tenant_farm_id'"
            )
        ).first()
        assert harvested_produce_lots_composite_unique is None, (
            "the CMP-015-added composite unique constraint must be dropped on downgrade"
        )


def _assert_upgraded_packing_schema_restored(test_engine) -> None:
    with test_engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN "
                "('packing_events', 'packing_input_lines', 'finished_goods_lots')"
            )
        ).scalars().all()
        assert sorted(tables) == ["finished_goods_lots", "packing_events", "packing_input_lines"]

        v2_trigger = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgrelid = 'produce_lot_ledger_entries'::regclass "
                "AND tgname = 'produce_lot_ledger_entries_enforce_insert_integrity_v2'"
            )
        ).first()
        assert v2_trigger is not None

        original_trigger_gone = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgrelid = 'produce_lot_ledger_entries'::regclass "
                "AND tgname = 'produce_lot_ledger_entries_enforce_insert_integrity'"
            )
        ).first()
        assert original_trigger_gone is None, "re-upgrade must not leave the original CMP-014 attachment alongside v2"

        harvested_produce_lots_composite_unique = conn.execute(
            text(
                "SELECT 1 FROM pg_constraint WHERE conrelid = 'harvested_produce_lots'::regclass "
                "AND conname = 'uq_harvested_produce_lots_tenant_farm_id'"
            )
        ).first()
        assert harvested_produce_lots_composite_unique is not None


@pytest.mark.integration
def test_migration_backfill_rejects_finished_goods_lot_with_broken_packing_event_reference(test_engine, alembic_head_restore) -> None:
    """Proves CMP-016's upgrade-time backfill validation is a real,
    reachable safety net, not dead code. The backfill's INSERT ... SELECT
    computes every receipt field directly from its lot/event in one pass,
    so a field-mismatched or orphaned *receipt* can never actually occur
    during backfill (there is no pre-existing ledger table for a stray row
    to live in, and the same join used to build a row is used to verify
    it). The one genuinely reachable failure is a pre-existing
    finished_goods_lot whose packing_event_id no longer resolves to a real
    packing_event (simulating data corruption that predates CMP-016) —
    the backfill's INSERT ... SELECT JOIN silently excludes that lot,
    which the very first check (lot_count vs receipt_count) catches. The
    16 downgrade-guard states in test_finished_goods_ledger_downgrade_guard.py
    exercise the same shared mismatch/orphan/duplicate predicates against
    genuinely reachable *downgrade-time* corruption instead."""
    import uuid
    from decimal import Decimal

    from sqlalchemy.orm import Session

    from app.services import packing_service
    from tests._packing_scenario import build_committed_scenario, cleanup_scenario, require_cmp_test

    def now():
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)

    _assert_operating_on_cmp_test_database(test_engine)
    require_cmp_test(test_engine)

    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    event = packing_service.record_packing(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), effective_time=now(), finished_goods_lot_code=f"FG-{scenario['suffix']}",
        package_count=6, packed_output_weight_kg=Decimal("2.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"harvested_produce_lot_id": scenario["lot_a_id"], "consumed_weight_kg": Decimal("2.000"), "consumed_whole_unit_count": None, "note": None}],
    )
    detail = packing_service.get_packing_event(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=event.id
    )
    fg_lot_id = detail.finished_goods_lot.id
    event_id = event.id
    session.commit()
    session.close()
    conn.close()

    try:
        # The receipt is well-formed, so this downgrade succeeds (proven
        # separately by the with-data downgrade-guard test) and drops the
        # ledger table entirely, leaving CMP-015 schema with no ledger to
        # corrupt directly.
        command.downgrade(_cfg(), "a91f4c7b2e58")

        bypass_conn = test_engine.connect()
        trans = bypass_conn.begin()
        bypass_conn.execute(text("SET session_replication_role = replica"))
        bypass_conn.execute(
            text("UPDATE finished_goods_lots SET packing_event_id = :bogus WHERE id = :lid"),
            {"bogus": uuid.uuid4(), "lid": fg_lot_id},
        )
        bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
        bypass_conn.close()

        with pytest.raises(RuntimeError, match="finished-goods lots but .* packing receipts"):
            command.upgrade(_cfg(), "head")

        with test_engine.connect() as conn2:
            current = conn2.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == "a91f4c7b2e58", "a failed backfill must leave the database at its pre-upgrade revision"
    finally:
        # Repair the corrupted reference before cleanup/re-upgrade: cleanup_scenario
        # itself does not touch finished_goods_lots.packing_event_id, and a
        # dangling reference would otherwise make the next upgrade fail again
        # for a test run afterward.
        repair_conn = test_engine.connect()
        repair_trans = repair_conn.begin()
        repair_conn.execute(text("SET session_replication_role = replica"))
        repair_conn.execute(
            text("UPDATE finished_goods_lots SET packing_event_id = :eid WHERE id = :lid"),
            {"eid": event_id, "lid": fg_lot_id},
        )
        repair_conn.execute(text("SET session_replication_role = DEFAULT"))
        repair_trans.commit()
        repair_conn.close()
        command.upgrade(_cfg(), "head")
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_migration_downgrade_removes_finished_goods_ledger_triggers_functions_and_table(test_engine, alembic_head_restore) -> None:
    """CMP-016's own downgrade guard follows CMP-014's reconstructible-
    projection model (not CMP-015's unconditional-block model): downgrade
    succeeds even while finished_goods_lots/packing_events data exists,
    as long as every receipt is well-formed. This test only proves clean
    schema removal/restoration with no data present; see
    test_finished_goods_ledger_downgrade_guard.py for the with-data and
    guard-triggering cases."""
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), "a91f4c7b2e58")
    try:
        with test_engine.connect() as conn:
            table_exists = conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'finished_goods_ledger_entries'")
            ).first()
            assert table_exists is None
            functions = conn.execute(
                text(
                    "SELECT proname FROM pg_proc WHERE proname IN ("
                    "'enforce_finished_goods_ledger_entry_insert_integrity', "
                    "'enforce_finished_goods_ledger_reconciliation')"
                )
            ).all()
            assert functions == []
            # CMP-015's own packing schema and reconciliation must remain untouched.
            packing_tables = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_name IN "
                    "('packing_events', 'packing_input_lines', 'finished_goods_lots')"
                )
            ).scalars().all()
            assert sorted(packing_tables) == ["finished_goods_lots", "packing_events", "packing_input_lines"]
            cmp015_reconciliation_intact = conn.execute(
                text("SELECT 1 FROM pg_proc WHERE proname = 'enforce_packing_reconciliation'")
            ).first()
            assert cmp015_reconciliation_intact is not None
    finally:
        command.upgrade(_cfg(), "head")

    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _resolve_head_revision(_cfg())
        table_exists = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'finished_goods_ledger_entries'")
        ).first()
        assert table_exists is not None
        triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                "AND NOT tgisinternal ORDER BY tgname"
            )
        ).scalars().all()
        # CMP-017 sits above CMP-016 at "head", so re-upgrading here also
        # reattaches its own sibling dispatch-reconciliation trigger on
        # this same table -- see the CMP-017 section below for its own
        # dedicated downgrade/re-upgrade proof.
        assert triggers == [
            "finished_goods_ledger_entries_enforce_dispatch_reconciliation",
            "finished_goods_ledger_entries_enforce_insert_integrity",
            "finished_goods_ledger_entries_enforce_reconciliation",
            "finished_goods_ledger_entries_no_delete",
            "finished_goods_ledger_entries_no_update",
        ]


# --- CMP-017: typed finished-goods dispatch foundation ----------------------


@pytest.mark.integration
def test_migration_downgrade_removes_dispatch_triggers_functions_tables_and_restores_cmp016_shape(
    test_engine, alembic_head_restore,
) -> None:
    """CMP-017's own downgrade guard follows CMP-015's unconditional-block
    model (not CMP-016's reconstructible-projection one): dispatch history
    is independent operational data, never reconstructible, so downgrade
    is blocked outright whenever any exists. This test only proves clean
    schema removal/restoration with no dispatch history present; see
    test_dispatch_downgrade_guard.py for the with-data and guard-
    triggering cases."""
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), "dd4e6fab718a")
    try:
        with test_engine.connect() as conn:
            tables = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_name IN "
                    "('dispatch_events', 'dispatch_lines')"
                )
            ).scalars().all()
            assert tables == [], "downgrade must drop both dispatch tables"

            functions = conn.execute(
                text(
                    "SELECT proname FROM pg_proc WHERE proname IN ("
                    "'enforce_finished_goods_ledger_entry_insert_integrity_v2', 'enforce_dispatch_reconciliation')"
                )
            ).all()
            assert functions == [], "every CMP-017 function, including the v2 ledger function, must be dropped"

            # CMP-016's own function must be untouched -- never modified, never dropped.
            cmp016_function_intact = conn.execute(
                text("SELECT 1 FROM pg_proc WHERE proname = 'enforce_finished_goods_ledger_entry_insert_integrity'")
            ).first()
            assert cmp016_function_intact is not None

            original_trigger = conn.execute(
                text(
                    "SELECT 1 FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                    "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity'"
                )
            ).first()
            assert original_trigger is not None, "downgrade must restore the exact original CMP-016 trigger attachment"

            dispatch_line_id_column = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'finished_goods_ledger_entries' AND column_name = 'dispatch_line_id'"
                )
            ).first()
            assert dispatch_line_id_column is None, "the dispatch_line_id column must be dropped on downgrade"

            packing_event_id_nullable = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'finished_goods_ledger_entries' AND column_name = 'packing_event_id'"
                )
            ).scalar_one()
            assert packing_event_id_nullable == "NO", "packing_event_id must be restored to NOT NULL"

            check_bodies = dict(
                conn.execute(
                    text(
                        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid = 'finished_goods_ledger_entries'::regclass AND contype = 'c' "
                        "AND conname IN ('ck_finished_goods_ledger_entries_kind_allowed', "
                        "'ck_finished_goods_ledger_entries_deterministic_id', "
                        "'ck_finished_goods_ledger_entries_weight_envelope', "
                        "'ck_finished_goods_ledger_entries_count_positive')"
                    )
                ).all()
            )
            assert check_bodies["ck_finished_goods_ledger_entries_kind_allowed"] == (
                "CHECK (((entry_kind)::text = 'packing_receipt'::text))"
            )
            assert check_bodies["ck_finished_goods_ledger_entries_deterministic_id"] == (
                "CHECK ((id = finished_goods_lot_id))"
            )
            assert "dispatch_issue" not in check_bodies["ck_finished_goods_ledger_entries_weight_envelope"]
            assert "typed_source_shape" not in str(check_bodies)

            # CMP-016's own packing schema and reconciliation must remain untouched.
            packing_tables = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_name IN "
                    "('packing_events', 'packing_input_lines', 'finished_goods_lots')"
                )
            ).scalars().all()
            assert sorted(packing_tables) == ["finished_goods_lots", "packing_events", "packing_input_lines"]
            cmp016_reconciliation_intact = conn.execute(
                text("SELECT 1 FROM pg_proc WHERE proname = 'enforce_finished_goods_ledger_reconciliation'")
            ).first()
            assert cmp016_reconciliation_intact is not None
    finally:
        command.upgrade(_cfg(), "head")

    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _resolve_head_revision(_cfg())

        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN "
                "('dispatch_events', 'dispatch_lines')"
            )
        ).scalars().all()
        assert sorted(tables) == ["dispatch_events", "dispatch_lines"]

        # CMP-020 sits above CMP-017 at "head", so re-upgrading here also
        # reattaches its own v4 trigger (which supersedes, rather than
        # coexists with, v2's/v3's attachment) -- see the CMP-018/CMP-020
        # sections for their own dedicated downgrade/re-upgrade proofs.
        v4_trigger = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                "AND tgfoid = to_regproc('enforce_finished_goods_ledger_entry_insert_integrity_v4')"
            )
        ).first()
        assert v4_trigger is not None, "re-upgrade must reattach the v4 trigger"

        fgle_triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                "AND NOT tgisinternal ORDER BY tgname"
            )
        ).scalars().all()
        assert fgle_triggers == [
            "finished_goods_ledger_entries_enforce_dispatch_reconciliation",
            "finished_goods_ledger_entries_enforce_insert_integrity",
            "finished_goods_ledger_entries_enforce_reconciliation",
            "finished_goods_ledger_entries_no_delete",
            "finished_goods_ledger_entries_no_update",
        ]

        dispatch_events_triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'dispatch_events'::regclass "
                "AND NOT tgisinternal ORDER BY tgname"
            )
        ).scalars().all()
        assert dispatch_events_triggers == [
            "dispatch_events_enforce_reconciliation", "dispatch_events_no_delete", "dispatch_events_no_update",
        ]

        dispatch_lines_triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'dispatch_lines'::regclass "
                "AND NOT tgisinternal ORDER BY tgname"
            )
        ).scalars().all()
        assert dispatch_lines_triggers == [
            "dispatch_lines_enforce_reconciliation", "dispatch_lines_no_delete", "dispatch_lines_no_update",
        ]


# --- CMP-018: cold-store location and finished-goods physical occupancy -----
#
# Follows the same unconditional-block model as CMP-015/017's own dispatch
# section above, not CMP-016's reconstructible-projection one: a storage
# movement row is independent operational data, never reconstructible, so
# downgrade is blocked outright whenever any exists. This test only proves
# clean schema removal/restoration with no movement history present; see
# test_finished_goods_storage_downgrade_guard.py for the with-data and
# guard-triggering cases. Unlike dispatch, CMP-018 adds no deferred
# reconciliation trigger on finished_goods_ledger_entries or on its own new
# table -- a storage movement is a single self-contained row with no child
# fan-out to reconcile, so none is needed (see FINISHED_GOODS_STORAGE_MODEL.md).


@pytest.mark.integration
def test_migration_downgrade_removes_storage_triggers_functions_table_and_restores_cmp017_shape(
    test_engine, alembic_head_restore,
) -> None:
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), "63d4d7e184e2")
    try:
        with test_engine.connect() as conn:
            table_exists = conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'finished_goods_storage_movements'")
            ).first()
            assert table_exists is None, "downgrade must drop the storage movement table"

            functions = conn.execute(
                text(
                    "SELECT proname FROM pg_proc WHERE proname IN ("
                    "'enforce_finished_goods_storage_movement_insert_integrity', "
                    "'enforce_finished_goods_ledger_entry_insert_integrity_v3')"
                )
            ).all()
            assert functions == [], "every CMP-018 function, including the v3 ledger function, must be dropped"

            # CMP-017's own v2 function must be untouched -- never modified, never dropped.
            cmp017_function_intact = conn.execute(
                text("SELECT 1 FROM pg_proc WHERE proname = 'enforce_finished_goods_ledger_entry_insert_integrity_v2'")
            ).first()
            assert cmp017_function_intact is not None

            v2_trigger = conn.execute(
                text(
                    "SELECT 1 FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                    "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                    "AND tgfoid = 'enforce_finished_goods_ledger_entry_insert_integrity_v2'::regproc"
                )
            ).first()
            assert v2_trigger is not None, "downgrade must restore the exact CMP-017 v2 trigger attachment"

            locations_unique_constraint = conn.execute(
                text(
                    "SELECT 1 FROM pg_constraint WHERE conname = 'uq_locations_tenant_farm_id' "
                    "AND conrelid = 'locations'::regclass"
                )
            ).first()
            assert locations_unique_constraint is None, "downgrade must remove the CMP-018-added composite unique"

            # CMP-017's own dispatch schema and reconciliation must remain untouched.
            dispatch_tables = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_name IN "
                    "('dispatch_events', 'dispatch_lines')"
                )
            ).scalars().all()
            assert sorted(dispatch_tables) == ["dispatch_events", "dispatch_lines"]
            cmp017_reconciliation_intact = conn.execute(
                text("SELECT 1 FROM pg_proc WHERE proname = 'enforce_dispatch_reconciliation'")
            ).first()
            assert cmp017_reconciliation_intact is not None

            # location_types/location_type_hierarchy_rules seed data (CMP-004)
            # is never touched by this ticket.
            cold_store_position_type = conn.execute(
                text("SELECT 1 FROM location_types WHERE code = 'cold_store_position'")
            ).first()
            assert cold_store_position_type is not None
    finally:
        command.upgrade(_cfg(), "head")

    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _resolve_head_revision(_cfg())

        table_exists = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'finished_goods_storage_movements'")
        ).first()
        assert table_exists is not None

        # CMP-020 sits above CMP-018 at "head", so re-upgrading here also
        # reattaches its own v4 ledger trigger and v2 storage-movement
        # trigger -- see the CMP-020 section for its own dedicated
        # downgrade/re-upgrade proof.
        v4_trigger = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                "AND tgfoid = to_regproc('enforce_finished_goods_ledger_entry_insert_integrity_v4')"
            )
        ).first()
        assert v4_trigger is not None, "re-upgrade must reattach the v4 trigger"

        locations_unique_constraint = conn.execute(
            text(
                "SELECT 1 FROM pg_constraint WHERE conname = 'uq_locations_tenant_farm_id' "
                "AND conrelid = 'locations'::regclass"
            )
        ).first()
        assert locations_unique_constraint is not None, "re-upgrade must recreate the composite unique on locations"

        storage_triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'finished_goods_storage_movements'::regclass "
                "AND NOT tgisinternal ORDER BY tgname"
            )
        ).scalars().all()
        assert storage_triggers == [
            "finished_goods_storage_movements_enforce_insert_integrity",
            "finished_goods_storage_movements_no_delete",
            "finished_goods_storage_movements_no_update",
        ]


# --- CMP-019: end-to-end recall and traceability foundation -----------------
#
# Indexes-only migration -- no table, trigger, or function of its own. See
# test_traceability_migration.py for the full with-data downgrade/re-upgrade
# proof; this section only adds the standard per-ticket smoke check.


@pytest.mark.integration
def test_migration_downgrade_removes_traceability_indexes_and_restores_cmp018_shape(test_engine, alembic_head_restore) -> None:
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), "dd8b86a52acf")
    try:
        with test_engine.connect() as conn:
            indexes = conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE indexname IN ("
                    "'ix_packing_input_lines_tenant_farm_produce_lot', "
                    "'ix_dispatch_lines_tenant_farm_finished_goods_lot', "
                    "'ix_finished_goods_storage_movements_tenant_farm_lot')"
                )
            ).scalars().all()
            assert indexes == [], "downgrade must remove all three CMP-019 indexes"

            # CMP-018's own table/triggers must remain fully intact.
            storage_triggers = conn.execute(
                text(
                    "SELECT tgname FROM pg_trigger WHERE tgrelid = 'finished_goods_storage_movements'::regclass "
                    "AND NOT tgisinternal ORDER BY tgname"
                )
            ).scalars().all()
            assert storage_triggers == [
                "finished_goods_storage_movements_enforce_insert_integrity",
                "finished_goods_storage_movements_no_delete",
                "finished_goods_storage_movements_no_update",
            ]
    finally:
        command.upgrade(_cfg(), "head")

    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _resolve_head_revision(_cfg())
        indexes = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE indexname IN ("
                "'ix_packing_input_lines_tenant_farm_produce_lot', "
                "'ix_dispatch_lines_tenant_farm_finished_goods_lot', "
                "'ix_finished_goods_storage_movements_tenant_farm_lot')"
            )
        ).scalars().all()
        assert sorted(indexes) == [
            "ix_dispatch_lines_tenant_farm_finished_goods_lot",
            "ix_finished_goods_storage_movements_tenant_farm_lot",
            "ix_packing_input_lines_tenant_farm_produce_lot",
        ]


# --- CMP-020: recall case containment foundation -----------------------------
#
# See test_recall_downgrade_guard.py for the full with-data guard,
# unconditional-block, and exact prior-trigger-restoration proofs; this
# section only adds the standard per-ticket smoke check.


@pytest.mark.integration
def test_migration_downgrade_removes_recall_tables_triggers_and_restores_cmp019_shape(test_engine, alembic_head_restore) -> None:
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), "677fcd22cb3c")
    try:
        with test_engine.connect() as conn:
            tables = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_name IN ("
                    "'recall_cases', 'recall_case_closures', 'recall_scope_batches', "
                    "'recall_scope_produce_lots', 'recall_scope_finished_goods_lots')"
                )
            ).scalars().all()
            assert tables == [], "downgrade must drop all five CMP-020 tables"

            functions = conn.execute(
                text(
                    "SELECT proname FROM pg_proc WHERE proname IN ("
                    "'enforce_recall_case_reconciliation', 'enforce_batch_derivation_source_containment', "
                    "'enforce_packing_input_line_insert_integrity_v2', "
                    "'enforce_finished_goods_storage_movement_insert_integrity_v2', "
                    "'enforce_finished_goods_ledger_entry_insert_integrity_v4')"
                )
            ).all()
            assert functions == [], "every CMP-020 function, including the v2/v2/v4 versioned ones, must be dropped"

            # CMP-015/018's own prior functions must be untouched -- never
            # modified, never dropped.
            for proname in (
                "enforce_packing_input_line_insert_integrity",
                "enforce_finished_goods_storage_movement_insert_integrity",
                "enforce_finished_goods_ledger_entry_insert_integrity_v3",
            ):
                intact = conn.execute(text("SELECT 1 FROM pg_proc WHERE proname = :p"), {"p": proname}).first()
                assert intact is not None, f"{proname} must remain untouched"

            # CMP-019's own traceability indexes are unaffected.
            indexes = conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE indexname IN ("
                    "'ix_packing_input_lines_tenant_farm_produce_lot', "
                    "'ix_dispatch_lines_tenant_farm_finished_goods_lot', "
                    "'ix_finished_goods_storage_movements_tenant_farm_lot')"
                )
            ).scalars().all()
            assert sorted(indexes) == [
                "ix_dispatch_lines_tenant_farm_finished_goods_lot",
                "ix_finished_goods_storage_movements_tenant_farm_lot",
                "ix_packing_input_lines_tenant_farm_produce_lot",
            ]
    finally:
        command.upgrade(_cfg(), "head")

    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _resolve_head_revision(_cfg())

        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN ("
                "'recall_cases', 'recall_case_closures', 'recall_scope_batches', "
                "'recall_scope_produce_lots', 'recall_scope_finished_goods_lots')"
            )
        ).scalars().all()
        assert sorted(tables) == [
            "recall_case_closures", "recall_cases", "recall_scope_batches",
            "recall_scope_finished_goods_lots", "recall_scope_produce_lots",
        ]

        for tgrelid, tgname, proname in (
            ("packing_input_lines", "packing_input_lines_enforce_insert_integrity", "enforce_packing_input_line_insert_integrity_v2"),
            ("finished_goods_storage_movements", "finished_goods_storage_movements_enforce_insert_integrity", "enforce_finished_goods_storage_movement_insert_integrity_v2"),
            ("finished_goods_ledger_entries", "finished_goods_ledger_entries_enforce_insert_integrity", "enforce_finished_goods_ledger_entry_insert_integrity_v4"),
        ):
            reattached = conn.execute(
                text(
                    f"SELECT 1 FROM pg_trigger WHERE tgrelid = '{tgrelid}'::regclass "
                    "AND tgname = :tgname AND tgfoid = to_regproc(:proname)"
                ),
                {"tgname": tgname, "proname": proname},
            ).first()
            assert reattached is not None, f"re-upgrade must reattach {proname} on {tgrelid}"

        derivation_gate = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgrelid = 'batch_derivation_sources'::regclass "
                "AND tgname = 'batch_derivation_sources_enforce_containment'"
            )
        ).first()
        assert derivation_gate is not None, "re-upgrade must recreate the batch-derivation containment trigger"


# ============================================================================
# DOMAIN-FARM-001.1: existing-topology guard on the classification-scoped
# hierarchy migration (9ca4ac801827). Each test downgrades to the revision
# immediately before it (68215f964ca9 -- the old, generic-only hierarchy
# schema), inserts a "pre-existing business location" via raw SQL (the ORM
# models reflect the NEW schema shape and cannot be used against a
# downgraded database), then attempts to upgrade to head and asserts the
# guard's behavior.
# ============================================================================

PRE_TOPOLOGY_REVISION = "68215f964ca9"


def _legacy_type_id(conn, code: str):
    return conn.execute(text("SELECT id FROM location_types WHERE code = :code"), {"code": code}).scalar_one()


def _insert_legacy_location(
    conn, *, tenant_id, farm_id, location_type_code: str, code: str,
    parent_location_id=None, greenhouse_classification=None,
):
    import uuid

    location_id = uuid.uuid4()
    type_id = _legacy_type_id(conn, location_type_code)
    conn.execute(
        text(
            "INSERT INTO locations (id, tenant_id, farm_id, parent_location_id, location_type_id, "
            "code, name, status, greenhouse_classification, occupiable) "
            "VALUES (:id, :tid, :fid, :pid, :ltid, :code, :code, 'active', :classification, false)"
        ),
        {
            "id": location_id, "tid": tenant_id, "fid": farm_id, "pid": parent_location_id,
            "ltid": type_id, "code": code, "classification": greenhouse_classification,
        },
    )
    return location_id


def _build_legacy_tenant_farm(conn, *, suffix: str):
    import uuid

    tenant_id = uuid.uuid4()
    farm_id = uuid.uuid4()
    conn.execute(
        text("INSERT INTO tenants (id, code, name, status) VALUES (:id, :code, :code, 'active')"),
        {"id": tenant_id, "code": f"df1-{suffix}"},
    )
    conn.execute(
        text(
            "INSERT INTO farms (id, tenant_id, code, name, status, country_code, timezone) "
            "VALUES (:id, :tid, :code, :code, 'active', 'AE', 'Asia/Dubai')"
        ),
        {"id": farm_id, "tid": tenant_id, "code": f"df1-farm-{suffix}"},
    )
    return tenant_id, farm_id


def _cleanup_legacy_tenant(test_engine, tenant_id) -> None:
    """The migration guard tests build tenants/farms/locations directly via
    raw SQL against a downgraded schema (the ORM-based shared scenario
    cleanups assume the current schema shape) -- clean up the same way,
    with FK/trigger checks disabled so this works regardless of which
    schema revision is currently active."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM locations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()


@pytest.mark.integration
def test_migration_upgrade_rejects_existing_nursery_greenhouse_with_invalid_zone_child(
    test_engine, alembic_head_restore
) -> None:
    """(A) An existing Nursery greenhouse with a `zone` child (legal under
    the old generic rules, illegal under the new Nursery-scoped rules,
    which do not use zone/span at all) must block the upgrade."""
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), PRE_TOPOLOGY_REVISION)

    conn = test_engine.connect()
    trans = conn.begin()
    tenant_id, farm_id = _build_legacy_tenant_farm(conn, suffix="nursery-zone")
    gh_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="greenhouse",
        code="GH-NURSERY-A", greenhouse_classification="nursery",
    )
    zone_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="zone",
        code="ZONE-A", parent_location_id=gh_id,
    )
    trans.commit()
    conn.close()

    try:
        with pytest.raises(RuntimeError, match="DOMAIN-FARM-001 cannot activate classification-scoped topology"):
            command.upgrade(_cfg(), "head")

        with test_engine.connect() as conn2:
            current = conn2.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == PRE_TOPOLOGY_REVISION, "a failed guard must leave the database at its pre-upgrade revision"

            # (H) data-preservation proof: both rows survive, unchanged.
            rows = conn2.execute(
                text("SELECT id, code, parent_location_id FROM locations WHERE tenant_id = :tid ORDER BY code"),
                {"tid": tenant_id},
            ).mappings().all()
            assert [r["code"] for r in rows] == ["GH-NURSERY-A", "ZONE-A"]
            assert rows[1]["parent_location_id"] == gh_id
    finally:
        _cleanup_legacy_tenant(test_engine, tenant_id)


@pytest.mark.integration
def test_migration_upgrade_rejects_existing_leafy_greenhouse_with_table_position_under_grow_table(
    test_engine, alembic_head_restore
) -> None:
    """(B) An existing Leafy greenhouse with a full, otherwise-legal
    greenhouse->zone->span->grow_table chain, plus one extra
    grow_table->table_position edge (legal under the old generic rules,
    illegal under the new Leafy-scoped rules, which stop at grow_table)."""
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), PRE_TOPOLOGY_REVISION)

    conn = test_engine.connect()
    trans = conn.begin()
    tenant_id, farm_id = _build_legacy_tenant_farm(conn, suffix="leafy-tp")
    gh_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="greenhouse",
        code="GH-LEAFY-A", greenhouse_classification="leafy_greens",
    )
    zone_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="zone",
        code="ZONE-A", parent_location_id=gh_id,
    )
    span_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="span",
        code="SPAN-A", parent_location_id=zone_id,
    )
    table_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="grow_table",
        code="TABLE-A", parent_location_id=span_id,
    )
    position_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="table_position",
        code="POS-A", parent_location_id=table_id,
    )
    trans.commit()
    conn.close()

    try:
        with pytest.raises(RuntimeError, match="DOMAIN-FARM-001 cannot activate classification-scoped topology"):
            command.upgrade(_cfg(), "head")

        with test_engine.connect() as conn2:
            current = conn2.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == PRE_TOPOLOGY_REVISION

            rows = conn2.execute(
                text("SELECT id, code FROM locations WHERE tenant_id = :tid ORDER BY code"),
                {"tid": tenant_id},
            ).mappings().all()
            assert [r["code"] for r in rows] == ["GH-LEAFY-A", "POS-A", "SPAN-A", "TABLE-A", "ZONE-A"]
    finally:
        _cleanup_legacy_tenant(test_engine, tenant_id)


@pytest.mark.integration
def test_migration_upgrade_rejects_existing_vines_greenhouse_with_gutter_side(
    test_engine, alembic_head_restore
) -> None:
    """(C) An existing Vines greenhouse with a full, otherwise-legal
    greenhouse->zone->span->grow_gutter chain, plus one extra
    grow_gutter->gutter_side edge (legal under the old generic rules,
    illegal under the new Vines-scoped rules -- gutter_side is deliberately
    absent, since it is not a crop-placement location)."""
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), PRE_TOPOLOGY_REVISION)

    conn = test_engine.connect()
    trans = conn.begin()
    tenant_id, farm_id = _build_legacy_tenant_farm(conn, suffix="vines-side")
    gh_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="greenhouse",
        code="GH-VINES-A", greenhouse_classification="vines",
    )
    zone_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="zone",
        code="ZONE-A", parent_location_id=gh_id,
    )
    span_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="span",
        code="SPAN-A", parent_location_id=zone_id,
    )
    gutter_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="grow_gutter",
        code="GUTTER-A", parent_location_id=span_id,
    )
    side_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="gutter_side",
        code="SIDE-A", parent_location_id=gutter_id,
    )
    trans.commit()
    conn.close()

    try:
        with pytest.raises(RuntimeError, match="DOMAIN-FARM-001 cannot activate classification-scoped topology"):
            command.upgrade(_cfg(), "head")

        with test_engine.connect() as conn2:
            current = conn2.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == PRE_TOPOLOGY_REVISION

            rows = conn2.execute(
                text("SELECT id, code FROM locations WHERE tenant_id = :tid ORDER BY code"),
                {"tid": tenant_id},
            ).mappings().all()
            assert [r["code"] for r in rows] == ["GH-VINES-A", "GUTTER-A", "SIDE-A", "SPAN-A", "ZONE-A"]
    finally:
        _cleanup_legacy_tenant(test_engine, tenant_id)


@pytest.mark.integration
def test_migration_upgrade_rejects_existing_leafy_greenhouse_span_shortcut(
    test_engine, alembic_head_restore
) -> None:
    """(D) An existing Leafy greenhouse with `span` created directly under
    the greenhouse (skipping zone -- legal under the old generic rules,
    illegal under the new Leafy-scoped rules, which require the full exact
    chain with no shortcuts)."""
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), PRE_TOPOLOGY_REVISION)

    conn = test_engine.connect()
    trans = conn.begin()
    tenant_id, farm_id = _build_legacy_tenant_farm(conn, suffix="leafy-shortcut")
    gh_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="greenhouse",
        code="GH-LEAFY-B", greenhouse_classification="leafy_greens",
    )
    span_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="span",
        code="SPAN-B", parent_location_id=gh_id,
    )
    trans.commit()
    conn.close()

    try:
        with pytest.raises(RuntimeError, match="DOMAIN-FARM-001 cannot activate classification-scoped topology"):
            command.upgrade(_cfg(), "head")

        with test_engine.connect() as conn2:
            current = conn2.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == PRE_TOPOLOGY_REVISION

            rows = conn2.execute(
                text("SELECT id, code FROM locations WHERE tenant_id = :tid ORDER BY code"),
                {"tid": tenant_id},
            ).mappings().all()
            assert [r["code"] for r in rows] == ["GH-LEAFY-B", "SPAN-B"]
    finally:
        _cleanup_legacy_tenant(test_engine, tenant_id)


@pytest.mark.integration
def test_migration_upgrade_accepts_existing_valid_greenhouse_trees(test_engine, alembic_head_restore) -> None:
    """(G) A pre-existing tree that already happens to match the new
    authoritative shape exactly (Nursery: greenhouse->germination_chamber
    ->chamber_position; Leafy: greenhouse->zone->span->grow_table) must
    upgrade cleanly -- the guard must not be a false positive against
    genuinely legal data."""
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), PRE_TOPOLOGY_REVISION)

    conn = test_engine.connect()
    trans = conn.begin()
    tenant_id, farm_id = _build_legacy_tenant_farm(conn, suffix="valid")
    nursery_gh_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="greenhouse",
        code="GH-NURSERY-VALID", greenhouse_classification="nursery",
    )
    chamber_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="germination_chamber",
        code="CHAMBER-VALID", parent_location_id=nursery_gh_id,
    )
    position_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="chamber_position",
        code="POS-VALID", parent_location_id=chamber_id,
    )
    leafy_gh_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="greenhouse",
        code="GH-LEAFY-VALID", greenhouse_classification="leafy_greens",
    )
    zone_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="zone",
        code="ZONE-VALID", parent_location_id=leafy_gh_id,
    )
    span_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="span",
        code="SPAN-VALID", parent_location_id=zone_id,
    )
    table_id = _insert_legacy_location(
        conn, tenant_id=tenant_id, farm_id=farm_id, location_type_code="grow_table",
        code="TABLE-VALID", parent_location_id=span_id,
    )
    trans.commit()
    conn.close()

    try:
        command.upgrade(_cfg(), "head")

        with test_engine.connect() as conn2:
            current = conn2.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == _resolve_head_revision(_cfg())

            rows = conn2.execute(
                text("SELECT id, code, parent_location_id FROM locations WHERE tenant_id = :tid ORDER BY code"),
                {"tid": tenant_id},
            ).mappings().all()
            assert {r["code"] for r in rows} == {
                "GH-NURSERY-VALID", "CHAMBER-VALID", "POS-VALID",
                "GH-LEAFY-VALID", "ZONE-VALID", "SPAN-VALID", "TABLE-VALID",
            }
            by_code = {r["code"]: r for r in rows}
            assert by_code["CHAMBER-VALID"]["parent_location_id"] == nursery_gh_id
            assert by_code["POS-VALID"]["parent_location_id"] == chamber_id
            assert by_code["TABLE-VALID"]["parent_location_id"] == span_id
    finally:
        _cleanup_legacy_tenant(test_engine, tenant_id)


# =====================================================================
# DOMAIN-FARM-002: capacity-aware occupancy migration round-trip (section 30)
# =====================================================================

PRE_CAPACITY_REVISION = "9ca4ac801827"


def _cleanup_capacity_migration_tenant(test_engine, tenant_id) -> None:
    """Unlike `_cleanup_legacy_tenant` (locations/farms/tenants only), these
    scenarios also create assets, asset_positions, occupancies, movements,
    and carriers -- delete those first, still under
    `session_replication_role = replica` (which disables PostgreSQL's
    internal FK-enforcement triggers too, not just user triggers)."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM occupancies WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM movements WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM asset_positions WHERE asset_id IN (SELECT id FROM assets WHERE tenant_id = :tid)"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM assets WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM locations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()


def _build_capacity_migration_scenario(test_engine, *, suffix: str, position_capacity):
    import uuid as uuid_module

    from sqlalchemy.orm import Session

    # users are global/platform-level and never cleaned up by
    # _cleanup_capacity_migration_tenant (mirrors every other ORM-based
    # scenario builder in this file) -- a random component guarantees
    # oidc_subject uniqueness across repeated runs, unlike a fixed label.
    suffix = f"{suffix}-{uuid_module.uuid4().hex[:8]}"

    from app.services import asset_service, farm_service, location_service, membership_service, tenant_service, user_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant = tenant_service.create_tenant(session, code=f"cap-mig-{suffix}", name="Capacity Migration Tenant")
    user = user_service.create_user(
        session, oidc_issuer="cap-mig", oidc_subject=suffix, email=f"cap-mig-{suffix}@example.com",
        display_name="Capacity Migration User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Capacity Migration Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    greenhouse = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code=f"gh-{suffix}", name="GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    chamber = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code=f"gc-{suffix}", name="Chamber",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=None,
    )
    position = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="chamber_position", code=f"p-{suffix}", name="Position",
        parent_location_id=chamber.id, greenhouse_classification=None, occupiable=None, capacity=position_capacity,
    )
    trolley = asset_service.register_asset(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name="Trolley", commissioned_date=None,
    )
    result = {"tenant_id": tenant.id, "farm_id": farm.id, "user_id": user.id, "position_id": position.id, "trolley_id": trolley.id}
    session.close()
    conn.close()
    return result


@pytest.mark.integration
def test_capacity_migration_safe_round_trip_downgrade_then_upgrade(test_engine, alembic_head_restore) -> None:
    """(Q) No expanded capacity, no multi-occupancy anywhere -- downgrading
    past f91c366cfe57 and upgrading back must succeed cleanly."""
    _assert_operating_on_cmp_test_database(test_engine)
    scenario = _build_capacity_migration_scenario(test_engine, suffix="safe", position_capacity=None)
    try:
        from app.services import movement_service
        from datetime import datetime, timezone
        from sqlalchemy.orm import Session
        import uuid as uuid_module

        conn = test_engine.connect()
        session = Session(bind=conn)
        movement_service.execute_movement(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid_module.uuid4(), effective_time=datetime.now(timezone.utc),
            occupant_kind="asset", occupant_id=scenario["trolley_id"],
            destination_kind="location", destination_id=scenario["position_id"], reason=None,
        )
        session.close()
        conn.close()

        command.downgrade(_cfg(), PRE_CAPACITY_REVISION)
        with test_engine.connect() as conn2:
            current = conn2.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == PRE_CAPACITY_REVISION
            has_capacity_column = conn2.execute(
                text("SELECT 1 FROM information_schema.columns WHERE table_name = 'locations' AND column_name = 'capacity'")
            ).scalar_one_or_none()
            assert has_capacity_column is None

        command.upgrade(_cfg(), "head")
        with test_engine.connect() as conn3:
            current = conn3.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == _resolve_head_revision(_cfg())
            rows = conn3.execute(
                text("SELECT code FROM locations WHERE tenant_id = :tid ORDER BY code"), {"tid": scenario["tenant_id"]}
            ).mappings().all()
            codes = {r["code"] for r in rows}
            assert len(codes) == 3
            assert any(c.startswith("gh-safe-") for c in codes)
            assert any(c.startswith("gc-safe-") for c in codes)
            assert any(c.startswith("p-safe-") for c in codes)
    finally:
        _cleanup_capacity_migration_tenant(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_capacity_migration_downgrade_refuses_when_capacity_configured(test_engine, alembic_head_restore) -> None:
    """(R) A Location with configured capacity > 1 exists (regardless of how
    many occupants are actually active right now) -- downgrade must refuse
    loudly rather than silently discard the configuration, and business
    rows must remain untouched."""
    _assert_operating_on_cmp_test_database(test_engine)
    scenario = _build_capacity_migration_scenario(test_engine, suffix="configured", position_capacity=3)
    try:
        with pytest.raises(RuntimeError, match="DOMAIN-FARM-002 downgrade refused"):
            command.downgrade(_cfg(), PRE_CAPACITY_REVISION)

        with test_engine.connect() as conn:
            current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == _resolve_head_revision(_cfg()), "a refused downgrade must leave the database at head"
            capacity = conn.execute(
                text("SELECT capacity FROM locations WHERE id = :id"), {"id": scenario["position_id"]}
            ).scalar_one()
            assert capacity == 3
    finally:
        _cleanup_capacity_migration_tenant(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_capacity_migration_downgrade_refuses_when_multi_occupancy_present(test_engine, alembic_head_restore) -> None:
    """(R) A target currently has more than one active occupancy (capacity
    actually in use, not merely configured) -- downgrade must refuse rather
    than collapse/delete occupants or choose one arbitrarily."""
    import uuid as uuid_module
    from datetime import datetime, timezone

    from app.models.movement import Movement
    from app.models.occupancy import Occupancy
    from sqlalchemy.orm import Session

    from app.services import asset_service

    _assert_operating_on_cmp_test_database(test_engine)
    scenario = _build_capacity_migration_scenario(test_engine, suffix="multiocc", position_capacity=2)
    conn = test_engine.connect()
    session = Session(bind=conn)
    second_trolley = asset_service.register_asset(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        asset_type_code="germination_trolley", code="GT-multiocc-2", name="Trolley 2", commissioned_date=None,
    )
    now = datetime.now(timezone.utc)
    for trolley_id in (scenario["trolley_id"], second_trolley.id):
        mv = Movement(
            id=uuid_module.uuid4(), tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            occupant_asset_id=trolley_id, destination_location_id=scenario["position_id"],
            command_type="movement", client_command_id=uuid_module.uuid4(),
            request_fingerprint=f"mig-{trolley_id}", effective_time=now, actor_user_id=scenario["user_id"],
        )
        session.add(mv)
        session.flush()
        occ = Occupancy(
            id=uuid_module.uuid4(), tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            occupant_asset_id=trolley_id, target_location_id=scenario["position_id"],
            effective_time=now, opened_by_movement_id=mv.id, actor_user_id=scenario["user_id"],
        )
        session.add(occ)
        session.flush()
    session.commit()
    session.close()
    conn.close()

    try:
        with pytest.raises(RuntimeError, match="DOMAIN-FARM-002 downgrade refused"):
            command.downgrade(_cfg(), PRE_CAPACITY_REVISION)

        with test_engine.connect() as conn2:
            current = conn2.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == _resolve_head_revision(_cfg())
            active_count = conn2.execute(
                text(
                    "SELECT COUNT(*) FROM occupancies WHERE target_location_id = :tid AND end_time IS NULL"
                ),
                {"tid": scenario["position_id"]},
            ).scalar_one()
            assert active_count == 2, "downgrade guard must never collapse/delete occupants"
    finally:
        _cleanup_capacity_migration_tenant(test_engine, scenario["tenant_id"])
