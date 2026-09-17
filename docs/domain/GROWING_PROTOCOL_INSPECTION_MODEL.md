# Growing Protocol and Crop Inspection Model

Full detail: `CLAUDE.md` rules 1, 6, 7, 9, 10, 12; the PILOT-AGRO-001 ticket. This document summarizes the approved model; it does not restate the ticket.

## Product questions this domain answers

1. What SHOULD happen to this crop? — `GrowingProtocol`/`GrowingProtocolVersion`/`ProtocolObservationRequirement`/`ProtocolCareActivity`.
2. What stage is it ACTUALLY in? — the existing `BatchStageRun`/`WorkflowStage`, read, never duplicated.
3. What grower checks are due? — `growing_protocol_service.get_batch_protocol_status`, a deterministic read.
4. What was actually observed? — `GrowerInspection`/`InspectionFinding`, plus the existing `ObservationEvent`.
5. Is there a crop problem? — `CropIssue`.
6. What action was assigned? — a `FarmWorkItem` linked via `crop_issue_id`.
7. Was follow-up performed? — `CropIssueFollowUp`.
8. Did the crop improve, remain unchanged, worsen, or resolve? — `CropIssueFollowUp.outcome`.

## Frozen domain rules

- **PROTOCOL != ACTUAL FARM EVENT.** A `GrowingProtocolVersion`/`ProtocolObservationRequirement`/`ProtocolCareActivity` states what SHOULD happen. It never proves an operation happened — only a `GrowerInspection`, `ObservationEvent`, or other authoritative farm transaction does.
- **AGE != STAGE.** Age (days since stage entry) can make an inspection due, show expected timing, and flag deviation (`get_batch_protocol_status`'s `is_due`/`is_overdue`/`is_outside_expected_window`). It never automatically advances `CropBatch`/`BatchStageRun`, moves/transfers plants, marks Harvest ready, or creates a farm event — the due/deviation read touches no table beyond `SELECT`.
- **ISSUE != LOSS.** Opening, updating, diagnosing, or following up a `CropIssue` never writes to `BatchCarrierAssignment.released_effective_time`, `CropBatch.state`, or any disposition/loss table. `InspectionFinding.affected_count` is descriptive only.
- **SUSPECTED CAUSE != CONFIRMED DIAGNOSIS.** `CropIssue.suspected_cause` and `CropIssue.confirmed_diagnosis` are two permanently distinct columns. `confirm_diagnosis` never reads or copies `suspected_cause`; it only ever writes `confirmed_diagnosis`/`diagnosis_confirmed_by_user_id`/`diagnosis_confirmed_at`.
- **ABNORMAL/WEAK != LOSS.** A weak/abnormal finding recorded on a living Batch never reduces `crop_batches`/`batch_carrier_assignments` living quantity — only an explicit, separately-owned Loss/Disposition command (existing domain, unchanged) does that.
- **WORK ITEM COMPLETE != ISSUE RESOLVED.** `farm_work_item_service.complete_work_item`/`link_operational_result` never touch `crop_issues`. Resolution (`resolve_crop_issue`) and closure (`close_crop_issue`) are always separate, deliberate, authorized commands.

## Growing Protocol identity and versioning

`GrowingProtocol` is the versioned identity of one agronomic program (e.g. "Iceberg Lettuce — DWC — Summer Standard"), scoped by the EXISTING `Crop`/`Variety`/`ProductionSystem` catalogs (mirrors `Workflow`'s own applicability shape) plus an optional free-text `season_context`. Identity fields: an immutable, tenant-unique human-readable `code` (caller-supplied, like `Workflow.code` — not server-generated, since it encodes crop/system/program semantics a sequence number cannot) and `name`. `status` (`active`/`inactive`) governs whether the identity itself is selectable for new versions — separate from any one version's own lifecycle.

`GrowingProtocolVersion` carries all agronomic content and has its own `DRAFT -> ACTIVE -> RETIRED` lifecycle (`growing_protocol_service.create_draft_version`/`activate_version`/`retire_version`), mirroring `WorkflowVersion`'s `draft -> published -> retired` shape and `GradeDefinitionVersion`'s per-command idempotency-column convention exactly:

- **DRAFT**: editable — `add_observation_requirement`/`add_care_activity` only succeed while `state = 'draft'` (`GrowingProtocolVersionNotDraftError` otherwise, checked in the service, the same place `workflow_service.add_stage` checks `WorkflowVersionNotDraftError` — no DB trigger duplicates this).
- **ACTIVE**: agronomic content immutable. Activating a version automatically retires the protocol's previously-ACTIVE version in the same transaction (its `retirement_client_command_id` stays `NULL`, distinguishing "superseded by replacement" from an explicit `retire_version` call — mirrors `GradeDefinitionVersion`'s identical convention). A DB partial unique index (`ux_growing_protocol_versions_active_once`) enforces at most one ACTIVE version per protocol.
- **RETIRED**: not selectable for new Batch assignments, but remains permanently, historically valid and readable — never hard-deleted.

Required metadata: `version_number` (server-assigned, `max + 1`), `author_user_id`, `reason` (required, non-blank — why this version exists), `effective_date` (an optional advisory planned date, independent of the lifecycle's own `activated_at`/`retired_at`), `created_at`, `activated_at`, `retired_at`.

### Protocol Stage Requirements

Mapped to the EXISTING workflow/stage concept — never a second crop lifecycle. `ProtocolObservationRequirement` and `ProtocolCareActivity` are both keyed by `stage_category` (`seeding`/`germination`/`nursery`/`transplanting`/`intermediate`/`production`/`harvest_ready`/`harvesting`/`completed`/`rejected` — `WorkflowStage`'s own existing, crop-agnostic classification), deliberately **not** a specific `workflow_stage_id` row: a `GrowingProtocolVersion` is scoped to Crop/Variety/ProductionSystem, not pinned to one exact `WorkflowVersion`, so pinning to one `WorkflowVersion`'s own stage row would silently orphan the requirement the moment that crop's workflow is republished (CMP-008 makes every past `WorkflowVersion` permanent and never edited in place). `stage_category` stays valid across every workflow version a Batch of that crop might run.

**`stage_category` granularity (PILOT-AGRO-001A domain closure review).** Confirmed against the pilot's own live template (`config/pilot/iceberg-pilot.example.yaml`) that more than one real `WorkflowStage` within a SINGLE `WorkflowVersion` can share one `stage_category` — that template's `INTO_INTERSALADS` (Seedling → InterSalads) and `PRODUCTION_TRANSFER` (InterSalads → Production) stages are BOTH `stage_category = 'transplanting'`. A requirement keyed by `stage_category` alone would therefore apply to both real moves even when only one was intended, and `stage_category` is otherwise too coarse for that one case (every other pilot distinction the review checked — Sowing/Germination/Seedling-care/Production/Harvest-ready — maps to its own distinct category with no collision). Closed with the smallest crop-agnostic fix: both models gained an optional `stage_sequence_index` (1-based). `NULL` (unchanged default) applies to every occurrence of the category, exactly as before this review. A positive integer narrows the requirement to the Nth occurrence of that `stage_category`, ordered by `display_order`, WITHIN WHICHEVER `WorkflowVersion` a Batch actually runs — resolved fresh at read time (`get_batch_protocol_status` computes the Batch's current stage's own occurrence rank among its `stage_category` siblings and filters against it), never persisted against one specific `WorkflowVersion`. This preserves full protocol portability: the same "occurrence 2 of transplanting" concept remains meaningful across different workflow versions of the same crop, exactly as `stage_category` itself already assumes. Proven by `test_stage_sequence_index_disambiguates_same_category_stages`.

`ProtocolObservationRequirement` REFERENCES an existing `ObservationDefinition` (never duplicates its value/unit/range architecture): `requirement_level` (`required`/`recommended`), optional `frequency_days` (repeat interval), optional `due_window_start_days`/`due_window_end_days` (days since stage entry), optional `stage_sequence_index`, `instructions`, `escalation_guidance`, `display_order`.

`ProtocolCareActivity` is a small, structured, non-dosing expectation: `activity_type` (`inspect_roots`/`scout_pests`/`pruning`/`training`/`spacing`/`crop_hygiene`/`transfer_readiness`/`harvest_readiness`/`other`), `title`, `instructions`, `frequency_days`, optional `stage_sequence_index` (stored for parity; no current read filters a Care Activity by it — only the Observation Requirement due-read does, as of this review), `display_order`. Explicitly **excludes** nutrient recipes, dosing, and irrigation management (PILOT-WATER-001 territory).

### Protocol content completeness (PILOT-AGRO-001A domain closure review)

Every frozen pilot concept the review checked is already expressible without further schema change:

| Concept | Status | How |
|---|---|---|
| Expected stage/window guidance | SUPPORTED | `ProtocolObservationRequirement.due_window_start_days`/`due_window_end_days`, feeding `is_outside_expected_window` |
| Required/routine Observation Definitions | SUPPORTED | `ProtocolObservationRequirement.observation_definition_id` + `requirement_level` |
| Inspection frequency | SUPPORTED | `ProtocolObservationRequirement.frequency_days` |
| Crop-care activities | SUPPORTED | `ProtocolCareActivity` |
| Spacing guidance | SUPPORTED VIA EXISTING RELATED ENTITY | `ProtocolCareActivity.activity_type = 'spacing'` + free-text `instructions` (no structured spacing value/unit field — intentionally small, matches the ticket's own "keep small" instruction) |
| Environmental/agronomic target guidance | SUPPORTED VIA EXISTING RELATED ENTITY | a `ProtocolObservationRequirement` referencing an `ObservationDefinition` that already carries its own `min_value`/`max_value` (CMP-010) — no duplicate EC/pH/environment model; not whether Water/Nutrient telemetry exists yet, per the review's own framing |
| Harvest-readiness criteria | SUPPORTED VIA EXISTING RELATED ENTITY | `stage_category = 'harvest_ready'` + `ProtocolCareActivity.activity_type = 'harvest_readiness'` (descriptive criteria) + an Observation Requirement with a due window at that stage (measurable trigger) |
| Escalation/deviation guidance | SUPPORTED | `ProtocolObservationRequirement.escalation_guidance` (direct field) |

No dedicated harvest-readiness or escalation model was added — composing the existing primitives already covers both without forcing a new one.

## Batch → Protocol Version assignment

`BatchProtocolAssignment` preserves full history — mirrors `BatchStageRun`'s own "one open-ended current row per Batch, closed by setting the previous row's own end timestamp when superseded" shape exactly (`ux_batch_protocol_assignments_active_batch`, a partial unique index on `batch_id WHERE effective_to IS NULL`). `assign_batch_protocol` requires the target version to be `ACTIVE` (`BatchProtocolVersionNotActiveError` otherwise); changing from V1 to V2 closes V1's row (`effective_to = <new effective_from>`) and inserts V2's row in the same transaction, so "Batch used V1 until X" / "Batch used V2 from X" is always readable directly from history — no historical Observation or Inspection row is ever rewritten. Manual assignment (no automatic protocol selection) is acceptable for the pilot, per the ticket.

**Protocol publication and Batch assignment are independent decisions (PILOT-AGRO-001A domain closure review, confirmed, no code change).** `activate_version` touches only `growing_protocol_versions` rows (retiring the previous ACTIVE version, activating the new one) — it contains no query or statement against `batch_protocol_assignments` at all. A Batch already assigned to V1 keeps its `BatchProtocolAssignment.growing_protocol_version_id` pointing at V1, unchanged, even after V1 is auto-retired by V2's activation; it keeps following the now-RETIRED V1 until an authorized user EXPLICITLY calls `assign_batch_protocol` to move it. Activating a new protocol version never silently migrates any existing Batch.

## Grower Inspection

`GrowerInspection` is a structured, fully immutable (insert-only, `reject_append_only_mutation`), ACTUAL floor record — never proof a protocol requirement was followed. It snapshots `batch_carrier_assignment_id`/`location_id` (the carrier's occupancy at record time, resolved once and stored — never re-derived later, so a subsequent move never changes what an old Inspection says about where it happened) and `growing_protocol_version_id` (the Batch's current assignment at record time, for historical context).

It may reference (never duplicate) the existing Observation architecture: `record_inspection` optionally calls `observation_service.record_observation` in the same command with the same resolved `effective_time`, storing the resulting `observation_event_id` — one `ObservationEvent` can hold many typed `ObservationValue`s, so "GrowerInspection -> links to ObservationEvents" is satisfied by this single reference rather than a second value-storage table.

**One Inspection, many observations (PILOT-AGRO-001A domain closure review).** A single crop walk recording plant height, root condition, pest count, an EC-related visual symptom, uniformity, and a leaf symptom — six DIFFERENT `ObservationDefinition`s — does not require six `GrowerInspection` records, or even six `ObservationEvent` rows: `record_inspection` passes its whole `observation_values` list to ONE `observation_service.record_observation` call, which stores one `ObservationValue` row per distinct definition under the SAME `ObservationEvent` (the unique index `ux_observation_values_batch_target` only forbids the SAME definition twice for the same batch-level target — it never limits how many DIFFERENT definitions one event holds). `GrowerInspection.observation_event_id` being a single FK is therefore already the correct, minimal realization of "GrowerInspection = inspection/crop-walk event; ObservationEvent(s) = zero, one, or many structured observations" — the "many" lives at the `ObservationValue` grain inside one Event, not as multiple Event rows, exactly matching CMP-010's own existing command shape (one command, many values) rather than duplicating it. Proven live during the review (six definitions, one `record_inspection` call, one `ObservationEvent`, six `ObservationValue` rows).

`inspected_count`/`affected_count` (on each `InspectionFinding`) are both optional counts; `affected_count <= inspected_count` is enforced in the service (`GrowerInspectionValidationError`), mirroring `observation_service`'s own established cross-row validation convention (no cross-table DB CHECK exists in Postgres) — never a DB constraint. Recording affected plants never changes living inventory (see Frozen domain rules).

### Findings

`InspectionFinding.category` covers the ticket's practical vocabulary (`vigor`/`uniformity`/`roots`/`leaf_condition`/`pest_evidence`/`disease_like_symptoms`/`physical_damage`/`deficiency_like_symptoms`/`growth_deviation`/`contamination_concern`/`other`) with `severity` (`low`/`medium`/`high`/`critical`), an optional `affected_count`, `notes`, and `suspected_cause` — no pathology ontology, no photo/file-storage infrastructure.

**Photo/evidence deferral (PILOT-AGRO-001A domain closure review).** No generic attachment/evidence/upload primitive exists anywhere in this codebase (backend or frontend) — confirmed by a repository-wide search before this decision, not assumed. Deferring evidence is safe WITHOUT schema impact: a future `InspectionEvidence`/`CropIssueEvidence` table (storing an external object reference — e.g. an S3 key/URL — never a binary blob in this row) would be a purely ADDITIVE child table referencing `grower_inspection_id`/`inspection_finding_id`/`crop_issue_id` by their already-stable UUID primary keys, exactly like `InspectionFinding` itself already references `GrowerInspection`. Nothing about `GrowerInspection`/`InspectionFinding`/`CropIssue`'s own identity, columns, or constraints would need to change to add it later — there is no "reserve a column now" cost to deferring. Building the actual upload/storage architecture (presigned URLs, a storage backend, size/type limits) is out of scope for PILOT-AGRO-001 and PILOT-AGRO-001A alike and is left for a dedicated future ticket once a generic CMP-wide evidence primitive is approved (rather than a Growing-Protocol-specific one-off).

## Crop Issue

`CropIssue` is a CURRENT-STATE row (ADR-005), like `FarmWorkItem`: identity/content fields (tenant/farm, `code`, `batch_id`, placement/location, `originating_grower_inspection_id`/`originating_finding_id`, `category`, `description`, `opened_by_user_id`/`opened_at`, creation idempotency) are frozen for life by `enforce_crop_issue_mutable_fields` (mirrors `enforce_farm_work_item_mutable_fields` exactly); only lifecycle fields (`severity`, `suspected_cause`, diagnosis fields, `status`, `assigned_owner_user_id`, `follow_up_due_at`, resolved/closed fields, and each command's own idempotency pair) ever change.

Human-readable `code` (`CI-YYYYMMDD-NNNN`, sequential per tenant per farm-local date, same `pg_advisory_xact_lock` convention as `farm_work_item_service._generate_work_item_code`).

**Persisted lifecycle is `OPEN -> RESOLVED -> CLOSED` only, never reopened.** The ticket's own "suggested lifecycle" additionally names `ACTION_IN_PROGRESS`/`FOLLOW_UP_DUE`; these are READ-MODEL overlays (`crop_issue_service.read_model_overlays`, exposed as `CropIssueRead.has_open_work_item`/`is_follow_up_overdue`), never persisted statuses — derived from "has an open `FarmWorkItem` linked" and "`follow_up_due_at` has passed", per section 14's own "these may be read-model items" guidance and the ticket's explicit "keep simple" instruction. This keeps the persisted state machine to three states with two deliberate, separate, authorized transitions (`resolve_crop_issue`, `close_crop_issue` — closure only from `resolved`, never directly from `open`), satisfying "Issue closure is deliberate + authorized" without extra transition commands that add no operator-visible signal beyond the overlay.

`suspected_cause` (copied from the originating Finding at open time, further editable via `update_crop_issue`) and `confirmed_diagnosis` (`confirm_diagnosis`, a separate authorized command) are permanently distinct — see Frozen domain rules.

**Inspection → Issue cardinality (PILOT-AGRO-001A domain closure review, confirmed, no code change).** `CropIssue.originating_grower_inspection_id` is a plain FK with no uniqueness constraint — one Inspection with several significant Findings (e.g. one pest finding and one unrelated disease-like-symptom finding recorded in the same crop walk) may legitimately open MULTIPLE `CropIssue` rows, each via its own `open_crop_issue` command with its own `originating_finding_id`. `CropIssueFollowUp.crop_issue_id` likewise has no cardinality limit — repeated follow-ups are ordinary inserts. Neither a follow-up nor an Issue resolution ever mutates `GrowerInspection`/`InspectionFinding` (both are insert-only tables; `crop_issue_service` never issues an `UPDATE` against either).

## Issue Actions — Work Item linkage

Reuses `FarmWorkItem` — no second task table. `farm_work_items.crop_issue_id` (new nullable column, additive) is set only at Work Item creation (`farm_work_item_service.create_work_item(..., crop_issue_id=...)`), frozen for life by the extended `enforce_farm_work_item_mutable_fields` trigger, exactly like the four pre-existing context columns (`crop_batch_id`/`location_id`/`carrier_id`/`asset_id`). There is deliberately no retrofit command to link an already-created Work Item — a Crop Issue's corrective work is always a NEW Work Item carrying this reference from the start.

Flow: Crop Issue -> operator (or supervisor) creates a Work Item with `crop_issue_id` set -> operator performs the actual work -> Work Item completes (`complete_work_item`, unchanged) -> Crop Issue **remains open** -> grower performs a follow-up Inspection/`CropIssueFollowUp` -> an authorized user deliberately resolves, then closes, the Issue.

## Follow-up

`CropIssueFollowUp` is fully immutable (insert-only), referencing the parent `CropIssue` and, optionally, a follow-up `GrowerInspection`. `outcome` is `IMPROVED`/`UNCHANGED`/`WORSENED`/`RESOLVED`. Recording a `RESOLVED` outcome never silently transitions the parent Issue — `resolve_crop_issue` must still be called deliberately (see Frozen domain rules).

## Due / deviation read (`get_batch_protocol_status`)

A deterministic, read-only function over already-recorded facts only: the Batch's current `BatchStageRun` (actual stage + entry time), the current `BatchProtocolAssignment`, that version's `ProtocolObservationRequirement`s for the current `stage_category`, and the most recent `ObservationEvent`/`ObservationValue` touching each required `ObservationDefinition` since stage entry. Returns `is_due`/`is_overdue`/`is_outside_expected_window`/`last_satisfied_at` per requirement, plus `open_crop_issue_count`. Never writes anything (no `INSERT`/`UPDATE` anywhere in its call path) — proven by `test_due_read_never_mutates_batch_or_stage`.

Example (ticket's own): a protocol names "Expected transfer: Day 25–30"; a Batch is actually at day 31. The read reports `is_outside_expected_window = True`; the UI displays "Outside expected protocol window. Grower review recommended." Nothing is automatically transferred or blocked.

## Operator frontend (PILOT-AGRO-001B)

The frontend operator workflow built directly on the frozen backend surface above, with no backend redesign:

- **Protocol administration** — `/growing-protocols` (tenant-wide, top-level route registered under `AppShell`'s Setup → "Company catalogs", not farm-scoped — it sits alongside every other tenant-wide master-data catalog, e.g. Workflows, Grade Definitions). Deliberately kept secondary to floor operations (CLAUDE.md "usability" + this ticket's own UX principle): no dashboard, a compact list, a per-Protocol version catalog, and a version editor for Observation Requirements/Care Activities. The compact list's columns (Code/Name/Crop/Variety/Production system/Season/Active version/Status) resolve Variety and Active Version through the same bounded `useQueries` reference-catalog fan-out already established by `useGradeVersionLabelMap` (tenant-wide master-data scale, not per-Batch operational scale) — `useVarietiesForCrops`/`useProtocolActiveVersionMap` in `lib/query/hooks.ts` — never a per-row detail fetch triggered on scroll/interaction. Activation always shows: *"Activating this version retires the currently active version. Existing Batch assignments are not automatically changed."* before the command runs — **Protocol publication ≠ Batch assignment**: activating a version never touches any already-assigned Batch.
- **Batch Protocol panel** — a new `protocol` tab on the existing Batch detail page (`components/agronomy/BatchProtocolPanel.tsx`), reusing `get_batch_protocol_status` verbatim. Shows current assignment, due/overdue Observation Requirements, and an Assign/Change Protocol action restricted to ACTIVE compatible versions only (crop/variety match, `state === "active"`). Reassignment shows: *"This changes the protocol for future guidance. Historical assignment remains preserved."* **Age/due guidance never advances a Batch** — the panel is a pure read, no assignment or observation-satisfying action ever calls a stage-transition command.
- **Inspect Crop workspace** — `/farms/{farmId}/production/inspect?batchId=…&assignmentId=…`. Preserves exact `assignmentId` context from a scan/Batch link — never silently widens a placement scan to a Batch-wide pick. One inspection records inspected/affected counts, every due Observation Requirement's value, and structured Findings in ONE `GrowerInspectionCreate` command (one `ObservationEvent`, many `ObservationValue`s) — **Inspection ≠ Issue**: recording an inspection, however abnormal its findings, never itself creates a Crop Issue. After saving, the operator explicitly chooses Done / Record another / Open Crop Issue / View Batch — opening an Issue is always a second, deliberate command (`originating_grower_inspection_id` required by the backend), and the workspace allows opening more than one Issue from the same Inspection without re-recording it.
- **Crop Issue workspace** — `/farms/{farmId}/crop-issues/{issueId}`. Suspected cause and Confirmed diagnosis are two visually separate panels; Confirm Diagnosis is its own explicit command, never auto-copying one into the other. Resolve and Close are two separate deliberate actions (OPEN → RESOLVED → CLOSED enforced by the backend; Close is only offered once `status === "resolved"`). **Corrective action = the existing Farm Work Item domain**: "Assign corrective work" reuses `CreateWorkItemForm` unchanged, extended additively with a `crop_issue_id` field (already present on the backend's `FarmWorkItemCreate`/`FarmWorkItemRead` since PILOT-AGRO-001) — never a second task/agronomy-work model. A Follow-up's `outcome: "resolved"` records that assessment only; it never transitions the Issue itself — the UI shows a separate, optional "Resolve this Issue?" prompt afterward, never an automatic transition (**FollowUp RESOLVED ≠ Issue RESOLVED**).
- **Today on the Farm** — two new `LiveSourcePanel` sections on the existing farm home page: "Crop Attention" (farm-wide open Crop Issues, `GET /farms/{farm_id}/crop-issues` with no `batch_id` — already supported with zero backend change) and "Inspections Due" (a new, small, justified farm-wide read — see below). Both follow the page's own established loading/error/empty three-way branch; a failed read never renders as "nothing due". Neither section persists a `FarmWorkItem` merely because an inspection is due — that stays a pure computed read; only explicit corrective work assigned from a Crop Issue becomes a `FarmWorkItem` row.
- **QR "Inspect Crop"** — see "QR scan-context additions" below. **A QR scan never itself records an Inspection** — every "Inspect Crop" action is a prepared link into the workspace above; the operator still explicitly fills in and submits the Inspection.

### QR scan-context additions (the one precedented backend touch this ticket makes)

`qr_service.resolve_scan_context` gained three new conditional `ScanAction("Inspect Crop", …)` entries, gated by `may("crop_inspection.manage")`, mirroring the exact existing pattern already used for "Record Observation"/"Harvest" on the same branches — justified because neither `CropBatchScanContext` nor `BatchCarrierAssignmentScanContext` exposes its own raw entity UUID as a JSON field, so the href can only be built server-side from the already-in-scope `entity_id`:

- `crop_batch` → Batch-level Inspect Crop (`?batchId=`), never a fabricated exact placement.
- `carrier` → only when the carrier has a CURRENT (unreleased) batch assignment — reuses `sowing_service.get_carrier_batch_assignment`, so a reused Carrier's historical Batch never offers Inspect Crop.
- `batch_carrier_assignment` → only when `released_effective_time is None` (mirrors Harvest's own identical gate on the same branch) — a historical Placement QR never offers current Inspect Crop.

Proven by `apps/api/tests/test_qr_inspect_crop_action.py` (4 focused tests against the fast `db_session` fixture).

### Farm-wide "Inspections Due" read (the other justified backend addition)

`growing_protocol_service.list_farm_protocol_due_summary` + `GET /farms/{farm_id}/growing-protocols/due-summary`: a genuinely missing read shape (only a per-Batch `protocol-status` endpoint existed) needed to avoid a client-side N+1 fan-out across every active Batch on a Farm. Reuses `get_batch_protocol_status` unchanged, one small server-side loop over currently-assigned active Batches, returning only rows that actually have something due/overdue or an open Crop Issue. A Batch with **no protocol assigned at all is deliberately never reported here** — whether every Batch should carry a protocol is a product policy this ticket has no authority to invent (CLAUDE.md "Authority and Stop Conditions"); that fact stays visible on the Batch's own Protocol panel only. Proven by three focused tests in `test_growing_protocol_and_crop_issue.py`.

## Authorization

Three new permission tiers, following this codebase's established entry-vs-definition/entry-vs-correction split precedent (`OBSERVATION_ENTRY_MANAGE`/`OBSERVATION_DEFINITION_MANAGE`, `BIOLOGICAL_DISPOSITION_MANAGE`/`_CORRECT`):

- `growing_protocol.read` / `growing_protocol.manage` — protocol/version master data, activation, Batch protocol assignment. `.manage` is grower/supervisory only (`farm_manager`, `head_grower`).
- `crop_inspection.read` / `crop_inspection.manage` — recording Grower Inspections (and Follow-ups). `.manage` is the same floor-execution tier as `observation_entry.manage` — granted to `operator`, `production_supervisor`, `qc_officer`, `head_grower`.
- `crop_issue.manage` — open/assign/diagnose/resolve/close a Crop Issue. Supervisory/quality only (`farm_manager`, `head_grower`, `production_supervisor`, `qc_officer`) — never `operator`.

Tenant/farm isolation is mandatory throughout: every service function takes `tenant_id` (and, for farm-scoped rows, `farm_id`) and every query/composite FK is scoped by it — proven by `test_tenant_isolation_on_growing_protocol`.

### Issue/Inspection action matrix (PILOT-AGRO-001A domain closure review, confirmed, no permission change)

| Action | Permission | `operator` | `production_supervisor` | `qc_officer` | `head_grower` | `farm_manager` |
|---|---|---|---|---|---|---|
| A. Record a Grower Inspection | `crop_inspection.manage` | ✓ | ✓ | ✓ | ✓ | — |
| B. Report/open a Crop Issue | `crop_issue.manage` | — | ✓ | ✓ | ✓ | ✓ |
| C. Add follow-up evidence/assessment | `crop_inspection.manage` | ✓ | ✓ | ✓ | ✓ | — |
| D. Assign corrective work (create a linked `FarmWorkItem`) | `farm_work_item.manage` (existing, pre-dates this ticket) | — | ✓ | — | ✓ | ✓ |
| E. Confirm diagnosis | `crop_issue.manage` | — | ✓ | ✓ | ✓ | ✓ |
| F. Resolve an Issue | `crop_issue.manage` | — | ✓ | ✓ | ✓ | ✓ |
| G. Close an Issue | `crop_issue.manage` | — | ✓ | ✓ | ✓ | ✓ |
| H. Define/manage Growing Protocols | `growing_protocol.manage` | — | — | — | ✓ | ✓ |

`operator` is not granted `crop_issue.manage` at all, so it never gains B/E/F/G merely by having A — the review's specific concern does not occur. B/E/F/G/update stay bundled under one `crop_issue.manage` (not split further) deliberately: this mirrors `QUALITY_HOLD_MANAGE`'s own existing, documented precedent in this exact codebase — place/release also stays unified for the pilot ("P1 hardening item for external commercialization, not split here", `docs/product/OPEN_QUESTIONS.md`) — so splitting Crop Issue open/diagnose/resolve/close now would be new, uneven policy invention rather than following established practice. D is already properly separated by the PRE-EXISTING `farm_work_item.manage`/`.execute` split (not `crop_issue.manage` at all): `qc_officer` holds only `.execute` (matches its established investigative-not-assigning character elsewhere in this permission catalog), so it can open/diagnose/resolve/close an Issue but cannot itself create the corrective Work Item.

## Audit

Every mutating command appends an `AuditEvent` (protocol/version create/activate/retire, requirement/activity add, Batch protocol assignment, Inspection recording, Crop Issue open/update/diagnosis/resolve/close/follow-up) — no second audit system. Read-only computations (`get_batch_protocol_status`) never append an audit event, since nothing changed.

## Migration

`203d62ed9e9f` (additive, single Alembic head): nine new tables (`growing_protocols`, `growing_protocol_versions`, `protocol_observation_requirements`, `protocol_care_activities`, `batch_protocol_assignments`, `grower_inspections`, `inspection_findings`, `crop_issues`, `crop_issue_follow_ups`) plus one additive `farm_work_items.crop_issue_id` column and a `CREATE OR REPLACE` of the pre-existing `enforce_farm_work_item_mutable_fields` function to cover it. No existing table's data, other columns, or constraints are touched. Downgrade is guarded (raises if any new-table row exists), mirroring every other domain-introducing migration in this codebase.
