"""AUTH-001A CMP-user resolution, tenant-context resolution, and dev/bearer
coexistence matrix. Most cases call `require_tenant_context`/
`require_authenticated_principal` directly as plain functions (they are
ordinary Python functions with FastAPI `Header`/`Depends` markers only as
*default values* -- calling them directly with explicit arguments bypasses
FastAPI entirely and lets tests assert precisely on the returned
`TenantContext`, including `role_code`, which no business route's response
body exposes). A handful of HTTP-level tests separately prove the actual
route wiring end-to-end."""

import uuid

import pytest
from fastapi import HTTPException

from app.core.auth import TenantContext, require_authenticated_principal, require_tenant_context
from app.services import membership_service, tenant_service, user_service
from tests._oidc_test_support import TEST_AUDIENCE, TEST_ISSUER, configured_oidc, mint_token, unique_subject  # noqa: F401


def _make_bearer_user(db_session, *, subject=None, status="active"):
    subject = subject or unique_subject()
    user = user_service.create_user(
        db_session, oidc_issuer=TEST_ISSUER, oidc_subject=subject, email="person@example.com", display_name="Person"
    )
    if status != "active":
        user.status = status
        db_session.flush()
    return user, subject


def _make_tenant_with_membership(db_session, user, *, tenant_status="active", membership_status="active", role_code="tenant_admin"):
    suffix = uuid.uuid4().hex[:8]
    tenant = tenant_service.create_tenant(db_session, code=f"auth-{suffix}", name="Auth Test Tenant")
    if tenant_status != "active":
        tenant.status = tenant_status
        db_session.flush()
    membership = membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    if membership_status != "active":
        membership.status = membership_status
        db_session.flush()
    return tenant


def _bearer_authorization(subject: str) -> str:
    return f"Bearer {mint_token(subject=subject)}"


# --- CMP user resolution ------------------------------------------------


def test_known_active_issuer_subject_resolves(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    tenant = _make_tenant_with_membership(db_session, user)
    ctx = require_tenant_context(
        authorization=_bearer_authorization(subject),
        x_cmp_tenant_id=str(tenant.id),
        x_dev_tenant_id=None,
        x_dev_user_id=None,
        db=db_session,
    )
    assert ctx.user_id == user.id
    assert ctx.tenant_id == tenant.id


def test_unknown_identity_is_403(db_session, configured_oidc) -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_authenticated_principal(
            authorization=_bearer_authorization(unique_subject()),
            x_dev_user_id=None,
            x_dev_tenant_id=None,
            db=db_session,
        )
    assert exc_info.value.status_code == 403


def test_inactive_user_is_403(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session, status="inactive")
    with pytest.raises(HTTPException) as exc_info:
        require_authenticated_principal(
            authorization=_bearer_authorization(subject), x_dev_user_id=None, x_dev_tenant_id=None, db=db_session
        )
    assert exc_info.value.status_code == 403


def test_unknown_and_inactive_identity_share_the_same_error_detail(db_session, configured_oidc) -> None:
    inactive_user, inactive_subject = _make_bearer_user(db_session, status="inactive")
    try:
        require_authenticated_principal(
            authorization=_bearer_authorization(inactive_subject), x_dev_user_id=None, x_dev_tenant_id=None, db=db_session
        )
    except HTTPException as exc:
        inactive_detail = exc.detail

    try:
        require_authenticated_principal(
            authorization=_bearer_authorization(unique_subject()), x_dev_user_id=None, x_dev_tenant_id=None, db=db_session
        )
    except HTTPException as exc:
        unknown_detail = exc.detail

    assert inactive_detail == unknown_detail


def test_email_collision_has_no_effect_on_identity_resolution(db_session, configured_oidc) -> None:
    # Two different users sharing an email (allowed -- `users.email` has
    # no uniqueness constraint) must resolve independently by
    # (issuer, subject) only.
    user_a = user_service.create_user(
        db_session, oidc_issuer=TEST_ISSUER, oidc_subject=unique_subject(), email="shared@example.com", display_name="A"
    )
    user_b = user_service.create_user(
        db_session, oidc_issuer=TEST_ISSUER, oidc_subject=unique_subject(), email="shared@example.com", display_name="B"
    )
    tenant_a = _make_tenant_with_membership(db_session, user_a)
    tenant_b = _make_tenant_with_membership(db_session, user_b)

    ctx_a = require_tenant_context(
        authorization=f"Bearer {mint_token(subject=user_a.oidc_subject, email='shared@example.com')}",
        x_cmp_tenant_id=str(tenant_a.id), x_dev_tenant_id=None, x_dev_user_id=None, db=db_session,
    )
    ctx_b = require_tenant_context(
        authorization=f"Bearer {mint_token(subject=user_b.oidc_subject, email='shared@example.com')}",
        x_cmp_tenant_id=str(tenant_b.id), x_dev_tenant_id=None, x_dev_user_id=None, db=db_session,
    )
    assert ctx_a.user_id == user_a.id
    assert ctx_b.user_id == user_b.id
    assert ctx_a.user_id != ctx_b.user_id


def test_token_email_change_has_no_effect_on_identity_resolution(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    tenant = _make_tenant_with_membership(db_session, user)
    token = mint_token(subject=subject, email="new-address@example.com")
    ctx = require_tenant_context(
        authorization=f"Bearer {token}", x_cmp_tenant_id=str(tenant.id), x_dev_tenant_id=None, x_dev_user_id=None, db=db_session
    )
    assert ctx.user_id == user.id
    # AUTH-001A is explicitly read-only w.r.t. CMP user data -- the stored
    # email must be untouched by a differing token email claim.
    db_session.refresh(user)
    assert user.email == "person@example.com"


def test_token_without_email_still_resolves_by_issuer_subject(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    tenant = _make_tenant_with_membership(db_session, user)
    token = mint_token(subject=subject, email=None, email_verified=None)
    ctx = require_tenant_context(
        authorization=f"Bearer {token}", x_cmp_tenant_id=str(tenant.id), x_dev_tenant_id=None, x_dev_user_id=None, db=db_session
    )
    assert ctx.user_id == user.id


# --- Tenant selection -----------------------------------------------------


def test_missing_tenant_header_is_400_for_bearer_request(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    _make_tenant_with_membership(db_session, user)
    with pytest.raises(HTTPException) as exc_info:
        require_tenant_context(
            authorization=_bearer_authorization(subject), x_cmp_tenant_id=None, x_dev_tenant_id=None, x_dev_user_id=None, db=db_session
        )
    assert exc_info.value.status_code == 400


def test_malformed_tenant_header_is_400(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    _make_tenant_with_membership(db_session, user)
    with pytest.raises(HTTPException) as exc_info:
        require_tenant_context(
            authorization=_bearer_authorization(subject), x_cmp_tenant_id="not-a-uuid", x_dev_tenant_id=None, x_dev_user_id=None, db=db_session
        )
    assert exc_info.value.status_code == 400


def test_removed_membership_is_403(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    tenant = _make_tenant_with_membership(db_session, user, membership_status="removed")
    with pytest.raises(HTTPException) as exc_info:
        require_tenant_context(
            authorization=_bearer_authorization(subject), x_cmp_tenant_id=str(tenant.id), x_dev_tenant_id=None, x_dev_user_id=None, db=db_session
        )
    assert exc_info.value.status_code == 403


def test_tenant_not_owned_by_user_is_403(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    _make_tenant_with_membership(db_session, user)
    other_user, _ = _make_bearer_user(db_session)
    other_tenant = _make_tenant_with_membership(db_session, other_user)

    with pytest.raises(HTTPException) as exc_info:
        require_tenant_context(
            authorization=_bearer_authorization(subject), x_cmp_tenant_id=str(other_tenant.id), x_dev_tenant_id=None, x_dev_user_id=None, db=db_session
        )
    assert exc_info.value.status_code == 403


def test_inactive_tenant_is_403(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    tenant = _make_tenant_with_membership(db_session, user, tenant_status="inactive")
    with pytest.raises(HTTPException) as exc_info:
        require_tenant_context(
            authorization=_bearer_authorization(subject), x_cmp_tenant_id=str(tenant.id), x_dev_tenant_id=None, x_dev_user_id=None, db=db_session
        )
    assert exc_info.value.status_code == 403


def test_role_code_propagated_to_tenant_context(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    tenant = _make_tenant_with_membership(db_session, user, role_code="qc_officer")
    ctx = require_tenant_context(
        authorization=_bearer_authorization(subject), x_cmp_tenant_id=str(tenant.id), x_dev_tenant_id=None, x_dev_user_id=None, db=db_session
    )
    assert ctx.role_code == "qc_officer"


def test_multi_tenant_user_can_select_each_owned_tenant_explicitly(db_session, configured_oidc) -> None:
    user, subject = _make_bearer_user(db_session)
    tenant_a = _make_tenant_with_membership(db_session, user, role_code="tenant_admin")
    tenant_b = _make_tenant_with_membership(db_session, user, role_code="read_only")

    ctx_a = require_tenant_context(
        authorization=_bearer_authorization(subject), x_cmp_tenant_id=str(tenant_a.id), x_dev_tenant_id=None, x_dev_user_id=None, db=db_session
    )
    ctx_b = require_tenant_context(
        authorization=_bearer_authorization(subject), x_cmp_tenant_id=str(tenant_b.id), x_dev_tenant_id=None, x_dev_user_id=None, db=db_session
    )
    assert ctx_a.tenant_id == tenant_a.id and ctx_a.role_code == "tenant_admin"
    assert ctx_b.tenant_id == tenant_b.id and ctx_b.role_code == "read_only"


def test_tenant_header_cannot_escalate_access(db_session, configured_oidc) -> None:
    """The header is never trusted by itself -- asking for a tenant the
    caller has no membership in is rejected regardless of what the header
    claims, proving selection cannot grant access on its own."""
    user, subject = _make_bearer_user(db_session)
    # No membership created for `user` anywhere.
    other_user, _ = _make_bearer_user(db_session)
    real_tenant = _make_tenant_with_membership(db_session, other_user)

    with pytest.raises(HTTPException) as exc_info:
        require_tenant_context(
            authorization=_bearer_authorization(subject), x_cmp_tenant_id=str(real_tenant.id), x_dev_tenant_id=None, x_dev_user_id=None, db=db_session
        )
    assert exc_info.value.status_code == 403


# --- Dev / bearer coexistence ----------------------------------------------


def test_dev_headers_still_work(db_session, active_context) -> None:
    tenant, user, dev_headers = active_context
    ctx = require_tenant_context(
        authorization=None,
        x_cmp_tenant_id=None,
        x_dev_tenant_id=dev_headers["X-Dev-Tenant-Id"],
        x_dev_user_id=dev_headers["X-Dev-User-Id"],
        db=db_session,
    )
    assert ctx.tenant_id == tenant.id
    assert ctx.user_id == user.id
    assert ctx.role_code == "tenant_admin"


def test_bearer_plus_dev_headers_is_401(db_session, active_context, configured_oidc) -> None:
    tenant, user, dev_headers = active_context
    with pytest.raises(HTTPException) as exc_info:
        require_tenant_context(
            authorization=_bearer_authorization(unique_subject()),
            x_cmp_tenant_id=None,
            x_dev_tenant_id=dev_headers["X-Dev-Tenant-Id"],
            x_dev_user_id=dev_headers["X-Dev-User-Id"],
            db=db_session,
        )
    assert exc_info.value.status_code == 401


def test_bearer_plus_partial_dev_header_is_401(db_session, active_context, configured_oidc) -> None:
    tenant, user, dev_headers = active_context
    with pytest.raises(HTTPException) as exc_info:
        require_tenant_context(
            authorization=_bearer_authorization(unique_subject()),
            x_cmp_tenant_id=None,
            x_dev_tenant_id=dev_headers["X-Dev-Tenant-Id"],
            x_dev_user_id=None,
            db=db_session,
        )
    assert exc_info.value.status_code == 401


def test_conflicting_tenant_mechanisms_rejected(db_session, active_context) -> None:
    tenant, user, dev_headers = active_context
    with pytest.raises(HTTPException) as exc_info:
        require_tenant_context(
            authorization=None,
            x_cmp_tenant_id=str(tenant.id),
            x_dev_tenant_id=dev_headers["X-Dev-Tenant-Id"],
            x_dev_user_id=dev_headers["X-Dev-User-Id"],
            db=db_session,
        )
    assert exc_info.value.status_code == 400


def test_dev_and_bearer_paths_resolve_to_the_same_tenant_context_structure(db_session, active_context, configured_oidc) -> None:
    tenant, user, dev_headers = active_context

    dev_ctx = require_tenant_context(
        authorization=None, x_cmp_tenant_id=None,
        x_dev_tenant_id=dev_headers["X-Dev-Tenant-Id"], x_dev_user_id=dev_headers["X-Dev-User-Id"], db=db_session,
    )

    bearer_user, subject = _make_bearer_user(db_session)
    bearer_tenant = _make_tenant_with_membership(db_session, bearer_user, role_code="operator")
    bearer_ctx = require_tenant_context(
        authorization=_bearer_authorization(subject), x_cmp_tenant_id=str(bearer_tenant.id),
        x_dev_tenant_id=None, x_dev_user_id=None, db=db_session,
    )

    assert isinstance(dev_ctx, TenantContext)
    assert isinstance(bearer_ctx, TenantContext)
    assert type(dev_ctx) is type(bearer_ctx)
    assert dev_ctx.tenant_id == tenant.id
    assert bearer_ctx.tenant_id == bearer_tenant.id
    assert bearer_ctx.role_code == "operator"


def test_no_credentials_at_all_is_401(db_session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_tenant_context(authorization=None, x_cmp_tenant_id=None, x_dev_tenant_id=None, x_dev_user_id=None, db=db_session)
    assert exc_info.value.status_code == 401


# --- HTTP-level route-wiring proof ------------------------------------------


@pytest.mark.integration
def test_route_returns_400_when_bearer_request_omits_tenant_header(client, configured_oidc, db_session) -> None:
    user, subject = _make_bearer_user(db_session)
    _make_tenant_with_membership(db_session, user)
    db_session.commit()
    response = client.get("/farms", headers={"Authorization": _bearer_authorization(subject)})
    assert response.status_code == 400


@pytest.mark.integration
def test_route_returns_403_for_unknown_bearer_identity(client, configured_oidc) -> None:
    response = client.get(
        "/farms",
        headers={"Authorization": _bearer_authorization(unique_subject()), "X-CMP-Tenant-Id": str(uuid.uuid4())},
    )
    assert response.status_code == 403


@pytest.mark.integration
def test_route_succeeds_end_to_end_with_valid_bearer_and_tenant(client, configured_oidc, db_session) -> None:
    user, subject = _make_bearer_user(db_session)
    tenant = _make_tenant_with_membership(db_session, user)
    db_session.commit()
    response = client.get(
        "/farms", headers={"Authorization": _bearer_authorization(subject), "X-CMP-Tenant-Id": str(tenant.id)}
    )
    assert response.status_code == 200
