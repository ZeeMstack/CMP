"""POSTHARVEST-OPS-001B migration proofs: sole head, clean downgrade/
re-upgrade, and the unconditional downgrade guard when persisted
PackagingUnit/PackSpecification/PackSpecificationVersion rows exist --
mirrors test_grade_definition_migration.py's own conventions exactly."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.settings import settings
from tests._pack_specification_scenario import (
    build_committed_scenario,
    build_pack_specification_only_scenario,
    build_packaging_unit_only_scenario,
    cleanup_scenario,
)

API_ROOT = Path(__file__).resolve().parent.parent
_THIS_REVISION = "e8d5f3a2b6c1"
_PARENT_REVISION = "c9e3f7a2d5b8"


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
def test_downgrade_blocked_when_packaging_unit_exists_alone(test_engine, alembic_head_restore) -> None:
    """Isolated proof (pre-commit verification item A): a PackagingUnit
    row exists with the pack_specifications and pack_specification_versions
    tables entirely EMPTY (this scenario never creates a crop or a spec at
    all) -- the guard must still fire on PackagingUnit existence alone."""
    scenario = build_packaging_unit_only_scenario(test_engine)
    try:
        with test_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM pack_specifications")).scalar_one() == 0
            assert conn.execute(text("SELECT count(*) FROM pack_specification_versions")).scalar_one() == 0
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001B"):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_when_pack_specification_exists_alone(test_engine, alembic_head_restore) -> None:
    """Isolated proof (pre-commit verification item B): a PackSpecification
    row exists while the packaging_units table is completely EMPTY for
    this tenant (a PackSpecification never requires a PackagingUnit --
    only its VERSION does) and pack_specification_versions is empty too --
    the guard must still fire on PackSpecification existence alone."""
    scenario = build_pack_specification_only_scenario(test_engine)
    try:
        with test_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM packaging_units")).scalar_one() == 0, (
                "this scenario must never create a PackagingUnit row"
            )
            assert conn.execute(text("SELECT count(*) FROM pack_specification_versions")).scalar_one() == 0
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001B"):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_when_pack_specification_version_exists(test_engine, alembic_head_restore) -> None:
    """Isolated proof (pre-commit verification item C): a
    PackSpecificationVersion exists -- its required parent PackSpecification
    and PackagingUnit prerequisite rows legitimately exist alongside it
    (a version cannot exist without them), which is explicitly allowed."""
    scenario = build_committed_scenario(test_engine, draft_version_count=1)
    try:
        with test_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM pack_specification_versions")).scalar_one() >= 1
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001B"):
            command.downgrade(_cfg(), _PARENT_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_clean_downgrade_and_reupgrade(test_engine, alembic_head_restore) -> None:
    expected_tables = ["pack_specification_versions", "pack_specifications", "packaging_units"]
    with test_engine.connect() as conn:
        tables_before = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name = ANY(:names)"
            ),
            {"names": expected_tables},
        ).scalars().all()
    assert sorted(tables_before) == sorted(expected_tables)

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
                "('enforce_packaging_unit_transition', 'reject_packaging_unit_delete', "
                " 'reject_pack_specification_mutation', 'enforce_pack_specification_version_transition', "
                " 'reject_pack_specification_version_delete', "
                " 'enforce_pack_specification_version_insert_integrity')"
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
                "AND table_name = ANY(:names)"
            ),
            {"names": expected_tables},
        ).scalars().all()
        assert sorted(tables_after_reupgrade) == sorted(expected_tables)
        trigger_count = conn.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgname IN "
                "('packaging_units_enforce_transition', 'packaging_units_no_delete', "
                " 'pack_specifications_no_update', 'pack_specifications_no_delete', "
                " 'pack_specification_versions_enforce_transition', 'pack_specification_versions_no_delete', "
                " 'pack_specification_versions_enforce_insert_integrity')"
            )
        ).scalar_one()
        assert trigger_count == 7, "re-upgrade must recreate every trigger"
