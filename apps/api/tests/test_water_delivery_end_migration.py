"""UX-OPS-001D0 migration proofs, against explicit `cmp_test` only (mirrors
test_harvest_forecast_capacity_migration.py's `_cfg()` convention): part of
the single revision chain, downgrade blocked while end-event history exists,
and a clean downgrade/re-upgrade that leaves existing delivery rows
byte-for-byte unchanged."""

import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.services import reservoir_operations_service
from tests._water_delivery_end_scenario import build_open_delivery_scenario, cleanup_scenario

API_ROOT = Path(__file__).resolve().parent.parent
_THIS_REVISION = "3686130d89a9"
_PARENT_REVISION = "b44ba79079ef"
_GUARD_MATCH = "Cannot downgrade past UX-OPS-001D0"


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _current_revision(test_engine) -> str:
    with test_engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _delivery_row_json(test_engine, delivery_id) -> dict:
    with test_engine.connect() as conn:
        return conn.execute(
            text("SELECT to_jsonb(d) FROM water_delivery_events d WHERE id = :id"), {"id": delivery_id}
        ).scalar_one()


def _schema_objects(test_engine) -> dict:
    with test_engine.connect() as conn:
        return {
            "table": conn.execute(text("SELECT to_regclass('water_delivery_end_events')")).scalar(),
            "constraint": conn.execute(
                text("SELECT count(*) FROM pg_constraint WHERE conname = 'uq_water_delivery_events_tenant_farm_id'")
            ).scalar_one(),
            "function": conn.execute(
                text("SELECT count(*) FROM pg_proc WHERE proname = 'enforce_water_delivery_end_event_parent'")
            ).scalar_one(),
        }


@pytest.mark.integration
def test_migration_is_part_of_the_current_revision_chain() -> None:
    script_dir = ScriptDirectory.from_config(_cfg())
    current_head = script_dir.get_current_head()
    ancestor_revisions = {rev.revision for rev in script_dir.iterate_revisions(current_head, "base")}
    assert _THIS_REVISION in ancestor_revisions
    assert script_dir.get_revision(_THIS_REVISION).down_revision == _PARENT_REVISION


@pytest.mark.integration
def test_downgrade_blocked_while_end_event_history_exists(test_engine, alembic_head_restore) -> None:
    scenario = build_open_delivery_scenario(test_engine)
    try:
        with test_engine.connect() as conn:
            session = Session(bind=conn)
            reservoir_operations_service.end_delivery_event(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], water_delivery_event_id=scenario["delivery_id"],
                effective_end=scenario["effective_start"] + timedelta(minutes=5), note=None,
                client_command_id=uuid.uuid4(),
            )
            session.close()
        with pytest.raises(RuntimeError, match=_GUARD_MATCH):
            command.downgrade(_cfg(), _PARENT_REVISION)
        assert _current_revision(test_engine) == ScriptDirectory.from_config(_cfg()).get_current_head()
        assert _schema_objects(test_engine)["table"] is not None
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_clean_downgrade_and_reupgrade_preserves_existing_delivery_rows(test_engine, alembic_head_restore) -> None:
    scenario = build_open_delivery_scenario(test_engine)
    try:
        before = _delivery_row_json(test_engine, scenario["delivery_id"])
        assert _schema_objects(test_engine) == {"table": "water_delivery_end_events", "constraint": 1, "function": 1}

        command.downgrade(_cfg(), _PARENT_REVISION)
        assert _current_revision(test_engine) == _PARENT_REVISION
        assert _schema_objects(test_engine) == {"table": None, "constraint": 0, "function": 0}
        assert _delivery_row_json(test_engine, scenario["delivery_id"]) == before

        command.upgrade(_cfg(), _THIS_REVISION)
        assert _current_revision(test_engine) == _THIS_REVISION
        assert _schema_objects(test_engine) == {"table": "water_delivery_end_events", "constraint": 1, "function": 1}
        # No backfill, and the existing delivery row is untouched.
        assert _delivery_row_json(test_engine, scenario["delivery_id"]) == before
        with test_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM water_delivery_end_events")).scalar_one() == 0
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])
