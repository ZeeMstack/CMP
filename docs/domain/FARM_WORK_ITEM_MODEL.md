# Farm Work Item and Shift Handover Model

Full detail: `CLAUDE.md` rules 6, 7, 10, 12; the PILOT-OPS-001 ticket ("Today on the Farm"). This document summarizes the approved model; it does not restate the ticket.

## What a Farm Work Item is, and is not

A `FarmWorkItem` is a small, operator-facing task/assignment record. It is **never** a substitute for the authoritative GrowCMP transaction it may relate to: harvesting a batch is recorded by a Harvest command, observing a batch by an Observation command — a Work Item only tracks that the work was assigned/started/blocked/completed, and, for operational work, which authoritative record proves it happened.

A CURRENT-STATE row (ADR-005), like `CropBatch`/`Location`: identity/content fields (tenant/farm, code, `work_type`, `category`, `title`, `instructions`, context references, `completion_mode`, `created_by_user_id`/`created_at`, and the creation command's own idempotency pair) are frozen for life by a DB trigger; only lifecycle fields (`status`, `priority`, `due_at`, `assigned_to_user_id`, `blocked_*`, `completed_*`, `result_*`, `cancelled_*`, `updated_at`, and each command's own idempotency evidence) ever change, and only through the service commands below. Full lifecycle history (created/assigned/started/blocked/unblocked/completed/cancelled) is read from the existing `audit_events` table (`entity_type = 'farm_work_item'`), never duplicated into a second event model.

## Identity

UUID primary key plus a server-generated, immutable human-readable `code` (`FW-YYYYMMDD-NNN`, sequential per tenant per farm-local calendar date, serialized by a `pg_advisory_xact_lock` — the same convention `nursery_service._generate_batch_code` established). The UUID is never the operator-facing identity.

## Status lifecycle

`OPEN → IN_PROGRESS → BLOCKED → COMPLETED / CANCELLED`, frozen at exactly these five values — no "done-ish" intermediate state. `COMPLETED` and `CANCELLED` are terminal; no reopen command exists in this ticket (a genuine, documented gap — see `docs/product/OPEN_QUESTIONS.md`).

- **Start** (`OPEN → IN_PROGRESS`): only when unassigned or assigned to the calling operator.
- **Block** (`OPEN`/`IN_PROGRESS → BLOCKED`): requires a non-blank `reason`, stored as free text plus `blocked_at`/`blocked_by_user_id` — no reason taxonomy yet (matches the ticket's own instruction).
- **Unblock/Resume** (`BLOCKED → IN_PROGRESS`): always resumes into `IN_PROGRESS` — a deliberate simplification (blocking directly from `OPEN` is rare, and resuming means the work is active again regardless of its exact pre-block state). Clears `blocked_reason`/`blocked_at`/`blocked_by_user_id`; the full block reason remains visible in history via `audit_events`.
- **Cancel**: supervisory only, from any non-terminal state.
- **Update** (reassign / change priority / change due window): one combined supervisory command with fully-specified target values (never a partial PATCH), covering "assign/reassign work", "change priority/due window" from the ticket's role list.

## Priority

`NORMAL` / `HIGH` / `CRITICAL` only — influences board ordering, never domain truth.

## Completion modes

- **`MANUAL_RECORD`** — completed via an explicit `complete` command, recording `completed_by_user_id`/`completed_at`/an optional `completion_note`. Used for genuinely manual work (cleaning, inspection, preparation).
- **`OPERATIONAL_RECORD`** — can **never** be completed via the manual `complete` command (rejected outright, `FarmWorkItemManualCompletionNotAllowedError`). It reaches `COMPLETED` only through `link_operational_result`, which stores `result_entity_type` (currently `harvest_event` or `observation_event`), `result_entity_id`, and `result_recorded_at` — the structured answer to "what record proves this work was completed?", never free-text evidence.

`completion_mode` is fixed at creation and is one of the identity fields the DB trigger freezes — an item cannot switch modes after the fact.

## Transaction-backed completion mechanism

`farm_work_item_service.link_operational_result` is the one reusable linking primitive, called by a domain service (`harvest_service.record_harvest`, `observation_service.record_observation`) **after** its own authoritative command has already committed — never before, and it never re-executes that command:

- **Idempotent by `client_command_id`** like every other command (unique per tenant, its own `link_result_client_command_id`/`link_result_request_fingerprint` column pair).
- **Idempotent by result reference, independent of the command id**: if the Work Item is already `COMPLETED` with the *exact same* `result_entity_type`/`result_entity_id`, a call with a *different* `client_command_id` (e.g. a UI reconciliation retry) is a harmless no-op, not an error.
- **A genuinely different result on an already-completed item is a conflict** (`FarmWorkItemResultConflictError`) — never silently overwritten.

`link_operational_result_best_effort` wraps this for the Harvest/Observation call sites: it swallows any exception and returns `"linked"`/`"failed"` for the response's own `work_item_link_status` field, so a link failure is never surfaced as if the Harvest/Observation itself failed, and the caller never repeats that command to retry the link. A UI can retry a failed link via the same `link_operational_result` command exposed at `POST /farms/{farm_id}/work-items/{id}/link-result` — the reconciliation path the ticket asks for.

## Context model

Structured, typed references only — never one opaque JSON blob, and never a fake mandatory reference. All optional: a pump-maintenance task has no Batch; a harvest task has crop/Batch/location context.

- `crop_batch_id` (composite FK to `crop_batches`)
- `location_id` (composite FK to `locations`)
- `carrier_id` (composite FK to `carriers`; this ticket adds `uq_carriers_tenant_farm_id`'s sibling on `assets`, `uq_assets_tenant_farm_id`, mirroring CMP-018's identical addition to `locations`)
- `asset_id` (composite FK to `assets`)
- `quantity` + `quantity_uom_id` (FK to the global `unit_of_measures` catalog)

**QR-compatibility (design now, build in PILOT-SCAN-001 next):** every context reference is a real, stable entity id a future scan can resolve straight into — never a display string, never something reconstructed from free text.

## Shift Handover — Pilot V1

`ShiftHandover` (+ `ShiftHandoverItem`, a pure join to optionally-flagged Work Items) is fully immutable, insert-only — no update, no delete, no status. Creating a handover never mutates, closes, or clones any Work Item it references; open work stays open. Today on the Farm shows the most recent handover (by `effective_time`) prominently but secondarily, above the work board, never as a KPI.

## Authorization

Three tiers, mapped onto the existing `Permission`/`ROLE_PERMISSIONS` architecture (`app.core.permissions`) — no second authorization system:

- `farm_work_item.read` — view.
- `farm_work_item.manage` — supervisory: create, reassign/reprioritize/change due window, cancel.
- `farm_work_item.execute` — floor: start/block/unblock assigned-or-available work, complete permitted (manual) work, author a Shift Handover, and link an operational result.

The `.manage`/`.execute` split mirrors this catalog's existing entry-vs-definition precedent (`OBSERVATION_ENTRY_MANAGE`/`OBSERVATION_DEFINITION_MANAGE`) — a role trusted to execute routine floor work should not automatically gain create/assign/cancel authority, and vice versa. Both are granted together only to `tenant_admin` (automatic) and `production_supervisor`; `farm_manager`/`head_grower` hold `.manage` only (they don't execute floor work); every specialist floor role (`operator`, `storekeeper`, `qc_officer`, `packing_supervisor`, `cold_store_supervisor`, `dispatch_officer`) holds `.execute` only; `auditor`/`read_only` hold `.read` only. See `docs/domain/AUTHORIZATION_MODEL.md`'s permission catalog table and `docs/domain/ROLE_PERMISSION_POLICY_PROPOSAL.md` for the full inventory this activation extends.

## Today on the Farm

Reuses the existing Farm Home route (`app/farms/[farmId]/page.tsx`) — no second competing Home. One bounded board read (`GET /farms/{farm_id}/work-items`, non-terminal items only) is bucketed client-side into My Work / In Progress / Blocked / Carryover / Farm Work by a pure function (`lib/format/workItemBoard.ts::bucketWorkItems`), mirroring `computeHomeKpis`/`groupBatchesByStage`'s established pattern — one backend read, several page-level lenses over it, not one endpoint per section.

**Carryover** is derived, never a nightly job: an item's "work date" (`due_at`, or `created_at` when no due date was set) compared against the farm's own local calendar date (`Intl.DateTimeFormat` in `farm.timezone`, never a naive UTC slice or the browser's local zone).

**Ready Now** (harvestable Leafy plates) and **Attention** (batches with an open quality hold) are LIVE operational-readiness reads, aggregated from the existing `leafy-production/harvestable-plates` and `crop-batches/operational-summary` endpoints — deliberately never duplicated into persisted Work Items, and each rendered with its own independent loading/error/empty state so a failed live source can never be silently read as "nothing to do."

## Leafy/Vines Harvest linkage (PILOT-OPS-001 closure)

The real operator-facing Leafy Harvest route (`POST /farms/{farm_id}/leafy-production/harvests`) and Vines Harvest route (`POST /farms/{farm_id}/vines-production/harvests`) both accept the identical optional `work_item_id` the generic Harvest route already did — both share the exact same `HarvestEvent`/`HarvestedProduceLot` result shape, so the same `link_operational_result_best_effort` wiring applies unchanged, with no second completion path invented. The Leafy Harvest page (`app/farms/[farmId]/leafy-production/harvest/page.tsx`) reads `?batchId=`/`?workItemId=` from a Work Item's own "Open Harvest" link (`WorkItemRow.tsx`, shown only for `work_type === "harvest"` items with Batch context), pre-filters the harvestable-plates panel to that Batch, and only forwards the Work Item id when the Harvest actually recorded is for the matching Batch — never blindly attached to an unrelated Harvest. On a failed link, the already-successful Harvest (its Harvest Lot, weight/count totals, idempotency, source-removal guards — everything about the Harvest command itself) is completely unaffected; the success panel offers a "Retry linking work item" action that calls the *same* `link_operational_result` reconciliation endpoint directly against the already-known Harvest Lot's `harvest_event_id`, never re-submitting the Harvest command.

**Vines is wired on the backend** (identical, structurally-required-nothing-extra change) but **not linked from the frontend board**: `FarmWorkItem` carries no crop-classification signal (Leafy vs. Vines) to route "Open Harvest" to the correct operator page automatically, and guessing would be worse than not linking. A future ticket that gives a Work Item (or its Batch) a resolvable crop/production-system classification can add the equivalent Vines link in `WorkItemRow.tsx` with no further backend change.

## Manual Work Item structured context (PILOT-OPS-001 closure)

The Create form's "Add context" disclosure exposes four optional selects — Location, Batch, Asset, Carrier — each populated from an already-fetched farm-scoped read Today on the Farm's own page already needs or cheaply adds (`useLocationsTree` flattened via the existing `flattenLocationTree` helper, `useOperationalSummary` reused as-is, `useAssets`/`useCarriers` farm-wide). Every option's value is the real entity id, never a display string — the same ids PILOT-SCAN-001 will later resolve from a QR scan. All four are independently optional and may be combined (e.g. Batch + Location together); board rows (`WorkItemRow.tsx`) render every structured piece the item actually carries and nothing for the kinds that don't apply — never an empty placeholder. Backend validation is unchanged: `create_work_item` already resolved each context id through the same tenant+farm-scoped lookup every other domain in this codebase uses (`location_service.get_location`, etc.), so a foreign-farm or cross-tenant id was already rejected before this closure — this pass only proved it with a dedicated test.

## Deferred / known gaps

- **Reopen**: no command to move `COMPLETED`/`CANCELLED` back to an active state.
- **Vines Harvest has no frontend "Open Harvest" link** — see "Leafy/Vines Harvest linkage" above; the backend linkage is fully wired and tested.
- **No user-name resolution anywhere in this app** (pre-existing, documented gap — see `docs/product/OPEN_QUESTIONS.md`'s "Crop Observations operator UI decisions"). Work Item rows show "You"/"Assigned"/"Unassigned", never a raw UUID or a name.
