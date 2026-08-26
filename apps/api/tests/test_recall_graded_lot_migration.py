"""POSTHARVEST-OPS-001D migration-chain proofs: parent revision and sole
head -- mirrors `test_grading_migration.py`'s own established conventions
for the immediately-preceding ticket."""
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.settings import settings

API_ROOT = Path(__file__).resolve().parent.parent
_THIS_REVISION = "c3f7a29d5e64"
_PARENT_REVISION = "f2c8a5d1e793"


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_head_revision(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_current_head()


@pytest.mark.integration
def test_migration_revises_the_expected_parent() -> None:
    script = ScriptDirectory.from_config(_cfg())
    this_revision = script.get_revision(_THIS_REVISION)
    assert this_revision.down_revision == _PARENT_REVISION


@pytest.mark.integration
def test_new_migration_is_sole_head() -> None:
    assert _resolve_head_revision(_cfg()) == _THIS_REVISION
