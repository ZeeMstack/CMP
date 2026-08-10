"""TEMPORARY, development-only tenant/user identity resolution.

Stands in for OIDC authentication (see `app.core.oidc`) for local
development and deterministic tests. Must never be relied on outside
local development, and converges into the exact same `TenantContext`
shape real authentication produces (see `app.core.auth`) -- callers and
business services never know or care which path produced their context.

Importing this module has no side effects; `check_dev_auth_startup_invariant`
must be called explicitly at app startup to enforce the environment guard
below.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import Settings, settings
from app.models.membership import TenantMembership
from app.models.tenant import Tenant
from app.models.user import User


def check_dev_auth_startup_invariant(cfg: Settings | None = None) -> None:
    cfg = cfg or settings
    if cfg.enable_dev_auth and cfg.env != "development":
        raise RuntimeError(
            "ENABLE_DEV_AUTH=true is not permitted when ENV != 'development'. "
            "This mechanism must never be active outside local development."
        )


def require_dev_auth_enabled() -> None:
    if not settings.enable_dev_auth:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dev auth is disabled")


def parse_uuid_header(value: str, header_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{header_name} must be a valid UUID",
        ) from exc


def resolve_dev_user(*, x_dev_user_id: str, db: Session) -> uuid.UUID:
    """Validates a dev user id alone -- used where no tenant is required
    yet (e.g. GET /auth/me in development). Requires dev auth enabled and
    an active user; returns the validated user id."""
    require_dev_auth_enabled()
    user_id = parse_uuid_header(x_dev_user_id, "X-Dev-User-Id")
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive user context")
    return user_id


def resolve_dev_tenant_context(
    *, x_dev_tenant_id: str, x_dev_user_id: str, db: Session
) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Tenant-scoped access requires an active tenant, an active user, and
    an active membership linking them -- not merely well-formed header
    values. Returns (tenant_id, user_id, role_code); role_code is
    guaranteed non-null by `ck_tenant_memberships_active_requires_role`
    for any row this query can return."""
    require_dev_auth_enabled()
    tenant_id = parse_uuid_header(x_dev_tenant_id, "X-Dev-Tenant-Id")
    user_id = parse_uuid_header(x_dev_user_id, "X-Dev-User-Id")

    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive tenant context")

    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive user context")

    membership = db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
        )
    ).scalar_one_or_none()
    if membership is None or not membership.role_code:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active membership for this tenant")

    return tenant_id, user_id, membership.role_code
