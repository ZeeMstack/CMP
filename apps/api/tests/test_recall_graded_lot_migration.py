"""POSTHARVEST-OPS-001D migration-chain proofs: parent revision and
remaining the sole chain's direct ancestor (POSTHARVEST-OPS-001E now sits
on top) -- mirrors `test_grading_migration.py`'s own established
conventions for the immediately-preceding ticket."""
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
def test_this_revision_remains_the_sole_chains_direct_ancestor() -> None:
    """POSTHARVEST-OPS-001E (`d8f4a1c92b57`) now sits on top of this
    migration -- `c3f7a29d5e64` is no longer itself the head, but must
    remain part of the one single, unambiguous chain leading to it, never
    orphaned by a competing branch. `test_migrations.py`'s own
    `test_alembic_script_graph_resolves_single_unambiguous_head` proves
    the "exactly one head" half generically for every revision; this test
    keeps this ticket's own local proof that its specific revision is
    still on that one chain, updated for whichever ticket currently sits
    on top of it -- mirrors `test_grading_migration.py`'s identical
    convention."""
    cfg = _cfg()
    script = ScriptDirectory.from_config(cfg)
    rev = script.get_revision(_resolve_head_revision(cfg))
    ancestors = set()
    while rev is not None:
        ancestors.add(rev.revision)
        rev = script.get_revision(rev.down_revision) if rev.down_revision else None
    assert _THIS_REVISION in ancestors
