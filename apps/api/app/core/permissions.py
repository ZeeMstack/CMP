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

    # POSTHARVEST-OPS-001: grading/sorting is its own post-harvest stage
    # (Harvest -> Grading -> Packing), deliberately given its own permission
    # pair rather than continuing to reuse `PACKING_READ`/`PACKING_MANAGE`
    # (the grading endpoints' original, now-superseded gate) -- mirroring
    # this catalog's own precedent of a dedicated pair per operational
    # stage. Every role's grant below is an exact mirror of that same
    # role's `PACKING_READ`/`PACKING_MANAGE` grant: grading and packing
    # have always been the same authority tier in practice (the same
    # packhouse-floor role performs both), and `farm_manager` deliberately
    # does NOT get `GRADING_MANAGE` for the identical reason it does not
    # get `PACKING_MANAGE` -- execution of a post-harvest production step
    # belongs to the specialist who owns that stage, not to the overseeing
    # farm manager (see `docs/domain/ROLE_PERMISSION_POLICY_PROPOSAL.md`
    # Matrix A / the farm_manager `packing.manage` removal rationale).
    GRADING_READ = "grading.read"
    GRADING_MANAGE = "grading.manage"

    FINISHED_GOODS_STORAGE_READ = "finished_goods_storage.read"
    FINISHED_GOODS_STORAGE_MANAGE = "finished_goods_storage.manage"

    DISPATCH_READ = "dispatch.read"
    DISPATCH_MANAGE = "dispatch.manage"

    RECALL_READ = "recall.read"
    RECALL_MANAGE = "recall.manage"

    # Pure derived/computed read -- no mutation endpoint exists.
    TRACEABILITY_READ = "traceability.read"

    # AUTHZ-OPS-001: GET /memberships (tenant Users & Roles administration
    # screen) needed its own `.read` permission -- the read-enforcement
    # architecture test (test_authz_read_enforcement_architecture.py)
    # requires every tenant-scoped GET route to be gated by a `.read`
    # permission, never the sibling `.manage`. Granted only to tenant_admin
    # (via the automatic frozenset(Permission) grant below) -- membership
    # administration remains tenant_admin-only, same as TENANT_MEMBERS_MANAGE.
    TENANT_MEMBERS_READ = "tenant.members.read"
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

    # STORE-INV-002A.1: the first operational (not master-data) Store &
    # Inventory permissions -- receiving stock and correcting existence
    # after the fact are deliberately different control powers, never
    # bundled (docs/domain/STORE_INVENTORY_MODEL.md §N). `INVENTORY_READ`
    # is visibility into operational existence/receipts/lots -- distinct
    # from the existing master-data `INVENTORY_ITEM_READ`/
    # `INVENTORY_CATEGORY_READ` pair, matching this catalog's own
    # established master-data-vs-operational split (e.g. `crop.read` vs.
    # `crop_batch.read`).
    INVENTORY_READ = "inventory.read"
    INVENTORY_RECEIPT_MANAGE = "inventory_receipt.manage"
    INVENTORY_ADJUSTMENT_MANAGE = "inventory_adjustment.manage"

    # STORE-INV-002A.2: release/hold/reject/hold-release, human correction,
    # and the partial-quantity disposition command all gate on this one
    # permission -- the "quality workflow" authority, deliberately never
    # bundled with `INVENTORY_RECEIPT_MANAGE` (segregation of duties is
    # enforced independently at the service layer, on top of this grant,
    # never instead of it -- docs/domain/STORE_INVENTORY_MODEL.md §11).
    # This does NOT authorize generic cohort-quantity partitioning as a
    # standalone capability -- `_split_cohort_core` remains an internal,
    # unrouted primitive with no `Permission` of its own.
    INVENTORY_QUALITY_MANAGE = "inventory_quality.manage"

    # STORE-INV-002B: physical custody / putaway (Bin placement and
    # bin-to-bin transfer) is its own control power, deliberately separate
    # from `INVENTORY_QUALITY_MANAGE` -- a QC officer decides disposition,
    # not where material physically sits, so `qc_officer` is explicitly
    # NOT granted this permission.
    INVENTORY_CUSTODY_MANAGE = "inventory_custody.manage"

    # STORE-INV-003: Reservation (a fungible CLAIM, never touching
    # existence/custody/quality) and Issue (a CUSTODY TRANSFER out of Store
    # Bins) are deliberately two separate control powers, mirroring this
    # catalog's own established segregation-of-duty precedent
    # (INVENTORY_QUALITY_MANAGE vs INVENTORY_CUSTODY_MANAGE) -- `qc_officer`
    # is explicitly NOT granted either.
    INVENTORY_RESERVATION_MANAGE = "inventory_reservation.manage"
    INVENTORY_ISSUE_MANAGE = "inventory_issue.manage"

    # STORE-INV-004: Consumption/Return/Scrap are their own control powers,
    # deliberately separate from `INVENTORY_ISSUE_MANAGE` (Issue is a
    # custody transfer only) -- mirroring this catalog's established
    # segregation-of-duty precedent. `qc_officer` is explicitly NOT granted
    # any of the three.
    INVENTORY_CONSUMPTION_MANAGE = "inventory_consumption.manage"
    INVENTORY_RETURN_MANAGE = "inventory_return.manage"
    INVENTORY_SCRAP_MANAGE = "inventory_scrap.manage"

    # PLANNING-OPS-001: the first Planning module permissions -- Production
    # Requirements and the Seeding Program are planning intent, deliberately
    # a single pair (never split per-entity) since both are edited by the
    # same planner role and neither has a materially different authority
    # tier from the other. Never confused with SOWING_MANAGE, which governs
    # the real, physical sowing command this planning module only links to.
    PLANNING_READ = "planning.read"
    PLANNING_MANAGE = "planning.manage"

    # PILOT-OPS-001: Farm Work Item / Shift Handover ("Today on the Farm").
    # Three tiers, not two -- `.manage` (supervisory: create work,
    # assign/reassign, change priority/due window, cancel) is deliberately
    # separate from `.execute` (floor: start/block/unblock assigned or
    # available work, and complete permitted work), mirroring this
    # catalog's own entry-vs-definition split precedent
    # (OBSERVATION_ENTRY_MANAGE/OBSERVATION_DEFINITION_MANAGE) -- a role
    # trusted to execute routine floor work should not automatically gain
    # the power to create/assign/cancel it, and vice versa. Shift Handover
    # reuses this same pair (`.execute` to author one, `.read` to view) --
    # it is a small communication artifact of the same domain, not a
    # separate permission domain.
    FARM_WORK_ITEM_READ = "farm_work_item.read"
    FARM_WORK_ITEM_MANAGE = "farm_work_item.manage"
    FARM_WORK_ITEM_EXECUTE = "farm_work_item.execute"

    # PILOT-AGRO-001: Growing Protocol / Grower Inspection / Crop Issue.
    # `GROWING_PROTOCOL_MANAGE` is master-data/agronomic-program authority
    # (draft/version editing, activation, Batch protocol assignment) --
    # grower/supervisory only. `CROP_INSPECTION_MANAGE` is the routine
    # floor act of recording a structured Inspection -- the same tier as
    # `OBSERVATION_ENTRY_MANAGE`, deliberately granted to `operator` too.
    # `CROP_ISSUE_MANAGE` (open/assign/diagnose/resolve/close a persistent
    # CropIssue) is a materially more consequential, supervisory authority
    # than recording a routine Inspection Finding -- deliberately split,
    # mirroring this catalog's own entry-vs-definition precedent
    # (OBSERVATION_ENTRY_MANAGE/OBSERVATION_DEFINITION_MANAGE).
    GROWING_PROTOCOL_READ = "growing_protocol.read"
    GROWING_PROTOCOL_MANAGE = "growing_protocol.manage"
    CROP_INSPECTION_READ = "crop_inspection.read"
    CROP_INSPECTION_MANAGE = "crop_inspection.manage"
    CROP_ISSUE_MANAGE = "crop_issue.manage"

    # PILOT-WATER-001A: water/nutrient domain. `WATER_TOPOLOGY_MANAGE`
    # covers WaterSource/Reservoir/IrrigationCircuit/WaterDeliveryPoint/
    # WaterReturnPoint identity and their effective-dated topology links --
    # infrastructure/master-data authority, grower/supervisory only, same
    # tier as `GROWING_PROTOCOL_MANAGE`. `SAMPLING_POINT_MANAGE` and
    # `WATER_INSTRUMENT_MANAGE` (which also covers recording Calibration --
    # ticket section 24 groups "manage calibration records" with grower/
    # supervisory authority) are their own pairs at the same tier.
    # `WATER_MEASUREMENT_MANAGE` and `NUTRIENT_OPERATIONS_MANAGE` (Mix/
    # Reservoir adjustment/Delivery recording) are deliberately the
    # OPERATOR-tier floor-recording authority the ticket calls out
    # explicitly ("record permitted measurements", "record mix/delivery/
    # adjustment events") -- never bundled with the manage-tier permissions
    # above. `NUTRIENT_RECIPE_MANAGE` (draft/version/activate/retire/
    # components) and `WATER_EXPOSURE_READ` (review exposure) are
    # grower/supervisory, mirroring `GROWING_PROTOCOL_MANAGE`/
    # `TRACEABILITY_READ`'s own precedent exactly.
    WATER_TOPOLOGY_READ = "water_topology.read"
    WATER_TOPOLOGY_MANAGE = "water_topology.manage"
    SAMPLING_POINT_READ = "sampling_point.read"
    SAMPLING_POINT_MANAGE = "sampling_point.manage"
    WATER_INSTRUMENT_READ = "water_instrument.read"
    WATER_INSTRUMENT_MANAGE = "water_instrument.manage"
    WATER_MEASUREMENT_READ = "water_measurement.read"
    WATER_MEASUREMENT_MANAGE = "water_measurement.manage"
    NUTRIENT_RECIPE_READ = "nutrient_recipe.read"
    NUTRIENT_RECIPE_MANAGE = "nutrient_recipe.manage"
    NUTRIENT_OPERATIONS_READ = "nutrient_operations.read"
    NUTRIENT_OPERATIONS_MANAGE = "nutrient_operations.manage"
    WATER_EXPOSURE_READ = "water_exposure.read"

    # PILOT-ASSET-001: Equipment Readiness / Critical Equipment Incidents.
    # Three tiers each, mirroring FARM_WORK_ITEM_READ/.MANAGE/.EXECUTE --
    # `.manage` (supervisory: release READY, maintenance transitions,
    # retire / assign owner, mark action-in-progress, resolve, close) is
    # deliberately separate from `.execute` (floor: record cleaning,
    # report damage, mark awaiting cleaning / open, acknowledge, link a
    # Work Item), for the identical reason PILOT-OPS-001 already
    # established: a role trusted to execute routine floor work should not
    # automatically gain supervisory release/closure authority.
    EQUIPMENT_READINESS_READ = "equipment_readiness.read"
    EQUIPMENT_READINESS_MANAGE = "equipment_readiness.manage"
    EQUIPMENT_READINESS_EXECUTE = "equipment_readiness.execute"
    EQUIPMENT_INCIDENT_READ = "equipment_incident.read"
    EQUIPMENT_INCIDENT_MANAGE = "equipment_incident.manage"
    EQUIPMENT_INCIDENT_EXECUTE = "equipment_incident.execute"

    # PILOT-PLAN-001A: Harvest Forecast / Capacity Planning. Two separate
    # pairs, deliberately not folded into PLANNING_READ/PLANNING_MANAGE --
    # a Batch harvest forecast is operational grower input (mirrors
    # HARVEST_MANAGE's own "who physically works the batch" distribution),
    # while a production capacity allocation is site-level planning
    # authority closer to PLANNING_MANAGE's own farm_manager/head_grower
    # ceiling. Never confused with HARVEST_MANAGE (an actual Harvest
    # command) or MOVEMENT_MANAGE (actual Occupancy).
    HARVEST_FORECAST_READ = "harvest_forecast.read"
    HARVEST_FORECAST_MANAGE = "harvest_forecast.manage"
    CAPACITY_PLAN_READ = "capacity_plan.read"
    CAPACITY_PLAN_MANAGE = "capacity_plan.manage"


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
        # STORE-INV-002A.1: farm_manager's own senior/accountable-correction
        # tier extends to existence adjustments, mirroring this role's
        # existing recall.manage precedent (docs/domain/
        # STORE_INVENTORY_MODEL.md §N) -- never inventory_receipt.manage or
        # inventory_quality.manage, which stay with the specialists who
        # execute routine receiving/quality work.
        Permission.INVENTORY_READ, Permission.INVENTORY_ADJUSTMENT_MANAGE,
        # STORE-INV-002B: farm_manager's senior/accountable tier also
        # extends to physical custody (Bin deactivation is LOCATION_MANAGE,
        # already held above; custody commands are their own permission).
        Permission.INVENTORY_CUSTODY_MANAGE,
        # STORE-INV-003: farm_manager's senior/accountable tier extends to
        # Reservation and Issue as well -- the same "day-to-day operational
        # execution" authority already granted for custody.
        Permission.INVENTORY_RESERVATION_MANAGE, Permission.INVENTORY_ISSUE_MANAGE,
        # STORE-INV-004: farm_manager's senior/accountable tier extends to
        # Consumption/Return/Scrap as well, same tier as Issue above.
        Permission.INVENTORY_CONSUMPTION_MANAGE, Permission.INVENTORY_RETURN_MANAGE,
        Permission.INVENTORY_SCRAP_MANAGE,
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
        Permission.GRADING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ, Permission.RECALL_MANAGE,
        Permission.TRACEABILITY_READ,
        # PLANNING-OPS-001: farm_manager has full planning authority
        # alongside its existing infrastructure/master-data ownership.
        Permission.PLANNING_READ, Permission.PLANNING_MANAGE,
        # PILOT-PLAN-001A: farm_manager gets planning/capacity visibility
        # AND capacity management (owns site-level production scheduling),
        # but not harvest_forecast.manage -- forecast entry stays with the
        # grower/supervisory roles who actually work the Batch.
        Permission.HARVEST_FORECAST_READ,
        Permission.CAPACITY_PLAN_READ, Permission.CAPACITY_PLAN_MANAGE,
        # PILOT-OPS-001: farm_manager creates/assigns/cancels Work Items
        # (supervisory oversight of "Today on the Farm") but does not
        # execute routine floor work itself.
        Permission.FARM_WORK_ITEM_READ, Permission.FARM_WORK_ITEM_MANAGE,
        # PILOT-AGRO-001: farm_manager owns protocol master data and Crop
        # Issue supervisory authority, same tier as its other master-data/
        # accountable-correction grants above -- no CROP_INSPECTION_MANAGE
        # (doesn't execute routine floor recording itself).
        Permission.GROWING_PROTOCOL_READ, Permission.GROWING_PROTOCOL_MANAGE,
        Permission.CROP_INSPECTION_READ, Permission.CROP_ISSUE_MANAGE,
        # PILOT-WATER-001A: farm_manager owns water/nutrient infrastructure
        # (topology, Sampling Points, Instruments/Calibration, Recipe
        # master data) and exposure review, same supervisory tier as its
        # GROWING_PROTOCOL_MANAGE grant above -- no floor-recording
        # authority (WATER_MEASUREMENT_MANAGE/NUTRIENT_OPERATIONS_MANAGE),
        # matching its existing "doesn't execute routine floor recording
        # itself" character.
        Permission.WATER_TOPOLOGY_READ, Permission.WATER_TOPOLOGY_MANAGE,
        Permission.SAMPLING_POINT_READ, Permission.SAMPLING_POINT_MANAGE,
        Permission.WATER_INSTRUMENT_READ, Permission.WATER_INSTRUMENT_MANAGE,
        Permission.NUTRIENT_RECIPE_READ, Permission.NUTRIENT_RECIPE_MANAGE,
        Permission.WATER_MEASUREMENT_READ, Permission.NUTRIENT_OPERATIONS_READ,
        Permission.WATER_EXPOSURE_READ,
        # PILOT-ASSET-001: farm_manager owns equipment readiness release/
        # maintenance/retirement authority and Incident supervisory
        # authority (assign/resolve/close), same infrastructure-owner tier
        # as its ASSET_MANAGE/CARRIER_MANAGE grant above -- no floor
        # execution authority (`.execute`), matching its "doesn't execute
        # routine floor work itself" character.
        Permission.EQUIPMENT_READINESS_READ, Permission.EQUIPMENT_READINESS_MANAGE,
        Permission.EQUIPMENT_INCIDENT_READ, Permission.EQUIPMENT_INCIDENT_MANAGE,
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
        # PLANNING-OPS-001: head_grower owns crop demand planning and the
        # Seeding Program, the same agronomic-planning tier as its existing
        # crop/workflow/batch-lifecycle authority above.
        Permission.PLANNING_READ, Permission.PLANNING_MANAGE,
        # PILOT-PLAN-001A: head_grower gets both forecast management (the
        # grower-owned harvest forecast) and production capacity planning
        # -- "forecast management + production capacity planning" is this
        # role's explicit ceiling for the new Planning domain.
        Permission.HARVEST_FORECAST_READ, Permission.HARVEST_FORECAST_MANAGE,
        Permission.CAPACITY_PLAN_READ, Permission.CAPACITY_PLAN_MANAGE,
        # PILOT-OPS-001: head_grower creates/assigns crop-care Work Items,
        # the same supervisory tier as farm_manager for this domain.
        Permission.FARM_WORK_ITEM_READ, Permission.FARM_WORK_ITEM_MANAGE,
        # PILOT-AGRO-001: head_grower owns Growing Protocol master data
        # (mirrors its CROP_MANAGE/WORKFLOW_MANAGE authority), records
        # Inspections (mirrors its OBSERVATION_ENTRY_MANAGE), and manages
        # Crop Issues (mirrors its HARVEST_MANAGE-tier agronomic authority).
        Permission.GROWING_PROTOCOL_READ, Permission.GROWING_PROTOCOL_MANAGE,
        Permission.CROP_INSPECTION_READ, Permission.CROP_INSPECTION_MANAGE, Permission.CROP_ISSUE_MANAGE,
        # PILOT-WATER-001A: head_grower owns water/nutrient infrastructure
        # and Recipe master data (mirrors its GROWING_PROTOCOL_MANAGE
        # authority above), and reviews exposure -- same tier as
        # farm_manager's identical grant.
        Permission.WATER_TOPOLOGY_READ, Permission.WATER_TOPOLOGY_MANAGE,
        Permission.SAMPLING_POINT_READ, Permission.SAMPLING_POINT_MANAGE,
        Permission.WATER_INSTRUMENT_READ, Permission.WATER_INSTRUMENT_MANAGE,
        Permission.NUTRIENT_RECIPE_READ, Permission.NUTRIENT_RECIPE_MANAGE,
        Permission.WATER_MEASUREMENT_READ, Permission.NUTRIENT_OPERATIONS_READ,
        Permission.WATER_EXPOSURE_READ,
        # PILOT-ASSET-001: read-only visibility -- head_grower has no
        # equipment-ownership role in this domain today (mirrors its
        # existing ASSET_READ-only, no ASSET_MANAGE, ceiling).
        Permission.EQUIPMENT_READINESS_READ, Permission.EQUIPMENT_INCIDENT_READ,
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
        # PLANNING-OPS-001: read-only visibility into the Seeding Program
        # (which plan line an execution-floor Sowing is meant to fulfill)
        # -- no planning.manage, matching this role's "no master-data
        # configuration" ceiling above.
        Permission.PLANNING_READ,
        # PILOT-PLAN-001A: production_supervisor records/revises the
        # operational harvest forecast input for batches it supervises,
        # but only reads capacity plans -- site-level capacity scheduling
        # stays with head_grower/farm_manager, matching this role's
        # existing "no master-data configuration" ceiling.
        Permission.HARVEST_FORECAST_READ, Permission.HARVEST_FORECAST_MANAGE,
        Permission.CAPACITY_PLAN_READ,
        # PILOT-OPS-001: production_supervisor both creates/assigns Work
        # Items (floor oversight) and executes them -- the same "does the
        # same transactional commands operators perform, plus supervisory
        # authority" character as its other grants above.
        Permission.FARM_WORK_ITEM_READ, Permission.FARM_WORK_ITEM_MANAGE, Permission.FARM_WORK_ITEM_EXECUTE,
        # PILOT-AGRO-001: production_supervisor records Inspections (same
        # tier as OBSERVATION_ENTRY_MANAGE) and manages Crop Issues (floor
        # oversight, same supervisory character as its other grants) -- no
        # GROWING_PROTOCOL_MANAGE (no master-data configuration authority,
        # matching this role's existing ceiling).
        Permission.GROWING_PROTOCOL_READ, Permission.CROP_INSPECTION_READ, Permission.CROP_INSPECTION_MANAGE,
        Permission.CROP_ISSUE_MANAGE,
        # PILOT-WATER-001A: production_supervisor performs the same
        # floor-recording commands as operator (measurements, mix/
        # reservoir/delivery events) plus supervisory oversight (exposure
        # review, mirroring its CROP_ISSUE_MANAGE character) -- no
        # topology/Sampling-Point/Instrument/Recipe MASTER-DATA authority,
        # matching this role's existing "no master-data configuration"
        # ceiling.
        Permission.WATER_TOPOLOGY_READ, Permission.SAMPLING_POINT_READ, Permission.WATER_INSTRUMENT_READ,
        Permission.NUTRIENT_RECIPE_READ,
        Permission.WATER_MEASUREMENT_READ, Permission.WATER_MEASUREMENT_MANAGE,
        Permission.NUTRIENT_OPERATIONS_READ, Permission.NUTRIENT_OPERATIONS_MANAGE,
        Permission.WATER_EXPOSURE_READ,
        # PILOT-ASSET-001: production_supervisor both creates/releases
        # equipment readiness and manages Incidents (floor oversight) AND
        # executes the floor-level commands (record cleaning, report
        # damage/incidents) -- the same "does the same transactional
        # commands operators perform, plus supervisory authority" character
        # as its FARM_WORK_ITEM_READ/.MANAGE/.EXECUTE triple grant above.
        Permission.EQUIPMENT_READINESS_READ, Permission.EQUIPMENT_READINESS_MANAGE,
        Permission.EQUIPMENT_READINESS_EXECUTE,
        Permission.EQUIPMENT_INCIDENT_READ, Permission.EQUIPMENT_INCIDENT_MANAGE,
        Permission.EQUIPMENT_INCIDENT_EXECUTE,
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
        # PILOT-OPS-001: operator executes assigned/available floor Work
        # Items (start/block/unblock/complete) -- no create/assign/cancel
        # authority, matching this role's "restricted transactional
        # execution only" ceiling.
        Permission.FARM_WORK_ITEM_READ, Permission.FARM_WORK_ITEM_EXECUTE,
        # PILOT-AGRO-001: operator views the current protocol and records
        # permitted Inspections (section 19) -- no protocol master-data or
        # Crop Issue supervisory authority.
        Permission.GROWING_PROTOCOL_READ, Permission.CROP_INSPECTION_READ, Permission.CROP_INSPECTION_MANAGE,
        # PILOT-WATER-001A section 24: operator reads water topology and
        # records permitted measurements/mix/reservoir/delivery events --
        # no topology/Sampling-Point/Instrument/Recipe MANAGE authority
        # (registering infrastructure, calibrating instruments, and
        # drafting/activating Recipes are grower/supervisory, per the
        # ticket's own explicit split), matching this role's "restricted
        # transactional execution only" ceiling.
        Permission.WATER_TOPOLOGY_READ, Permission.SAMPLING_POINT_READ, Permission.WATER_INSTRUMENT_READ,
        Permission.NUTRIENT_RECIPE_READ,
        Permission.WATER_MEASUREMENT_READ, Permission.WATER_MEASUREMENT_MANAGE,
        Permission.NUTRIENT_OPERATIONS_READ, Permission.NUTRIENT_OPERATIONS_MANAGE,
        # PILOT-ASSET-001: operator records cleaning, reports damage/
        # incidents, and marks equipment awaiting cleaning -- no release/
        # maintenance/retire/resolve/close authority, matching this role's
        # "restricted transactional execution only" ceiling.
        Permission.EQUIPMENT_READINESS_READ, Permission.EQUIPMENT_READINESS_EXECUTE,
        Permission.EQUIPMENT_INCIDENT_READ, Permission.EQUIPMENT_INCIDENT_EXECUTE,
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
        # STORE-INV-002A.1: the first genuinely operational Store &
        # Inventory authority this role receives -- receiving stock only,
        # never adjustment or quality (docs/domain/STORE_INVENTORY_MODEL.md
        # §N), matching this role's existing narrow "one genuine function"
        # characterization.
        Permission.INVENTORY_READ, Permission.INVENTORY_RECEIPT_MANAGE,
        # STORE-INV-002B: putaway/transfer is the routine "where does it
        # physically sit" custody work this role executes day-to-day --
        # never inventory_quality.manage, which stays with the QC
        # specialist.
        Permission.INVENTORY_CUSTODY_MANAGE,
        # STORE-INV-003: reserving stock for planned use and issuing it to
        # farm operations are this role's own routine day-to-day execution
        # work, same tier as receiving/custody above.
        Permission.INVENTORY_RESERVATION_MANAGE, Permission.INVENTORY_ISSUE_MANAGE,
        # STORE-INV-004: recording what comes back (Return), what is
        # disposed of (Scrap), and what was actually consumed by operations
        # are this role's own routine day-to-day execution work too --
        # same tier as Issue above.
        Permission.INVENTORY_RETURN_MANAGE, Permission.INVENTORY_SCRAP_MANAGE,
        Permission.INVENTORY_CONSUMPTION_MANAGE,
        # PILOT-OPS-001: storekeeper executes its own store/cleaning/
        # putaway Work Items -- same routine execution tier as its other
        # grants above.
        Permission.FARM_WORK_ITEM_READ, Permission.FARM_WORK_ITEM_EXECUTE,
        # PILOT-ASSET-001: read-only visibility -- equipment
        # registration/readiness release remains centralized under
        # farm_manager/production_supervisor, matching this role's
        # existing narrow "one genuine function" characterization.
        Permission.EQUIPMENT_READINESS_READ, Permission.EQUIPMENT_INCIDENT_READ,
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
        # STORE-INV-002A.2: qc_officer's own genuinely operational Store &
        # Inventory authority -- visibility into existence/receipts/lots
        # plus the quality-disposition workflow itself. Deliberately never
        # inventory_receipt.manage/inventory_adjustment.manage, which stay
        # with the specialists who execute routine receiving/correction
        # work (docs/domain/STORE_INVENTORY_MODEL.md §N).
        Permission.INVENTORY_READ, Permission.INVENTORY_QUALITY_MANAGE,
        Permission.CROP_READ,
        Permission.CROP_BATCH_READ,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ,
        Permission.TRANSPLANT_READ,
        Permission.OBSERVATION_READ, Permission.OBSERVATION_ENTRY_MANAGE,
        Permission.QUALITY_HOLD_READ, Permission.QUALITY_HOLD_MANAGE,
        Permission.HARVEST_READ,
        Permission.PACKING_READ,
        Permission.GRADING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
        # PILOT-OPS-001: qc_officer executes its own quality Work Items --
        # same routine execution tier as its other grants above.
        Permission.FARM_WORK_ITEM_READ, Permission.FARM_WORK_ITEM_EXECUTE,
        # PILOT-AGRO-001: qc_officer records Inspections (same tier as
        # OBSERVATION_ENTRY_MANAGE) and manages Crop Issues -- diagnosis
        # confirmation and resolution fit this role's existing quality-
        # investigation authority (QUALITY_HOLD_MANAGE) exactly.
        Permission.GROWING_PROTOCOL_READ, Permission.CROP_INSPECTION_READ, Permission.CROP_INSPECTION_MANAGE,
        Permission.CROP_ISSUE_MANAGE,
        # PILOT-WATER-001A: qc_officer reviews water/nutrient facts and
        # exposure for root-cause investigation (mirrors its existing
        # TRACEABILITY_READ grant) -- read-only, no floor-recording or
        # master-data authority, matching its "no recall.manage" restraint
        # elsewhere in this role.
        Permission.WATER_TOPOLOGY_READ, Permission.SAMPLING_POINT_READ, Permission.WATER_INSTRUMENT_READ,
        Permission.NUTRIENT_RECIPE_READ, Permission.WATER_MEASUREMENT_READ, Permission.NUTRIENT_OPERATIONS_READ,
        Permission.WATER_EXPOSURE_READ,
        # PILOT-ASSET-001: read-only visibility for root-cause
        # investigation (mirrors its existing TRACEABILITY_READ/
        # WATER_EXPOSURE_READ character) -- no floor-recording or
        # supervisory authority.
        Permission.EQUIPMENT_READINESS_READ, Permission.EQUIPMENT_INCIDENT_READ,
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
        Permission.GRADING_READ, Permission.GRADING_MANAGE,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
        # PILOT-OPS-001: packing_supervisor executes its own post-harvest
        # Work Items -- same routine execution tier as its other grants
        # above.
        Permission.FARM_WORK_ITEM_READ, Permission.FARM_WORK_ITEM_EXECUTE,
        # PILOT-ASSET-001: packing_supervisor records cleaning/reports
        # damage/incidents on its own stage's equipment -- same routine
        # execution tier as its FARM_WORK_ITEM_EXECUTE grant above; no
        # release/maintenance/retire/resolve/close authority.
        Permission.EQUIPMENT_READINESS_READ, Permission.EQUIPMENT_READINESS_EXECUTE,
        Permission.EQUIPMENT_INCIDENT_READ, Permission.EQUIPMENT_INCIDENT_EXECUTE,
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
        Permission.GRADING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ, Permission.FINISHED_GOODS_STORAGE_MANAGE,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
        # PILOT-OPS-001: cold_store_supervisor executes its own store Work
        # Items -- same routine execution tier as its other grants above.
        Permission.FARM_WORK_ITEM_READ, Permission.FARM_WORK_ITEM_EXECUTE,
        # PILOT-ASSET-001: cold_store_supervisor records cleaning/reports
        # damage/incidents on its own stage's equipment (e.g. a cold-store
        # cooling problem) -- same routine execution tier as its
        # FARM_WORK_ITEM_EXECUTE grant above.
        Permission.EQUIPMENT_READINESS_READ, Permission.EQUIPMENT_READINESS_EXECUTE,
        Permission.EQUIPMENT_INCIDENT_READ, Permission.EQUIPMENT_INCIDENT_EXECUTE,
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
        Permission.GRADING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ, Permission.DISPATCH_MANAGE,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
        # PILOT-OPS-001: dispatch_officer executes its own dispatch Work
        # Items -- same routine execution tier as its other grants above.
        Permission.FARM_WORK_ITEM_READ, Permission.FARM_WORK_ITEM_EXECUTE,
        # PILOT-ASSET-001: dispatch_officer records cleaning/reports
        # damage/incidents on its own stage's equipment -- same routine
        # execution tier as its FARM_WORK_ITEM_EXECUTE grant above.
        Permission.EQUIPMENT_READINESS_READ, Permission.EQUIPMENT_READINESS_EXECUTE,
        Permission.EQUIPMENT_INCIDENT_READ, Permission.EQUIPMENT_INCIDENT_EXECUTE,
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
        Permission.GRADING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
        # PLANNING-OPS-001: broad read visibility extends to the Planning
        # module too, matching this role's "every `.read` permission"
        # character -- zero `.manage`.
        Permission.PLANNING_READ,
        # PILOT-PLAN-001A: identical "every `.read`, zero `.manage`"
        # extension to Harvest Forecast / Capacity Planning.
        Permission.HARVEST_FORECAST_READ, Permission.CAPACITY_PLAN_READ,
        # PILOT-OPS-001: read-only visibility into Work Items, matching
        # this role's "every `.read` permission, zero mutations" character.
        Permission.FARM_WORK_ITEM_READ,
        # PILOT-AGRO-001: identical "every .read, zero mutations" character.
        Permission.GROWING_PROTOCOL_READ, Permission.CROP_INSPECTION_READ,
        # PILOT-WATER-001A: identical "every .read, zero mutations"
        # character, including exposure review.
        Permission.WATER_TOPOLOGY_READ, Permission.SAMPLING_POINT_READ, Permission.WATER_INSTRUMENT_READ,
        Permission.NUTRIENT_RECIPE_READ, Permission.WATER_MEASUREMENT_READ, Permission.NUTRIENT_OPERATIONS_READ,
        Permission.WATER_EXPOSURE_READ,
        # PILOT-ASSET-001: identical "every .read, zero mutations"
        # character.
        Permission.EQUIPMENT_READINESS_READ, Permission.EQUIPMENT_INCIDENT_READ,
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
        Permission.GRADING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
        # PLANNING-OPS-001: identical to `auditor`'s own addition above, by
        # the same "zero mutations" design.
        Permission.PLANNING_READ,
        # PILOT-PLAN-001A: identical to `auditor`'s own addition above.
        Permission.HARVEST_FORECAST_READ, Permission.CAPACITY_PLAN_READ,
        # PILOT-OPS-001: identical to `auditor`'s own addition above, by
        # the same "zero mutations" design.
        Permission.FARM_WORK_ITEM_READ,
        # PILOT-AGRO-001: identical to `auditor`'s own addition above.
        Permission.GROWING_PROTOCOL_READ, Permission.CROP_INSPECTION_READ,
        # PILOT-WATER-001A: identical to `auditor`'s own addition above.
        Permission.WATER_TOPOLOGY_READ, Permission.SAMPLING_POINT_READ, Permission.WATER_INSTRUMENT_READ,
        Permission.NUTRIENT_RECIPE_READ, Permission.WATER_MEASUREMENT_READ, Permission.NUTRIENT_OPERATIONS_READ,
        Permission.WATER_EXPOSURE_READ,
        # PILOT-ASSET-001: identical to `auditor`'s own addition above.
        Permission.EQUIPMENT_READINESS_READ, Permission.EQUIPMENT_INCIDENT_READ,
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
