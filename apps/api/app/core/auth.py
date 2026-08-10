"""Unified authentication / tenant-context resolution (AUTH-001A).

Converges two identity mechanisms -- real OIDC bearer tokens
(`app.core.oidc`) and explicit development headers (`app.core.dev_auth`,
development/test only) -- into the exact same downstream shapes
(`AuthenticatedPrincipal`, `TenantContext`) so business routes/services
never know or care which one produced their context. This is the one and
only trust-boundary abstraction business code should depend on; no route
or service should import from `app.core.oidc` or `app.core.dev_auth`
directly.

Mixing mechanisms in a single request (a bearer token alongside any
X-Dev-* header) is always rejected as ambiguous -- never silently
resolved by preferring one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core import dev_auth
from app.core.db import get_db
from app.core.oidc import AuthenticatedIdentity, TokenVerificationError, verify_bearer_token
from app.models.tenant import Tenant
from app.models.user import User
from app.services.membership_service import get_active_membership
from app.services.user_service import get_user_by_issuer_subject


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """WHO the caller is -- a resolved, active CMP user -- but not yet
    scoped to any tenant. `source` is diagnostic/testing metadata only;
    business logic must never branch on it, only on the fact that
    resolution already succeeded."""

    user_id: uuid.UUID
    source: Literal["bearer", "dev"]


@dataclass(frozen=True)
class TenantContext:
    """The production successor to the former `DevTenantContext` -- WHICH
    tenant a request operates in, as WHOM, with WHAT role. Only ever
    constructed after proving: user active, tenant active, an active
    membership links them, and that membership carries a role. Every
    tenant-scoped business route/service depends on this and nothing
    lower-level (never raw claims, never a token)."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role_code: str


_WWW_AUTHENTICATE_BEARER = {"WWW-Authenticate": "Bearer"}


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Returns None if no Authorization header was sent at all (not an
    error -- the caller may be using dev headers instead, or no
    authentication at all). Raises 401 immediately for a header that IS
    present but not a well-formed bearer credential."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed Authorization header",
            headers=_WWW_AUTHENTICATE_BEARER,
        )
    return token


def _verify_bearer(authorization: str | None) -> AuthenticatedIdentity | None:
    token = _extract_bearer_token(authorization)
    if token is None:
        return None
    try:
        return verify_bearer_token(token)
    except TokenVerificationError as exc:
        # Never surface the specific verification failure reason to the
        # client -- generic detail only, to avoid a verification oracle.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired credentials",
            headers=_WWW_AUTHENTICATE_BEARER,
        ) from exc


def _resolve_cmp_user_for_identity(identity: AuthenticatedIdentity, db: Session) -> User:
    """403, not 401: the bearer token itself was cryptographically valid
    (real, verified external authentication) -- CMP simply has no usable
    account for it. An unknown identity and a known-but-inactive user
    return the exact same generic detail, so a client can never
    distinguish "no such identity" from "identity exists but disabled"."""
    user = get_user_by_issuer_subject(db, oidc_issuer=identity.issuer, oidc_subject=identity.subject)
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No CMP access for this identity")
    return user


def require_authenticated_principal(
    authorization: str | None = Header(None),
    x_dev_user_id: str | None = Header(None, alias="X-Dev-User-Id"),
    x_dev_tenant_id: str | None = Header(None, alias="X-Dev-Tenant-Id"),
    db: Session = Depends(get_db),
) -> AuthenticatedPrincipal:
    """WHO-only resolution, with no tenant selection -- used by
    GET /auth/me, whose entire purpose is letting a client discover which
    tenants it may select. Development mode needs only X-Dev-User-Id
    here (not the tenant header), mirroring the same "no tenant required"
    shape as the real bearer path."""
    identity = _verify_bearer(authorization)
    dev_headers_present = x_dev_user_id is not None or x_dev_tenant_id is not None

    if identity is not None and dev_headers_present:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ambiguous identity mechanism",
            headers=_WWW_AUTHENTICATE_BEARER,
        )

    if identity is not None:
        user = _resolve_cmp_user_for_identity(identity, db)
        return AuthenticatedPrincipal(user_id=user.id, source="bearer")

    if x_dev_user_id is not None:
        user_id = dev_auth.resolve_dev_user(x_dev_user_id=x_dev_user_id, db=db)
        return AuthenticatedPrincipal(user_id=user_id, source="dev")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers=_WWW_AUTHENTICATE_BEARER,
    )


def require_tenant_context(
    authorization: str | None = Header(None),
    x_cmp_tenant_id: str | None = Header(None, alias="X-CMP-Tenant-Id"),
    x_dev_tenant_id: str | None = Header(None, alias="X-Dev-Tenant-Id"),
    x_dev_user_id: str | None = Header(None, alias="X-Dev-User-Id"),
    db: Session = Depends(get_db),
) -> TenantContext:
    """The unified, tenant-scoped successor to the former
    `require_dev_tenant_context`. Every tenant-scoped business route
    depends on this and only this -- a mechanical trust-boundary
    replacement, not a behavior change to any route."""
    identity = _verify_bearer(authorization)
    dev_headers_present = x_dev_user_id is not None or x_dev_tenant_id is not None

    if identity is not None and dev_headers_present:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ambiguous identity mechanism",
            headers=_WWW_AUTHENTICATE_BEARER,
        )

    if dev_headers_present:
        # Dev headers already fully specify tenant + user together;
        # X-CMP-Tenant-Id alongside them is a second, conflicting
        # tenant-selection mechanism in the same request -- never a
        # silent override of one by the other.
        if x_cmp_tenant_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Conflicting tenant-selection mechanisms"
            )
        if x_dev_tenant_id is None or x_dev_user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incomplete development identity",
                headers=_WWW_AUTHENTICATE_BEARER,
            )
        tenant_id, user_id, role_code = dev_auth.resolve_dev_tenant_context(
            x_dev_tenant_id=x_dev_tenant_id, x_dev_user_id=x_dev_user_id, db=db
        )
        return TenantContext(tenant_id=tenant_id, user_id=user_id, role_code=role_code)

    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers=_WWW_AUTHENTICATE_BEARER,
        )

    user = _resolve_cmp_user_for_identity(identity, db)

    if x_cmp_tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="X-CMP-Tenant-Id is required")
    try:
        tenant_id = uuid.UUID(x_cmp_tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="X-CMP-Tenant-Id must be a valid UUID"
        ) from exc

    # Tenant not found and tenant inactive return the identical 403 --
    # never leak whether a given tenant ID exists at all.
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is not accessible")

    # The header is never trusted as authorization by itself -- active
    # membership is re-checked against the database on every request, so
    # changing the header can never escalate access.
    membership = get_active_membership(db, tenant_id=tenant_id, user_id=user.id)
    if membership is None or not membership.role_code:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No active membership for this tenant")

    return TenantContext(tenant_id=tenant_id, user_id=user.id, role_code=membership.role_code)
