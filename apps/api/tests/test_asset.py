import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.main import app
from app.models.asset_type import AssetType
from app.schemas.asset import AssetCreate
from app.services import asset_service, farm_service, tenant_service
from app.services.errors import (
    AssetNotFoundError,
    AssetTypeNotFoundError,
    DuplicateAssetCodeError,
    FarmNotFoundError,
)

# --- Application-level (Pydantic) validation — no DB required ---


def test_asset_code_trimmed_and_uppercased() -> None:
    payload = AssetCreate(asset_type_code="weighing_scale", code="  ws-01  ", name="Scale 1")
    assert payload.code == "WS-01"


def test_asset_blank_code_rejected() -> None:
    with pytest.raises(ValueError):
        AssetCreate(asset_type_code="weighing_scale", code="   ", name="Scale 1")


def test_asset_service_exposes_no_delete_function() -> None:
    assert not hasattr(asset_service, "delete_asset")


def test_no_delete_route_registered_for_assets() -> None:
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if "DELETE" in methods and "/assets/" in path:
            pytest.fail(f"unexpected DELETE route: {path}")


# --- Integration (DB) ---


def _register(db_session, tenant, farm, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id,
        farm_id=farm.id,
        actor_user_id=user.id,
        asset_type_code="weighing_scale",
        code="WS-01",
        name="Scale 1",
        commissioned_date=None,
    )
    defaults.update(overrides)
    return asset_service.register_asset(db_session, **defaults)


@pytest.mark.integration
def test_asset_registration(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register(db_session, tenant, farm, user, asset_type_code="germination_trolley", code="GT-0001", name="Trolley 1")
    assert asset.code == "GT-0001"
    assert asset.status == "active"
    assert asset.retired_date is None


@pytest.mark.integration
def test_unknown_asset_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(AssetTypeNotFoundError):
        _register(db_session, tenant, farm, user, asset_type_code="not_a_type")


@pytest.mark.integration
def test_tenant_wide_case_insensitive_code_uniqueness(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _register(db_session, tenant, farm, user, code="WS-01")
    with pytest.raises(DuplicateAssetCodeError):
        _register(db_session, tenant, farm, user, code="ws-01")


@pytest.mark.integration
def test_same_asset_code_allowed_in_different_tenants(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset_a = _register(db_session, tenant, farm, user, code="WS-01")

    other_tenant = tenant_service.create_tenant(db_session, code="other-asset-tenant", name="Other")
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    asset_b = asset_service.register_asset(
        db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, actor_user_id=None,
        asset_type_code="weighing_scale", code="WS-01", name="Scale 1", commissioned_date=None,
    )
    assert asset_a.code == asset_b.code
    assert asset_a.tenant_id != asset_b.tenant_id


@pytest.mark.integration
def test_cross_tenant_asset_lookup_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register(db_session, tenant, farm, user)
    other_tenant = tenant_service.create_tenant(db_session, code="other-lookup-tenant", name="Other")
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, code="other-farm-2", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    with pytest.raises(AssetNotFoundError):
        asset_service.get_asset(db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, asset_id=asset.id)


@pytest.mark.integration
def test_inactive_farm_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    farm.status = "inactive"
    db_session.flush()
    with pytest.raises(FarmNotFoundError):
        _register(db_session, tenant, farm, user)


@pytest.mark.integration
def test_required_active_membership_for_asset_routes(client, db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="no-mem-asset-tenant", name="No Membership")
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="farm-1", name="Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    from app.services import user_service

    user = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="no-mem-asset", email="nma@example.com", display_name="NM"
    )
    response = client.get(
        f"/farms/{farm.id}/assets",
        headers={"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)},
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_retired_asset_without_retired_date_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset_type = db_session.execute(
        select(AssetType).where(AssetType.code == "weighing_scale")
    ).scalar_one()
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO assets (id, tenant_id, farm_id, asset_type_id, code, name, status) "
                    "VALUES (:id, :tenant_id, :farm_id, :type_id, 'BAD', 'Bad', 'retired')"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id, "type_id": asset_type.id},
            )


@pytest.mark.integration
def test_direct_sql_deletion_of_asset_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register(db_session, tenant, farm, user)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM assets WHERE id = :id"), {"id": asset.id})


@pytest.mark.integration
def test_failed_asset_registration_leaves_no_audit_event(db_session, active_context_with_farm) -> None:
    from sqlalchemy import func

    from app.models.audit_event import AuditEvent

    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(AssetTypeNotFoundError):
        _register(db_session, tenant, farm, user, asset_type_code="not_a_type")
    count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "asset.registered")
    ).scalar_one()
    assert count == 0
