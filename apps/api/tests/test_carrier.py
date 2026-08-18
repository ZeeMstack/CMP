import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.main import app
from app.models.carrier_type import CarrierType
from app.schemas.carrier import CarrierCreate
from app.services import carrier_service, farm_service, tenant_service
from app.services.errors import (
    CarrierNotFoundError,
    CarrierTypeNotFoundError,
    DuplicateCarrierCodeError,
    FarmNotFoundError,
)
from tests.conftest import ensure_seed_tray_specification

# --- Application-level (Pydantic) validation — no DB required ---


def test_carrier_code_trimmed_and_uppercased() -> None:
    payload = CarrierCreate(carrier_type_code="seed_tray", code="  st-01  ")
    assert payload.code == "ST-01"


def test_carrier_blank_code_rejected() -> None:
    with pytest.raises(ValueError):
        CarrierCreate(carrier_type_code="seed_tray", code="   ")


def test_carrier_service_exposes_no_delete_function() -> None:
    assert not hasattr(carrier_service, "delete_carrier")


def test_no_delete_route_registered_for_carriers() -> None:
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if "DELETE" in methods and "/carriers/" in path:
            pytest.fail(f"unexpected DELETE route: {path}")


# --- Integration (DB) ---


def _register(db_session, tenant, farm, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id,
        farm_id=farm.id,
        actor_user_id=user.id,
        carrier_type_code="seed_tray",
        code="ST-00001",
        issued_date=None,
    )
    # CARRIER-CONFIG-001A: only swap in a resolved seed_tray specification
    # when the caller is actually using the seed_tray default -- a caller
    # overriding carrier_type_code (e.g. to "grow_bag"/"not_a_type") must
    # not also inherit a seed_tray specification_id, which would collide
    # with CarrierSpecificationTypeMismatchError.
    if "carrier_type_code" not in overrides:
        defaults["carrier_type_code"] = None
        defaults["specification_id"] = ensure_seed_tray_specification(
            db_session, tenant_id=tenant.id, actor_user_id=user.id,
        ).id
    defaults.update(overrides)
    return carrier_service.register_carrier(db_session, **defaults)


@pytest.mark.integration
def test_carrier_registration(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register(db_session, tenant, farm, user, carrier_type_code="grow_bag", code="GB-00001")
    assert carrier.code == "GB-00001"
    assert carrier.status == "active"


@pytest.mark.integration
def test_unknown_carrier_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(CarrierTypeNotFoundError):
        _register(db_session, tenant, farm, user, carrier_type_code="not_a_type")


@pytest.mark.integration
def test_tenant_wide_case_insensitive_code_uniqueness(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _register(db_session, tenant, farm, user, code="ST-00001")
    with pytest.raises(DuplicateCarrierCodeError):
        _register(db_session, tenant, farm, user, code="st-00001")


@pytest.mark.integration
def test_same_carrier_code_allowed_in_different_tenants(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier_a = _register(db_session, tenant, farm, user, code="ST-00001")

    other_tenant = tenant_service.create_tenant(db_session, code="other-carrier-tenant", name="Other")
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_spec = ensure_seed_tray_specification(db_session, tenant_id=other_tenant.id, actor_user_id=None)
    carrier_b = carrier_service.register_carrier(
        db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, actor_user_id=None,
        specification_id=other_spec.id, code="ST-00001", issued_date=None,
    )
    assert carrier_a.code == carrier_b.code
    assert carrier_a.tenant_id != carrier_b.tenant_id


@pytest.mark.integration
def test_cross_tenant_carrier_lookup_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register(db_session, tenant, farm, user)
    other_tenant = tenant_service.create_tenant(db_session, code="other-carrier-lookup", name="Other")
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, code="other-farm-2", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    with pytest.raises(CarrierNotFoundError):
        carrier_service.get_carrier(
            db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, carrier_id=carrier.id
        )


@pytest.mark.integration
def test_inactive_farm_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    farm.status = "inactive"
    db_session.flush()
    with pytest.raises(FarmNotFoundError):
        _register(db_session, tenant, farm, user)


@pytest.mark.integration
def test_required_active_membership_for_carrier_routes(client, db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="no-mem-carrier-tenant", name="No Membership")
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="farm-1", name="Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    from app.services import user_service

    user = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="no-mem-carrier", email="nmc@example.com", display_name="NM"
    )
    response = client.get(
        f"/farms/{farm.id}/carriers",
        headers={"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)},
    )
    # AUTH-001D: valid dev identity, no active membership -- a tenant-access
    # failure, 403 (previously 401; aligned with the real bearer path).
    assert response.status_code == 403


@pytest.mark.integration
def test_retired_carrier_without_retired_date_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier_type = db_session.execute(
        select(CarrierType).where(CarrierType.code == "seed_tray")
    ).scalar_one()
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO carriers (id, tenant_id, farm_id, carrier_type_id, code, status) "
                    "VALUES (:id, :tenant_id, :farm_id, :type_id, 'BAD', 'retired')"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id, "type_id": carrier_type.id},
            )


@pytest.mark.integration
def test_direct_sql_deletion_of_carrier_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register(db_session, tenant, farm, user)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM carriers WHERE id = :id"), {"id": carrier.id})
