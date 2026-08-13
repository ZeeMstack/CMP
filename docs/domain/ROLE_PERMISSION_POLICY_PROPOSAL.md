# Role / Permission Policy Proposal (AUTHZ-002A, challenge-reviewed AUTHZ-002A.1/A.2)

**Status: PROPOSAL — not implemented.** `app.core.permissions.Permission` and `ROLE_PERMISSIONS` remain unchanged (`tenant_admin` → all permissions; every other role → empty set) until a follow-up ticket is explicitly authorized to implement this design. This document is the product-policy design and review artifact only.

**Revision note (AUTHZ-002A.1):** this version supersedes the single-matrix AUTHZ-002A draft after a challenge review. Material changes: (1) a previously-unaudited farm-scope architecture gap was found and is now the headline finding; (2) `farm_manager`'s grant set was tightened (harvest/packing/finished-goods-storage `.manage` removed; dispatch `.manage` demoted to an optional "broader pilot" grant); (3) `storekeeper` was tightened (asset/carrier `.manage` removed as unjustified); (4) the design is now split into two separate matrices (Imperial Pilot vs. External Commercial V1) instead of one; (5) `observation.manage` for `operator` is now explicitly marked **BLOCKED**, not "SOP-compensated."

**Revision note (AUTHZ-002A.2):** AUTHZ-002A.1 correctly identified `observation.manage` as a P0 granularity problem for `operator`, but inconsistently still showed it granted to `production_supervisor` and `qc_officer` in the *current implementable* matrix. This revision applies the same "does this role need entry, definition, or both?" test to **every** role that touched `observation.manage`, not just `operator`. Result: under the current, unsplit permission, only `head_grower` (and `tenant_admin`) can safely receive it — `production_supervisor` and `qc_officer` are now also marked **BLOCKED** in the current-implementable matrix (§5A, §12). A separate **POST-P0-SPLIT DESIRED** table/matrix is added showing the intended per-role authority once entry and definition are split, which must not be conflated with what can be granted today. See §5A for the full reconciliation.

**Revision note (AUTHZ-002B1) — the permission split described below is now IMPLEMENTED at the code level.** `Permission.OBSERVATION_MANAGE` no longer exists; it has been replaced by `Permission.OBSERVATION_ENTRY_MANAGE` (`observation_entry.manage`) and `Permission.OBSERVATION_DEFINITION_MANAGE` (`observation_definition.manage`) in `app/core/permissions.py`, wired to the correct routes (`POST .../observations` and `POST /observation-definitions` respectively). The catalog is now **42** permissions (was 41), **22** `.manage` permissions (was 21). Every `BLOCKED` marker below that referred specifically to the *software-authority impossibility* of granting `production_supervisor`/`operator`/`qc_officer` entry-only authority is now resolved — that impossibility no longer exists. **This does not mean those roles can use the feature.** `ROLE_PERMISSIONS` was deliberately left untouched by AUTHZ-002B1: every non-admin role, including all five roles this document's approved design would eventually grant an observation permission to, still resolves to the empty set. Activating the approved grants is AUTHZ-002B2's job. Sections below are updated to show the **proposed** policy (now technically grantable) while explicitly marking it **not yet active**; do not read a `GRANT` cell for `production_supervisor`/`operator`/`qc_officer`'s observation permissions as something a real user can do today. See the fully updated §5/§5A and Matrix A/B (§12) for the reconciled detail; the former standalone "POST-P0-SPLIT DESIRED" table has been folded into the main matrices now that the split it described actually exists.

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
| `observation.read` | View recorded observations and observation definitions (unified — see AUTHZ-002B1 note below; no security reason found to split this) |
| `observation_entry.manage` | Record a routine observation (**AUTHZ-002B1**: split from the former unified `observation.manage`) |
| `observation_definition.manage` | Create/configure an observation definition — master data (**AUTHZ-002B1**: split from the former unified `observation.manage`) |
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
- **operator** — Restricted transactional execution: sowing, transplant, movement, harvest recording — routine, single-purpose commands only. No planning, no configuration, no quality/compliance authority. Observation recording (`observation_entry.manage`) is proposed for this role and technically grantable as of AUTHZ-002B1, but **not active** until AUTHZ-002B2 — see §5/§5A.
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
- **head_grower (25 proposed, NOT yet active — see AUTHZ-002B1 note)** — farm.read, location.read, asset.read, carrier.read, crop.read/manage, production_system.read/manage, workflow.read/manage, crop_batch.read/manage, batch_derivation.read/manage, seed_lot.read, sowing.read, transplant.read, observation.read, **observation_entry.manage, observation_definition.manage** (both — the split, proposed under AUTHZ-002B2), quality_hold.read, harvest.read/manage, recall.read, traceability.read.
- **production_supervisor (24 proposed, NOT yet active)** — farm.read, location.read, asset.read, carrier.read, crop.read, production_system.read, workflow.read, crop_batch.read/manage, batch_derivation.read/manage, seed_lot.read, sowing.read/manage, transplant.read/manage, movement.manage, observation.read, **observation_entry.manage** (proposed under AUTHZ-002B2 — technically grantable since AUTHZ-002B1, **not** `observation_definition.manage`), quality_hold.read, harvest.read/manage, recall.read, traceability.read.
- **operator (16 proposed, NOT yet active)** — farm.read, location.read, asset.read, carrier.read, crop_batch.read, seed_lot.read, sowing.read/manage, transplant.read/manage, movement.manage, observation.read, **observation_entry.manage** (proposed under AUTHZ-002B2 — technically grantable since AUTHZ-002B1, **not** `observation_definition.manage`), quality_hold.read, harvest.read/manage.
- **storekeeper (6)** — farm.read, location.read, asset.read, carrier.read, seed_lot.read/manage.
- **qc_officer (19 proposed, NOT yet active)** — farm.read, location.read, asset.read, carrier.read, crop.read, crop_batch.read, seed_lot.read, sowing.read, transplant.read, observation.read, **observation_entry.manage** (proposed under AUTHZ-002B2 — technically grantable since AUTHZ-002B1, **not** `observation_definition.manage`; see §5A/§4 — a definition grant still can't be safely scoped to "QC-specific" vs. "agronomic"), quality_hold.read/manage, harvest.read, packing.read, finished_goods_storage.read, dispatch.read, recall.read, traceability.read.
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

All 22 `.manage` permissions (21 pre-AUTHZ-002B1; `observation.manage` split into two — see §5A) × 11 non-admin roles. Only `G` cells shown with justification; every blank cell is a deliberate deny. Every `G` in this table is **proposed policy**, not necessarily an active `ROLE_PERMISSIONS` grant — see §0.D and the AUTHZ-002B1 revision note at the top for which roles have zero active permissions today. Reflects the **revised** (post-challenge) grants — see §3 and §7 for what changed and why.

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
| observation_entry.manage *(AUTHZ-002B1)* | | G — proposed; genuinely needs entry authority (see §5A) | G — proposed; routine floor-level recording (see §5A) | G — proposed; routine execution, now technically grantable since the split (see §5) | | G — proposed; QC's core recording function (see §5A/§6) | | | | | |
| observation_definition.manage *(AUTHZ-002B1)* | | G — proposed; genuinely needs definition authority (see §5A) | | | | | | | | | |
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
| observation_entry.manage / observation_definition.manage *(split by AUTHZ-002B1)* | Already DENY | Definition delegated to Head Grower only (§5A). Entry is proposed for Production Supervisor and QC too (unlike farm_manager) — but none of it is active for any role until AUTHZ-002B2 |
| harvest.manage | **REMOVE** | Execution belongs to Head Grower/Production Supervisor/Operator, who are the people physically harvesting |
| farm.manage / location.manage / asset.manage / carrier.manage | **KEEP** | Not on the ticket's "especially strict" list; infrastructure/site setup is the one area where "farm manager" as a job title clearly implies direct configuration authority |

### A. Minimum viable farm_manager (25)
All 20 `*.read` permissions + `farm.manage`, `location.manage`, `asset.manage`, `carrier.manage`, `recall.manage`.

### B. Broader pilot farm_manager (26)
Minimum viable (25) + `dispatch.manage` (backup/escalation authority for a small team where `dispatch_officer` coverage may be thin).

**Delta from the original 29**: −4 (`harvest.manage`, `packing.manage`, `finished_goods_storage.manage` removed entirely; `dispatch.manage` moved from unconditional to broader-tier-only). The farm manager retains full visibility everywhere and full infrastructure authority, but no longer personally executes any post-harvest production step — those stay with the specialists who own them.

---

## 4. Challenge: head_grower (25 proposed) vs. production_supervisor (24 proposed)

**AUTHZ-002B1 update**: counts below reflect the *proposed* policy now that the observation permission split (§5A) exists at the code level — neither role's grant is actually active yet (pending AUTHZ-002B2), but both counts shift by the same mechanism: the old single `observation.manage` (counted once, head_grower-only) is replaced by `observation_entry.manage` (now proposed for **both** roles) and `observation_definition.manage` (still head_grower-only). Both roles gain one permission each relative to the AUTHZ-002A.3 figures (24→25 and 23→24) because `production_supervisor` newly gains a proposed `observation_entry.manage` grant that did not previously exist at all (it was BLOCKED, not merely absent).

The raw count is a **misleading proxy for seniority** — permission count ≠ authority weight regardless of the exact numbers. Diffing the two proposed sets:

- **Only head_grower has (4)**: `crop.manage`, `production_system.manage`, `workflow.manage`, `observation_definition.manage` — foundational, tenant/farm-wide **master-data/configuration** authority: head_grower literally defines the crop catalog, the stage/transition graph (`workflow.manage`) that `production_supervisor`'s own `crop_batch.manage` (stage transitions) must operate within, and — uniquely among all roles — what observation types can be recorded at all.
- **Only production_supervisor has (3)**: `movement.manage`, `sowing.manage`, `transplant.manage` — routine, high-frequency, narrowly-scoped floor-execution commands.
- **Shared (21)**: farm.read, location.read, asset.read, carrier.read, crop.read, production_system.read, workflow.read, crop_batch.read/manage, batch_derivation.read/manage, seed_lot.read, sowing.read, transplant.read, observation.read, **observation_entry.manage** (newly shared as of AUTHZ-002B1's split — both roles' proposed policy includes it), quality_hold.read, harvest.read/manage, recall.read, traceability.read.

**Net: head_grower = 4(only) + 21(shared) = 25. production_supervisor = 3(only) + 21(shared) = 24.** Head Grower still leads Production Supervisor by exactly one permission, unchanged from the AUTHZ-002A.3 conclusion — the split added one permission to each role's proposed set symmetrically, so the gap and the underlying hierarchy argument are both unaffected. The qualitative hierarchy argument below holds independently of the exact count.

**Pilot-team practicality note**: `TenantMembership` enforces exactly one active role per `(tenant_id, user_id)` (`ux_tenant_memberships_active_tenant_user`, a partial unique index on `status='active'`) — a single person **cannot** simultaneously hold both `head_grower` and `production_supervisor` in the same tenant. For a very small pilot team where one person covers both functions, assign whichever role that person's day-to-day work more closely matches (likely `production_supervisor`, since it's execution-heavy) rather than attempting to force premature separation; this is a staffing/assignment choice, not a permission-model defect.

No inversion requires fixing — the hierarchy is real, just not count-shaped.

---

## 5. Challenge: operator (16 grants proposed — the split unblocked one, see §5A)

**READ (11)**: farm.read, location.read, asset.read, carrier.read, crop_batch.read, seed_lot.read, sowing.read, transplant.read, observation.read, quality_hold.read, harvest.read.

**MANAGE (5, proposed — 4 active today)**: sowing.manage, transplant.manage, movement.manage, harvest.manage (all active-eligible, unaffected by this section), **observation_entry.manage (proposed only — not yet active, pending AUTHZ-002B2)**.

Per-permission check — "routine execution only, or does it also expose configuration/master-data authority?" — traced against the actual router endpoints each permission gates:

| Permission | Endpoint(s) gated | Mixes configuration? | Verdict |
|---|---|---|---|
| sowing.manage | `POST .../sowings` only | No — single execution action | **SAFE, GRANT** |
| transplant.manage | `POST .../transplants` only | No — single execution action | **SAFE, GRANT** |
| movement.manage | `POST /farms/{farm_id}/movements` only | No — single execution action | **SAFE, GRANT** |
| harvest.manage | `POST .../harvests` only | No — single execution action | **SAFE, GRANT** |
| observation_entry.manage *(AUTHZ-002B1 — proposed, not yet active)* | `POST .../observations` only | No — split from the former unified `observation.manage`; this permission alone no longer reaches `POST /observation-definitions` | **SAFE, GRANT (proposed)** |
| observation_definition.manage *(AUTHZ-002B1)* | `POST /observation-definitions` only | n/a — operator was never proposed to receive this | **Correctly DENY — not this role's domain (§4/§11)** |

**AUTHZ-002B1 resolved the software-authority impossibility this section originally found.** `observation.manage`'s bundling of routine recording with observation-*definition* creation made it impossible to safely grant `operator` any part of it — that impossibility no longer exists: `observation_entry.manage` reaches only the recording endpoint. **This is a permission-model resolution, not an active grant.** `ROLE_PERMISSIONS` still maps `operator` to the empty set (AUTHZ-002B1 deliberately does not activate any non-admin grant — that is AUTHZ-002B2's job); until then, `operator` still cannot record an observation in practice, for a purely sequencing reason now, not a security-impossibility reason. Do not conflate "technically resolved" with "usable today."

The other 4 manage grants remain confirmed safe and unchanged.

---

## 5A. Observation entry/definition split — reconciliation (AUTHZ-002A.2 design; AUTHZ-002B1 implemented the permission model)

AUTHZ-002A.1 blocked `operator` correctly but stopped short of applying the same test to every other role that touched `observation.manage`; AUTHZ-002A.2 reconciled that inconsistently-applied test across every role. **AUTHZ-002B1 has now implemented the permission split this section always described as the fix** — `Permission.OBSERVATION_MANAGE` no longer exists in `app/core/permissions.py`; `Permission.OBSERVATION_ENTRY_MANAGE` and `Permission.OBSERVATION_DEFINITION_MANAGE` exist in its place, wired to the correct routes. The analysis and target policy below are unchanged in substance from AUTHZ-002A.2 — only their status changes, from "design intent, not yet implementable" to "implemented at the permission-model level, proposed but not yet active as a real grant."

### A. Every role previously receiving observation.manage, and the entry/definition test

| Role | 1. Needs routine ENTRY? | 2. Needs DEFINITION/configuration authority? | 3/4. Verdict — proposed grant now that the split exists (AUTHZ-002B1); **not yet active**, pending AUTHZ-002B2 |
|---|---|---|---|
| `head_grower` | Yes — occasional expert-level agronomic assessments | **Yes** — head_grower is the agronomic protocol owner; deciding what gets measured for a crop/production system (e.g. adding an EC/pH check, defining a new leaf-color score) is core planning authority, not an accident of the permission model | **Proposed: both `observation_entry.manage` and `observation_definition.manage`.** Not over-granting; this is the one role for which holding both reflects genuine, deliberate authority. |
| `production_supervisor` | Yes — routine floor-level observation recording is core to execution oversight | **No** — PS was already established (§4) as execution-oversight, explicitly *not* master-data configuration; defining new observation types is head_grower's domain | **Proposed: `observation_entry.manage` only.** The split resolves the AUTHZ-002A.1 inconsistency that had granted this role the old unified permission — PS was never meant to hold definition authority. |
| `qc_officer` | Yes — QC's core function | **No, and cannot be safely scoped even if desired** — see §4 below: CMP's `ObservationDefinition` model has no field distinguishing an "agronomic" definition from a "QC-specific" one, so granting QC definition authority would let QC redefine *any* observation type tenant-wide, including agronomic ones outside QC's mandate | **Proposed: `observation_entry.manage` only.** The unresolved scoping limitation (§B below) means QC does not get `observation_definition.manage` even now that a split exists — the split fixed the entry/definition *bundling* problem, not the separate "can't scope a definition to QC's purpose" problem. |
| `operator` | Yes — routine floor execution | No | **Proposed: `observation_entry.manage` only.** |
| `farm_manager` | No — oversight via `observation.read` is sufficient | No | Correctly denied both, unchanged across every revision — see §7 below. |
| `tenant_admin`, all other roles | n/a | n/a | `tenant_admin` unaffected (superuser, automatically holds both new permissions). No other role was ever proposed to receive either. |

**Consequence**: the split is real and correctly wired (AUTHZ-002B1), but `ROLE_PERMISSIONS` grants nothing to any non-admin role yet. `production_supervisor`, `operator`, and `qc_officer` are no longer *blocked by the permission model* from recording observations — they are simply *not yet granted* the now-existing `observation_entry.manage`, pending AUTHZ-002B2's implementation of this section's proposed policy. This is the P0 finding's technical resolution (§15/§13); staff cannot use the capability until B2 activates it.

### B. Proposed post-split authority (AUTHZ-002B1: these are real `Permission` values now — see §0.B)

Conceptually distinguish **OBSERVATION ENTRY** (recording a value against an existing definition — `Permission.OBSERVATION_ENTRY_MANAGE`) from **OBSERVATION DEFINITION** (creating/configuring what can be recorded — `Permission.OBSERVATION_DEFINITION_MANAGE`):

| Role | ENTRY | DEFINITION | Notes |
|---|---|---|---|
| tenant_admin | GRANT (active) | GRANT (active) | Superuser, automatic — already true today |
| farm_manager | DENY | DENY | Oversight via `observation.read` only — see §7; not granted configuration authority merely for seniority |
| head_grower | GRANT (proposed) | GRANT (proposed) | Genuine dual need — see §6 below |
| production_supervisor | GRANT (proposed) | DENY | Execution oversight, not configuration — see §5 above |
| operator | GRANT (proposed) | DENY | Routine execution only |
| storekeeper | DENY | DENY | Outside this role's domain entirely |
| qc_officer | GRANT (proposed) | **DENY** | See §4 below — the ambiguous case; DENY is the recommended resolution, not a straightforward yes/no |
| auditor | DENY | DENY | Read-only role (`observation.read` unaffected) |
| packing_supervisor | DENY | DENY | Outside this role's domain |
| cold_store_supervisor | DENY | DENY | Outside this role's domain |
| dispatch_officer | DENY | DENY | Outside this role's domain |
| read_only | DENY | DENY | Read-only role (`observation.read` unaffected) |

Every "(proposed)" cell above requires AUTHZ-002B2 to become an active grant in `ROLE_PERMISSIONS`; only the two "(active)" `tenant_admin` cells reflect real, current behavior.

**Ambiguous case — qc_officer's DEFINITION authority**: QC plausibly wants to define QC-specific inspection criteria (e.g. a defect-scoring checklist). The current data model cannot express "QC may define QC-purpose observation types but not agronomic ones" — `ObservationDefinition` has no category/purpose field (fields are `code`, `name`, `description`, `value_type`, `unit`, `target_scope`, `min_value`/`max_value`, `status` only; confirmed by reading `app/models/observation_definition.py` directly). Two honest options, neither implemented here: (a) deny QC definition authority entirely and route QC's definition *requests* through `head_grower`/`tenant_admin` (recommended default — keeps a single, coherent owner of the definition catalog and avoids QC silently gaining reach over agronomic metrics), or (b) add a category/purpose field to `ObservationDefinition` first, enabling a genuinely scoped, separately-permissioned QC-definition capability later. This document does not resolve which; it flags the limitation rather than pretending the authority is cleanly separable today. **This is unaffected by AUTHZ-002B1** — the entry/definition split does not by itself solve the QC-vs-agronomic scoping problem, which is a different, still-open limitation.

### C. Section-by-section decisions requested by the original challenge ticket

**§4 — QC**: QC should **not** manage observation definitions. QC needs ENTRY only. The system cannot distinguish QC-purpose from agronomic definitions, so granting QC definition authority is not "QC configuring its own inspection criteria" in isolation — it's QC gaining reach over the *entire* tenant-wide definition catalog, including agronomic metrics that are head_grower's domain. Flagged as a genuine current-model limitation (§B above), not solved by over-granting, and not resolved by AUTHZ-002B1's split (which fixed a different problem — see §B).

**§5 — production_supervisor**: Does not need definition authority — confirmed via the same "execution oversight, not master-data configuration" principle already established for this role in §4 (the earlier, role-hierarchy section) and §11 (master-data table). Proposed grant: `observation_entry.manage` only, once AUTHZ-002B2 activates it.

**§6 — head_grower**: Legitimately needs both. Head_grower is the sole role in this design whose planning mandate genuinely spans deciding *what* gets measured (definition) and personally recording expert-level agronomic assessments (entry). Because head_grower is also the role this document already concentrates all other agronomic master-data authority in (`crop.manage`, `production_system.manage`, `workflow.manage` — §4, §11), keeping definition authority with the same role avoids fragmenting "who owns the agronomic rulebook" across multiple people. Proposed grant: both `observation_entry.manage` and `observation_definition.manage`, once AUTHZ-002B2 activates them — the one role for which this document does not recommend withholding either half.

**§7 — farm_manager**: Farm Manager needs `observation.read` only, not either new `.manage` permission. This was already the design in every prior revision (farm_manager was never granted `observation.manage`, and gains neither of its replacements) — reaffirmed here explicitly rather than assumed: a farm manager's oversight need is fully satisfied by visibility into what's been observed; deciding what gets measured is head_grower's agronomic authority, and recording routine observations is production_supervisor's/operator's/QC's execution-level work. Seniority alone is not a reason to grant configuration authority — consistent with the same reasoning already applied to `workflow.manage`/`crop.manage`/`production_system.manage` in §3.

---

## 6. Challenge: qc_officer

Full proposed grant list (19 — see §5A/§0.D; not yet active pending AUTHZ-002B2): farm.read, location.read, asset.read, carrier.read, crop.read, crop_batch.read, seed_lot.read, sowing.read, transplant.read, observation.read, **observation_entry.manage** (proposed, AUTHZ-002B1), quality_hold.read/manage, harvest.read, packing.read, finished_goods_storage.read, dispatch.read, recall.read, traceability.read.

Explicit answers:

| Permission | Granted? | Justification |
|---|---|---|
| quality_hold.manage | **GRANT** | QC's core function — place and release, under the current unified policy |
| recall.manage | **DENY** | See below — recall is escalated to `farm_manager`/`tenant_admin`, not owned by QC |
| packing.manage | **DENY** | Inspection ≠ execution — QC gets `packing.read` only |
| harvest.manage | **DENY** | QC gets `harvest.read` only |
| dispatch.manage | **DENY** | QC gets `dispatch.read` only |

Confirms the stated principle ("QC may inspect broadly, but should not automatically execute unrelated production/logistics work") holds throughout — QC's proposed `.manage` grants are `quality_hold.manage` and, as of AUTHZ-002B1, `observation_entry.manage` only. **History**: AUTHZ-002A.1 granted QC the then-current, unsplit `observation.manage` on the reasoning that QC should both record and define quality-relevant observations. AUTHZ-002A.2 re-examined this: QC genuinely needs observation *entry*, but not tenant-wide observation *definition* authority — CMP's `ObservationDefinition` model cannot scope a definition to "QC-specific" versus "agronomic," so granting QC definition authority would let QC redefine any observation type in the system, not just its own (unchanged limitation — see §5A.B). AUTHZ-002B1 has since implemented the entry/definition split QC's case originally motivated: QC's proposed grant is now precisely `observation_entry.manage`, with `observation_definition.manage` correctly withheld — not "BLOCKED" any more (that was a software-authority impossibility that no longer exists), simply "not proposed" for the definition half, and "proposed but not yet active" for the entry half pending AUTHZ-002B2.

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
| observation_definition.manage | | G (proposed) | | | | | | |
| observation_entry.manage *(see note)* | | | | | | | | |

`observation_entry.manage` is **not** in this table's scope (it is OPERATIONAL, not master data — see the full classification below) and is listed only to make explicit that it was formerly part of the same row as `observation_definition.manage` before AUTHZ-002B1's split; it does not belong in a "master data" scrutiny list at all now that the split has separated it out.

**Confirmed, revised per AUTHZ-002B1**: no routine floor role (`operator`, `packing_supervisor`, `cold_store_supervisor`, `dispatch_officer`) and no pure-visibility role (`auditor`, `read_only`) touches *any* of these master-data permissions. Master-data/configuration authority is concentrated in exactly three roles (`farm_manager` for infrastructure, `head_grower` for agronomic catalog/workflow/observation-definition, `storekeeper` for seed-lot intake) — all proposed grants, none active yet outside `farm_manager`'s and `head_grower`'s permissions already covered elsewhere. `production_supervisor` and `qc_officer` get `observation_entry.manage` (proposed) but correctly never get `observation_definition.manage` — the split (§5A) resolved the prior all-or-nothing bundling without changing who should hold configuration authority. Routine operational personnel cannot casually change farm configuration under this design, and no role gains configuration authority merely to work around a coarse permission — the split exists specifically so that stops being necessary.

### Full manage-permission classification (all 22, post-split)

Requested by AUTHZ-002B1 §14: classify every `.manage` permission as MASTER DATA, OPERATIONAL, CONTROL/QUALITY, or ADMINISTRATION. This supersedes the single, internally-mixed `observation.manage` classification that existed before the split.

| Permission | Classification |
|---|---|
| farm.manage | MASTER DATA |
| location.manage | MASTER DATA |
| asset.manage | MASTER DATA |
| carrier.manage | OPERATIONAL (input) |
| movement.manage | OPERATIONAL |
| crop.manage | MASTER DATA |
| production_system.manage | MASTER DATA |
| workflow.manage | MASTER DATA |
| crop_batch.manage | OPERATIONAL (mixed — creation is planning-adjacent, transition is routine execution) |
| batch_derivation.manage | OPERATIONAL |
| seed_lot.manage | OPERATIONAL (input) |
| sowing.manage | OPERATIONAL |
| transplant.manage | OPERATIONAL |
| **observation_entry.manage** | **OPERATIONAL / QUALITY ENTRY** (AUTHZ-002B1 — routine data capture, no configuration authority) |
| **observation_definition.manage** | **MASTER DATA** (AUTHZ-002B1 — defines what can be recorded tenant-wide; immutable-once-created semantic fields, enforced by a DB trigger, reinforce that this is master data, not a transaction) |
| quality_hold.manage | CONTROL/QUALITY |
| harvest.manage | OPERATIONAL |
| packing.manage | OPERATIONAL |
| finished_goods_storage.manage | OPERATIONAL |
| dispatch.manage | OPERATIONAL, elevated CONTROL characteristics |
| recall.manage | CONTROL/QUALITY |
| tenant.members.manage | ADMINISTRATION |

The former single `observation.manage` row was necessarily classified as an internally-mixed OPERATIONAL/CONTROL hybrid (it was the sharpest example of that problem in the whole catalog — see the pre-AUTHZ-002B1 revisions of this document). That classification is now retired: the two successor permissions each have one clean, unambiguous classification, matching the goal stated in the ticket that motivated this split.

---

## 12. Matrices (proposal only — NOT active as real `ROLE_PERMISSIONS` grants)

Two distinctions matter here, not one: (a) Imperial Pilot vs. External Commercial V1, and (b) **PROPOSED** (this document's recommended policy — every `G` in the matrices below) vs. **ACTIVE** (what `ROLE_PERMISSIONS` actually grants today, in code, right now). As of AUTHZ-002B1, the entire permission catalog needed to implement this proposal exists (including the observation entry/definition split), but **zero non-admin role has any active grant** — `tenant_admin` is the only role with anything active. The former separate "CURRENT IMPLEMENTABLE" vs. "POST-P0-SPLIT DESIRED" distinction from AUTHZ-002A.2 is retired: it existed only because the observation split didn't exist yet as real permissions, forcing a separate, explicitly-not-grantable table. That's no longer true — the split is implemented, so its proposed grants now live directly in Matrix A/B below like every other permission's proposed grants, with the standard caveat that *no* non-admin proposed grant in this document is active until its own implementation ticket runs (AUTHZ-002B2 for the observation permissions specifically).

### MATRIX A — Imperial Pilot (proposed policy; only `tenant_admin` is active today)
One active farm, small trusted team, SOP compensation acceptable where explicitly justified (§6 only, for `quality_hold.manage`).

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
| observation_entry.manage | G | – | G | G | G | – | G | – | – | – | – | – |
| observation_definition.manage | G | – | G | – | – | – | – | – | – | – | – | – |
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

`*` = `farm_manager`'s `dispatch.manage` is the "broader pilot" tier grant (§3.B); use the "minimum viable" tier (§3.A, remove this one cell) for a more conservative pilot posture. `production_supervisor`/`operator`/`qc_officer`'s `observation_entry.manage` cells are real proposed `G`s as of AUTHZ-002B1 (no longer BLOCKED — that was a software-authority impossibility that no longer exists) but are **not active** in `ROLE_PERMISSIONS` until AUTHZ-002B2 implements this proposal, exactly like every other non-`tenant_admin` `G` in this matrix.

Grant totals (mechanically verified against this matrix, AUTHZ-002B1): TA **42**, FM 26 (broader tier) / 25 (minimum tier), **HG 25** (was 24 — gains `observation_definition.manage` in addition to the renamed entry permission), **PS 24** (was 23 — no longer BLOCKED from `observation_entry.manage`), **OP 16** (was 15 — no longer BLOCKED), SK 6, **QC 19** (was 18 — no longer BLOCKED), PK 12, CS 11, DO 11, AU 20, RO 20.

### MATRIX B — External Commercial V1
Multi-user, potentially multi-farm customer; stronger segregation; fewer manual controls accepted.

Identical to Matrix A **except**:
- `farm_manager` uses the **minimum viable** tier (25) — `dispatch.manage` removed; an external farm_manager does not get open-ended backup authority over the highest-stakes non-recall action by default.
- `farm_manager`'s `recall.manage` is retained but **conditionally flagged**: do not onboard with this grant live until the recall open/close split (§13, P1) has shipped, or restrict to `tenant_admin`-only for that customer in the meantime (§10.B).
- `qc_officer`'s `quality_hold.manage` is retained but **flagged P1**: the place/release split should ship at or shortly after external launch — SOP alone (acceptable for the pilot's trusted small team, §6) is a weaker control for an external customer.
- `operator`, `production_supervisor`, and `qc_officer`'s proposed `observation_entry.manage` grant is **not recommended to activate for external commercial rollout** until AUTHZ-002B2 actually ships it as a real grant — the permission-model blocker is resolved (AUTHZ-002B1), but for a customer paying for the product, a role that still cannot perform a core, obvious floor task (recording an observation) because the grant was never activated is a product-quality problem, not just a security nicety.
- `storekeeper`'s narrow scope (§7) becomes a **P1** gap rather than an acceptable pilot limitation — an external paying customer is more likely to expect real input/store tracking as a baseline feature.
- **Multi-farm caveat (§1)**: this matrix assumes either a single-farm customer or that farm-scoped role assignment has been implemented. For a genuinely multi-farm external customer without that, granting any operational role to an individual gives them that authority across **every** farm in the tenant, not just their assigned site. This is a **P0** blocker for that customer segment specifically (§1, §13) — not solved by this permission matrix, and not safe to paper over with role choice alone. The available interim mitigation is provisioning one CMP tenant per farm for that customer (CMP is already multi-tenant), accepted explicitly, not silently.
- `auditor` vs `read_only` remains identical (§9); flagged as a discoverability question a compliance-conscious paying customer may explicitly ask about, elevating `audit.read` from a "nice to have" toward something worth prioritizing sooner.

Matrix B's `observation_entry.manage` cells for `production_supervisor`, `operator`, and `qc_officer` are inherited unchanged from Matrix A as **proposed** grants (same permission-model reality regardless of pilot-vs-external deployment shape) — whether to *activate* them sooner or later for an external customer is the recommendation immediately above, not a difference in what's technically proposed. Every other Matrix B reduction from Matrix A is a risk-based recommendation (flagged, conditional, or role-not-recommended), not a hard technical impossibility, and is stated as such rather than dressed up as a blocker it isn't.

---

## 13. Revised priority gaps (P0/P1/P2)

| # | Gap | Imperial pilot | Multi-farm Imperial | External SaaS |
|---|---|---|---|---|
| 1 | Farm-scoped role assignment (no user/role↔farm restriction exists — §1) | P2 (no impact, single farm) | P1 | **P0** |
| 2 | `observation.manage` bundled routine entry + definition configuration (§5, §5A) | **TECHNICALLY RESOLVED at the permission-model level (AUTHZ-002B1)** — `observation_entry.manage`/`observation_definition.manage` now exist and are correctly wired. **Not resolved operationally**: `ROLE_PERMISSIONS` still grants nothing to `production_supervisor`/`operator`/`qc_officer` — activating this document's proposed grants is AUTHZ-002B2's job and remains its own required step, tracked as a normal implementation task rather than a granularity P0 | Same — activation still pending | Same — activation still pending |
| 3 | `quality_hold.manage` bundles place+release (§6) | P1 (SOP acceptable interim) | P1 | P1 |
| 4 | `recall.manage` bundles open+close (§10) | P1 (role-restriction mitigates) | P1 | P1 (gates `farm_manager`'s grant in Matrix B) |
| 5 | No general Input/Store module/permissions (§7) | P1 | P1 | P1 |
| 6 | No `audit.read` — `auditor`/`read_only` indistinguishable (§9) | P2 | P2 | P2 (discoverability risk with compliance-focused customers) |
| 7 | `crop_batch.manage` bundles creation + stage-transition | P2 | P2 | P2 |
| 8 | `dispatch.manage` lacks a confirm/dual-control step | P2 | P2 | P2 |

**Post-AUTHZ-002B1 status**: the observation-granularity item (#2) — previously the sole disciplined P0 blocking the Imperial pilot — is now technically resolved. What remains before the Imperial pilot can actually use `production_supervisor`/`operator`/`qc_officer` observation recording is a normal implementation step (AUTHZ-002B2 activating this document's already-proposed grants in `ROLE_PERMISSIONS`), not a further design or granularity problem. Item #1 (farm-scoped role assignment) remains correctly excluded from the pilot's own P0 list — P2 for the Imperial single-farm pilot itself, with no practical effect until a second farm or an external multi-farm customer is in scope. Everything else (#3–#8) remains a real, tracked hardening item for external commercialization, unaffected by this ticket.

---

## Summary of what this document does NOT do

- Does not modify `app.core.permissions.Permission` or `ROLE_PERMISSIONS`.
- Does not add, remove, split, or rename any permission.
- Does not add, remove, or merge any role.
- Does not implement farm-scoped authorization.
- Does not change any router, service, model, schema, or migration.
- Is a design/policy proposal for a future, explicitly-scoped implementation ticket to act on.
