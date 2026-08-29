"""PILOT-SETUP-001B2: `POST /platform/tenants`, `GET /platform/tenants`,
`GET /platform/tenants/{tenant_id}` HTTP-level behavioral coverage. Uses
real bearer-token authentication throughout (`tests._oidc_test_support`) --
deliberately never sends `X-Dev-Tenant-Id`/`X-CMP-Tenant-Id`/
`X-Dev-User-Id` at all, which is itself part of the proof that no tenant
selector is required for any of these routes.

Rows these tests create are committed for real by `onboard_tenant`'s own
dedicated connection (see `tests/_platform_tenant_scenario.py`) -- every
test cleans up what it created."""

import uuid

import pytest

from app.services import membership_service, platform_admin_service, tenant_service, user_service
from tests._oidc_test_support import TEST_ISSUER, bearer_headers, configured_oidc, unique_subject  # noqa: F401
from tests._platform_tenant_scenario import cleanup_onboarded_tenant


def _make_platform_admin(db_session):
    subject = unique_subject()
    user = user_service.create_user(
        db_session, oidc_issuer=TEST_ISSUER, oidc_subject=subject, email=f"{subject}@example.com",
        display_name="Platform Admin",
    )
    platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)
    return user, subject


def _onboarding_payload(**overrides) -> dict:
    unique = uuid.uuid4().hex[:10]
    payload = {
        "tenant": {"code": f"http-onb-{unique}", "name": "HTTP Onboarding Tenant"},
        "initial_admin": {
            "oidc_issuer": "https://issuer.example",
            "oidc_subject": f"http-admin-{unique}",
            "email": f"{unique}@example.com",
            "display_name": "HTTP Onboarding Admin",
        },
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def _cleanup_registry(test_engine):
    created: list[tuple] = []
    yield created
    for tenant_id, user_id in created:
        cleanup_onboarded_tenant(test_engine, tenant_id, user_id)


# --- 10. Platform Admin POST succeeds ---------------------------------------


@pytest.mark.integration
def test_platform_admin_can_create_tenant(client, db_session, configured_oidc, _cleanup_registry) -> None:
    _admin, subject = _make_platform_admin(db_session)
    payload = _onboarding_payload()

    resp = client.post("/platform/tenants", headers=bearer_headers(subject=subject), json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    _cleanup_registry.append((uuid.UUID(body["tenant"]["id"]), uuid.UUID(body["admin_user"]["id"])))

    assert body["tenant"]["code"] == payload["tenant"]["code"]
    assert body["admin_user"]["oidc_subject"] == payload["initial_admin"]["oidc_subject"]
    assert body["admin_user_created"] is True
    assert body["membership"]["role_code"] == "tenant_admin"
    assert body["membership"]["status"] == "active"


# --- 11. Platform Admin GET list succeeds -----------------------------------


@pytest.mark.integration
def test_platform_admin_can_list_tenants(client, db_session, configured_oidc, _cleanup_registry) -> None:
    _admin, subject = _make_platform_admin(db_session)
    payload = _onboarding_payload()
    create_resp = client.post("/platform/tenants", headers=bearer_headers(subject=subject), json=payload)
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    _cleanup_registry.append((uuid.UUID(created["tenant"]["id"]), uuid.UUID(created["admin_user"]["id"])))

    resp = client.get("/platform/tenants", headers=bearer_headers(subject=subject))
    assert resp.status_code == 200, resp.text
    codes = [t["code"] for t in resp.json()]
    assert payload["tenant"]["code"] in codes


# --- 12. Platform Admin GET detail succeeds ---------------------------------


@pytest.mark.integration
def test_platform_admin_can_get_tenant_detail(client, db_session, configured_oidc, _cleanup_registry) -> None:
    _admin, subject = _make_platform_admin(db_session)
    payload = _onboarding_payload()
    create_resp = client.post("/platform/tenants", headers=bearer_headers(subject=subject), json=payload)
    created = create_resp.json()
    tenant_id = created["tenant"]["id"]
    _cleanup_registry.append((uuid.UUID(tenant_id), uuid.UUID(created["admin_user"]["id"])))

    resp = client.get(f"/platform/tenants/{tenant_id}", headers=bearer_headers(subject=subject))
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == payload["tenant"]["code"]


# --- 13. ordinary User -> 403 ------------------------------------------------


@pytest.mark.integration
def test_ordinary_authenticated_user_gets_403(client, db_session, configured_oidc) -> None:
    subject = unique_subject()
    user_service.create_user(
        db_session, oidc_issuer=TEST_ISSUER, oidc_subject=subject, email="ordinary@example.com",
        display_name="Ordinary User",
    )

    resp = client.get("/platform/tenants", headers=bearer_headers(subject=subject))
    assert resp.status_code == 403

    resp = client.post("/platform/tenants", headers=bearer_headers(subject=subject), json=_onboarding_payload())
    assert resp.status_code == 403


# --- 14. tenant_admin-only -> 403 -------------------------------------------


@pytest.mark.integration
def test_tenant_admin_only_user_gets_403(client, db_session, configured_oidc) -> None:
    subject = unique_subject()
    user = user_service.create_user(
        db_session, oidc_issuer=TEST_ISSUER, oidc_subject=subject, email="tenantadmin@example.com",
        display_name="Tenant Admin Only",
    )
    tenant = tenant_service.create_tenant(db_session, code=f"ta-only-{subject[:8]}", name="Tenant Admin Only Co")
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None,
    )

    resp = client.get("/platform/tenants", headers=bearer_headers(subject=subject))
    assert resp.status_code == 403

    resp = client.post("/platform/tenants", headers=bearer_headers(subject=subject), json=_onboarding_payload())
    assert resp.status_code == 403


# --- 15. revoked Platform Admin -> 403 --------------------------------------


@pytest.mark.integration
def test_revoked_platform_admin_gets_403(client, db_session, configured_oidc) -> None:
    admin, subject = _make_platform_admin(db_session)
    platform_admin_service.revoke_platform_admin(db_session, user_id=admin.id, revoked_by_user_id=None)

    resp = client.get("/platform/tenants", headers=bearer_headers(subject=subject))
    assert resp.status_code == 403


# --- 16. no tenant header required ------------------------------------------


@pytest.mark.integration
def test_no_tenant_header_of_any_kind_is_sent_or_required(
    client, db_session, configured_oidc, _cleanup_registry
) -> None:
    """Every request in this file already omits X-CMP-Tenant-Id/
    X-Dev-Tenant-Id/X-Dev-User-Id entirely and still succeeds for a Platform
    Admin -- this test asserts that fact explicitly for the create route,
    the one most likely to accidentally grow a tenant-context dependency."""
    _admin, subject = _make_platform_admin(db_session)
    headers = bearer_headers(subject=subject)
    assert "X-CMP-Tenant-Id" not in headers
    assert "X-Dev-Tenant-Id" not in headers

    resp = client.post("/platform/tenants", headers=headers, json=_onboarding_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    _cleanup_registry.append((uuid.UUID(body["tenant"]["id"]), uuid.UUID(body["admin_user"]["id"])))


# --- 17. duplicate Tenant -> 409 --------------------------------------------


@pytest.mark.integration
def test_duplicate_tenant_code_returns_409(client, db_session, configured_oidc, _cleanup_registry) -> None:
    _admin, subject = _make_platform_admin(db_session)
    payload = _onboarding_payload()
    first = client.post("/platform/tenants", headers=bearer_headers(subject=subject), json=payload)
    assert first.status_code == 201, first.text
    created = first.json()
    _cleanup_registry.append((uuid.UUID(created["tenant"]["id"]), uuid.UUID(created["admin_user"]["id"])))

    retry_payload = _onboarding_payload(tenant={"code": payload["tenant"]["code"], "name": "Different Name"})
    second = client.post("/platform/tenants", headers=bearer_headers(subject=subject), json=retry_payload)
    assert second.status_code == 409, second.text


# --- 18. unknown Tenant detail -> 404 ---------------------------------------


@pytest.mark.integration
def test_unknown_tenant_detail_returns_404(client, db_session, configured_oidc) -> None:
    _admin, subject = _make_platform_admin(db_session)
    resp = client.get(f"/platform/tenants/{uuid.uuid4()}", headers=bearer_headers(subject=subject))
    assert resp.status_code == 404


# --- 19. response contains no credentials/secrets ---------------------------


@pytest.mark.integration
def test_onboarding_response_contains_no_credentials_or_secrets(
    client, db_session, configured_oidc, _cleanup_registry
) -> None:
    _admin, subject = _make_platform_admin(db_session)
    resp = client.post(
        "/platform/tenants", headers=bearer_headers(subject=subject), json=_onboarding_payload()
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    _cleanup_registry.append((uuid.UUID(body["tenant"]["id"]), uuid.UUID(body["admin_user"]["id"])))

    flat = str(body).lower()
    for forbidden in ("password", "token", "secret", "credential"):
        assert forbidden not in flat


# --- PLATFORM ADMIN != TENANT ADMIN: caller receives no implicit membership -


@pytest.mark.integration
def test_platform_admin_caller_receives_no_membership_only_initial_admin_does(
    client, db_session, configured_oidc, _cleanup_registry
) -> None:
    admin, subject = _make_platform_admin(db_session)
    resp = client.post(
        "/platform/tenants", headers=bearer_headers(subject=subject), json=_onboarding_payload()
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    tenant_id = uuid.UUID(body["tenant"]["id"])
    admin_user_id = uuid.UUID(body["admin_user"]["id"])
    _cleanup_registry.append((tenant_id, admin_user_id))

    # The calling Platform Admin gets no Membership anywhere -- not on the
    # new tenant, not anywhere else (they had none before this call either).
    assert membership_service.get_active_membership(db_session, tenant_id=tenant_id, user_id=admin.id) is None
    # Only the requested initial_admin identity does.
    assert (
        membership_service.get_active_membership(db_session, tenant_id=tenant_id, user_id=admin_user_id)
        is not None
    )
