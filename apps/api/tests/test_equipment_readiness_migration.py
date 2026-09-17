"""PILOT-ASSET-001: proves `b202c013643f`'s downgrade guard actually
refuses once a real Equipment Incident exists, mirroring the established
downgrade-guard test shape (`test_farm_work_item_migration.py`). Uses the
dynamically-resolved current Alembic head rather than hardcoding this
migration's revision id as "head"."""
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.services import asset_service, equipment_incident_service, farm_service, membership_service, tenant_service, user_service
from tests.conftest import assert_cmp_test_database

API_ROOT = Path(__file__).resolve().parent.parent
NEW_REVISION = "b202c013643f"


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_current_head(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_current_head()


def _parent_revision(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_revision(NEW_REVISION).down_revision


def _current_version(test_engine) -> str:
    with test_engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _build_committed_incident(test_engine) -> dict:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"eqi-migr-{suffix}", name="Equipment Incident Migration Guard Tenant")
    user = user_service.create_user(
        session, oidc_issuer="eqi-migr", oidc_subject=suffix, email=f"eqi-migr-{suffix}@example.com",
        display_name="Equipment Migration Guard User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Equipment Migration Guard Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    asset = asset_service.register_asset(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_type_code="weighing_scale",
        code=f"WS-{suffix}", name="Scale", commissioned_date=None,
    )
    incident = equipment_incident_service.open_incident(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        asset_id=asset.id, location_id=None, potentially_impacted_location_id=None, severity="high",
        category="scale", description="Scale malfunction", detected_at=datetime.now(timezone.utc),
        assigned_owner_user_id=None, notes=None,
    )
    result = {"tenant_id": tenant.id, "incident_id": incident.id, "incident_code": incident.code}
    session.close()
    conn.close()
    return result


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        if conn.execute(text("SELECT to_regclass('qr_identifiers')")).scalar() is not None:
            conn.execute(text("DELETE FROM qr_identifiers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM equipment_incidents WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM equipment_readiness_states WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM assets WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_downgrade_refuses_once_an_equipment_incident_exists(test_engine, alembic_head_restore) -> None:
    assert_cmp_test_database(test_engine)
    cfg = _cfg()
    assert _current_version(test_engine) == _resolve_current_head(cfg), (
        "this test assumes the session-wide apply_test_migrations fixture already brought cmp_test to head"
    )
    info = _build_committed_incident(test_engine)
    starting_head = _resolve_current_head(cfg)

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past PILOT-ASSET-001"):
            command.downgrade(cfg, _parent_revision(cfg))

        assert _current_version(test_engine) == starting_head

        with test_engine.connect() as conn:
            row = conn.execute(
                text("SELECT code, status FROM equipment_incidents WHERE id = :iid"), {"iid": info["incident_id"]},
            ).mappings().one()
        assert row["code"] == info["incident_code"]
        assert row["status"] == "open"
    finally:
        _cleanup(test_engine, info["tenant_id"])
