"""Platform-level authorization (PILOT-SETUP-001B1).

Structurally independent of CMP's tenant-scoped authorization model
(`app.core.permissions`). A platform administrator is a global capability
granted directly to a `User` via `PlatformAdmin`
(`app.models.platform_admin`, `app.services.platform_admin_service`) -- it
has no `tenant_id`, no `role_code`, and is never a `TenantMembership`.
`tenant_admin` (the maximal *tenant-scoped* role) neither implies nor is
implied by platform-admin authority; the two are unrelated facts about a
User.

Holding platform-admin authority grants NO tenant data access whatsoever:
`require_platform_admin` is built strictly on top of
`require_authenticated_principal` (WHO-only resolution, exactly as
`GET /auth/me` already uses) and never resolves, returns, or depends on a
`TenantContext`. A route gated only by this dependency has no
`tenant_id`/`role_code` available to it at all -- a tenant operation still
requires its own, entirely separate, active TenantMembership + role_code +
Permission grant via `require_tenant_context`/`require_permission`, exactly
as before this ticket.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db
from app.services.platform_admin_service import is_platform_admin


def require_platform_admin(
    principal: AuthenticatedPrincipal = Depends(require_authenticated_principal),
    db: Session = Depends(get_db),
) -> AuthenticatedPrincipal:
    """WHO-only resolution (no tenant selection, no X-CMP-Tenant-Id/
    X-Dev-Tenant-Id involved -- identical shape to
    `require_authenticated_principal`) plus one additional check: does this
    resolved CMP user currently hold an active platform-admin assignment?
    Authentication failures (no/invalid credentials, unknown identity,
    inactive user) surface exactly as `require_authenticated_principal`
    already defines them (401/403) -- this dependency adds nothing to that
    behavior, only one more check once a principal has been resolved.

    Returns the same `AuthenticatedPrincipal` unchanged so callers keep
    using `principal.user_id` exactly as `require_authenticated_principal`
    callers already do."""
    if not is_platform_admin(db, user_id=principal.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform administrator authority required",
        )
    return principal
