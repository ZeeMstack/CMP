"""TEMPORARY, development-only tenant/user context.

Stands in for OIDC authentication, which does not exist yet. Must never be
relied on outside local development, and is replaced wholesale — not
extended — once real authentication is built. Importing this module has no
side effects; `check_dev_auth_startup_invariant` must be called explicitly at
app startup to enforce the environment guard below.
"""

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
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


def _require_dev_auth_enabled() -> None:
    if not settings.enable_dev_auth:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Dev auth is disabled")


def _parse_uuid_header(value: str, header_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{header_name} must be a valid UUID",
        ) from exc


@dataclass(frozen=True)
class DevTenantContext:
    tenant_id: uuid.UUID
    user_id: uuid.UUID


def require_dev_tenant_context(
    x_dev_tenant_id: str = Header(..., alias="X-Dev-Tenant-Id"),
    x_dev_user_id: str = Header(..., alias="X-Dev-User-Id"),
    db: Session = Depends(get_db),
) -> DevTenantContext:
    """Tenant-scoped access requires an active tenant, an active user, and an
    active membership linking them — not merely well-formed header values."""
    _require_dev_auth_enabled()
    tenant_id = _parse_uuid_header(x_dev_tenant_id, "X-Dev-Tenant-Id")
    user_id = _parse_uuid_header(x_dev_user_id, "X-Dev-User-Id")

    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive tenant context"
        )

    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or inactive user context"
        )

    membership = db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No active membership for this tenant"
        )

    return DevTenantContext(tenant_id=tenant_id, user_id=user_id)
