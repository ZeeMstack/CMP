# Role / Permission Policy Proposal (AUTHZ-002A, challenge-reviewed AUTHZ-002A.1/A.2)

**Status: PROPOSAL — not implemented.** `app.core.permissions.Permission` and `ROLE_PERMISSIONS` remain unchanged (`tenant_admin` → all permissions; every other role → empty set) until a follow-up ticket is explicitly authorized to implement this design. This document is the product-policy design and review artifact only.

**Revision note (AUTHZ-002A.1):** this version supersedes the single-matrix AUTHZ-002A draft after a challenge review. Material changes: (1) a previously-unaudited farm-scope architecture gap was found and is now the headline finding; (2) `farm_manager`'s grant set was tightened (harvest/packing/finished-goods-storage `.manage` removed; dispatch `.manage` demoted to an optional "broader pilot" grant); (3) `storekeeper` was tightened (asset/carrier `.manage` removed as unjustified); (4) the design is now split into two separate matrices (Imperial Pilot vs. External Commercial V1) instead of one; (5) `observation.manage` for `operator` is now explicitly marked **BLOCKED**, not "SOP-compensated."

**Revision note (AUTHZ-002A.2):** AUTHZ-002A.1 correctly identified `observation.manage` as a P0 granularity problem for `operator`, but inconsistently still showed it granted to `production_supervisor` and `qc_officer` in the *current implementable* matrix. This revision applies the same "does this role need entry, definition, or both?" test to **every** role that touched `observation.manage`, not just `operator`. Result: under the current, unsplit permission, only `head_grower` (and `tenant_admin`) can safely receive it — `production_supervisor` and `qc_officer` are now also marked **BLOCKED** in the current-implementable matrix (§5A, §12). A separate **POST-P0-SPLIT DESIRED** table/matrix is added showing the intended per-role authority once entry and definition are split, which must not be conflated with what can be granted today. See §5A for the full reconciliation.

Full architecture/enforcement background: `docs/domain/AUTHORIZATION_MODEL.md`.

---

## 0. Baseline reference: role inventory, permission catalog, responsibilities, inverse view

### 0.A. Definitive role inventory

Source of truth: `app.models.membership.APPROVED_ROLE_CODES` (a `frozenset`, also enforced at the database layer via `ck_tenant_memberships_role_code_allowed`). Exactly **12** approved role codes.

| `role_code` | Where defined/validated | Docs describing authority | Test precedent | Operational purpose |
|---|---|---|---|---|
| `tenant_admin` | `APPROVED_ROLE_CODES`; DB check constraint; `app/schemas/membership.py` field validator | `AUTHORIZATION_MODEL.md` ("all permissions") | Extensive — every domain test's default actor | Clear: tenant superuser |
| `farm_manager` | same | name only (`CMP_MASTER_SPEC.md` §11: "facility manager") | `test_auth_me.py` (identity/display only) | Clear in outline, defined by this document |
| `head_grower` | same | name only | `test_authz_read_enforcement_http.py` (zero-permission negative-test role) | Clear in outline, defined by this document |
| `production_supervisor` | same | name only ("supervisor") | none beyond role-catalog fixtures | Clear in outline, defined by this document |
| `operator` | same | name only | `test_auth_context.py`, `test_auth_me.py`, `test_membership.py` (identity/tenant-context mechanics only) | Clear in outline, defined by this document |
| `storekeeper` | same | name only | none beyond role-catalog fixtures | Partially blocked — see §7 |
| `qc_officer` | same | name only ("QC") | `test_auth_context.py` | Clear in outline, defined by this document |
| `auditor` | same | name only | none beyond role-catalog fixtures | Technically identical to `read_only` today — see §9 |
| `packing_supervisor` | same | name only ("packing... users") | none beyond role-catalog fixtures | Clear in outline, defined by this document |
| `cold_store_supervisor` | same | name only ("cold-store... users") | none beyond role-catalog fixtures | Clear in outline, defined by this document |
| `dispatch_officer` | same | name only ("dispatch... users") | none beyond role-catalog fixtures | Clear in outline, defined by this document |
| `read_only` | same | name only ("read-only management") | `test_auth_me.py`, `test_authz_read_enforcement_http.py` | Technically identical to `auditor` today — see §9 |

No test anywhere asserts a *behavioral* expectation for any non-admin role beyond "this is a valid, authenticatable `role_code`."

### 0.B. Full 41-permission inventory (plain-language)

| Permission | Plain-language meaning |
|---|---|
| `farm.read` | View farm(s) and their basic info |
| `farm.manage` | Create/configure a farm |
| `location.read` | View the greenhouse/farm location hierarchy (tree, path, occupancy, subtree occupancy) |
| `location.manage` | Create/configure locations (zones, spans, tables, positions), including bulk generation |
| `asset.read` | View mobile assets (trolleys, racks) and their positions |
| `asset.manage` | Register an asset; generate its positions (shelves/slots) |
| `carrier.read` | View crop carriers (trays, gutters, bags) |
| `carrier.manage` | Register a carrier, individually or in bulk |
| `movement.manage` | Execute an occupancy-relocation command (place/move/remove an asset or carrier) — no standalone read tier; history is read via `asset.read`/`carrier.read` |
| `crop.read` | View the crop/variety catalog |
| `crop.manage` | Create a crop or variety |
| `production_system.read` | View the production-system catalog (e.g. NFT, DWC) |
| `production_system.manage` | Create a production system |
| `workflow.read` | View crop workflows, versions, stages, transitions |
| `workflow.manage` | Create a workflow, draft a version, add stages/transitions, publish a version |
| `crop_batch.read` | View crop batches, current stage, stage history |
| `crop_batch.manage` | Create a batch; execute a stage transition |
| `batch_derivation.read` | View split/merge lineage |
| `batch_derivation.manage` | Execute a batch split or merge |
| `seed_lot.read` | View seed-lot inventory |
| `seed_lot.manage` | Register a seed lot (the one true "input receiving" action in the current catalog) |
| `sowing.read` | View sowing events / carrier batch assignments |
| `sowing.manage` | Execute a sowing event |
| `transplant.read` | View transplant events |
| `transplant.manage` | Execute a transplant (carrier release + reassignment) |
| `observation.read` | View recorded observations and observation definitions |
| `observation.manage` | Record an observation **or** create a new observation definition (bundled — see §5A) |
| `quality_hold.read` | View quality holds on a batch |
| `quality_hold.manage` | Place **or** release a quality hold (bundled — current unified policy, see §6) |
| `harvest.read` | View harvest events / harvested produce lots (incl. ledger/balance) |
| `harvest.manage` | Record a harvest event |
| `packing.read` | View packing events / finished-goods lots (incl. ledger/balance) |
| `packing.manage` | Record a packing event |
| `finished_goods_storage.read` | View storage placements/movements/location inventory |
| `finished_goods_storage.manage` | Execute a finished-goods storage movement |
| `dispatch.read` | View dispatch events |
| `dispatch.manage` | Record a dispatch event (goods leave the farm) |
| `recall.read` | View recall cases |
| `recall.manage` | Open **or** close a recall case (bundled — current unified policy, see §10) |
| `traceability.read` | Trace a lot forward/backward — pure read, no mutation endpoint exists at all |
| `tenant.members.manage` | Add a tenant membership — no `GET /memberships` exists today |

### 0.C. Responsibility statement per role

- **tenant_admin** — Tenant-wide superuser. All 41 permissions. Distinguished from `farm_manager` by SaaS-level authority (tenant membership administration) that `farm_manager` never receives.
- **farm_manager** — Site general manager: owns physical/infrastructure setup (farm, location, asset, carrier), full read visibility everywhere, and the senior escalation action (`recall.manage`) plus (in the broader-pilot tier only) dispatch backup authority. Does **not** routinely execute specialist harvest/packing/storage work, does **not** hold agronomic master-data authority, and does **not** administer tenant membership.
- **head_grower** — Agronomic planning and crop-batch-of-record authority: crop/production-system/workflow master data, observation-definition configuration, crop batch lifecycle (creation, stage transitions, splits/merges), and harvest as the conclusion of the batches they own. Not finance/admin/dispatch/QC-independent authority.
- **production_supervisor** — Execution oversight of the production floor: the same transactional actions operators perform, plus supervisory-level actions operators should not have unilaterally (crop batch creation/stage transitions, splits/merges). Not master-data configuration (including observation definitions — see §5A), not QC, not post-harvest chain.
- **operator** — Restricted transactional execution: sowing, transplant, movement, harvest recording — routine, single-purpose commands only. No planning, no configuration, no quality/compliance authority. Observation recording is currently **blocked** — see §5/§5A.
- **storekeeper** — Input/equipment receiving: currently limited to seed lots (its one genuine function) plus passive context visibility. Not asset/carrier registration (that remains `farm_manager`'s infrastructure authority — see §7).
- **qc_officer** — Quality authority: observation entry (not definition — see §5A), quality holds (place and release, under the current unified policy), and cross-chain read visibility (production, harvest, packing, storage, dispatch, recall) for root-cause investigation. Not production execution, not master-data configuration, not final recall authority.
- **packing_supervisor** — Packing execution: `packing.manage`, upstream `harvest.read`, downstream `finished_goods_storage.read`, plus hold/recall/traceability visibility. Not storage or dispatch manage.
- **cold_store_supervisor** — Finished-goods storage execution: `finished_goods_storage.manage`, upstream `packing.read`, downstream `dispatch.read`, plus hold/recall/traceability visibility. Not packing or dispatch manage.
- **dispatch_officer** — Dispatch execution: `dispatch.manage`, upstream `finished_goods_storage.read`/`packing.read`, plus hold/recall/traceability visibility. Not packing or storage manage.
- **auditor** — Intended as broad compliance/traceability visibility, potentially broader than `read_only`. Under the current catalog, technically identical to `read_only` — see §9.
- **read_only** — Broad operational visibility (all 20 `*.read` permissions), zero mutations.

### 0.D. Inverse view — role → granted permissions (CURRENT IMPLEMENTABLE, Matrix A, mechanically verified against §12)

- **tenant_admin (41)** — all.
- **farm_manager (25 minimum / 26 broader-pilot)** — farm.read/manage, location.read/manage, asset.read/manage, carrier.read/manage, crop.read, production_system.read, workflow.read, crop_batch.read, batch_derivation.read, seed_lot.read, sowing.read, transplant.read, observation.read, quality_hold.read, harvest.read, packing.read, finished_goods_storage.read, dispatch.read, recall.read/manage, traceability.read + `dispatch.manage` (broader-pilot tier only).
- **head_grower (24)** — farm.read, location.read, asset.read, carrier.read, crop.read/manage, production_system.read/manage, workflow.read/manage, crop_batch.read/manage, batch_derivation.read/manage, seed_lot.read, sowing.read, transplant.read, observation.read/manage, quality_hold.read, harvest.read/manage, recall.read, traceability.read.
- **production_supervisor (23)** — farm.read, location.read, asset.read, carrier.read, crop.read, production_system.read, workflow.read, crop_batch.read/manage, batch_derivation.read/manage, seed_lot.read, sowing.read/manage, transplant.read/manage, movement.manage, observation.read (**not** manage — BLOCKED, §5A), quality_hold.read, harvest.read/manage, recall.read, traceability.read.
- **operator (15)** — farm.read, location.read, asset.read, carrier.read, crop_batch.read, seed_lot.read, sowing.read/manage, transplant.read/manage, movement.manage, observation.read (**not** manage — BLOCKED), quality_hold.read, harvest.read/manage.
- **storekeeper (6)** — farm.read, location.read, asset.read, carrier.read, seed_lot.read/manage.
- **qc_officer (18)** — farm.read, location.read, asset.read, carrier.read, crop.read, crop_batch.read, seed_lot.read, sowing.read, transplant.read, observation.read (**not** manage — BLOCKED, §5A), quality_hold.read/manage, harvest.read, packing.read, finished_goods_storage.read, dispatch.read, recall.read, traceability.read.
- **packing_supervisor (12)** — farm.read, location.read, asset.read, carrier.read, crop_batch.read, harvest.read, packing.read/manage, finished_goods_storage.read, quality_hold.read, recall.read, traceability.read.
- **cold_store_supervisor (11)** — farm.read, location.read, asset.read, carrier.read, packing.read, finished_goods_storage.read/manage, dispatch.read, quality_hold.read, recall.read, traceability.read.
- **dispatch_officer (11)** — farm.read, location.read, asset.read, carrier.read, packing.read, finished_goods_storage.read, dispatch.read/manage, quality_hold.read, recall.read, traceability.read.
- **auditor (20)** — all 20 `*.read`/`traceability.read` permissions. Identical to `read_only` — see §9.
- **read_only (20)** — all 20 `*.read`/`traceability.read` permissions.

---

## 1. Farm-scope architecture gap (headline finding)

**Traced directly from source, not inferred.**

- `app.core.auth.TenantContext` (the only object `require_permission`/`has_permission` ever consult) has exactly three fields: `tenant_id`, `user_id`, `role_code`. No `farm_id`.
- `app.models.membership.TenantMembership` has exactly `tenant_id`, `user_id`, `status`, `role_code`. No `farm_id` column; no separate user↔farm or role↔farm assignment table exists anywhere in `app/models/` (confirmed by grep across every model file).
- Every service function that accepts a `farm_id` (e.g. `crop_batch_service`, `asset_service`, `batch_derivation_service`, all following the same `_require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)` pattern) only verifies the farm **exists and belongs to the caller's tenant and is active** — via `farm_service.get_farm(db, tenant_id=..., farm_id=...)`, the same tenant-isolation + 404-concealment pattern used everywhere else. This is a *tenant-isolation* check, not a *role/permission* check, and it never consults `role_code`.
- `app.core.permissions.require_permission`/`has_permission` never receive or examine `farm_id` at all.

**Explicit answer to the ticket's scenario**: if Tenant X contains Farm A, Farm B, and Farm C, and Zeeshan has `role_code = farm_manager` in Tenant X, the current model **cannot** distinguish "manager of Farm A only" from "manager of every farm in Tenant X." `role_code` is a pure tenant-wide grant. Once a `TenantMembership` exists with a given role, that role's full permission set applies identically to every farm the tenant owns — there is no code path capable of restricting it to a subset.

**Classification and priority**:

| Deployment shape | Is this a real gap? | Priority |
|---|---|---|
| Imperial single-farm pilot | No practical impact — tenant-wide role *is* farm-wide role when the tenant owns exactly one farm | **P2** |
| Multi-farm Imperial deployment (Imperial adds a second site) | Real gap the moment more than one farm exists and staff should be restricted to their own site | **P1** |
| External multi-farm SaaS customer | Hard blocker — a `farm_manager` (or any operational role) at that customer's Farm A would, with zero technical restriction, also hold full authority over that customer's Farm B/C. This is a genuine access-control failure for any multi-site paying customer, not a cosmetic gap | **P0** |

**Not implemented here** — per instruction, no farm-scoped authorization is added. This is recorded as a formal policy/architecture gap (also folded into §13's revised priority list) and factored into Matrix B (§12): any external customer operating more than one farm must not be onboarded with the current tenant-wide-only model without this being explicitly accepted as a known risk, worked around operationally (e.g. one CMP tenant per farm — itself a real, available mitigation given CMP is already multi-tenant), or fixed first.

---

## 2. All non-admin `*.manage` grants (compact review surface)

All 21 `.manage` permissions × 11 non-admin roles. Only `G` cells shown with justification; every blank cell is a deliberate deny. Reflects the **revised** (post-challenge) grants — see §3 and §7 for what changed and why.

| Permission | FM | HG | PS | OP | SK | QC | AU | PK | CS | DO | RO |
|---|---|---|---|---|---|---|---|---|---|---|---|
| farm.manage | G — owns their site's basic configuration | | | | | | | | | | |
| location.manage | G — owns physical layout/structure of their site | | | | | | | | | | |
| asset.manage | G — owns equipment setup for their site | | | | | | | | | | |
| carrier.manage | G — owns carrier-fleet setup for their site | | | | | | | | | | |
| movement.manage | | | G — supervises/executes floor relocation | G — routine execution of an assigned move | | | | | | | |
| crop.manage | | G — owns the crop/variety catalog (agronomic master data) | | | | | | | | | |
| production_system.manage | | G — owns the production-system catalog | | | | | | | | | |
| workflow.manage | | G — designs the stage/transition graph production executes against | | | | | | | | | |
| crop_batch.manage | | G — initiates/plans batches, approves stage transitions | G — executes routine stage transitions under an existing batch | | | | | | | | |
| batch_derivation.manage | | G — approves significant lineage-changing splits/merges | G — executes an approved split/merge | | | | | | | | |
| seed_lot.manage | | | | | G — the one genuine input-receiving function this role exists for | | | | | | |
| sowing.manage | | | G — supervises/executes | G — routine execution of an assigned sowing | | | | | | | |
| transplant.manage | | | G — supervises/executes | G — routine execution of an assigned transplant | | | | | | | |
| observation.manage | | G — genuinely needs both entry and definition authority; safe to grant the unsplit permission (see §5A) | **BLOCKED — see §5A** (needs entry only; unsplit grant would over-grant definition authority) | **BLOCKED — see §5** | | **BLOCKED — see §5A** (needs entry only; definitions can't be safely scoped to "QC-specific," see §5A/§4) | | | | | |
| quality_hold.manage | | | | | | G — QC's core function; place/release kept unified per current policy (see §6) | | | | | |
| harvest.manage | | G — natural conclusion of the batch lifecycle they own | G — supervises/executes | G — routine recording of an assigned harvest | | | | | | | |
| packing.manage | | | | | | | | G — owns packing execution for their stage | | | |
| finished_goods_storage.manage | | | | | | | | | G — owns storage execution for their stage | | |
| dispatch.manage | *(G in "broader pilot" tier only — see §3)* | | | | | | | | | G — owns dispatch execution for their stage | |
| recall.manage | G — senior escalation authority; see §10 | | | | | | | | | | |
| tenant.members.manage | | | | | | | | | | | |

`farm_manager`'s `harvest.manage`, `packing.manage`, `finished_goods_storage.manage` are **removed** from this revision (see §3) — a farm manager can see everything (`*.read`) but does not need to personally execute what packing/cold-store/production specialists already own.

---

## 3. Challenge: farm_manager (29 → revised)

**Original 29**: farm.read/manage, location.read/manage, asset.read/manage, carrier.read/manage, crop.read, production_system.read, workflow.read, crop_batch.read, batch_derivation.read, seed_lot.read, sowing.read, transplant.read, observation.read, quality_hold.read, harvest.read/**manage**, packing.read/**manage**, finished_goods_storage.read/**manage**, dispatch.read/**manage**, recall.read/manage, traceability.read.

Applying "does a normal farm manager need to execute this directly, or merely see/supervise?" to every `.manage` grant:

| Permission | Verdict | Reasoning |
|---|---|---|
| tenant.members.manage | Already DENY | SaaS account administration, not a farm-operations action (unchanged from AUTHZ-002A) |
| quality_hold.manage | Already DENY | QC independence (unchanged) |
| recall.manage | **KEEP** | Not routine execution — a rare, senior, accountable escalation decision that structurally belongs at this level; "supervise from a distance" isn't meaningful for an action this consequential |
| packing.manage | **REMOVE** | Packing execution belongs to `packing_supervisor`; a farm manager overseeing does not need to personally record a packing event |
| finished_goods_storage.manage | **REMOVE** | Same reasoning — `cold_store_supervisor`'s job |
| dispatch.manage | **DEMOTE** to "broader pilot" tier only | Borderline: dispatch is the highest-stakes single-action point in the commercial chain after recall (goods/custody leave the farm) and a small pilot team may need FM as backup when `dispatch_officer` is unavailable — but it is not clearly *necessary*, unlike recall |
| workflow.manage | Already DENY | Head Grower's agronomic-configuration domain (unchanged) |
| crop.manage | Already DENY | Head Grower's domain (unchanged) |
| production_system.manage | Already DENY | Head Grower's domain (unchanged) |
| observation.manage | Already DENY | Delegated to Head Grower only (revised, §5A) — Production Supervisor and QC are themselves BLOCKED from it pending the entry/definition split |
| harvest.manage | **REMOVE** | Execution belongs to Head Grower/Production Supervisor/Operator, who are the people physically harvesting |
| farm.manage / location.manage / asset.manage / carrier.manage | **KEEP** | Not on the ticket's "especially strict" list; infrastructure/site setup is the one area where "farm manager" as a job title clearly implies direct configuration authority |

### A. Minimum viable farm_manager (25)
All 20 `*.read` permissions + `farm.manage`, `location.manage`, `asset.manage`, `carrier.manage`, `recall.manage`.

### B. Broader pilot farm_manager (26)
Minimum viable (25) + `dispatch.manage` (backup/escalation authority for a small team where `dispatch_officer` coverage may be thin).

**Delta from the original 29**: −4 (`harvest.manage`, `packing.manage`, `finished_goods_storage.manage` removed entirely; `dispatch.manage` moved from unconditional to broader-tier-only). The farm manager retains full visibility everywhere and full infrastructure authority, but no longer personally executes any post-harvest production step — those stay with the specialists who own them.

---

## 4. Challenge: head_grower (24) vs. production_supervisor (23)

**AUTHZ-002A.3 mechanical-reconciliation correction**: prior revisions of this section undercounted `head_grower` at 23 and misclassified `recall.read` as production-supervisor-only. Both counts and the shared/unique breakdown below are corrected against Matrix A (§12), the authoritative grid, verified by direct parsing rather than manual counting.

The raw count is a **misleading proxy for seniority** — permission count ≠ authority weight regardless of the exact numbers. Diffing the two sets (updated per §5A: `production_supervisor` no longer receives `observation.manage`):

- **Only head_grower has (4)**: `crop.manage`, `production_system.manage`, `workflow.manage`, `observation.manage` — foundational, tenant/farm-wide **master-data/configuration** authority: head_grower literally defines the crop catalog, the stage/transition graph (`workflow.manage`) that `production_supervisor`'s own `crop_batch.manage` (stage transitions) must operate within, and — since AUTHZ-002A.2 (§5A) — what observation types can be recorded at all.
- **Only production_supervisor has (3)**: `movement.manage`, `sowing.manage`, `transplant.manage` — routine, high-frequency, narrowly-scoped floor-execution commands. (`recall.read` is **not** unique to production_supervisor — corrected below; both roles have it.)
- **Shared (20)**: farm.read, location.read, asset.read, carrier.read, crop.read, production_system.read, workflow.read, crop_batch.read/manage, batch_derivation.read/manage, seed_lot.read, sowing.read, transplant.read, observation.read, quality_hold.read, harvest.read/manage, **recall.read**, traceability.read.

**Net: head_grower = 4(only) + 20(shared) = 24. production_supervisor = 3(only) + 20(shared) = 23.** Head Grower now leads Production Supervisor by exactly one permission — not tied, not inverted, and consistent with (rather than merely not contradicting) the intended seniority ordering. The qualitative hierarchy argument below holds independently of the exact count and would hold regardless of which way this correction landed — permission count was never the right lens, but it's worth getting right regardless.

**Pilot-team practicality note**: `TenantMembership` enforces exactly one active role per `(tenant_id, user_id)` (`ux_tenant_memberships_active_tenant_user`, a partial unique index on `status='active'`) — a single person **cannot** simultaneously hold both `head_grower` and `production_supervisor` in the same tenant. For a very small pilot team where one person covers both functions, assign whichever role that person's day-to-day work more closely matches (likely `production_supervisor`, since it's execution-heavy) rather than attempting to force premature separation; this is a staffing/assignment choice, not a permission-model defect.

No inversion requires fixing — the hierarchy is real, just not count-shaped.

---

## 5. Challenge: operator (15 grants)

**READ (11)**: farm.read, location.read, asset.read, carrier.read, crop_batch.read, seed_lot.read, sowing.read, transplant.read, observation.read, quality_hold.read, harvest.read.

**MANAGE (4)**: sowing.manage, transplant.manage, movement.manage, harvest.manage.

Per-permission check — "routine execution only, or does it also expose configuration/master-data authority?" — traced against the actual router endpoints each permission gates:

| Permission | Endpoint(s) gated | Mixes configuration? | Verdict |
|---|---|---|---|
| sowing.manage | `POST .../sowings` only | No — single execution action | **SAFE, GRANT** |
| transplant.manage | `POST .../transplants` only | No — single execution action | **SAFE, GRANT** |
| movement.manage | `POST /farms/{farm_id}/movements` only | No — single execution action | **SAFE, GRANT** |
| harvest.manage | `POST .../harvests` only | No — single execution action | **SAFE, GRANT** |
| observation.manage *(not currently granted)* | `POST .../observations` **and** `POST /observation-definitions` | **Yes** — the same permission that lets an operator record a routine germination check also lets them create a new observation *definition* (configuration/master data) | **UNSAFE — see below** |

**`observation.manage` is explicitly marked BLOCKED for `operator` in both proposed matrices (§12), not merely denied.** Per instruction, this is not compensated with SOP alone — SOP is an acceptable *interim* stopgap only for low-frequency, low-blast-radius risks (see §6's treatment of `quality_hold.manage`); denying an operator the ability to record any observation at all is a **P0 software-authority problem**, not a policy choice, because the underlying permission cannot be granted safely at any scope smaller than "also let this operator define new observation types." The fix is a permission split (`observation.manage` → routine recording + `observation_definition.manage` → configuration), not a workaround. Until that split ships, `operator`'s observation-recording function is **BLOCKED**, and this should be communicated to pilot operations as a known limitation, not silently absorbed into "someone else does it."

The other 4 manage grants remain confirmed safe and unchanged.

---

## 5A. observation.manage reconciliation (AUTHZ-002A.2)

AUTHZ-002A.1 blocked `operator` correctly but stopped short of applying the same test to every other role that touched `observation.manage`. Reconciled here consistently.

### A. Every role previously receiving observation.manage, and the entry/definition test

| Role | 1. Needs routine ENTRY? | 2. Needs DEFINITION/configuration authority? | 3/4. Verdict on current (unsplit) `observation.manage` |
|---|---|---|---|
| `head_grower` | Yes — occasional expert-level agronomic assessments | **Yes** — head_grower is the agronomic protocol owner; deciding what gets measured for a crop/production system (e.g. adding an EC/pH check, defining a new leaf-color score) is core planning authority, not an accident of the permission model | **Needs both — current unsplit permission remains justified.** Not over-granting; this is the one role for which the bundle reflects genuine, deliberate authority. |
| `production_supervisor` | Yes — routine floor-level observation recording is core to execution oversight | **No** — PS was already established (§4) as execution-oversight, explicitly *not* master-data configuration; defining new observation types is head_grower's domain | **Needs entry only. Current unsplit permission must NOT be granted before the split — BLOCKED**, same reasoning as `operator`. This corrects an inconsistency in AUTHZ-002A.1. |
| `qc_officer` | Yes — QC's core function | **No, and cannot be safely granted even if desired** — see §4 below: CMP's `ObservationDefinition` model has no field distinguishing an "agronomic" definition from a "QC-specific" one, so granting QC definition authority would let QC redefine *any* observation type tenant-wide, including agronomic ones outside QC's mandate | **Needs entry only. Current unsplit permission must NOT be granted before the split — BLOCKED.** This corrects the second inconsistency in AUTHZ-002A.1 (QC was previously granted the unsplit permission on the reasoning that "QC should define what gets observed" — too broad; QC needs to *use* definitions, not *own* the tenant-wide definition catalog). |
| `operator` | Yes — routine floor execution | No | **Needs entry only. BLOCKED** (unchanged from AUTHZ-002A.1). |
| `farm_manager` | No — oversight via `observation.read` is sufficient | No | Already correctly denied in every prior revision — see §7 below. |
| `tenant_admin`, all other roles | n/a | n/a | `tenant_admin` unaffected (superuser). No other role was ever proposed to receive `observation.manage`. |

**Consequence**: under the *current, unsplit* permission, `observation.manage` can only safely go to `head_grower` and `tenant_admin`. `production_supervisor`, `operator`, and `qc_officer` — three of the roles that most need to record observations day-to-day — are all **BLOCKED**. This is a materially more severe finding than AUTHZ-002A.1 reported (which only blocked `operator`), and is reflected in the revised Matrix A (§12) and the P0 list (§8/§13).

### B. Target post-split authority (design intent only — no `Permission` enum names chosen)

Conceptually distinguish **OBSERVATION ENTRY** (recording a value against an existing definition) from **OBSERVATION DEFINITION** (creating/configuring what can be recorded):

| Role | ENTRY | DEFINITION | Notes |
|---|---|---|---|
| tenant_admin | GRANT | GRANT | Superuser, unaffected |
| farm_manager | DENY | DENY | Oversight via `observation.read` only — see §7; not granted configuration authority merely for seniority |
| head_grower | GRANT | GRANT | Genuine dual need — see §6 below |
| production_supervisor | GRANT | DENY | Execution oversight, not configuration — see §5 above |
| operator | GRANT | DENY | Routine execution only |
| storekeeper | DENY | DENY | Outside this role's domain entirely |
| qc_officer | GRANT | **DENY** | See §4 below — the ambiguous case; DENY is the recommended resolution, not a straightforward yes/no |
| auditor | DENY | DENY | Read-only role (`observation.read` unaffected) |
| packing_supervisor | DENY | DENY | Outside this role's domain |
| cold_store_supervisor | DENY | DENY | Outside this role's domain |
| dispatch_officer | DENY | DENY | Outside this role's domain |
| read_only | DENY | DENY | Read-only role (`observation.read` unaffected) |

**Ambiguous case — qc_officer's DEFINITION authority**: QC plausibly wants to define QC-specific inspection criteria (e.g. a defect-scoring checklist). The current data model cannot express "QC may define QC-purpose observation types but not agronomic ones" — `ObservationDefinition` has no category/purpose field (fields are `code`, `name`, `description`, `value_type`, `unit`, `target_scope`, `min_value`/`max_value`, `status` only; confirmed by reading `app/models/observation_definition.py` directly). Two honest options, neither implemented here: (a) deny QC definition authority entirely and route QC's definition *requests* through `head_grower`/`tenant_admin` (recommended default — keeps a single, coherent owner of the definition catalog and avoids QC silently gaining reach over agronomic metrics), or (b) add a category/purpose field to `ObservationDefinition` first, enabling a genuinely scoped `observation_definition.manage` split later. This document does not resolve which; it flags the limitation rather than pretending the authority is cleanly separable today.

### C. Section-by-section decisions requested by the ticket

**§4 — QC**: QC should **not** manage observation definitions. QC needs ENTRY only. The system cannot distinguish QC-purpose from agronomic definitions, so granting QC definition authority is not "QC configuring its own inspection criteria" in isolation — it's QC gaining reach over the *entire* tenant-wide definition catalog, including agronomic metrics that are head_grower's domain. Flagged as a genuine current-model limitation (§B above), not solved by over-granting.

**§5 — production_supervisor**: Does not need definition authority — confirmed via the same "execution oversight, not master-data configuration" principle already established for this role in §4 (the earlier, role-hierarchy section) and §11 (master-data table). Current `observation.manage` must be **BLOCKED** pending the split, consistent with `operator`.

**§6 — head_grower**: Legitimately needs both. Head_grower is the sole role in this design whose planning mandate genuinely spans deciding *what* gets measured (definition) and personally recording expert-level agronomic assessments (entry). Because head_grower is also the role this document already concentrates all other agronomic master-data authority in (`crop.manage`, `production_system.manage`, `workflow.manage` — §4, §11), keeping definition authority with the same role avoids fragmenting "who owns the agronomic rulebook" across multiple people. Current unsplit `observation.manage` **remains safe and justified for head_grower**, and is the one role where this document does not recommend blocking it.

**§7 — farm_manager**: Farm Manager needs `observation.read` only, not `observation.manage` in any form (neither half). This was already the design in every prior revision (farm_manager was never granted `observation.manage`) — reaffirmed here explicitly rather than assumed: a farm manager's oversight need is fully satisfied by visibility into what's been observed; deciding what gets measured is head_grower's agronomic authority, and recording routine observations is production_supervisor's/operator's/QC's execution-level work. Seniority alone is not a reason to grant configuration authority — consistent with the same reasoning already applied to `workflow.manage`/`crop.manage`/`production_system.manage` in §3.

---

## 6. Challenge: qc_officer

Full grant list (19, unchanged from AUTHZ-002A): farm.read, location.read, asset.read, carrier.read, crop.read, crop_batch.read, seed_lot.read, sowing.read, transplant.read, observation.read/manage, quality_hold.read/manage, harvest.read, packing.read, finished_goods_storage.read, dispatch.read, recall.read, traceability.read.

Explicit answers:

| Permission | Granted? | Justification |
|---|---|---|
| quality_hold.manage | **GRANT** | QC's core function — place and release, under the current unified policy |
| recall.manage | **DENY** | See below — recall is escalated to `farm_manager`/`tenant_admin`, not owned by QC |
| packing.manage | **DENY** | Inspection ≠ execution — QC gets `packing.read` only |
| harvest.manage | **DENY** | QC gets `harvest.read` only |
| dispatch.manage | **DENY** | QC gets `dispatch.read` only |

Confirms the stated principle ("QC may inspect broadly, but should not automatically execute unrelated production/logistics work") holds throughout — QC's only `.manage` grant in the **current, implementable** matrix is `quality_hold.manage`. **Correction from AUTHZ-002A.1**: that revision also granted QC the current, unsplit `observation.manage` on the reasoning that QC should both record and define quality-relevant observations. Re-examined in §5A: QC genuinely needs observation *entry*, but not tenant-wide observation *definition* authority — CMP's `ObservationDefinition` model cannot scope a definition to "QC-specific" versus "agronomic," so granting QC the unsplit permission would let QC redefine any observation type in the system, not just its own. QC's `observation.manage` is now **BLOCKED** in the current-implementable matrix, same as `operator` and `production_supervisor` — see §5A for the full reconciliation.

**Is pilot SOP enough for `quality_hold.manage`'s place/release bundling?** **Yes, for Pilot V1 specifically**, for a qualitatively different reason than `operator`/`observation.manage`: a quality hold is internally-scoped and fully reversible (it never leaves the farm, never reaches a customer), and the truly catastrophic action (`recall.manage`) is *not* delegated to QC at all — containing the worst case to a single lot/batch-level hold. This is a low-frequency, low-blast-radius, reversible risk, unlike the operator/observation gap (a high-frequency, zero-risk, purely usability-blocking gap). SOP (a documented peer/supervisor conversation before the same officer both places and releases) is an acceptable *interim* mitigation here. Still flagged **P1** — required before an external paid customer.

**Recall recommendation**: QC should **not** own `recall.manage`. Recommend **escalate recall execution to `farm_manager`/`tenant_admin`** (unchanged from AUTHZ-002A, now explicitly reaffirmed against this challenge's specific question). QC gets `recall.read` only — full visibility to flag/investigate, no unilateral authority to act. This preserves detection (QC) vs. decision (management) separation, matching `CMP_MASTER_SPEC.md` §11's own stated principle ("a user cannot approve or audit their own restricted transaction").

---

## 7. Challenge: storekeeper — revised to PARTIALLY ACTIVE, grant set tightened

**Original grant set (8)**: farm.read, location.read, asset.read/manage, carrier.read/manage, seed_lot.read/manage.

**Challenge**: "Do not give unrelated asset/carrier permissions merely to make the role look useful." Re-examined: `asset.manage`/`carrier.manage` (registering trolleys/trays as equipment) is not clearly *storekeeping* — it's equipment/fleet commissioning, already legitimately owned by `farm_manager` as infrastructure authority (§3). Registering a new carrier or asset happens rarely (only when new equipment is procured) and is not "input receiving" in the sense the role name implies. Kept in the original draft only to "give the role something to do" — exactly what the challenge warns against.

**Revised grant set (6)**: farm.read, location.read, asset.read, carrier.read, seed_lot.read/manage. `asset.manage`/`carrier.manage` **removed** — equipment registration remains centralized under `farm_manager`.

**What real storekeeping work CMP can currently support**: exactly one thing — **seed lot registration/receiving** (`seed_lot.manage`), plus passive visibility (`seed_lot.read` and basic location/asset/carrier context so they know where things are). Nothing else. No fertilizer/nutrient/substrate/consumables/PPE tracking exists in the 41-permission catalog at all — the general "input store" module named in `CMP_MASTER_SPEC.md`'s product boundary is simply not built yet.

**Revised classification for Imperial pilot**: **PARTIALLY ACTIVE.** Genuinely useful for its one real function (seed-lot receiving); not a general store role. Do not present this role to pilot staff as "the storekeeper" in the full traditional sense — communicate its actual, narrow current scope.

---

## 8. Challenge: packing / cold store / dispatch handoff

|  | Packing | Cold Store | Dispatch |
|---|---|---|---|
| packing.manage | `packing_supervisor` | — | — |
| finished_goods_storage.manage | — | `cold_store_supervisor` | — |
| dispatch.manage | — | — | `dispatch_officer` |

**Zero cross-stage `.manage` grants** — confirmed, unchanged from AUTHZ-002A; each role manages exactly one stage.

Upstream/downstream `.read` grants (visibility without authority) per role:

- **packing_supervisor**: upstream `harvest.read` (what's available to pack); downstream `finished_goods_storage.read` (visibility once packed). Plus `quality_hold.read`, `recall.read`, `traceability.read`, `crop_batch.read` (lot context).
- **cold_store_supervisor**: upstream `packing.read` (what finished-goods lots exist to place); downstream `dispatch.read` (what's left their custody). Plus `quality_hold.read`, `recall.read`, `traceability.read`.
- **dispatch_officer**: upstream `finished_goods_storage.read` (what's available/placed to dispatch) **and** `packing.read` (lot provenance for shipment documentation). Plus `quality_hold.read`, `recall.read`, `traceability.read`.

All three also get `quality_hold.read` and `recall.read` specifically so a held or recalled lot's status is visible before it's packed/stored/dispatched — visibility only; none of the three can place a hold, release a hold, or open/close a recall themselves.

---

## 9. auditor vs. read_only — confirmed identical, not fabricated

**Yes, currently identical.** Both roles' proposed grant sets are the exact same 20 permissions: farm.read, location.read, asset.read, carrier.read, crop.read, production_system.read, workflow.read, crop_batch.read, batch_derivation.read, seed_lot.read, sowing.read, transplant.read, observation.read, quality_hold.read, harvest.read, packing.read, finished_goods_storage.read, dispatch.read, recall.read, traceability.read. Not merely the same count — the same set. No difference is fabricated here.

**Intended future difference**: once an `audit.read` permission exists (gating the raw `audit_events` log — actor, action, entity, timestamp, event payload — which today has no dedicated read permission at all), `auditor` would receive it and `read_only` would not. That is the entire intended distinction; nothing else currently differentiates or should differentiate them.

**Recommendation**: **keep both role codes available in Pilot V1** despite identical current technical authority. Reasoning: (a) the role_code is also an organizational-clarity label independent of enforced permissions — "auditor" communicates a different expectation to the org than "read_only" even before the permissions diverge; (b) zero risk in keeping both active, since both are equally zero-mutation; (c) `audit.read` can be added to `auditor`'s grant set later with no role rename or membership migration required — the role already exists and can simply gain a permission.

---

## 10. Recall authority — final recommendation

`recall.manage` remains the single highest-consequence permission in the catalog (bundles open+close; legal/safety/brand/financial impact).

**A. Imperial pilot**: `farm_manager` + `tenant_admin`. **Not** `qc_officer` (see §6 — detection vs. decision separation). This is the minimum set of people with both the authority and accountability to make the call, without being the same function that raised the underlying quality issue.

**B. External commercial V1**: **conditionally the same** (`farm_manager` + `tenant_admin`), but this recommendation is **explicitly gated on the open/close split (§13, P1) shipping first, or on restricting to `tenant_admin`-only in the meantime.** Do not onboard an external paying customer with the current *unsplit* `recall.manage` still assigned to `farm_manager` without one of: (a) the split has shipped, giving at least a two-step/two-permission control, or (b) an explicit, accepted decision to restrict recall authority to `tenant_admin` only for that customer until it does. This is stricter than the pilot recommendation deliberately — a pilot is a trusted small internal team; an external customer's `farm_manager` is an unknown third party whose incentives (e.g. avoiding the cost/reputational hit of a recall) are not necessarily aligned with taking the recall action promptly.

Not granted merely because a role can read traceability — `traceability.read` is granted broadly (farm_manager, head_grower, production_supervisor, qc_officer, packing/cold-store/dispatch, auditor, read_only) precisely because it's pure, harmless visibility; `recall.manage` is evaluated entirely independently and kept to the two roles above only.

---

## 11. Configuration (master data) authority

The 9 permissions warranting the closest scrutiny (farm/location/asset/carrier/crop/production_system/workflow/seed_lot `.manage`, plus `observation.manage` when read as bundled with observation-definition authority):

| Permission | FM | HG | PS | OP | SK | QC | PK/CS/DO | AU/RO |
|---|---|---|---|---|---|---|---|---|
| farm.manage | G | | | | | | | |
| location.manage | G | | | | | | | |
| asset.manage | G | | | | | | | |
| carrier.manage | G | | | | | | | |
| crop.manage | | G | | | | | | |
| production_system.manage | | G | | | | | | |
| workflow.manage | | G | | | | | | |
| seed_lot.manage | | | | | G | | | |
| observation.manage | | G | **BLOCKED** | **BLOCKED** | | **BLOCKED** | | |

**Confirmed, revised per §5A**: no routine floor role (`operator`, `packing_supervisor`, `cold_store_supervisor`, `dispatch_officer`) and no pure-visibility role (`auditor`, `read_only`) touches *any* of these nine permissions. Master-data/configuration authority under the *current, implementable* permission set is concentrated in exactly three roles (`farm_manager` for infrastructure, `head_grower` for agronomic catalog/workflow/observation-definition, `storekeeper` for seed-lot intake). `production_supervisor` and `qc_officer` do **not** get `observation.manage` today — both are BLOCKED pending the entry/definition split (§5A), since neither genuinely needs definition authority and the current permission cannot be granted for entry alone. Routine operational personnel cannot casually change farm configuration under this design, and — as of this revision — no role gains configuration authority merely to work around the coarse permission either.

---

## 12. Matrices (proposal only — not implemented)

Two distinctions matter here, not one: (a) Imperial Pilot vs. External Commercial V1, and (b) **CURRENT IMPLEMENTABLE** (what can actually be granted using today's unsplit permissions) vs. **POST-P0-SPLIT DESIRED** (the target authority once entry/definition are split — §5A.B). Matrix A and Matrix B below are both CURRENT IMPLEMENTABLE. The POST-P0-SPLIT DESIRED table follows separately and must not be read as grantable today.

### MATRIX A — Imperial Pilot (CURRENT IMPLEMENTABLE)
One active farm, small trusted team, SOP compensation acceptable where explicitly justified (§6 only, for `quality_hold.manage` — never for the `observation.manage` gap, per §5/§5A).

| Permission | TA | FM | HG | PS | OP | SK | QC | PK | CS | DO | AU | RO |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| farm.read | G | G | G | G | G | G | G | G | G | G | G | G |
| farm.manage | G | G | – | – | – | – | – | – | – | – | – | – |
| location.read | G | G | G | G | G | G | G | G | G | G | G | G |
| location.manage | G | G | – | – | – | – | – | – | – | – | – | – |
| asset.read | G | G | G | G | G | G | G | G | G | G | G | G |
| asset.manage | G | G | – | – | – | – | – | – | – | – | – | – |
| carrier.read | G | G | G | G | G | G | G | G | G | G | G | G |
| carrier.manage | G | G | – | – | – | – | – | – | – | – | – | – |
| movement.manage | G | – | – | G | G | – | – | – | – | – | – | – |
| crop.read | G | G | G | G | – | – | G | – | – | – | G | G |
| crop.manage | G | – | G | – | – | – | – | – | – | – | – | – |
| production_system.read | G | G | G | G | – | – | – | – | – | – | G | G |
| production_system.manage | G | – | G | – | – | – | – | – | – | – | – | – |
| workflow.read | G | G | G | G | – | – | – | – | – | – | G | G |
| workflow.manage | G | – | G | – | – | – | – | – | – | – | – | – |
| crop_batch.read | G | G | G | G | G | – | G | G | – | – | G | G |
| crop_batch.manage | G | – | G | G | – | – | – | – | – | – | – | – |
| batch_derivation.read | G | G | G | G | – | – | – | – | – | – | G | G |
| batch_derivation.manage | G | – | G | G | – | – | – | – | – | – | – | – |
| seed_lot.read | G | G | G | G | G | G | G | – | – | – | G | G |
| seed_lot.manage | G | – | – | – | – | G | – | – | – | – | – | – |
| sowing.read | G | G | G | G | G | – | G | – | – | – | G | G |
| sowing.manage | G | – | – | G | G | – | – | – | – | – | – | – |
| transplant.read | G | G | G | G | G | – | G | – | – | – | G | G |
| transplant.manage | G | – | – | G | G | – | – | – | – | – | – | – |
| observation.read | G | G | G | G | G | – | G | – | – | – | G | G |
| observation.manage | G | – | G | **BLOCKED** | **BLOCKED** | – | **BLOCKED** | – | – | – | – | – |
| quality_hold.read | G | G | G | G | G | – | G | G | G | G | G | G |
| quality_hold.manage | G | – | – | – | – | – | G | – | – | – | – | – |
| harvest.read | G | G | G | G | G | – | G | G | – | – | G | G |
| harvest.manage | G | – | G | G | G | – | – | – | – | – | – | – |
| packing.read | G | G | – | – | – | – | G | G | G | G | G | G |
| packing.manage | G | – | – | – | – | – | – | G | – | – | – | – |
| finished_goods_storage.read | G | G | – | – | – | – | G | G | G | G | G | G |
| finished_goods_storage.manage | G | – | – | – | – | – | – | – | G | – | – | – |
| dispatch.read | G | G | – | – | – | – | G | – | G | G | G | G |
| dispatch.manage | G | G* | – | – | – | – | – | – | – | G | – | – |
| recall.read | G | G | G | G | – | – | G | G | G | G | G | G |
| recall.manage | G | G | – | – | – | – | – | – | – | – | – | – |
| traceability.read | G | G | G | G | – | – | G | G | G | G | G | G |
| tenant.members.manage | G | – | – | – | – | – | – | – | – | – | – | – |

`*` = `farm_manager`'s `dispatch.manage` is the "broader pilot" tier grant (§3.B); use the "minimum viable" tier (§3.A, remove this one cell) for a more conservative pilot posture. `production_supervisor`/`operator`/`qc_officer`'s `observation.manage` cells are marked **BLOCKED**, not denied — see §5/§5A; these are known, communicated software-authority gaps, not policy choices. Only `head_grower` and `tenant_admin` can safely record observations under the current unsplit permission.

Grant totals (mechanically verified against this matrix, AUTHZ-002A.3): TA 41, FM 26 (broader tier) / 25 (minimum tier), **HG 24** (corrected — see §4), PS 23, OP 15, SK 6, QC 18, PK 12, CS 11, DO 11, AU 20, RO 20.

### MATRIX B — External Commercial V1
Multi-user, potentially multi-farm customer; stronger segregation; fewer manual controls accepted.

Identical to Matrix A **except**:
- `farm_manager` uses the **minimum viable** tier (25) — `dispatch.manage` removed; an external farm_manager does not get open-ended backup authority over the highest-stakes non-recall action by default.
- `farm_manager`'s `recall.manage` is retained but **conditionally flagged**: do not onboard with this grant live until the recall open/close split (§13, P1) has shipped, or restrict to `tenant_admin`-only for that customer in the meantime (§10.B).
- `qc_officer`'s `quality_hold.manage` is retained but **flagged P1**: the place/release split should ship at or shortly after external launch — SOP alone (acceptable for the pilot's trusted small team, §6) is a weaker control for an external customer.
- `operator` role is **not recommended for external commercial rollout** until the `observation.manage` split ships — for the pilot, blocking one function is tolerable; for a customer paying for the product, a role that cannot perform a core, obvious floor task (recording an observation) is a product-quality problem, not just a security nicety. The same applies to `production_supervisor` and `qc_officer`'s now-also-BLOCKED observation-recording ability (§5A) — under the current permission model, only `head_grower`/`tenant_admin` can record any observation at all, which is not a credible posture for an external commercial launch.
- `storekeeper`'s narrow scope (§7) becomes a **P1** gap rather than an acceptable pilot limitation — an external paying customer is more likely to expect real input/store tracking as a baseline feature.
- **Multi-farm caveat (§1)**: this matrix assumes either a single-farm customer or that farm-scoped role assignment has been implemented. For a genuinely multi-farm external customer without that, granting any operational role to an individual gives them that authority across **every** farm in the tenant, not just their assigned site. This is a **P0** blocker for that customer segment specifically (§1, §13) — not solved by this permission matrix, and not safe to paper over with role choice alone. The available interim mitigation is provisioning one CMP tenant per farm for that customer (CMP is already multi-tenant), accepted explicitly, not silently.
- `auditor` vs `read_only` remains identical (§9); flagged as a discoverability question a compliance-conscious paying customer may explicitly ask about, elevating `audit.read` from a "nice to have" toward something worth prioritizing sooner.

Matrix B's BLOCKED cells (revised, §5A): `observation.manage` for `production_supervisor`, `operator`, **and** `qc_officer` — inherited unchanged from Matrix A, since this is a software-authority limitation independent of pilot-vs-external deployment shape. Every other Matrix B reduction from Matrix A is a risk-based recommendation (flagged, conditional, or role-not-recommended), not a hard technical impossibility, and is stated as such rather than dressed up as a blocker it isn't.

---

### POST-P0-SPLIT DESIRED — target authority once the entry/definition split ships

**Not implementable today — do not treat any GRANT below as currently available.** This is the design intent §5A.B describes, restated as a matrix slice for the affected permission only, applicable identically to both Matrix A and Matrix B once the split ships:

| Role | OBSERVATION ENTRY (desired) | OBSERVATION DEFINITION (desired) |
|---|---|---|
| tenant_admin | GRANT | GRANT |
| farm_manager | DENY | DENY |
| head_grower | GRANT | GRANT |
| production_supervisor | GRANT | DENY |
| operator | GRANT | DENY |
| storekeeper | DENY | DENY |
| qc_officer | GRANT | DENY *(see §5A — ambiguous; DENY is the recommended resolution given the current inability to scope definitions to "QC-specific")* |
| auditor | DENY | DENY |
| packing_supervisor | DENY | DENY |
| cold_store_supervisor | DENY | DENY |
| dispatch_officer | DENY | DENY |
| read_only | DENY | DENY |

Once this ships, both matrices' `observation.manage` row is replaced by two rows using this table directly — `production_supervisor`, `operator`, and `qc_officer` move from **BLOCKED** to a real **GRANT** on the entry-only permission, with no change to any other role.

---

## 13. Revised priority gaps (P0/P1/P2)

| # | Gap | Imperial pilot | Multi-farm Imperial | External SaaS |
|---|---|---|---|---|
| 1 | Farm-scoped role assignment (no user/role↔farm restriction exists — §1) | P2 (no impact, single farm) | P1 | **P0** |
| 2 | `observation.manage` bundles routine entry + definition configuration (§5, §5A) | **P0** — under the current unsplit permission, only `head_grower`/`tenant_admin` can safely record any observation at all; `production_supervisor`, `operator`, and `qc_officer` are all BLOCKED (§5A corrected two of these from AUTHZ-002A.1, which had granted them the unsplit permission inconsistently) | P0 | P0 |
| 3 | `quality_hold.manage` bundles place+release (§6) | P1 (SOP acceptable interim) | P1 | P1 |
| 4 | `recall.manage` bundles open+close (§10) | P1 (role-restriction mitigates) | P1 | P1 (gates `farm_manager`'s grant in Matrix B) |
| 5 | No general Input/Store module/permissions (§7) | P1 | P1 | P1 |
| 6 | No `audit.read` — `auditor`/`read_only` indistinguishable (§9) | P2 | P2 | P2 (discoverability risk with compliance-focused customers) |
| 7 | `crop_batch.manage` bundles creation + stage-transition | P2 | P2 | P2 |
| 8 | `dispatch.manage` lacks a confirm/dual-control step | P2 | P2 | P2 |

Conservative but practical, per instruction: only #1 (for the external/multi-farm segments only — **P2 for the Imperial single-farm pilot itself**) and #2 (a genuine P0 for every deployment shape, since it blocks `production_supervisor`, `operator`, and `qc_officer` — not just `operator` — from recording any observation at all) are treated as hard P0s for the Imperial pilot. Everything else (#3–#8) is a real, tracked hardening item that does not block the Imperial single-farm pilot as designed in Matrix A. This matches the expected shape: essentially one disciplined P0 (the observation split) for the pilot itself, with the farm-scope gap correctly excluded from the pilot's own P0 list since it has no practical effect on a single-farm deployment.

---

## Summary of what this document does NOT do

- Does not modify `app.core.permissions.Permission` or `ROLE_PERMISSIONS`.
- Does not add, remove, split, or rename any permission.
- Does not add, remove, or merge any role.
- Does not implement farm-scoped authorization.
- Does not change any router, service, model, schema, or migration.
- Is a design/policy proposal for a future, explicitly-scoped implementation ticket to act on.
