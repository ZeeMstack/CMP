"""CMP authorization: permission catalog, role policy, and enforcement
primitives (AUTHZ-001A).

Auth0 authenticates WHO the caller is (exact issuer + subject -> CMP
`User`, see `app.core.oidc`/`app.core.auth`). It has no concept of CMP
tenants, roles, or permissions, and none of its claims (roles,
organizations, profile metadata) are ever consulted here. Authorization --
WHAT an authenticated CMP user may do -- is entirely CMP's own concern,
derived from exactly one source of truth: the caller's *active* tenant
membership for the tenant already resolved by `require_tenant_context`
(`app.core.auth.TenantContext`), specifically its `role_code`.

This is the one and only place a CMP role is translated into a set of
permissions -- no route or service should hardcode a `role_code` string
comparison (grep for `role_code ==` outside this module and
`app.core.auth`/`app.core.dev_auth` if one ever appears; it shouldn't).
Deny by default: any `role_code` not explicitly granted a permission set
below -- including every currently-approved role other than
`tenant_admin`, any future/unrecognized role, and a missing/blank role --
resolves to the empty set. See `docs/AUTHORIZATION_MODEL.md` for the
architecture writeup and the full endpoint/permission inventory.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from types import MappingProxyType

from fastapi import Depends, HTTPException, status

from app.core.auth import TenantContext, require_tenant_context


class Permission(StrEnum):
    """The CMP permission catalog. Values are stable, dotted domain
    strings (`<domain>.read` / `<domain>.manage`) -- never an Auth0 role,
    scope, or permission name, and never persisted to the database. Two
    tiers per domain unless the endpoint audit gave no reason for one of
    them to exist (e.g. `traceability` has no mutation endpoint at all;
    `movement` and `tenant.members` currently have no standalone read
    endpoint). `manage` covers every mutation/command in that domain --
    CMP has no PUT/PATCH/DELETE endpoints anywhere (every mutation is an
    append-only POST, create or domain command), so a narrower
    per-verb split was not justified by current behavior.

    Derived directly from the AUTHZ-001A endpoint audit
    (`docs/AUTHORIZATION_MODEL.md`) -- every value here corresponds to at
    least one real, currently-mounted endpoint.
    """

    FARM_READ = "farm.read"
    FARM_MANAGE = "farm.manage"

    LOCATION_READ = "location.read"
    LOCATION_MANAGE = "location.manage"

    ASSET_READ = "asset.read"
    ASSET_MANAGE = "asset.manage"

    CARRIER_READ = "carrier.read"
    CARRIER_MANAGE = "carrier.manage"

    # Occupant relocation (asset/carrier -> location/asset_position) is its
    # own cross-entity command, not owned by asset or carrier alone -- no
    # standalone "movements" read endpoint exists (movement history is
    # read via asset.read/carrier.read's own nested endpoints).
    MOVEMENT_MANAGE = "movement.manage"

    CROP_READ = "crop.read"
    CROP_MANAGE = "crop.manage"

    PRODUCTION_SYSTEM_READ = "production_system.read"
    PRODUCTION_SYSTEM_MANAGE = "production_system.manage"

    WORKFLOW_READ = "workflow.read"
    WORKFLOW_MANAGE = "workflow.manage"

    CROP_BATCH_READ = "crop_batch.read"
    CROP_BATCH_MANAGE = "crop_batch.manage"

    BATCH_DERIVATION_READ = "batch_derivation.read"
    BATCH_DERIVATION_MANAGE = "batch_derivation.manage"

    SEED_LOT_READ = "seed_lot.read"
    SEED_LOT_MANAGE = "seed_lot.manage"

    SOWING_READ = "sowing.read"
    SOWING_MANAGE = "sowing.manage"

    TRANSPLANT_READ = "transplant.read"
    TRANSPLANT_MANAGE = "transplant.manage"

    OBSERVATION_READ = "observation.read"
    OBSERVATION_MANAGE = "observation.manage"

    QUALITY_HOLD_READ = "quality_hold.read"
    QUALITY_HOLD_MANAGE = "quality_hold.manage"

    HARVEST_READ = "harvest.read"
    HARVEST_MANAGE = "harvest.manage"

    PACKING_READ = "packing.read"
    PACKING_MANAGE = "packing.manage"

    FINISHED_GOODS_STORAGE_READ = "finished_goods_storage.read"
    FINISHED_GOODS_STORAGE_MANAGE = "finished_goods_storage.manage"

    DISPATCH_READ = "dispatch.read"
    DISPATCH_MANAGE = "dispatch.manage"

    RECALL_READ = "recall.read"
    RECALL_MANAGE = "recall.manage"

    # Pure derived/computed read -- no mutation endpoint exists.
    TRACEABILITY_READ = "traceability.read"

    # No GET /memberships endpoint currently exists -- only the mutation
    # (POST /memberships) is a real, mounted capability today.
    TENANT_MEMBERS_MANAGE = "tenant.members.manage"


_ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

# The one centralized role -> permission policy. `tenant_admin` is the
# only role whose authority is established by this ticket's own
# instruction ("tenant_admin has all currently defined CMP tenant
# permissions"); every other currently-approved `role_code`
# (`app.models.membership.APPROVED_ROLE_CODES`) -- farm_manager,
# head_grower, production_supervisor, operator, storekeeper, qc_officer,
# auditor, packing_supervisor, cold_store_supervisor, dispatch_officer,
# read_only -- has real precedent in fixtures/tests as an authenticatable
# role, but NO source or doc establishes what that role specifically may
# or may not do (confirmed against docs/CMP_MASTER_SPEC.md section 11,
# which only lists role *names*, not permissions). Inventing a permission
# set for any of them here would be a product decision this ticket is not
# authorized to make -- they are deliberately left unmapped, which (via
# `get_permissions_for_role`'s deny-by-default lookup) grants them zero
# permissions. This is intentional, not an oversight; see
# docs/AUTHORIZATION_MODEL.md's "deferred to AUTHZ-001B" section.
#
# Immutability (AUTHZ-001A.1): each grant is already a `frozenset`, which
# has no `.add()`/`.remove()` -- `ROLE_PERMISSIONS["tenant_admin"].add(...)`
# fails with `AttributeError` on its own. The mapping itself is built as a
# module-private plain dict (`_ROLE_PERMISSIONS`, never exported) and
# exposed publicly only through a `MappingProxyType` view -- the standard-
# library "read-only dict" idiom -- so `ROLE_PERMISSIONS["x"] = ...`,
# assigning a new key, or `del ROLE_PERMISSIONS["tenant_admin"]` all raise
# `TypeError` through the only reference any other module ever has. This
# guards against *casual* mutation (the entire exported surface), not
# against another module in the same process deliberately reaching into
# `app.core.permissions._ROLE_PERMISSIONS` by its private name -- Python
# has no true module-private enforcement, and that residual case is not
# "casual".
_ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "tenant_admin": _ALL_PERMISSIONS,
}
ROLE_PERMISSIONS: Mapping[str, frozenset[Permission]] = MappingProxyType(_ROLE_PERMISSIONS)


def get_permissions_for_role(role_code: str | None) -> frozenset[Permission]:
    """Deny by default: a missing/blank role, an unrecognized role_code
    (including any of the currently-approved-but-unmapped roles listed
    above, and any string that isn't an approved role_code at all), all
    resolve to the empty set via the same lookup path -- there is no
    separate "unknown role" code branch to drift out of sync with the
    "known but unmapped role" branch."""
    if not role_code:
        return frozenset()
    return ROLE_PERMISSIONS.get(role_code, frozenset())


def has_permission(ctx: TenantContext, permission: Permission) -> bool:
    """Authorization is derived exclusively from `ctx.role_code` -- the
    role_code of the *active* membership `require_tenant_context` already
    proved exists for `ctx.tenant_id`/`ctx.user_id`. Never authorize from
    email, Auth0 profile metadata, Auth0 roles/organizations, or any
    tenant id that was not independently verified against an active
    membership (that verification already happened one layer down, in
    `require_tenant_context`, before a `TenantContext` could exist at
    all)."""
    return permission in get_permissions_for_role(ctx.role_code)


def require_permission(permission: Permission) -> Callable[..., TenantContext]:
    """FastAPI dependency factory: `Depends(require_permission(Permission.FARM_READ))`.

    Built on top of `require_tenant_context` (never bypasses or
    duplicates it) -- authentication/tenant-membership errors (401 for no
    session or malformed tenant context, 400 for a missing/malformed
    tenant selector, 403 for no active membership at all) are raised by
    that dependency exactly as before this ticket; this layer only adds
    one more check, and only once a `TenantContext` has already been
    proven to exist. A granted permission returns that same
    `TenantContext` unchanged, so callers keep using `ctx.tenant_id`/
    `ctx.user_id` exactly as they already do -- routers never need to
    inspect `role_code` themselves.

    A denied permission raises a generic, stable 403 -- never naming the
    permission, the role, or any internal policy detail, so a caller can
    never use this endpoint as an oracle for what roles/permissions this
    deployment defines."""

    def _dependency(ctx: TenantContext = Depends(require_tenant_context)) -> TenantContext:
        if not has_permission(ctx, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to perform this action",
            )
        return ctx

    return _dependency
