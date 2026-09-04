"""UX-IA-001: proves `10430de8731e`'s downgrade guard actually refuses once
real command-idempotency evidence exists, rather than only being exercised
against an empty table (as the rest of the suite implicitly does, since
`apply_test_migrations` always starts each session at head on a schema no
test in this file has yet populated). Mirrors the established downgrade-
guard test shape (`test_produce_lot_ledger_downgrade_guard_hardening.py`,
`a1c4e8f2b6d3`'s own guard in the migration this one sits directly above)
at the smallest scale this guard actually needs: one populated command-id
column is sufficient to prove the guard fires; a full multi-state matrix is
not warranted for a guard this narrow (a single `count(*) > 0` check across
three columns, not a multi-fact reconciliation)."""
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.services import farm_service, location_service, membership_service, tenant_service
from tests.conftest import assert_cmp_test_database

API_ROOT = Path(__file__).resolve().parent.parent
NEW_REVISION = "10430de8731e"


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _parent_revision(cfg: Config) -> str:
    """Never hardcoded: derived from the live revision graph."""
    return ScriptDirectory.from_config(cfg).get_revision(NEW_REVISION).down_revision


def _current_version(test_engine) -> str:
    with test_engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _build_committed_location_with_update_history(test_engine) -> dict:
    """A real, committed Store Location that has actually gone through
    `update_location` once -- populating `update_client_command_id`/
    `update_request_fingerprint` exactly as a real rename would, via a
    dedicated connection/commit (not the rollback-only `db_session`
    fixture), so it's genuinely visible to the separate Alembic connection
    `command.downgrade` opens."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"loc-migr-{suffix}", name="Loc Migration Guard Tenant")
    from app.services import user_service

    user = user_service.create_user(
        session, oidc_issuer="loc-migr", oidc_subject=suffix, email=f"loc-migr-{suffix}@example.com",
        display_name="Loc Migration Guard User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Loc Migration Guard Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    store = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="store", code="STORE-1", name="Store",
        parent_location_id=None, greenhouse_classification=None, occupiable=None,
    )
    renamed = location_service.update_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=store.id, name="Renamed Store",
    )
    result = {"tenant_id": tenant.id, "location_id": renamed.id, "location_name": renamed.name}
    session.close()
    conn.close()
    return result


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM locations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_downgrade_refuses_once_command_history_is_populated(test_engine, alembic_head_restore) -> None:
    assert_cmp_test_database(test_engine)
    assert _current_version(test_engine) == NEW_REVISION, (
        "this test assumes the session-wide apply_test_migrations fixture already brought cmp_test to head"
    )
    info = _build_committed_location_with_update_history(test_engine)

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past UX-IA-001"):
            command.downgrade(_cfg(), _parent_revision(_cfg()))

        # Refused: still at NEW_REVISION, nothing dropped.
        assert _current_version(test_engine) == NEW_REVISION

        # The Location itself, and its command-history evidence, survive
        # untouched -- the guard's whole purpose is to never silently
        # discard this.
        with test_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT name, update_client_command_id, update_request_fingerprint FROM locations "
                    "WHERE id = :lid"
                ),
                {"lid": info["location_id"]},
            ).mappings().one()
        assert row["name"] == info["location_name"]
        assert row["update_client_command_id"] is not None
        assert row["update_request_fingerprint"] is not None
    finally:
        _cleanup(test_engine, info["tenant_id"])
