"""PILOT-READY-001 migration round-trip proof for 2cd787662e3d (dispatch
temperature). Confirms, via `information_schema` introspection (never
merely "it round-tripped without error"): upgrade from f823982f465a lands
on 2cd787662e3d as the sole head; `dispatch_events.dispatch_temperature_c`
exists (nullable, numeric) with its sanity-range CHECK constraint after
upgrade; downgrade back to f823982f465a removes both the column and the
constraint; re-upgrade restores them and the sole head."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.settings import settings

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_REVISION = "f823982f465a"
_THIS_REVISION = "2cd787662e3d"


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_head_revision(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_current_head()


def _column_exists(conn) -> bool:
    return conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'dispatch_events' AND column_name = 'dispatch_temperature_c')"
        )
    ).scalar_one()


def _check_constraint_exists(conn) -> bool:
    return conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.check_constraints "
            "WHERE constraint_name = 'ck_dispatch_events_temperature_sane_range')"
        )
    ).scalar_one()


@pytest.mark.integration
def test_dispatch_temperature_migration_round_trip(test_engine, alembic_head_restore) -> None:
    cfg = _cfg()
    expected_head = _resolve_head_revision(cfg)
    assert expected_head == _THIS_REVISION, "this test's own file must be the current Alembic head"

    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert current == _THIS_REVISION, "test_engine fixture must start every test already at head"

    with test_engine.connect() as conn:
        assert _column_exists(conn) is True
        assert _check_constraint_exists(conn) is True

    command.downgrade(cfg, _PRE_REVISION)
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _PRE_REVISION
        assert _column_exists(conn) is False
        assert _check_constraint_exists(conn) is False

    command.upgrade(cfg, "head")
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _resolve_head_revision(cfg)
        assert current == _THIS_REVISION
        assert _column_exists(conn) is True
        assert _check_constraint_exists(conn) is True
