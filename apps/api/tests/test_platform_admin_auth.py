"""PILOT-SETUP-001B1: `require_platform_admin` dependency matrix. Mirrors
`test_auth_context.py`'s own convention of calling FastAPI dependencies
directly as plain functions (they are ordinary Python functions with
`Header`/`Depends` markers only as default values) -- no HTTP route uses
this dependency yet (deliberately out of scope for this ticket), so every
test here calls `require_platform_admin` directly with explicit arguments."""

import pytest
from fastapi import HTTPException

from app.core.platform_auth import require_platform_admin
from app.services import membership_service, platform_admin_service, tenant_service, user_service
from tests._oidc_test_support import configured_oidc, mint_token, unique_subject  # noqa: F401


def _bearer_authorization(subject: str) -> str:
    return f"Bearer {mint_token(subject=subject)}"


def _make_bearer_user(db_session, *, subject=None, status="active"):
    subject = subject or unique_subject()
    from tests._oidc_test_support import TEST_ISSUER

    user = user_service.create_user(
        db_session, oidc_issuer=TEST_ISSUER, oidc_subject=subject, email="person@example.com", display_name="Person"
    )
    if status != "active":
        user.status = status
        db_session.flush()
    return user, subject


# --- 1. active platform admin passes ----------------------------------------


@pytest.mark.integration
def test_active_platform_admin_is_accepted(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)

    principal = _resolve_principal(db_session, subject)
    result = require_platform_admin(principal=principal, db=db_session)
    assert result.user_id == user.id


def _resolve_principal(db_session, subject):
    from app.core.auth import require_authenticated_principal

    return require_authenticated_principal(
        authorization=_bearer_authorization(subject), x_dev_user_id=None, x_dev_tenant_id=None, db=db_session
    )


# --- 2. authenticated normal User (no platform admin row) gets 403 ---------


@pytest.mark.integration
def test_ordinary_authenticated_user_is_rejected(db_session, configured_oidc) -> None:
    _user, subject = _make_bearer_user(db_session)
    principal = _resolve_principal(db_session, subject)

    with pytest.raises(HTTPException) as exc_info:
        require_platform_admin(principal=principal, db=db_session)
    assert exc_info.value.status_code == 403


# --- 3. revoked platform admin gets 403 -------------------------------------


@pytest.mark.integration
def test_revoked_platform_admin_is_rejected(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)
    platform_admin_service.revoke_platform_admin(db_session, user_id=user.id, revoked_by_user_id=None)

    principal = _resolve_principal(db_session, subject)
    with pytest.raises(HTTPException) as exc_info:
        require_platform_admin(principal=principal, db=db_session)
    assert exc_info.value.status_code == 403


# --- 4. unknown/unprovisioned User retains existing authentication behavior -


@pytest.mark.integration
def test_unknown_identity_retains_existing_401_403_behavior(db_session, configured_oidc) -> None:
    """require_platform_admin never runs its own check for an identity that
    require_authenticated_principal itself already rejects -- the failure
    happens one layer down, unchanged (403 for an unknown issuer+subject,
    matching require_authenticated_principal's own documented contract)."""
    with pytest.raises(HTTPException) as exc_info:
        _resolve_principal(db_session, unique_subject())
    assert exc_info.value.status_code == 403


@pytest.mark.integration
def test_no_credentials_at_all_is_401(db_session) -> None:
    from app.core.auth import require_authenticated_principal

    with pytest.raises(HTTPException) as exc_info:
        require_authenticated_principal(authorization=None, x_dev_user_id=None, x_dev_tenant_id=None, db=db_session)
    assert exc_info.value.status_code == 401


# --- 5. dependency works WITHOUT X-Dev-Tenant-Id ----------------------------


@pytest.mark.integration
def test_dev_identity_works_without_any_tenant_header(db_session, active_context, monkeypatch) -> None:
    """active_context creates a tenant/user/membership, but this test
    deliberately only ever passes X-Dev-User-Id -- no X-Dev-Tenant-Id, no
    X-CMP-Tenant-Id -- proving require_platform_admin's own upstream
    dependency needs no tenant selector at all. Dev auth is explicitly
    enabled via monkeypatch (mirrors tests/test_dev_auth.py's own
    convention) rather than relying on ambient .env state."""
    from app.core import dev_auth as dev_auth_module
    from app.core.auth import require_authenticated_principal

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)

    _tenant, user, dev_headers = active_context
    platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)

    principal = require_authenticated_principal(
        authorization=None, x_dev_user_id=dev_headers["X-Dev-User-Id"], x_dev_tenant_id=None, db=db_session
    )
    result = require_platform_admin(principal=principal, db=db_session)
    assert result.user_id == user.id


# --- 6. dependency does not require TenantMembership ------------------------


@pytest.mark.integration
def test_platform_admin_without_any_tenant_membership_is_accepted(db_session, configured_oidc) -> None:
    """A user with an active platform-admin grant and ZERO tenant
    memberships anywhere still passes require_platform_admin -- proving the
    dependency never consults tenant_memberships at all."""
    user, subject = _make_bearer_user(db_session)
    platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)

    principal = _resolve_principal(db_session, subject)
    result = require_platform_admin(principal=principal, db=db_session)
    assert result.user_id == user.id


# --- 7. being tenant_admin alone does NOT satisfy platform-admin check -----


@pytest.mark.integration
def test_tenant_admin_role_alone_does_not_satisfy_platform_admin(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    tenant = tenant_service.create_tenant(db_session, code=f"pa-{unique_subject()[:8]}", name="Platform Auth Tenant")
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )

    principal = _resolve_principal(db_session, subject)
    with pytest.raises(HTTPException) as exc_info:
        require_platform_admin(principal=principal, db=db_session)
    assert exc_info.value.status_code == 403


# --- 8. platform admin gains NO automatic tenant permissions ---------------


@pytest.mark.integration
def test_platform_admin_grant_does_not_satisfy_tenant_permission_check(db_session, configured_oidc) -> None:
    """Holding platform-admin authority must never let a caller read/act on
    tenant-scoped data without its own, separate, active TenantMembership.
    require_tenant_context knows nothing about PlatformAdmin at all -- a
    platform admin with no membership for this tenant is rejected exactly
    like any other stranger."""
    from app.core.auth import require_tenant_context

    user, subject = _make_bearer_user(db_session)
    platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)
    tenant = tenant_service.create_tenant(db_session, code=f"pa2-{unique_subject()[:8]}", name="Platform Auth Tenant 2")
    # Deliberately no membership created for this tenant.

    with pytest.raises(HTTPException) as exc_info:
        require_tenant_context(
            authorization=_bearer_authorization(subject),
            x_cmp_tenant_id=str(tenant.id),
            x_dev_tenant_id=None,
            x_dev_user_id=None,
            db=db_session,
        )
    assert exc_info.value.status_code == 403
