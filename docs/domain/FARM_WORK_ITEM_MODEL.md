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

## Deferred / known gaps

- **Reopen**: no command to move `COMPLETED`/`CANCELLED` back to an active state.
- **Manual creation UI has no location/asset/carrier/batch picker yet** — the compact Create form (`CreateWorkItemForm`) covers the ticket's own manual examples (cleaning/inspection/preparation, which need no such context); creating an `OPERATIONAL_RECORD` item with real context is currently backend-only (proven by the Harvest/Observation integration tests). A future ticket adding real location/asset/batch pickers should wire this form up to them.
- **Leafy/Vines Harvest recording pages are not yet wired to pass `work_item_id`** — those pages call the specialized `leafy-production`/`vines-production` harvest endpoints, not the generic `POST /farms/{farm_id}/crop-batches/{batch_id}/harvests` endpoint this ticket extended (already fully tested end-to-end). Wiring the specialized endpoints is a separate, larger frontend+backend change, deliberately out of this ticket's scope ("do not modify ten operational modules"). Observation recording *is* wired (the Observations page already uses the one generic endpoint).
- **No user-name resolution anywhere in this app** (pre-existing, documented gap — see `docs/product/OPEN_QUESTIONS.md`'s "Crop Observations operator UI decisions"). Work Item rows show "You"/"Assigned"/"Unassigned", never a raw UUID or a name.
