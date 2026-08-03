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
