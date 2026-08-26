"""POSTHARVEST-OPS-001A migration proofs: sole head, clean downgrade/
re-upgrade, and the unconditional downgrade guard when persisted
GradeDefinition/GradeDefinitionVersion rows exist — mirrors
test_packing_downgrade_guard.py's own `_cfg()`/downgrade-guard
conventions exactly."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.settings import settings
from tests._grade_definition_scenario import build_committed_scenario, cleanup_scenario

API_ROOT = Path(__file__).resolve().parent.parent
_THIS_REVISION = "c9e3f7a2d5b8"
_PARENT_REVISION = "b8f3c6d1e947"


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
def test_new_migration_is_sole_head() -> None:
    assert _resolve_head_revision(_cfg()) == _THIS_REVISION


@pytest.mark.integration
def test_downgrade_blocked_when_grade_definition_exists(test_engine, alembic_head_restore) -> None:
    scenario = build_committed_scenario(test_engine, draft_version_count=0)
    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001A"):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_when_grade_definition_version_exists(test_engine, alembic_head_restore) -> None:
    scenario = build_committed_scenario(test_engine, draft_version_count=1)
    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001A"):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_clean_downgrade_and_reupgrade(test_engine, alembic_head_restore) -> None:
    with test_engine.connect() as conn:
        tables_before = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name IN ('grade_definitions', 'grade_definition_versions')"
            )
        ).scalars().all()
    assert sorted(tables_before) == ["grade_definition_versions", "grade_definitions"]

    command.downgrade(_cfg(), _PARENT_REVISION)
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _PARENT_REVISION
        tables_after_downgrade = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name IN ('grade_definitions', 'grade_definition_versions')"
            )
        ).scalars().all()
        assert tables_after_downgrade == []
        functions_after_downgrade = conn.execute(
            text(
                "SELECT proname FROM pg_proc WHERE proname IN "
                "('enforce_grade_definition_version_transition', 'reject_grade_definition_version_delete', "
                " 'reject_grade_definition_mutation')"
            )
        ).scalars().all()
        assert functions_after_downgrade == [], "downgrade must drop every function it created"

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _resolve_head_revision(_cfg())
        tables_after_reupgrade = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name IN ('grade_definitions', 'grade_definition_versions')"
            )
        ).scalars().all()
        assert sorted(tables_after_reupgrade) == ["grade_definition_versions", "grade_definitions"]
        trigger_count = conn.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgname IN "
                "('grade_definition_versions_enforce_transition', 'grade_definition_versions_no_delete', "
                " 'grade_definitions_no_update', 'grade_definitions_no_delete')"
            )
        ).scalar_one()
        assert trigger_count == 4, "re-upgrade must recreate every trigger"
