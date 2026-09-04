"""STORE-INV-001B downgrade-guard proof tests -- mirrors
test_carrier_specification_downgrade_guard.py's own approach exactly."""
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_STORE_INVENTORY_REVISION = "b3bcfef4052e"


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


def _create_minimal_tenant(session, *, code_suffix: str):
    from app.services import tenant_service, user_service, membership_service

    tenant = tenant_service.create_tenant(session, code=f"invguard-{code_suffix}", name="Inventory Guard Tenant")
    user = user_service.create_user(
        session, oidc_issuer="invguard", oidc_subject=code_suffix, email=f"invguard-{code_suffix}@example.com",
        display_name="Inventory Guard User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    return tenant, user


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup against database {current_db!r}; "
            "this cleanup is only permitted against 'cmp_test'"
        )

    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM inventory_items WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM inventory_categories WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM locations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    except Exception:
        trans.rollback()
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        raise
    else:
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_downgrade_blocked_when_inventory_category_exists(test_engine, alembic_head_restore) -> None:
    from app.services import inventory_category_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user = _create_minimal_tenant(session, code_suffix=f"cat-{suffix}")
        tenant_id = tenant.id
        inventory_category_service.register_inventory_category(
            session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            code="GUARD-CAT", name="Guard Category",
        )
        session.commit()

        with pytest.raises(RuntimeError, match="inventory_categories row"):
            command.downgrade(_cfg(), _PRE_STORE_INVENTORY_REVISION)

        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup(test_engine, tenant_id)


@pytest.mark.integration
def test_downgrade_blocked_when_inventory_item_exists(test_engine, alembic_head_restore) -> None:
    from app.models.unit_of_measure import UnitOfMeasure
    from sqlalchemy import select
    from app.services import inventory_category_service, inventory_item_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user = _create_minimal_tenant(session, code_suffix=f"item-{suffix}")
        tenant_id = tenant.id
        category = inventory_category_service.register_inventory_category(
            session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            code="GUARD-CAT2", name="Guard Category 2",
        )
        uom_id = session.execute(select(UnitOfMeasure.id).where(UnitOfMeasure.code == "EA")).scalar_one()
        inventory_item_service.register_inventory_item(
            session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            code="GUARD-ITEM", name="Guard Item", category_id=category.id, base_uom_id=uom_id,
            lot_tracking_required=False, expiry_tracking_required=False, qc_release_required=False,
        )
        session.commit()

        with pytest.raises(RuntimeError, match="inventory_items row"):
            command.downgrade(_cfg(), _PRE_STORE_INVENTORY_REVISION)

        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup(test_engine, tenant_id)


@pytest.mark.integration
def test_downgrade_blocked_when_store_area_location_exists(test_engine, alembic_head_restore) -> None:
    from app.services import farm_service, location_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user = _create_minimal_tenant(session, code_suffix=f"loc-{suffix}")
        tenant_id = tenant.id
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"guard-farm-{suffix}",
            name="Guard Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        store = location_service.create_location(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="store",
            code="GUARD-STORE", name="Guard Store", parent_location_id=None, greenhouse_classification=None,
            occupiable=None,
        )
        location_service.create_location(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            location_type_code="store_area", code="GUARD-AREA", name="Guard Area",
            parent_location_id=store.id, greenhouse_classification=None, occupiable=None,
        )
        session.commit()

        with pytest.raises(RuntimeError, match="store_area/store_rack"):
            command.downgrade(_cfg(), _PRE_STORE_INVENTORY_REVISION)

        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup(test_engine, tenant_id)


@pytest.mark.integration
def test_downgrade_clean_when_no_store_inventory_data_exists(test_engine, alembic_head_restore) -> None:
    command.downgrade(_cfg(), _PRE_STORE_INVENTORY_REVISION)
    with test_engine.connect() as verify_conn:
        current = verify_conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert current == _PRE_STORE_INVENTORY_REVISION
    command.upgrade(_cfg(), "head")
    _assert_at_head(test_engine)
