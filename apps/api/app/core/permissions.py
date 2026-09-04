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

    # CARRIER-CONFIG-001: deliberately separate from CARRIER_MANAGE (which
    # governs registering an individual physical Carrier) -- redefining the
    # reusable physical DESIGN every Carrier of a type is built from is a
    # materially different, more consequential authority, mirroring the
    # same entry-vs-definition split AUTHZ-002B1 already established for
    # OBSERVATION_ENTRY_MANAGE/OBSERVATION_DEFINITION_MANAGE.
    CARRIER_SPECIFICATION_READ = "carrier_specification.read"
    CARRIER_SPECIFICATION_MANAGE = "carrier_specification.manage"

    # Occupant relocation (asset/carrier -> location/asset_position) is its
    # own cross-entity command, not owned by asset or carrier alone -- no
    # standalone "movements" read endpoint exists (movement history is
    # read via asset.read/carrier.read's own nested endpoints).
    MOVEMENT_MANAGE = "movement.manage"

    # NURSERY-OPS-003B: a biological quantity-REDUCING action is materially
    # more consequential than a descriptive Observation (which
    # OBSERVATION_ENTRY_MANAGE already covers) -- deliberately split,
    # mirroring AUTHZ-002B1's own precedent of splitting a permission
    # exactly when two "recording" actions carry different authority
    # levels. No standalone read counterpart: Seedling balance/disposition-
    # history reads reuse SOWING_READ, matching NURSERY-OPS-003A's own
    # precedent for `list_seedling_candidate_trays` (see
    # ROLE_PERMISSION_POLICY_PROPOSAL.md discussion pattern for
    # OBSERVATION_ENTRY_MANAGE/OBSERVATION_DEFINITION_MANAGE).
    BIOLOGICAL_DISPOSITION_MANAGE = "biological_disposition.manage"

    # BIOLOGICAL-DISPOSITION-AUTHZ-001: deliberately separate from
    # BIOLOGICAL_DISPOSITION_MANAGE -- correcting an already-recorded
    # historical Disposition fact (potentially restoring previously-
    # exhausted biology and its Carrier assignment) is a materially more
    # consequential, supervisory authority than recording an ordinary one,
    # mirroring TRANSPLANT_CORRECT's own identical split from
    # TRANSPLANT_MANAGE.
    BIOLOGICAL_DISPOSITION_CORRECT = "biological_disposition.correct"

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

    # TRANSPLANT-CORRECTION-001: deliberately separate from TRANSPLANT_MANAGE
    # -- correcting/voiding an already-recorded biological Transplant fact is
    # a materially more consequential, supervisor-level authority than
    # recording an ordinary one (mirrors BIOLOGICAL_DISPOSITION_MANAGE's own
    # split from OBSERVATION_ENTRY_MANAGE). Granted only to tenant_admin,
    # farm_manager, head_grower, production_supervisor -- explicitly NOT to
    # operator (who holds TRANSPLANT_MANAGE) or any other role.
    TRANSPLANT_CORRECT = "transplant.correct"

    # Split (AUTHZ-002B1) from a single OBSERVATION_MANAGE: routine
    # observation recording and observation-definition configuration are
    # deliberately different authority levels (recording an observation
    # against an existing definition vs. defining what can be recorded at
    # all is master data) -- the prior unified permission made it
    # impossible to grant one without the other. OBSERVATION_READ remains
    # unified for both records and definitions; no operational reason was
    # found to split visibility (see docs/domain/AUTHORIZATION_MODEL.md).
    OBSERVATION_READ = "observation.read"
    OBSERVATION_ENTRY_MANAGE = "observation_entry.manage"
    OBSERVATION_DEFINITION_MANAGE = "observation_definition.manage"

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

    # STORE-INV-001B: the first Store & Inventory master-data permissions --
    # closes the "no general Input/Store module/permissions" gap
    # `ROLE_PERMISSION_POLICY_PROPOSAL.md` §7/§13 already documented as a
    # known P1 limitation of the `storekeeper` role. Minted fresh (not
    # reusing an existing domain's permission) since Inventory is a new
    # domain, not a sub-concern of one that already has its own pair.
    INVENTORY_CATEGORY_READ = "inventory_category.read"
    INVENTORY_CATEGORY_MANAGE = "inventory_category.manage"

    INVENTORY_ITEM_READ = "inventory_item.read"
    INVENTORY_ITEM_MANAGE = "inventory_item.manage"

    # Read-only system catalog -- deliberately no `.manage` counterpart,
    # mirroring TRACEABILITY_READ's own read-only-by-design precedent.
    # Store hierarchy itself reuses LOCATION_READ/LOCATION_MANAGE --
    # a Store is a Location, not a separate permission domain.
    UNIT_OF_MEASURE_READ = "unit_of_measure.read"


_ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

# The one centralized role -> permission policy.
#
# AUTHZ-002B2 activates the Imperial Pilot policy designed and
# progressively challenge-reviewed in AUTHZ-002A/.1/.2 and
# AUTHZ-002B1, whose single source of truth is Matrix A ("Imperial
# Pilot") in docs/domain/ROLE_PERMISSION_POLICY_PROPOSAL.md. Every
# non-admin grant below was mechanically derived from that document's
# current-implementable matrix (not re-derived from memory) before
# this file was edited -- see that document for the full per-permission
# justification, the master-data/operational/control classification,
# and the segregation-of-duty analysis behind each inclusion/exclusion.
# `farm_manager` uses that document's explicit MINIMUM tier (25
# permissions) for this pilot activation, not the optional 26-permission
# "broader pilot" tier that additionally includes `dispatch.manage` as
# backup authority -- that tier is documented but deliberately not
# activated here.
#
# External-commercial-V1 hardening items the policy document itself
# defers (farm-scoped role assignment; quality-hold place/release
# split; recall open/close split; a general Input/Store module; an
# `audit.read` permission distinguishing `auditor` from `read_only`)
# are NOT implemented by this activation -- see that document's P1/P2
# gap list, unchanged by this ticket.
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
    # Site general manager (MINIMUM tier, 25) -- infrastructure setup,
    # full read visibility, senior recall escalation authority. Does NOT
    # get tenant.members.manage (SaaS account admin is tenant_admin-only)
    # and does NOT get dispatch.manage under this pilot's minimum policy
    # (the optional broader-pilot backup-dispatch grant is not activated).
    "farm_manager": frozenset({
        Permission.FARM_READ, Permission.FARM_MANAGE,
        Permission.LOCATION_READ, Permission.LOCATION_MANAGE,
        Permission.ASSET_READ, Permission.ASSET_MANAGE,
        Permission.CARRIER_READ, Permission.CARRIER_MANAGE,
        Permission.CARRIER_SPECIFICATION_READ, Permission.CARRIER_SPECIFICATION_MANAGE,
        Permission.INVENTORY_CATEGORY_READ, Permission.INVENTORY_CATEGORY_MANAGE,
        Permission.INVENTORY_ITEM_READ, Permission.INVENTORY_ITEM_MANAGE,
        Permission.UNIT_OF_MEASURE_READ,
        Permission.CROP_READ,
        Permission.PRODUCTION_SYSTEM_READ,
        Permission.WORKFLOW_READ,
        Permission.CROP_BATCH_READ,
        Permission.BATCH_DERIVATION_READ,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ,
        Permission.TRANSPLANT_READ, Permission.TRANSPLANT_CORRECT,
        Permission.OBSERVATION_READ,
        Permission.BIOLOGICAL_DISPOSITION_CORRECT,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ,
        Permission.PACKING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ, Permission.RECALL_MANAGE,
        Permission.TRACEABILITY_READ,
    }),
    # Agronomic planning/master-data authority (25): crop/production-system
    # /workflow catalog, observation definitions, crop-batch lifecycle
    # (creation, stage transitions, splits/merges), harvest as the
    # conclusion of the batches this role owns. No tenant administration,
    # no dispatch/packing/storage authority.
    "head_grower": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.INVENTORY_CATEGORY_READ,
        Permission.INVENTORY_ITEM_READ,
        Permission.UNIT_OF_MEASURE_READ,
        Permission.CROP_READ, Permission.CROP_MANAGE,
        Permission.PRODUCTION_SYSTEM_READ, Permission.PRODUCTION_SYSTEM_MANAGE,
        Permission.WORKFLOW_READ, Permission.WORKFLOW_MANAGE,
        Permission.CROP_BATCH_READ, Permission.CROP_BATCH_MANAGE,
        Permission.BATCH_DERIVATION_READ, Permission.BATCH_DERIVATION_MANAGE,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ,
        Permission.TRANSPLANT_READ, Permission.TRANSPLANT_CORRECT,
        Permission.OBSERVATION_READ, Permission.OBSERVATION_ENTRY_MANAGE,
        Permission.OBSERVATION_DEFINITION_MANAGE,
        Permission.BIOLOGICAL_DISPOSITION_CORRECT,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ, Permission.HARVEST_MANAGE,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    # Production-floor execution oversight (24): the same transactional
    # commands operators perform, plus supervisory-level authority
    # operators do not have (batch creation/stage transitions,
    # splits/merges). No master-data configuration -- in particular no
    # observation_definition.manage, unlike head_grower.
    "production_supervisor": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.INVENTORY_CATEGORY_READ,
        Permission.INVENTORY_ITEM_READ,
        Permission.UNIT_OF_MEASURE_READ,
        Permission.MOVEMENT_MANAGE,
        Permission.CROP_READ,
        Permission.PRODUCTION_SYSTEM_READ,
        Permission.WORKFLOW_READ,
        Permission.CROP_BATCH_READ, Permission.CROP_BATCH_MANAGE,
        Permission.BATCH_DERIVATION_READ, Permission.BATCH_DERIVATION_MANAGE,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ, Permission.SOWING_MANAGE,
        Permission.TRANSPLANT_READ, Permission.TRANSPLANT_MANAGE, Permission.TRANSPLANT_CORRECT,
        Permission.OBSERVATION_READ, Permission.OBSERVATION_ENTRY_MANAGE,
        Permission.BIOLOGICAL_DISPOSITION_MANAGE, Permission.BIOLOGICAL_DISPOSITION_CORRECT,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ, Permission.HARVEST_MANAGE,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    # Restricted transactional execution (16): routine, single-purpose
    # floor commands only -- sowing, transplant, movement, harvest
    # recording, observation entry. No planning, no configuration, no
    # quality/compliance authority. observation_definition.manage is
    # deliberately absent -- entry and definition authority were split
    # by AUTHZ-002B1 specifically so this role could receive one without
    # the other.
    "operator": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.INVENTORY_CATEGORY_READ,
        Permission.INVENTORY_ITEM_READ,
        Permission.UNIT_OF_MEASURE_READ,
        Permission.MOVEMENT_MANAGE,
        Permission.CROP_BATCH_READ,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ, Permission.SOWING_MANAGE,
        Permission.TRANSPLANT_READ, Permission.TRANSPLANT_MANAGE,
        Permission.OBSERVATION_READ, Permission.OBSERVATION_ENTRY_MANAGE,
        Permission.BIOLOGICAL_DISPOSITION_MANAGE,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ, Permission.HARVEST_MANAGE,
    }),
    # Input/equipment receiving (6) -- intentionally narrow: the only
    # genuine "input receiving" action the current permission catalog
    # supports is seed-lot registration. No asset.manage/carrier.manage
    # (equipment registration remains centralized under farm_manager) --
    # not withheld to make the role look narrow, but because a general
    # Input/Store module (nutrients, substrate, consumables) does not
    # exist yet; see the policy document's storekeeper section.
    "storekeeper": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.SEED_LOT_READ, Permission.SEED_LOT_MANAGE,
        # STORE-INV-001B: closes the "no general Input/Store module" gap
        # ROLE_PERMISSION_POLICY_PROPOSAL.md §7/§13 documented as a known
        # P1 limitation of this role's narrow scope.
        Permission.INVENTORY_CATEGORY_READ, Permission.INVENTORY_CATEGORY_MANAGE,
        Permission.INVENTORY_ITEM_READ, Permission.INVENTORY_ITEM_MANAGE,
        Permission.UNIT_OF_MEASURE_READ,
    }),
    # Quality authority (19): observation entry (not definition -- cannot
    # be safely scoped to "QC-specific" vs. agronomic, see the policy
    # document), quality-hold place/release (still unified -- P1 hardening
    # item for external commercialization, not split here), and cross-
    # chain read visibility for root-cause investigation. No recall.manage
    # -- recall is a management escalation, deliberately kept separate
    # from the function that detects the underlying quality issue.
    "qc_officer": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.INVENTORY_CATEGORY_READ,
        Permission.INVENTORY_ITEM_READ,
        Permission.UNIT_OF_MEASURE_READ,
        Permission.CROP_READ,
        Permission.CROP_BATCH_READ,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ,
        Permission.TRANSPLANT_READ,
        Permission.OBSERVATION_READ, Permission.OBSERVATION_ENTRY_MANAGE,
        Permission.QUALITY_HOLD_READ, Permission.QUALITY_HOLD_MANAGE,
        Permission.HARVEST_READ,
        Permission.PACKING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    # Packing execution (12): owns its own stage only. Upstream
    # harvest.read (what's available to pack), downstream
    # finished_goods_storage.read (visibility once packed) -- never
    # finished_goods_storage.manage or dispatch.manage; those stay with
    # cold_store_supervisor/dispatch_officer.
    "packing_supervisor": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.INVENTORY_CATEGORY_READ,
        Permission.INVENTORY_ITEM_READ,
        Permission.UNIT_OF_MEASURE_READ,
        Permission.CROP_BATCH_READ,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ,
        Permission.PACKING_READ, Permission.PACKING_MANAGE,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    # Finished-goods storage execution (11): owns its own stage only.
    # Upstream packing.read, downstream dispatch.read -- never
    # packing.manage or dispatch.manage.
    "cold_store_supervisor": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.INVENTORY_CATEGORY_READ,
        Permission.INVENTORY_ITEM_READ,
        Permission.UNIT_OF_MEASURE_READ,
        Permission.QUALITY_HOLD_READ,
        Permission.PACKING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ, Permission.FINISHED_GOODS_STORAGE_MANAGE,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    # Dispatch execution (11): owns its own stage only. Upstream
    # finished_goods_storage.read and packing.read (lot provenance for
    # shipment documentation) -- never packing.manage or
    # finished_goods_storage.manage.
    "dispatch_officer": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.INVENTORY_CATEGORY_READ,
        Permission.INVENTORY_ITEM_READ,
        Permission.UNIT_OF_MEASURE_READ,
        Permission.QUALITY_HOLD_READ,
        Permission.PACKING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ, Permission.DISPATCH_MANAGE,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    # Broad compliance/traceability visibility (20) -- every `.read`
    # permission, zero `.manage`. Technically identical to `read_only`
    # today: the policy document's intended differentiator (an
    # `audit.read` permission gating the raw audit-event log) does not
    # exist yet -- see that document's gap list. Not fabricating a
    # difference here.
    "auditor": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.INVENTORY_CATEGORY_READ,
        Permission.INVENTORY_ITEM_READ,
        Permission.UNIT_OF_MEASURE_READ,
        Permission.CROP_READ,
        Permission.PRODUCTION_SYSTEM_READ,
        Permission.WORKFLOW_READ,
        Permission.CROP_BATCH_READ,
        Permission.BATCH_DERIVATION_READ,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ,
        Permission.TRANSPLANT_READ,
        Permission.OBSERVATION_READ,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ,
        Permission.PACKING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    # Broad operational visibility (20), zero mutations -- identical set
    # to `auditor` today, by design (see that role's comment above).
    "read_only": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.INVENTORY_CATEGORY_READ,
        Permission.INVENTORY_ITEM_READ,
        Permission.UNIT_OF_MEASURE_READ,
        Permission.CROP_READ,
        Permission.PRODUCTION_SYSTEM_READ,
        Permission.WORKFLOW_READ,
        Permission.CROP_BATCH_READ,
        Permission.BATCH_DERIVATION_READ,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ,
        Permission.TRANSPLANT_READ,
        Permission.OBSERVATION_READ,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ,
        Permission.PACKING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
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
