"""PILOT-PLAN-001A migration proofs: sole head, clean downgrade/re-upgrade
when no forecast/capacity history exists, and the two-table downgrade
guard (a `BatchHarvestForecast` row / a `ProductionCapacityAllocation`
row) -- mirrors test_planning_migration.py's `_cfg()`/downgrade-guard
conventions exactly."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.settings import settings
from tests._harvest_forecast_capacity_migration_scenario import (
    build_batch_harvest_forecast_scenario,
    build_capacity_allocation_scenario,
    cleanup_scenario,
)

API_ROOT = Path(__file__).resolve().parent.parent
_THIS_REVISION = "b44ba79079ef"
_PARENT_REVISION = "b202c013643f"
_GUARD_MATCH = "Cannot downgrade past PILOT-PLAN-001A"


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
def test_migration_is_part_of_the_current_revision_chain() -> None:
    script_dir = ScriptDirectory.from_config(_cfg())
    current_head = script_dir.get_current_head()
    ancestor_revisions = {rev.revision for rev in script_dir.iterate_revisions(current_head, "base")}
    assert _THIS_REVISION in ancestor_revisions
    this_rev = script_dir.get_revision(_THIS_REVISION)
    assert this_rev.down_revision == _PARENT_REVISION


@pytest.mark.integration
def test_downgrade_blocked_when_batch_harvest_forecast_exists(test_engine, alembic_head_restore) -> None:
    scenario = build_batch_harvest_forecast_scenario(test_engine)
    try:
        with pytest.raises(RuntimeError, match=_GUARD_MATCH):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_when_production_capacity_allocation_exists(test_engine, alembic_head_restore) -> None:
    scenario = build_capacity_allocation_scenario(test_engine)
    try:
        with pytest.raises(RuntimeError, match=_GUARD_MATCH):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_clean_downgrade_and_reupgrade_when_no_plan_history(test_engine, alembic_head_restore) -> None:
    with test_engine.connect() as conn:
        tables_before = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name IN ('batch_harvest_forecasts', 'production_capacity_allocations')"
            )
        ).scalars().all()
    assert sorted(tables_before) == ["batch_harvest_forecasts", "production_capacity_allocations"]

    command.downgrade(_cfg(), _PARENT_REVISION)
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _PARENT_REVISION
        tables_after_downgrade = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name IN ('batch_harvest_forecasts', 'production_capacity_allocations')"
            )
        ).scalars().all()
        assert tables_after_downgrade == []
        triggers_after_downgrade = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN "
                "('batch_harvest_forecasts_no_delete', 'production_capacity_allocations_no_delete')"
            )
        ).scalars().all()
        assert triggers_after_downgrade == []

    command.upgrade(_cfg(), _THIS_REVISION)
    with test_engine.connect() as conn:
        current_after_reupgrade = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current_after_reupgrade == _THIS_REVISION
        tables_after_reupgrade = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name IN ('batch_harvest_forecasts', 'production_capacity_allocations')"
            )
        ).scalars().all()
        assert sorted(tables_after_reupgrade) == ["batch_harvest_forecasts", "production_capacity_allocations"]
