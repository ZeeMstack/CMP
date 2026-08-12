"""AUTHZ-001B1 representative HTTP-level authorization tests (ticket
section 7). Deliberately NOT one test per newly-protected endpoint --
`test_authz_read_enforcement_architecture.py` already structurally proves
every tenant-scoped GET is wired to require_permission with a real
Permission, and the existing per-domain test files (test_location.py,
test_asset.py, test_crop_batch.py, etc.) already prove success/resource
behavior for a tenant_admin caller, unaffected by this ticket since
tenant_admin holds every permission. What's new and needs its own
end-to-end HTTP proof is the *authorization* behavior itself, exercised
across a representative cross-section of domains (location, asset,
crop_batch) rather than all ~20: a zero-permission role is denied, a
same-user-different-tenant-role caller is evaluated independently per
tenant, and cross-tenant concealment still wins over a granted
permission."""

import uuid

import pytest

from app.services import (
    farm_service,
    location_service,
    membership_service,
    tenant_service,
    user_service,
)


def _membership_headers(db_session, *, role_code: str) -> tuple[uuid.UUID, dict[str, str]]:
    tenant = tenant_service.create_tenant(db_session, code=f"t-rd-{uuid.uuid4().hex[:8]}", name="Read Enforcement Tenant")
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"rd-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Read Enforcement User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    return tenant.id, headers


# --- tenant_admin: allowed across a representative domain sample ------------


@pytest.mark.integration
def test_tenant_admin_can_read_across_representative_domains(client, active_context_with_farm) -> None:
    tenant, _user, headers, farm = active_context_with_farm

    assert client.get(f"/farms/{farm.id}/locations/tree", headers=headers).status_code == 200
    assert client.get(f"/farms/{farm.id}/crop-batches", headers=headers).status_code == 200
    assert client.get(f"/farms/{farm.id}/assets", headers=headers).status_code == 200
    assert client.get("/crops", headers=headers).status_code == 200


# --- zero-permission role: 403 on the same representative reads -------------


@pytest.mark.integration
def test_zero_permission_role_is_forbidden_across_representative_domains(client, db_session) -> None:
    """`operator` is a real, DB-approved role with zero granted
    permissions (see docs/domain/AUTHORIZATION_MODEL.md) -- proves the
    denial generalizes across domains, not just the AUTHZ-001A farm
    proof slice."""
    tenant_id, headers = _membership_headers(db_session, role_code="operator")
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant_id, actor_user_id=None, code="rd-farm", name="RD Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )

    assert client.get(f"/farms/{farm.id}/locations/tree", headers=headers).status_code == 403
    assert client.get(f"/farms/{farm.id}/crop-batches", headers=headers).status_code == 403
    assert client.get(f"/farms/{farm.id}/assets", headers=headers).status_code == 403
    assert client.get("/crops", headers=headers).status_code == 403


# --- same user, different role per tenant, for a READ permission ------------


@pytest.mark.integration
def test_same_user_different_role_per_tenant_for_a_read_permission(client, db_session) -> None:
    """Extends AUTHZ-001A.1's FARM_MANAGE proof to a read permission on a
    different domain (location.read): one user, tenant_admin in Tenant A
    (has LOCATION_READ), read_only in Tenant B (has none) -- selecting
    Tenant B must still deny, proving the role used is always the ACTIVE
    membership's role_code for the SELECTED tenant, never a role held
    elsewhere."""
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"rd-multitenant-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="RD Multi Tenant User",
    )
    tenant_a = tenant_service.create_tenant(db_session, code="t-rd-multi-a", name="RD Tenant A")
    tenant_b = tenant_service.create_tenant(db_session, code="t-rd-multi-b", name="RD Tenant B")
    membership_service.add_membership(
        db_session, tenant_id=tenant_a.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user.id, role_code="read_only", actor_user_id=None
    )
    farm_a = farm_service.create_farm(
        db_session, tenant_id=tenant_a.id, actor_user_id=None, code="rd-farm-a", name="RD Farm A",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    farm_b = farm_service.create_farm(
        db_session, tenant_id=tenant_b.id, actor_user_id=None, code="rd-farm-b", name="RD Farm B",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )

    headers_a = {"X-Dev-Tenant-Id": str(tenant_a.id), "X-Dev-User-Id": str(user.id)}
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user.id)}

    assert client.get(f"/farms/{farm_a.id}/locations/tree", headers=headers_a).status_code == 200
    assert client.get(f"/farms/{farm_b.id}/locations/tree", headers=headers_b).status_code == 403


# --- inactive/no membership: still fails before permission evaluation -------


@pytest.mark.integration
def test_no_membership_fails_before_reaching_a_non_farm_read_permission(client, db_session) -> None:
    """Structural guarantee, not domain-specific: require_permission
    always wraps require_tenant_context, so a caller with no active
    membership at all never reaches ANY permission check, regardless of
    which domain's read permission the route requires. Exercised here
    against location.read specifically (not the farm.read proof slice)
    to show it is not an accident of the farms router."""
    tenant = tenant_service.create_tenant(db_session, code="t-rd-no-mem", name="RD No Membership Tenant")
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"rd-no-mem-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="RD No Membership User",
    )
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="rd-farm-nomem", name="RD Farm No Mem",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}

    response = client.get(f"/farms/{farm.id}/locations/tree", headers=headers)
    assert response.status_code == 403  # AUTH-001D: no active membership -> 403, aligned across dev/bearer


# --- cross-tenant resource: still 404 after permission succeeds -------------


@pytest.mark.integration
def test_cross_tenant_resource_is_404_after_permission_succeeds_for_a_non_farm_domain(
    client, db_session, active_context_with_farm
) -> None:
    """A fully-permitted tenant_admin caller (has LOCATION_READ) must
    still get 404, not the location, for a resource that exists but
    belongs to a different tenant -- proves the permission layer and the
    tenant-scoped resource lookup are independent controls (AUTHZ-001A's
    own principle), for a domain beyond the farms proof slice."""
    other_tenant = tenant_service.create_tenant(db_session, code="t-rd-foreign", name="RD Foreign Tenant")
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, code="rd-foreign-farm", name="RD Foreign Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    foreign_location = location_service.create_location(
        db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, actor_user_id=None,
        location_type_code="greenhouse", code="rd-foreign-gh", name="RD Foreign Greenhouse",
        parent_location_id=None, greenhouse_classification="leafy_greens", occupiable=None,
    )

    _tenant, _user, headers, farm = active_context_with_farm  # tenant_admin -- has LOCATION_READ

    response = client.get(f"/farms/{farm.id}/locations/{foreign_location.id}", headers=headers)
    assert response.status_code == 404

    # Also verify the farm itself is 404 under the caller's own farm_id
    # combined with the foreign location id (the realistic attack shape --
    # a caller guessing/reusing a location id from another tenant).
    response = client.get(f"/farms/{other_farm.id}/locations/{foreign_location.id}", headers=headers)
    assert response.status_code == 404
