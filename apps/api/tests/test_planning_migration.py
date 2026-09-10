"""PLANNING-OPS-001 migration proofs: sole head, clean downgrade/re-upgrade
when no Planning history exists, and the three-tier downgrade guard
(Production Requirement rows / Seeding Program Line rows / an actual
Sowing Event's own `seeding_program_line_id` reference) -- mirrors
test_grade_definition_migration.py's `_cfg()`/downgrade-guard conventions
exactly."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.settings import settings
from tests._planning_migration_scenario import (
    build_linked_sowing_scenario,
    build_requirement_and_line_scenario,
    build_requirement_only_scenario,
    cleanup_scenario,
)

API_ROOT = Path(__file__).resolve().parent.parent
_THIS_REVISION = "2c3b8d0bab94"
_PARENT_REVISION = "5a26ba0dae6c"
_GUARD_MATCH = "Cannot downgrade past PLANNING-OPS-001"


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
    """2c3b8d0bab94 was the sole Alembic head at the time PLANNING-OPS-001
    was built. A later ticket may legitimately extend the chain on top of
    it -- asserting literal current sole-headedness here would go stale on
    purpose the moment that happens. The ongoing, ticket-agnostic "exactly
    one head" guarantee lives in
    test_migrations.py::test_alembic_script_graph_resolves_single_unambiguous_head,
    not here; this test only proves 2c3b8d0bab94 remains a real, reachable
    ancestor of whatever the current head is, with 5a26ba0dae6c as its
    immediate, unedited parent."""
    script_dir = ScriptDirectory.from_config(_cfg())
    current_head = script_dir.get_current_head()
    ancestor_revisions = {rev.revision for rev in script_dir.iterate_revisions(current_head, "base")}
    assert _THIS_REVISION in ancestor_revisions
    this_rev = script_dir.get_revision(_THIS_REVISION)
    assert this_rev.down_revision == _PARENT_REVISION


@pytest.mark.integration
def test_downgrade_blocked_when_production_requirement_exists(test_engine, alembic_head_restore) -> None:
    scenario = build_requirement_only_scenario(test_engine)
    try:
        with pytest.raises(RuntimeError, match=_GUARD_MATCH):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_when_seeding_program_line_exists(test_engine, alembic_head_restore) -> None:
    scenario = build_requirement_and_line_scenario(test_engine)
    try:
        with pytest.raises(RuntimeError, match=_GUARD_MATCH):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_when_sowing_event_references_seeding_program_line(
    test_engine, alembic_head_restore
) -> None:
    scenario = build_linked_sowing_scenario(test_engine)
    try:
        with pytest.raises(RuntimeError, match=_GUARD_MATCH):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_clean_downgrade_and_reupgrade_when_no_planning_history(test_engine, alembic_head_restore) -> None:
    with test_engine.connect() as conn:
        tables_before = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name IN ('production_requirements', 'seeding_program_lines')"
            )
        ).scalars().all()
        column_before = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'sowing_events' "
                "AND column_name = 'seeding_program_line_id'"
            )
        ).scalars().all()
    assert sorted(tables_before) == ["production_requirements", "seeding_program_lines"]
    assert column_before == ["seeding_program_line_id"]

    command.downgrade(_cfg(), _PARENT_REVISION)
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _PARENT_REVISION
        tables_after_downgrade = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name IN ('production_requirements', 'seeding_program_lines')"
            )
        ).scalars().all()
        assert tables_after_downgrade == []
        column_after_downgrade = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'sowing_events' "
                "AND column_name = 'seeding_program_line_id'"
            )
        ).scalars().all()
        assert column_after_downgrade == [], "downgrade must drop the additive sowing_events column"
        triggers_after_downgrade = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN "
                "('production_requirements_no_delete', 'seeding_program_lines_no_delete')"
            )
        ).scalars().all()
        assert triggers_after_downgrade == [], "downgrade must drop every trigger it created"

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _resolve_head_revision(_cfg())
        tables_after_reupgrade = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name IN ('production_requirements', 'seeding_program_lines')"
            )
        ).scalars().all()
        assert sorted(tables_after_reupgrade) == ["production_requirements", "seeding_program_lines"]
        column_after_reupgrade = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'sowing_events' "
                "AND column_name = 'seeding_program_line_id'"
            )
        ).scalars().all()
        assert column_after_reupgrade == ["seeding_program_line_id"]
        triggers_after_reupgrade = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger WHERE tgname IN "
                "('production_requirements_no_delete', 'seeding_program_lines_no_delete')"
            )
        ).scalars().all()
        assert sorted(triggers_after_reupgrade) == [
            "production_requirements_no_delete", "seeding_program_lines_no_delete",
        ], "re-upgrade must recreate every trigger"
