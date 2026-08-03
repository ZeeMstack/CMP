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
