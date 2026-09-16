"""PILOT-OPS-001: proves `3a278fa65f80`'s downgrade guard actually refuses
once a real Farm Work Item exists, mirroring the established downgrade-guard
test shape (`test_location_maintenance_migration.py`). Uses the
dynamically-resolved current Alembic head rather than hardcoding this
migration's revision id as "head" -- a later ticket's migration stacking on
top of this one must not make this test stale (see
`tests/test_migrations.py::_resolve_head_revision`)."""
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.services import farm_service, farm_work_item_service, membership_service, tenant_service, user_service
from tests.conftest import assert_cmp_test_database

API_ROOT = Path(__file__).resolve().parent.parent
NEW_REVISION = "3a278fa65f80"


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


def _build_committed_work_item(test_engine) -> dict:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"fwi-migr-{suffix}", name="FWI Migration Guard Tenant")
    user = user_service.create_user(
        session, oidc_issuer="fwi-migr", oidc_subject=suffix, email=f"fwi-migr-{suffix}@example.com",
        display_name="FWI Migration Guard User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="FWI Migration Guard Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    item = farm_work_item_service.create_work_item(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        work_type="cleaning", category="cleaning", title="Clean Trolley", instructions=None, priority="normal",
        due_at=None, assigned_to_user_id=None, crop_batch_id=None, location_id=None, carrier_id=None,
        asset_id=None, quantity=None, quantity_uom_id=None, completion_mode="manual_record",
    )
    result = {"tenant_id": tenant.id, "work_item_id": item.id, "work_item_code": item.code}
    session.close()
    conn.close()
    return result


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        # PILOT-SCAN-001D: qr_identifiers has only outbound FKs, so it is
        # always safe to delete first -- see tests/_traceability_scenario.py's
        # identical comment for the full rationale. Existence-guarded since
        # this cleanup may run while cmp_test is deliberately downgraded
        # below the migration that creates this table.
        if conn.execute(text("SELECT to_regclass('qr_identifiers')")).scalar() is not None:
            conn.execute(text("DELETE FROM qr_identifiers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farm_work_items WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_downgrade_refuses_once_a_farm_work_item_exists(test_engine, alembic_head_restore) -> None:
    assert_cmp_test_database(test_engine)
    cfg = _cfg()
    assert _current_version(test_engine) == _resolve_current_head(cfg), (
        "this test assumes the session-wide apply_test_migrations fixture already brought cmp_test to head, "
        "and that 3a278fa65f80 (PILOT-OPS-001) is that head"
    )
    info = _build_committed_work_item(test_engine)
    starting_head = _resolve_current_head(cfg)

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past PILOT-OPS-001"):
            command.downgrade(cfg, _parent_revision(cfg))

        # PILOT-AGRO-001: `env.py` runs a whole multi-revision `command.
        # downgrade(...)` call inside ONE transaction (no `transaction_per_
        # migration=True`), so an aborted downgrade rolls the ENTIRE batch
        # back to wherever it started -- never to the hardcoded `NEW_
        # REVISION` this test used to assert, which only happened to equal
        # the starting point while 3a278fa65f80 was itself still the
        # Alembic head. A later ticket's migration(s) stacking on top of
        # this one (as PILOT-AGRO-001's own 203d62ed9e9f now does) makes
        # `starting_head` something further downstream -- the guard still
        # fires at the same point in the chain (crossing 3a278fa65f80), so
        # asserting the dynamically-resolved starting head is what actually
        # stays correct for every future ticket, matching this file's own
        # docstring intent.
        assert _current_version(test_engine) == starting_head

        with test_engine.connect() as conn:
            row = conn.execute(
                text("SELECT code, status FROM farm_work_items WHERE id = :wid"), {"wid": info["work_item_id"]},
            ).mappings().one()
        assert row["code"] == info["work_item_code"]
        assert row["status"] == "open"
    finally:
        _cleanup(test_engine, info["tenant_id"])


@pytest.mark.integration
def test_downgrade_and_reupgrade_succeeds_on_empty_schema(test_engine, alembic_head_restore) -> None:
    """No Farm Work Item/Shift Handover row exists yet -- the guard must not
    block a clean downgrade/re-upgrade cycle."""
    assert_cmp_test_database(test_engine)
    cfg = _cfg()
    parent = _parent_revision(cfg)
    command.downgrade(cfg, parent)
    assert _current_version(test_engine) == parent
    command.upgrade(cfg, NEW_REVISION)
    assert _current_version(test_engine) == NEW_REVISION
