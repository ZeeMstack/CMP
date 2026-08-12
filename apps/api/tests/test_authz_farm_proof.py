"""AUTHZ-001A technical proof (section 7 of the ticket): the new
`require_permission` dependency wired into a small, representative slice
-- `GET /farms/{farm_id}` (Permission.FARM_READ) and `POST /farms`
(Permission.FARM_MANAGE) -- proving the architecture end-to-end without
retrofitting the rest of the API.

Every test here goes through the real HTTP layer (the `client` fixture),
the real `require_tenant_context`/`require_permission` dependency chain,
and a real `cmp_test` database -- except the one test that deliberately
overrides `require_tenant_context` to inject a role_code the database
itself would reject (a genuinely *unknown* role can never be persisted,
since `ck_tenant_memberships_role_code_allowed` constrains role_code to
`APPROVED_ROLE_CODES`); that override targets the exact same production
dependency `app.core.db.get_db`/`get_engine` are already overridden
through in `conftest.py`'s `client` fixture, so it does not weaken
coverage of `require_permission` itself.
"""

import uuid

import pytest

from app.core.auth import TenantContext, require_tenant_context
from app.main import app
from app.services import farm_service, membership_service, tenant_service, user_service
from tests._oidc_test_support import TEST_ISSUER, configured_oidc, mint_token, unique_subject  # noqa: F401


def _membership_headers(db_session, *, role_code: str) -> tuple[uuid.UUID, dict[str, str]]:
    """Creates a fresh tenant + user + active membership with the given
    role_code and returns (tenant_id, dev headers). role_code must be one
    of APPROVED_ROLE_CODES (the DB enforces this)."""
    tenant = tenant_service.create_tenant(db_session, code=f"t-authz-{uuid.uuid4().hex[:8]}", name="Authz Tenant")
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"authz-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Authz User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    return tenant.id, headers


# --- tenant_admin: allowed ---------------------------------------------------


@pytest.mark.integration
def test_tenant_admin_can_create_and_read_a_farm(client, active_context) -> None:
    tenant, _user, headers = active_context

    create_response = client.post(
        "/farms",
        headers=headers,
        json={"code": "authz-01", "name": "Authz Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    )
    assert create_response.status_code == 201
    farm_id = create_response.json()["id"]

    read_response = client.get(f"/farms/{farm_id}", headers=headers)
    assert read_response.status_code == 200
    assert read_response.json()["tenant_id"] == str(tenant.id)


# --- known role, zero permissions: 403 --------------------------------------


@pytest.mark.integration
def test_known_role_with_no_granted_permissions_is_forbidden_from_reading_and_managing(client, db_session) -> None:
    """`operator` is a real, DB-approved role (APPROVED_ROLE_CODES) with
    real precedent elsewhere in this test suite -- not a malformed or
    unrecognized value -- but AUTHZ-001A deliberately grants it zero
    permissions (see docs/AUTHORIZATION_MODEL.md). This proves
    `require_permission` denies a legitimately-authenticated, legitimately
    tenant-scoped caller whose role simply isn't authorized for this
    action -- distinct from any authentication failure."""
    _tenant_id, headers = _membership_headers(db_session, role_code="operator")

    read_response = client.get(f"/farms/{uuid.uuid4()}", headers=headers)
    assert read_response.status_code == 403
    assert "role" not in read_response.json()["detail"].lower()
    assert "permission" in read_response.json()["detail"].lower() or "action" in read_response.json()["detail"].lower()

    create_response = client.post(
        "/farms",
        headers=headers,
        json={"code": "authz-02", "name": "Authz Farm 2", "country_code": "AE", "timezone": "Asia/Dubai"},
    )
    assert create_response.status_code == 403


# --- unknown role: 403 -------------------------------------------------------


@pytest.mark.integration
def test_unknown_role_code_is_forbidden(client) -> None:
    """A role_code that isn't even in APPROVED_ROLE_CODES can never be
    persisted (the DB CHECK constraint would reject it) -- exercised here
    by overriding require_tenant_context directly, the same dependency-
    override mechanism conftest.py's own `client` fixture already uses for
    get_db/get_engine, so this still proves require_permission's real
    wiring on the real /farms route."""
    bogus_ctx = TenantContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), role_code="not_a_real_role_at_all")
    app.dependency_overrides[require_tenant_context] = lambda: bogus_ctx
    try:
        response = client.get(f"/farms/{uuid.uuid4()}")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(require_tenant_context, None)


# --- same user, different role per tenant: no role bleed between tenants ----


@pytest.mark.integration
def test_same_user_different_role_per_tenant_is_authorized_independently(client, db_session) -> None:
    """AUTHZ-001A.1 section 3: one CMP user holds `tenant_admin` in Tenant A
    and `read_only` in Tenant B. Selecting Tenant A must grant FARM_MANAGE;
    selecting Tenant B (same user, same bearer/dev identity, only the
    selected tenant differs) must deny it. The role used for the
    permission check is the ACTIVE membership's role_code for the
    SELECTED tenant specifically -- never a role held in a different
    tenant, and never the 'most permissive role this user holds
    anywhere'."""
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"authz-multitenant-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Multi Tenant User",
    )
    tenant_a = tenant_service.create_tenant(db_session, code="t-authz-multi-a", name="Tenant A")
    tenant_b = tenant_service.create_tenant(db_session, code="t-authz-multi-b", name="Tenant B")
    membership_service.add_membership(
        db_session, tenant_id=tenant_a.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user.id, role_code="read_only", actor_user_id=None
    )

    headers_a = {"X-Dev-Tenant-Id": str(tenant_a.id), "X-Dev-User-Id": str(user.id)}
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user.id)}

    response_a = client.post(
        "/farms",
        headers=headers_a,
        json={"code": "authz-multi-a", "name": "Farm A", "country_code": "AE", "timezone": "Asia/Dubai"},
    )
    assert response_a.status_code == 201
    assert response_a.json()["tenant_id"] == str(tenant_a.id)

    response_b = client.post(
        "/farms",
        headers=headers_b,
        json={"code": "authz-multi-b", "name": "Farm B", "country_code": "AE", "timezone": "Asia/Dubai"},
    )
    assert response_b.status_code == 403


# --- cross-tenant resource: still 404 even with the required permission -----


@pytest.mark.integration
def test_cross_tenant_farm_is_404_not_403_even_for_a_fully_permitted_caller(client, db_session, active_context) -> None:
    other_tenant = tenant_service.create_tenant(db_session, code="t-authz-foreign", name="Foreign Tenant")
    foreign_farm = farm_service.create_farm(
        db_session,
        tenant_id=other_tenant.id,
        actor_user_id=None,
        code="foreign-01",
        name="Foreign Farm",
        country_code="AE",
        city_region=None,
        timezone="Asia/Dubai",
    )
    _tenant, _user, headers = active_context  # tenant_admin -- has FARM_READ

    response = client.get(f"/farms/{foreign_farm.id}", headers=headers)
    assert response.status_code == 404


# --- unauthenticated: existing 401 preserved ---------------------------------


@pytest.mark.integration
def test_unauthenticated_request_is_401_not_403(client) -> None:
    response = client.get(f"/farms/{uuid.uuid4()}")
    assert response.status_code == 401

    response = client.post(
        "/farms", json={"code": "x", "name": "x", "country_code": "AE", "timezone": "Asia/Dubai"}
    )
    assert response.status_code == 401


# --- dev-auth still flows through CMP membership + permission authorization -


@pytest.mark.integration
def test_dev_auth_identity_is_still_subject_to_permission_checks(client, db_session) -> None:
    """Dev-auth bypasses Auth0/OIDC, never CMP's own authorization -- a
    dev-mode caller with a real active membership but no granted
    permissions must be denied exactly like a real bearer-authenticated
    caller would be."""
    _tenant_id, headers = _membership_headers(db_session, role_code="read_only")
    response = client.get(f"/farms/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 403


@pytest.mark.integration
def test_real_bearer_inactive_membership_is_403_not_401(client, db_session, configured_oidc) -> None:
    """AUTHZ-001A.2: the established contract is 401 only for invalid/
    unusable identity credentials; 403 once identity is valid but the
    caller has no *active* accessible membership for the selected tenant
    (permission evaluation never even begins -- `require_permission`'s
    own check cannot run until `require_tenant_context` has already
    returned a `TenantContext`, which it never does here). The real
    bearer path (`app.core.auth.require_tenant_context`'s own inline
    membership check, not dev_auth.py) already implements this correctly
    and is unaffected by AUTHZ-001A/A.1/A.2 -- this HTTP-level test closes
    a gap in this ticket's own proof-slice suite (previously only the
    dev-auth variant below was covered here); the equivalent dependency-
    level proof has existed since AUTH-001A as
    tests/test_auth_context.py::test_removed_membership_is_403."""
    subject = unique_subject()
    user = user_service.create_user(
        db_session,
        oidc_issuer=TEST_ISSUER,
        oidc_subject=subject,
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Inactive Membership Bearer User",
    )
    tenant = tenant_service.create_tenant(db_session, code="t-authz-inactive-bearer", name="Inactive Membership Tenant")
    membership = membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    membership.status = "removed"
    db_session.commit()

    headers = {"Authorization": f"Bearer {mint_token(subject=subject)}", "X-CMP-Tenant-Id": str(tenant.id)}
    response = client.get(f"/farms/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 403


@pytest.mark.integration
def test_dev_auth_inactive_membership_is_403_matching_real_bearer_contract(client, db_session) -> None:
    """AUTH-001D: fixes the AUTHZ-001A.2 finding. `app.core.dev_auth.
    resolve_dev_tenant_context` now raises 403 ("No active membership for
    this tenant") for this exact condition, matching
    `app.core.auth.require_tenant_context`'s own inline real-bearer check
    (see `test_real_bearer_inactive_membership_is_403_not_401` above) --
    the two identity paths no longer disagree on this status code."""
    tenant = tenant_service.create_tenant(db_session, code="t-authz-inactive-dev", name="Inactive Membership Tenant")
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"authz-inactive-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Inactive Membership Dev User",
    )
    membership = membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    membership.status = "removed"
    db_session.commit()

    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    response = client.get(f"/farms/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 403


@pytest.mark.integration
def test_dev_auth_missing_membership_entirely_is_403(client, db_session) -> None:
    """Same contract, no membership row at all (as opposed to a removed
    one) -- a valid dev identity, a valid active tenant, but the user has
    never been a member of it."""
    tenant = tenant_service.create_tenant(db_session, code="t-authz-no-membership-dev", name="No Membership Tenant")
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"authz-no-membership-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="No Membership Dev User",
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    response = client.get(f"/farms/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 403


@pytest.mark.integration
def test_dev_auth_inactive_tenant_is_403(client, db_session) -> None:
    """A valid dev identity with an otherwise-valid membership, but the
    tenant itself is inactive -- matches the real bearer path's
    equivalent (`tests/test_auth_context.py::test_inactive_tenant_is_403`)."""
    tenant = tenant_service.create_tenant(db_session, code="t-authz-inactive-tenant-dev", name="Inactive Tenant")
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"authz-inactive-tenant-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Inactive Tenant Dev User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    tenant.status = "inactive"
    db_session.commit()

    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    response = client.get(f"/farms/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 403


@pytest.mark.integration
def test_dev_auth_unknown_user_id_remains_401_unaffected_by_auth_001d(client, db_session) -> None:
    """AUTH-001D deliberately does not touch dev user lookup semantics --
    a dev identity that doesn't resolve to any real CMP user at all is an
    authentication failure (is this a usable identity?), not a
    tenant-access failure (does this identity have access to this
    tenant?), and must remain 401. Uses an otherwise-valid, active tenant
    so the only failing condition is the unknown user id."""
    tenant = tenant_service.create_tenant(db_session, code="t-authz-unknown-user-dev", name="Unknown User Tenant")
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(uuid.uuid4())}
    response = client.get(f"/farms/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 401


@pytest.mark.integration
def test_dev_auth_tenant_admin_is_still_granted_access(client, db_session) -> None:
    tenant_id, headers = _membership_headers(db_session, role_code="tenant_admin")
    response = client.get("/farms", headers=headers)  # unaffected list endpoint, still require_tenant_context
    assert response.status_code == 200

    create_response = client.post(
        "/farms",
        headers=headers,
        json={"code": "authz-03", "name": "Authz Farm 3", "country_code": "AE", "timezone": "Asia/Dubai"},
    )
    assert create_response.status_code == 201
    assert create_response.json()["tenant_id"] == str(tenant_id)
