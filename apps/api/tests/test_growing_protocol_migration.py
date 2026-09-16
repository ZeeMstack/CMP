"""PILOT-AGRO-001 migration proof for `203d62ed9e9f` (growing protocols
and crop inspections): confirms it is the sole Alembic head, and that its
downgrade guard actually refuses once real agronomic history exists --
mirrors `test_farm_work_item_migration.py`'s own downgrade-guard shape,
using the dynamically-resolved current head (never a hardcoded revision
id) so a later ticket's migration stacking on top of this one cannot make
this test stale (see that file's own fix for exactly this failure mode)."""

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.services import (
    crop_service,
    growing_protocol_service,
    membership_service,
    tenant_service,
    user_service,
)
from tests.conftest import assert_cmp_test_database

API_ROOT = Path(__file__).resolve().parent.parent
THIS_REVISION = "203d62ed9e9f"


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_current_head(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_current_head()


def _parent_revision(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_revision(THIS_REVISION).down_revision


def _current_version(test_engine) -> str:
    with test_engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


@pytest.mark.integration
def test_migration_is_part_of_a_single_alembic_head_chain(test_engine, alembic_head_restore) -> None:
    """PILOT-AGRO-001 proof (22): exactly one Alembic head, and this
    migration is reachable from it."""
    cfg = _cfg()
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"expected exactly one Alembic head, found {heads}"
    assert _current_version(test_engine) == heads[0]

    # Walk back from head to prove 203d62ed9e9f is actually in the chain.
    script = ScriptDirectory.from_config(cfg)
    revs = {r.revision for r in script.walk_revisions(base="base", head=heads[0])}
    assert THIS_REVISION in revs


def _build_committed_scenario(test_engine) -> dict:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"gp-migr-{suffix}", name="GP Migration Guard Tenant")
    user = user_service.create_user(
        session, oidc_issuer="gp-migr", oidc_subject=suffix, email=f"gp-migr-{suffix}@example.com",
        display_name="GP Migration Guard User",
    )
    membership_service.add_membership(session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"CROP-{suffix}", common_name="Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    protocol = growing_protocol_service.register_protocol(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"GP-{suffix}", name="Migration Guard Protocol",
        crop_id=crop.id, variety_id=None, production_system_id=None, season_context=None,
    )
    result = {"tenant_id": tenant.id, "protocol_id": protocol.id, "protocol_code": protocol.code}
    session.close()
    conn.close()
    return result


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        for table in (
            "crop_issue_follow_ups", "crop_issues", "inspection_findings", "grower_inspections",
            "batch_protocol_assignments", "protocol_care_activities", "protocol_observation_requirements",
            "growing_protocol_versions", "growing_protocols", "audit_events", "farms", "tenant_memberships",
            "tenants",
        ):
            if conn.execute(text(f"SELECT to_regclass('{table}')")).scalar() is not None:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_downgrade_refuses_once_a_growing_protocol_exists(test_engine, alembic_head_restore) -> None:
    assert_cmp_test_database(test_engine)
    cfg = _cfg()
    starting_head = _resolve_current_head(cfg)
    info = _build_committed_scenario(test_engine)

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past PILOT-AGRO-001"):
            command.downgrade(cfg, _parent_revision(cfg))

        assert _current_version(test_engine) == starting_head

        with test_engine.connect() as conn:
            row = conn.execute(
                text("SELECT code FROM growing_protocols WHERE id = :pid"), {"pid": info["protocol_id"]},
            ).mappings().one()
        assert row["code"] == info["protocol_code"]
    finally:
        _cleanup(test_engine, info["tenant_id"])


@pytest.mark.integration
def test_downgrade_and_reupgrade_succeeds_on_empty_schema(test_engine, alembic_head_restore) -> None:
    assert_cmp_test_database(test_engine)
    cfg = _cfg()
    parent = _parent_revision(cfg)
    command.downgrade(cfg, parent)
    assert _current_version(test_engine) == parent
    command.upgrade(cfg, THIS_REVISION)
    assert _current_version(test_engine) == THIS_REVISION
