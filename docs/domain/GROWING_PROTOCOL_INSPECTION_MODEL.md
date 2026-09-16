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

`ProtocolObservationRequirement` REFERENCES an existing `ObservationDefinition` (never duplicates its value/unit/range architecture): `requirement_level` (`required`/`recommended`), optional `frequency_days` (repeat interval), optional `due_window_start_days`/`due_window_end_days` (days since stage entry), `instructions`, `escalation_guidance`, `display_order`.

`ProtocolCareActivity` is a small, structured, non-dosing expectation: `activity_type` (`inspect_roots`/`scout_pests`/`pruning`/`training`/`spacing`/`crop_hygiene`/`transfer_readiness`/`harvest_readiness`/`other`), `title`, `instructions`, `frequency_days`, `display_order`. Explicitly **excludes** nutrient recipes, dosing, and irrigation management (PILOT-WATER-001 territory).

## Batch → Protocol Version assignment

`BatchProtocolAssignment` preserves full history — mirrors `BatchStageRun`'s own "one open-ended current row per Batch, closed by setting the previous row's own end timestamp when superseded" shape exactly (`ux_batch_protocol_assignments_active_batch`, a partial unique index on `batch_id WHERE effective_to IS NULL`). `assign_batch_protocol` requires the target version to be `ACTIVE` (`BatchProtocolVersionNotActiveError` otherwise); changing from V1 to V2 closes V1's row (`effective_to = <new effective_from>`) and inserts V2's row in the same transaction, so "Batch used V1 until X" / "Batch used V2 from X" is always readable directly from history — no historical Observation or Inspection row is ever rewritten. Manual assignment (no automatic protocol selection) is acceptable for the pilot, per the ticket.

## Grower Inspection

`GrowerInspection` is a structured, fully immutable (insert-only, `reject_append_only_mutation`), ACTUAL floor record — never proof a protocol requirement was followed. It snapshots `batch_carrier_assignment_id`/`location_id` (the carrier's occupancy at record time, resolved once and stored — never re-derived later, so a subsequent move never changes what an old Inspection says about where it happened) and `growing_protocol_version_id` (the Batch's current assignment at record time, for historical context).

It may reference (never duplicate) the existing Observation architecture: `record_inspection` optionally calls `observation_service.record_observation` in the same command with the same resolved `effective_time`, storing the resulting `observation_event_id` — one `ObservationEvent` can hold many typed `ObservationValue`s, so "GrowerInspection -> links to ObservationEvents" is satisfied by this single reference rather than a second value-storage table.

`inspected_count`/`affected_count` (on each `InspectionFinding`) are both optional counts; `affected_count <= inspected_count` is enforced in the service (`GrowerInspectionValidationError`), mirroring `observation_service`'s own established cross-row validation convention (no cross-table DB CHECK exists in Postgres) — never a DB constraint. Recording affected plants never changes living inventory (see Frozen domain rules).

### Findings

`InspectionFinding.category` covers the ticket's practical vocabulary (`vigor`/`uniformity`/`roots`/`leaf_condition`/`pest_evidence`/`disease_like_symptoms`/`physical_damage`/`deficiency_like_symptoms`/`growth_deviation`/`contamination_concern`/`other`) with `severity` (`low`/`medium`/`high`/`critical`), an optional `affected_count`, `notes`, and `suspected_cause` — no pathology ontology, no photo/file-storage infrastructure.

## Crop Issue

`CropIssue` is a CURRENT-STATE row (ADR-005), like `FarmWorkItem`: identity/content fields (tenant/farm, `code`, `batch_id`, placement/location, `originating_grower_inspection_id`/`originating_finding_id`, `category`, `description`, `opened_by_user_id`/`opened_at`, creation idempotency) are frozen for life by `enforce_crop_issue_mutable_fields` (mirrors `enforce_farm_work_item_mutable_fields` exactly); only lifecycle fields (`severity`, `suspected_cause`, diagnosis fields, `status`, `assigned_owner_user_id`, `follow_up_due_at`, resolved/closed fields, and each command's own idempotency pair) ever change.

Human-readable `code` (`CI-YYYYMMDD-NNNN`, sequential per tenant per farm-local date, same `pg_advisory_xact_lock` convention as `farm_work_item_service._generate_work_item_code`).

**Persisted lifecycle is `OPEN -> RESOLVED -> CLOSED` only, never reopened.** The ticket's own "suggested lifecycle" additionally names `ACTION_IN_PROGRESS`/`FOLLOW_UP_DUE`; these are READ-MODEL overlays (`crop_issue_service.read_model_overlays`, exposed as `CropIssueRead.has_open_work_item`/`is_follow_up_overdue`), never persisted statuses — derived from "has an open `FarmWorkItem` linked" and "`follow_up_due_at` has passed", per section 14's own "these may be read-model items" guidance and the ticket's explicit "keep simple" instruction. This keeps the persisted state machine to three states with two deliberate, separate, authorized transitions (`resolve_crop_issue`, `close_crop_issue` — closure only from `resolved`, never directly from `open`), satisfying "Issue closure is deliberate + authorized" without extra transition commands that add no operator-visible signal beyond the overlay.

`suspected_cause` (copied from the originating Finding at open time, further editable via `update_crop_issue`) and `confirmed_diagnosis` (`confirm_diagnosis`, a separate authorized command) are permanently distinct — see Frozen domain rules.

## Issue Actions — Work Item linkage

Reuses `FarmWorkItem` — no second task table. `farm_work_items.crop_issue_id` (new nullable column, additive) is set only at Work Item creation (`farm_work_item_service.create_work_item(..., crop_issue_id=...)`), frozen for life by the extended `enforce_farm_work_item_mutable_fields` trigger, exactly like the four pre-existing context columns (`crop_batch_id`/`location_id`/`carrier_id`/`asset_id`). There is deliberately no retrofit command to link an already-created Work Item — a Crop Issue's corrective work is always a NEW Work Item carrying this reference from the start.

Flow: Crop Issue -> operator (or supervisor) creates a Work Item with `crop_issue_id` set -> operator performs the actual work -> Work Item completes (`complete_work_item`, unchanged) -> Crop Issue **remains open** -> grower performs a follow-up Inspection/`CropIssueFollowUp` -> an authorized user deliberately resolves, then closes, the Issue.

## Follow-up

`CropIssueFollowUp` is fully immutable (insert-only), referencing the parent `CropIssue` and, optionally, a follow-up `GrowerInspection`. `outcome` is `IMPROVED`/`UNCHANGED`/`WORSENED`/`RESOLVED`. Recording a `RESOLVED` outcome never silently transitions the parent Issue — `resolve_crop_issue` must still be called deliberately (see Frozen domain rules).

## Due / deviation read (`get_batch_protocol_status`)

A deterministic, read-only function over already-recorded facts only: the Batch's current `BatchStageRun` (actual stage + entry time), the current `BatchProtocolAssignment`, that version's `ProtocolObservationRequirement`s for the current `stage_category`, and the most recent `ObservationEvent`/`ObservationValue` touching each required `ObservationDefinition` since stage entry. Returns `is_due`/`is_overdue`/`is_outside_expected_window`/`last_satisfied_at` per requirement, plus `open_crop_issue_count`. Never writes anything (no `INSERT`/`UPDATE` anywhere in its call path) — proven by `test_due_read_never_mutates_batch_or_stage`.

Example (ticket's own): a protocol names "Expected transfer: Day 25–30"; a Batch is actually at day 31. The read reports `is_outside_expected_window = True`; the UI displays "Outside expected protocol window. Grower review recommended." Nothing is automatically transferred or blocked.

## Today on the Farm / Batch UI / QR integration (backend-ready, frontend follow-up)

The backend surface (`GET .../crop-batches/{batch_id}/protocol-status`, Grower Inspection and Crop Issue CRUD/lifecycle endpoints) is complete and sufficient for read-model "Inspections Due"/"Crop Attention" sections, a compact Batch protocol panel, an Inspection workspace, and a QR "Inspect Crop" scan action — all UI wiring is left to a focused follow-up ticket; see `docs/product/OPEN_QUESTIONS.md`.

## Authorization

Three new permission tiers, following this codebase's established entry-vs-definition/entry-vs-correction split precedent (`OBSERVATION_ENTRY_MANAGE`/`OBSERVATION_DEFINITION_MANAGE`, `BIOLOGICAL_DISPOSITION_MANAGE`/`_CORRECT`):

- `growing_protocol.read` / `growing_protocol.manage` — protocol/version master data, activation, Batch protocol assignment. `.manage` is grower/supervisory only (`farm_manager`, `head_grower`).
- `crop_inspection.read` / `crop_inspection.manage` — recording Grower Inspections (and Follow-ups). `.manage` is the same floor-execution tier as `observation_entry.manage` — granted to `operator`, `production_supervisor`, `qc_officer`, `head_grower`.
- `crop_issue.manage` — open/assign/diagnose/resolve/close a Crop Issue. Supervisory/quality only (`farm_manager`, `head_grower`, `production_supervisor`, `qc_officer`) — never `operator`.

Tenant/farm isolation is mandatory throughout: every service function takes `tenant_id` (and, for farm-scoped rows, `farm_id`) and every query/composite FK is scoped by it — proven by `test_tenant_isolation_on_growing_protocol`.

## Audit

Every mutating command appends an `AuditEvent` (protocol/version create/activate/retire, requirement/activity add, Batch protocol assignment, Inspection recording, Crop Issue open/update/diagnosis/resolve/close/follow-up) — no second audit system. Read-only computations (`get_batch_protocol_status`) never append an audit event, since nothing changed.

## Migration

`203d62ed9e9f` (additive, single Alembic head): nine new tables (`growing_protocols`, `growing_protocol_versions`, `protocol_observation_requirements`, `protocol_care_activities`, `batch_protocol_assignments`, `grower_inspections`, `inspection_findings`, `crop_issues`, `crop_issue_follow_ups`) plus one additive `farm_work_items.crop_issue_id` column and a `CREATE OR REPLACE` of the pre-existing `enforce_farm_work_item_mutable_fields` function to cover it. No existing table's data, other columns, or constraints are touched. Downgrade is guarded (raises if any new-table row exists), mirroring every other domain-introducing migration in this codebase.
