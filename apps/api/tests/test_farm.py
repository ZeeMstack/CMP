import uuid

import pytest

from app.services import farm_service, tenant_service, user_service
from app.services.errors import DuplicateFarmCodeError, FarmNotFoundError


@pytest.mark.integration
def test_create_farm(db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="t-farm-1", name="T1")
    farm = farm_service.create_farm(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=None,
        code="pb-01",
        name="Farm PB-01",
        country_code="AE",
        city_region="Dubai",
        timezone="Asia/Dubai",
    )
    assert farm.id is not None
    assert farm.tenant_id == tenant.id
    assert farm.status == "active"


@pytest.mark.integration
def test_farm_code_unique_case_insensitively_within_tenant(db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="t-farm-2", name="T2")
    farm_service.create_farm(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=None,
        code="pb-01",
        name="Farm PB-01",
        country_code="AE",
        city_region=None,
        timezone="Asia/Dubai",
    )
    with pytest.raises(DuplicateFarmCodeError):
        farm_service.create_farm(
            db_session,
            tenant_id=tenant.id,
            actor_user_id=None,
            code="PB-01",
            name="Duplicate",
            country_code="AE",
            city_region=None,
            timezone="Asia/Dubai",
        )


@pytest.mark.integration
def test_same_farm_code_allowed_in_different_tenants(db_session) -> None:
    tenant_a = tenant_service.create_tenant(db_session, code="t-farm-3a", name="T3A")
    tenant_b = tenant_service.create_tenant(db_session, code="t-farm-3b", name="T3B")

    farm_a = farm_service.create_farm(
        db_session,
        tenant_id=tenant_a.id,
        actor_user_id=None,
        code="pb-01",
        name="Farm A",
        country_code="AE",
        city_region=None,
        timezone="Asia/Dubai",
    )
    farm_b = farm_service.create_farm(
        db_session,
        tenant_id=tenant_b.id,
        actor_user_id=None,
        code="pb-01",
        name="Farm B",
        country_code="AE",
        city_region=None,
        timezone="Asia/Dubai",
    )
    assert farm_a.code == farm_b.code
    assert farm_a.tenant_id != farm_b.tenant_id


@pytest.mark.integration
def test_cross_tenant_farm_lookup_rejected_at_service_layer(db_session) -> None:
    tenant_a = tenant_service.create_tenant(db_session, code="t-farm-4a", name="T4A")
    tenant_b = tenant_service.create_tenant(db_session, code="t-farm-4b", name="T4B")
    farm = farm_service.create_farm(
        db_session,
        tenant_id=tenant_a.id,
        actor_user_id=None,
        code="pb-01",
        name="Farm A",
        country_code="AE",
        city_region=None,
        timezone="Asia/Dubai",
    )
    with pytest.raises(FarmNotFoundError):
        farm_service.get_farm(db_session, tenant_id=tenant_b.id, farm_id=farm.id)


@pytest.mark.integration
def test_farm_endpoints_require_tenant_context(client) -> None:
    # No bearer token, no dev headers, no X-CMP-Tenant-Id at all -- a
    # deliberate 401 ("Authentication required"), not a generic validation
    # error: require_tenant_context's headers are optional with real
    # internal resolution logic, unlike the old defaultless dev-only
    # dependency this route used to depend on.
    response = client.get("/farms")
    assert response.status_code == 401


@pytest.mark.integration
def test_farm_access_rejected_without_active_membership(client, db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="t-farm-9", name="T9")
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject="no-membership",
        email="nm@example.com",
        display_name="No Membership",
    )
    response = client.get(
        "/farms", headers={"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_create_farm_via_api_with_active_context(client, active_context) -> None:
    tenant, _user, headers = active_context
    response = client.post(
        "/farms",
        headers=headers,
        json={"code": "pb-02", "name": "Farm PB-02", "country_code": "ae", "timezone": "Asia/Dubai"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == str(tenant.id)
    assert body["country_code"] == "AE"


@pytest.mark.integration
def test_cross_tenant_farm_lookup_returns_404_via_api(client, db_session, active_context) -> None:
    tenant_a = tenant_service.create_tenant(db_session, code="t-farm-5a", name="T5A")
    farm = farm_service.create_farm(
        db_session,
        tenant_id=tenant_a.id,
        actor_user_id=None,
        code="pb-01",
        name="Farm A",
        country_code="AE",
        city_region=None,
        timezone="Asia/Dubai",
    )
    _tenant_b, _user_b, headers_b = active_context

    response = client.get(f"/farms/{farm.id}", headers=headers_b)
    assert response.status_code == 404


@pytest.mark.integration
def test_farm_creation_rejects_invalid_country_code(client, active_context) -> None:
    _tenant, _user, headers = active_context
    response = client.post(
        "/farms",
        headers=headers,
        json={"code": "pb-01", "name": "Farm", "country_code": "USA", "timezone": "Asia/Dubai"},
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_farm_creation_rejects_invalid_timezone(client, active_context) -> None:
    _tenant, _user, headers = active_context
    response = client.post(
        "/farms",
        headers=headers,
        json={"code": "pb-01", "name": "Farm", "country_code": "AE", "timezone": "Not/A_Timezone"},
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_unknown_farm_id_returns_404(client, active_context) -> None:
    _tenant, _user, headers = active_context
    response = client.get(f"/farms/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 404
