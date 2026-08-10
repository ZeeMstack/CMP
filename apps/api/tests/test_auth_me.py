"""AUTH-001A GET /auth/me matrix -- membership discovery. HTTP-level via
the real route, since the response *body* (not just the status code) is
the contract under test."""

import uuid

import pytest

from app.services import membership_service, tenant_service, user_service
from tests._oidc_test_support import TEST_ISSUER, configured_oidc, mint_token, unique_subject  # noqa: F401


def _make_user(db_session, *, status="active"):
    subject = unique_subject()
    user = user_service.create_user(
        db_session, oidc_issuer=TEST_ISSUER, oidc_subject=subject, email="me@example.com", display_name="Me"
    )
    if status != "active":
        user.status = status
        db_session.flush()
    return user, subject


def _make_tenant(db_session, *, name, code=None, status="active"):
    code = code or f"auth-me-{uuid.uuid4().hex[:8]}"
    tenant = tenant_service.create_tenant(db_session, code=code, name=name)
    if status != "active":
        tenant.status = status
        db_session.flush()
    return tenant


def _add_membership(db_session, *, tenant, user, role_code="tenant_admin", status="active"):
    membership = membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    if status != "active":
        membership.status = status
        db_session.flush()
    return membership


def _bearer(subject: str) -> dict:
    return {"Authorization": f"Bearer {mint_token(subject=subject)}"}


@pytest.mark.integration
def test_zero_memberships_returns_200_with_empty_list(client, configured_oidc, db_session) -> None:
    user, subject = _make_user(db_session)
    db_session.commit()
    response = client.get("/auth/me", headers=_bearer(subject))
    assert response.status_code == 200
    body = response.json()
    assert body["memberships"] == []
    assert body["user"]["id"] == str(user.id)


@pytest.mark.integration
def test_one_active_tenant(client, configured_oidc, db_session) -> None:
    user, subject = _make_user(db_session)
    tenant = _make_tenant(db_session, name="Solo Tenant")
    _add_membership(db_session, tenant=tenant, user=user, role_code="farm_manager")
    db_session.commit()

    response = client.get("/auth/me", headers=_bearer(subject))
    assert response.status_code == 200
    body = response.json()
    assert len(body["memberships"]) == 1
    assert body["memberships"][0]["tenant_id"] == str(tenant.id)
    assert body["memberships"][0]["role_code"] == "farm_manager"
    assert body["memberships"][0]["tenant_name"] == "Solo Tenant"


@pytest.mark.integration
def test_multiple_active_tenants(client, configured_oidc, db_session) -> None:
    user, subject = _make_user(db_session)
    tenant_b = _make_tenant(db_session, name="Bravo Tenant")
    tenant_a = _make_tenant(db_session, name="Alpha Tenant")
    _add_membership(db_session, tenant=tenant_b, user=user, role_code="operator")
    _add_membership(db_session, tenant=tenant_a, user=user, role_code="read_only")
    db_session.commit()

    response = client.get("/auth/me", headers=_bearer(subject))
    assert response.status_code == 200
    tenant_ids = {m["tenant_id"] for m in response.json()["memberships"]}
    assert tenant_ids == {str(tenant_a.id), str(tenant_b.id)}


@pytest.mark.integration
def test_deterministic_ordering_by_tenant_name(client, configured_oidc, db_session) -> None:
    user, subject = _make_user(db_session)
    tenant_z = _make_tenant(db_session, name="Zulu Tenant")
    tenant_a = _make_tenant(db_session, name="Alpha Tenant")
    tenant_m = _make_tenant(db_session, name="Mike Tenant")
    for t in (tenant_z, tenant_a, tenant_m):
        _add_membership(db_session, tenant=t, user=user)
    db_session.commit()

    response = client.get("/auth/me", headers=_bearer(subject))
    names = [m["tenant_name"] for m in response.json()["memberships"]]
    assert names == ["Alpha Tenant", "Mike Tenant", "Zulu Tenant"]


@pytest.mark.integration
def test_removed_membership_excluded(client, configured_oidc, db_session) -> None:
    user, subject = _make_user(db_session)
    active_tenant = _make_tenant(db_session, name="Active One")
    removed_tenant = _make_tenant(db_session, name="Removed One")
    _add_membership(db_session, tenant=active_tenant, user=user)
    _add_membership(db_session, tenant=removed_tenant, user=user, status="removed")
    db_session.commit()

    response = client.get("/auth/me", headers=_bearer(subject))
    tenant_names = {m["tenant_name"] for m in response.json()["memberships"]}
    assert tenant_names == {"Active One"}


@pytest.mark.integration
def test_inactive_tenant_excluded(client, configured_oidc, db_session) -> None:
    user, subject = _make_user(db_session)
    active_tenant = _make_tenant(db_session, name="Active Tenant")
    inactive_tenant = _make_tenant(db_session, name="Inactive Tenant", status="inactive")
    _add_membership(db_session, tenant=active_tenant, user=user)
    _add_membership(db_session, tenant=inactive_tenant, user=user)
    db_session.commit()

    response = client.get("/auth/me", headers=_bearer(subject))
    tenant_names = {m["tenant_name"] for m in response.json()["memberships"]}
    assert tenant_names == {"Active Tenant"}


@pytest.mark.integration
def test_unknown_identity_is_403(client, configured_oidc) -> None:
    response = client.get("/auth/me", headers=_bearer(unique_subject()))
    assert response.status_code == 403


@pytest.mark.integration
def test_inactive_user_is_403(client, configured_oidc, db_session) -> None:
    user, subject = _make_user(db_session, status="inactive")
    db_session.commit()
    response = client.get("/auth/me", headers=_bearer(subject))
    assert response.status_code == 403


@pytest.mark.integration
def test_no_tenant_header_required(client, configured_oidc, db_session) -> None:
    user, subject = _make_user(db_session)
    db_session.commit()
    # Deliberately no X-CMP-Tenant-Id anywhere in this request.
    response = client.get("/auth/me", headers=_bearer(subject))
    assert response.status_code == 200


@pytest.mark.integration
def test_response_never_exposes_oidc_subject_or_token(client, configured_oidc, db_session) -> None:
    user, subject = _make_user(db_session)
    db_session.commit()
    response = client.get("/auth/me", headers=_bearer(subject))
    body_text = response.text
    assert subject not in body_text
    assert "oidc_subject" not in body_text
    assert "oidc_issuer" not in body_text


@pytest.mark.integration
def test_dev_identity_works_for_auth_me_without_tenant_header(client, active_context) -> None:
    tenant, user, dev_headers = active_context
    response = client.get("/auth/me", headers={"X-Dev-User-Id": dev_headers["X-Dev-User-Id"]})
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["id"] == str(user.id)
    assert len(body["memberships"]) == 1
    assert body["memberships"][0]["tenant_id"] == str(tenant.id)
