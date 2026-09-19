# Equipment Readiness and Critical Equipment Incidents

Full detail: `CLAUDE.md` rules 4–7, 10–12; the PILOT-ASSET-001 ticket. This document summarizes the approved model; it does not restate the ticket.

## Frozen distinctions

**Empty != Ready. Location != Readiness. Cleaning Completed != Ready. Incident != Work Item. Incident != Crop Issue. Work Item Complete != Incident Resolved. Retired is terminal. UNKNOWN != Ready.**

## Readiness is layered on top of the existing registry, never merged into it

`Asset.status`/`Carrier.status` (`active`/`inactive`/`damaged`/`retired`, CMP-005) is **registry lifecycle** — is this record still a valid, non-retired entry in the catalog — and was explicitly documented as "maintenance condition is a separate, future concern" (`docs/domain/ASSET_CARRIER_MODEL.md`). This ticket is that future concern. `EquipmentReadinessState` is a second, independent current-state row answering a different question (is this specific physical unit currently usable), never a replacement for `status`. A retired-from-registry Asset/Carrier (`status='retired'`) is additionally always `RETIRED` in readiness (enforced by the service layer, not merged into one column) — the two "retired" words name the same terminal real-world fact from two different tables, by design, not duplication to be collapsed.

## Readiness scope (PART 1)

Readiness applies only where operationally useful, via a new `readiness_tracked` flag on the global `carrier_types`/`asset_types` catalogs (mirrors the existing `supports_positions`/`requires_specification` type-level-flag precedent) — never forced onto every row:

| Carrier type | `readiness_tracked` | `requires_cleaning` |
|---|---|---|
| `seed_tray`, `cultivation_plate`, `nursery_cultivation_plate`, `production_cultivation_plate`, `harvest_crate` | true | true |
| `grow_cube`, `grow_bag` | false | — |

Grow Cube/Grow Bag are substrate-linked, not maintained reusable equipment (`ASSET_CARRIER_MODEL.md`'s own "grow bag is a replaceable crop carrier only" classification) — explicitly out of PART 1's pilot example list.

| Asset type | `readiness_tracked` | `requires_cleaning` |
|---|---|---|
| `germination_trolley`, `transfer_trolley` | true | true |
| `seeding_machine`, `weighing_scale`, `label_printer`, `water_quality_meter` | true | false |

Every current Asset type is readiness-tracked (an Asset is by definition "can require maintenance tracking", `ASSET_CARRIER_MODEL.md`); the four operational-equipment types don't cycle through a physical cleaning step the way a trolley or a crop carrier does — their readiness concern is damage/maintenance/retirement, not AWAITING_CLEANING. An entity whose type has `readiness_tracked=false` has no `EquipmentReadinessState` row and no readiness UI/actions at all.

## Readiness state model (PARTS 2–3)

`EquipmentReadinessState` — one current-state row per readiness-tracked Asset/Carrier (XOR occupant, mirrors `Occupancy`/`QrIdentifier`). Persisted `current_state`:

`UNKNOWN | AWAITING_CLEANING | CLEANING_COMPLETED | READY | DAMAGED | MAINTENANCE | RETIRED`

**`IN_USE` is deliberately never a stored value** — PART 4 says "prevent disagreement" between readiness and occupancy; the only way to structurally guarantee that is to never store a second copy of a fact occupancy already owns. "In use" is a read-time overlay only: for a Carrier, `is_in_use` is derived from an active `BatchCarrierAssignment` (the authoritative "does this carrier currently hold a batch" fact — distinct from physical `Occupancy`, which only answers *where*, per `OCCUPANCY_MOVEMENT_MODEL.md`). For an Asset there is no single authoritative "in active use" signal in the current domain (a Germination Trolley's own `Occupancy` records *where* it sits, not whether it is "in use" the way a Carrier's assignment does) — `is_in_use` is not computed for Assets; this is a documented, honest gap, not a guess.

## Legacy backfill: UNKNOWN, not READY (PARTS 27–28)

The migration backfills one `EquipmentReadinessState(current_state='UNKNOWN')` row for every existing readiness-tracked Asset/Carrier (`state_changed_by_user_id=NULL`, `state_changed_at=migration run time`) — never `READY` (would fabricate an assessment that never happened) and never left absent (an absent row would make every legacy item silently invisible to the readiness UI instead of visibly "not yet assessed"). **Corrected transition rule:** `UNKNOWN` is excluded from every "available" read, exactly like `AWAITING_CLEANING`/`DAMAGED`/`MAINTENANCE`/`RETIRED` — `UNKNOWN != READY` is a frozen rule with no exception, including for legacy backfilled equipment. This means every pre-existing readiness-tracked tray/plate/trolley becomes operationally unallocatable the moment this ticket deploys, until an operator deliberately runs it through the explicit lifecycle (`mark_ready`, or cleaning then `mark_ready`) — a real, accepted operational transition cost, not a gap: PART 27's "never fabricate READY" and the frozen "UNKNOWN != READY" rule leave no reading where legacy equipment can be silently treated as usable. `mark_ready` itself also rejects a direct `UNKNOWN → READY` call for a `requires_cleaning` type (it must first pass through `AWAITING_CLEANING → CLEANING_COMPLETED`), so a never-assessed cleaning-required item cannot bypass cleaning via this path either.

## Occupancy interaction (PART 4)

- Carrier `mark_ready` is rejected while the Carrier has an active `BatchCarrierAssignment` (a real, current use) — `EquipmentReadinessCarrierInUseError`.
- Releasing a Carrier's assignment does **not** automatically move its readiness to `AWAITING_CLEANING`. Auto-deriving that transition would require hooking into every release path (transplant, harvest, disposition, batch derivation) — a materially larger, cross-cutting change this ticket does not make (see "Known gaps" below and `docs/product/OPEN_QUESTIONS.md`). `mark_awaiting_cleaning` is an explicit command an operator (or a future integration) calls after release.
- `mark_awaiting_cleaning` is rejected outright when the entity's type has `requires_cleaning=false` (`EquipmentReadinessCleaningNotRequiredError`) — operators of that equipment go straight to `mark_ready`/`report_damage`/`send_to_maintenance` instead.

## Cleaning record (PART 5)

`CleaningEvent` — immutable, insert-only (tenant/farm, Asset XOR Carrier, `effective_at`, `recorded_at`, `performed_by_user_id`, optional `method`, `result` ∈ `COMPLETED | NEEDS_REWORK`, optional `notes`, `client_command_id`/`request_fingerprint`). `record_cleaning_completed` inserts one `CleaningEvent` and, in the same transaction, advances `EquipmentReadinessState.current_state` to `CLEANING_COMPLETED` **regardless of `result`** — a `NEEDS_REWORK` result still deliberately does not return the item to `AWAITING_CLEANING` automatically (that would be an invented auto-transition); it leaves the item at `CLEANING_COMPLETED` with the failing result visible in history, and a supervisor decides the next step (`mark_awaiting_cleaning` again, or `mark_ready` only ever validates against a `COMPLETED`-result cleaning — see below). `record_cleaning_completed` requires `current_state='AWAITING_CLEANING'` (`EquipmentReadinessInvalidTransitionError` otherwise) — cleaning is always a response to an awaiting-cleaning item, never a free-floating event.

## Ready validation (PART 7)

`mark_ready` requires, in order: not `RETIRED`; not `MAINTENANCE`; not `DAMAGED`; if the type `requires_cleaning`, the current state must be `CLEANING_COMPLETED` **with its most recent `CleaningEvent.result = 'COMPLETED'`** (a `NEEDS_REWORK` cleaning blocks `mark_ready` — `EquipmentReadinessCleaningNotCompletedError`) or `READY` (idempotent) — **`UNKNOWN` is never accepted here for a `requires_cleaning` type** (corrected: an earlier draft of this section wrongly listed `UNKNOWN` as an accepted source alongside `CLEANING_COMPLETED`; the implementation and the "Legacy backfill" section above have always been the approved rule — allowing a direct `UNKNOWN -> READY` would let a never-cleaned item skip `AWAITING_CLEANING`/`CLEANING_COMPLETED` entirely, so a never-assessed cleaning-required item must first pass through that sequence); if the type does not require cleaning, the current state must be `UNKNOWN`, `READY` (idempotent), or `AWAITING_CLEANING` (a type that was reclassified, or was momentarily marked awaiting-cleaning in error); for a Carrier, no active `BatchCarrierAssignment`. Every blocking condition raises a distinct, named domain error — never silently overridden.

## Allowed transitions (PART 6)

```
UNKNOWN            -> AWAITING_CLEANING, READY, DAMAGED, MAINTENANCE, RETIRED
AWAITING_CLEANING  -> CLEANING_COMPLETED, DAMAGED, MAINTENANCE, RETIRED
CLEANING_COMPLETED -> READY, AWAITING_CLEANING, DAMAGED, MAINTENANCE, RETIRED
READY              -> AWAITING_CLEANING, DAMAGED, MAINTENANCE, RETIRED
DAMAGED            -> MAINTENANCE, RETIRED
MAINTENANCE        -> AWAITING_CLEANING (if requires_cleaning), READY (if not), DAMAGED, RETIRED
RETIRED            -> (none — terminal, PART 28/CLAUDE.md rule 6)
```

Commands: `mark_awaiting_cleaning`, `record_cleaning_completed` (see above), `mark_ready`, `report_damage` (-> `DAMAGED`, from any non-terminal state), `send_to_maintenance` (-> `MAINTENANCE`, from any non-terminal state), `return_from_maintenance` (-> `AWAITING_CLEANING` or `READY` per `requires_cleaning`), `retire` (-> `RETIRED`, from any non-terminal state, requires the underlying Asset/Carrier to also be moved to registry `status='retired'` in the same transaction — the two "retired" facts are set together by this one command, never independently). Every command is a `Depends`-gated service function with its own `client_command_id`/`request_fingerprint` pair, row-locked, replay-safe, exactly mirroring `farm_work_item_service`'s established shape.

## History (PART 8)

`EquipmentReadinessState` is a CURRENT-STATE row (ADR-005): identity fields frozen for life by a DB trigger, only lifecycle fields mutate. Full transition history reads from `audit_events` (`entity_type='equipment_readiness_state'`), exactly like `FarmWorkItem`/`CropIssue` — never a second duplicated history table. `CleaningEvent` rows are themselves the permanent cleaning history (insert-only, never edited).

## Critical Equipment Incident (PARTS 9–11)

`EquipmentIncident` — a CURRENT-STATE row modeled directly on `CropIssue`'s shape (immutable code `EI-YYYYMMDD-NNNN`; identity fields frozen by trigger). Required: tenant/farm, `asset_id` (required — every example in the ticket is equipment, i.e. an Asset; a Carrier-condition problem is readiness's `report_damage`, not an Incident), optional `location_id` (where the equipment/incident is), optional `potentially_impacted_location_id` (PART 13's "Potentially impacted area" — deliberately a *second*, independently-optional location field, never reused/aliased from `location_id`: a pump failure's own location is the pump room, while the area it may affect is the circuit/zone it serves — collapsing the two would silently misreport one as the other), `severity` (`low|medium|high|critical`, mirrors `InspectionFinding.FINDING_SEVERITIES`), `category` (`cooling|ventilation|irrigation_water|fertigation_dosing|ro_plant|reservoir|germination_chamber|seeding_equipment|scale|cold_store|other` — drawn directly from the ticket's own worked examples, never an invented exhaustive failure taxonomy), `description`, `detected_by_user_id`/`detected_at`. Optional `assigned_owner_user_id`, `resolution_note`, `resolved_by_user_id`/`resolved_at`, `close_note`, `closed_by_user_id`/`closed_at`, `notes`.

`AssetType.criticality` does not exist; **criticality lives on the `assets` row itself** (`normal|important|critical`, default `normal`) — an instance fact ("this specific chamber is critical to this farm"), not a type-level classification (per PART 11, "inspect... if no concept exists, add... only where useful" — a per-Asset field, not a scoring engine). It informs Today-on-the-Farm ordering and severity presentation only; it never changes Incident status automatically.

## Incident lifecycle (PART 10)

`OPEN -> ACKNOWLEDGED -> ACTION_IN_PROGRESS -> RESOLVED -> CLOSED`, all five persisted (unlike `CropIssue`'s `ACTION_IN_PROGRESS`, which is a read-model overlay there — this ticket's own PART 10 lists it as a real suggested state, not explicitly a derived one, so it is persisted directly; kept intentionally small, no further sub-states). `RESOLVED`/`CLOSED` are always deliberate, separate commands — never implied by anything else (PART 4/CLAUDE.md "Work Item Complete != Incident Resolved").

## Incident != Work Item, Incident != Crop Issue (PARTS 4–5, 12–13)

`FarmWorkItem` gains one additive nullable `equipment_incident_id` column (composite FK, frozen at creation by extending `enforce_farm_work_item_mutable_fields`, mirrors `crop_issue_id` exactly — the established extensible-context-reference precedent). An Incident may have zero, one, or several linked Work Items over its life (e.g. a first corrective attempt that didn't fix it, then a second). Completing a linked Work Item never changes the Incident's status — an authorized person always calls `resolve_incident` deliberately. `EquipmentIncident` never creates, references, or infers a `CropIssue`, and vice versa; `potentially_impacted_location_id` is presented as "Potentially impacted area" everywhere in the UI, never "Affected crop" (PART 13) — no Crop Issue is ever auto-opened from an Incident.

## Available-resource read hardening (PARTS 16–17)

Audited every existing "available X" endpoint (`nursery_service.list_available_seed_trays`, `intersalads_transplant_service.list_available_intersalads_plates`, `leafy_production_transfer_service.list_available_production_plates`) — each already filters `Carrier.status == 'active'` and "no active `BatchCarrierAssignment`". Each is hardened with one additional eligibility condition: a Carrier is eligible only when its type is not readiness-tracked (unaffected, exactly as an untracked type is treated everywhere else), OR a matching `EquipmentReadinessState` row exists with `current_state = 'ready'`. `CLEANING_COMPLETED` and `UNKNOWN` both correctly fall out as ineligible under this positive test, for the same reason PART 17's original four-item exclusion list needed both added — leaving either out would let, respectively, a cleaned-but-not-yet-released Plate or a never-assessed Plate silently allocate, contradicting "Cleaning Completed != Ready" and "UNKNOWN != Ready" at the one place each matters operationally.

**N02A review correction (Correction #3):** the four selectors above (plus `list_available_trolleys` below) originally implemented this as a `NOT IN`/`NOT EXISTS` filter over the *known non-ready* states — which fails **open** for a tracked Carrier/Asset with no `EquipmentReadinessState` row at all (nothing to match against, so it silently passed through as "available"), the exact opposite of the write-side's fail-closed behavior. Corrected to the positive `IN`/`EXISTS`-shaped test described above (`equipment_readiness_service.eligible_carrier_ids_subquery`/`eligible_asset_ids_subquery` for the SQLAlchemy-style callers; an inlined `readiness_tracked`-joined `EXISTS` for the raw-SQL callers), which naturally excludes a missing row for a tracked type. The older `NOT IN`-shaped `non_ready_carrier_ids_subquery` was removed outright (dead after rewiring); `non_ready_asset_ids_subquery`/`NON_READY_STATES` are kept only for their one remaining unrelated caller and now carry an explicit warning against reuse for a new "available X" read.

Germination Trolley/Chamber selection (`germination_service.list_available_trolleys`) is classified **NEEDS FILTER** and hardened identically (readiness on the Asset side). Seed-tray-on-trolley-level selection, Seedling Table selection, and every Location-only availability read are classified **NOT APPLICABLE** (no readiness-tracked occupant involved).

## Write-time allocation enforcement (N02A)

The read-side hardening above is a convenience for the operator's picker — it is never, by itself, the backend invariant. A resource can appear READY when a form opens and move to a non-READY state before the operator submits (a concurrent `mark_awaiting_cleaning`/`send_to_maintenance`/`report_damage`/`retire`), and a direct API or service call never goes through a picker at all. N02A closes this gap: **every write command that allocates a readiness-tracked Asset/Carrier authoritatively re-checks and locks its current readiness inside the same write transaction, immediately before committing any new operational row** — a selector result is never trusted as a substitute.

The shared, single implementation is `equipment_readiness_service.require_ready_for_allocation` (tenant/farm-scoped; takes explicit `asset_ids`/`carrier_ids`). It: resolves which of the given entities are actually `readiness_tracked` (an untracked type is silently unaffected, exactly as the read-side filters treat it); locks every tracked entity's `EquipmentReadinessState` row in one batched, deterministically-ordered `SELECT ... FOR UPDATE` (never a query per entity); requires `current_state == 'ready'` for every one of them; and fails closed — raising the shared `EquipmentReadinessNotReadyError` — both for a non-READY state and for a tracked entity with no readiness row at all (frozen rule: a missing row is a data-integrity/ineligible condition, never treated as Ready). The API layer maps this error to `409 Conflict` (an otherwise-valid, found resource whose current readiness blocks the requested allocation) — distinct from `404` (missing/cross-tenant/cross-farm identifier, unchanged) and from the existing `422` domain-validation mapping (payload/shape errors unrelated to concurrent readiness).

Applied at exactly the points that already validate registry status/type/capacity/assignment for these commands, so the readiness check rides the same lock scope rather than adding a second one:

- **Sowing** (`sowing_service._sow_batch_core`) — every destination Seed Tray Carrier in the command, after they are already locked (`SELECT ... FOR UPDATE`, sorted order) and status/type/assignment/capacity-checked.
- **Germination Trolley placement/use** (`germination_service.place_tray`) — the selected Trolley Asset, checked only when the call is a genuinely new command (a `movement_service._find_existing_movement` hit means this is a replay or a same-id/different-payload reuse, both already handled by `movement_service`'s own idempotency, so re-running eligibility there would violate the replay guarantee below). **N02A review correction (Correction #2):** the new-command path now genuinely locks the Trolley Asset row itself (`_validate_trolley(..., lock=True)`, a `SELECT ... FOR UPDATE` re-validating status/type under lock) immediately before calling `require_ready_for_allocation` — the original patch called an unlocked `asset_service.get_asset` read here while claiming the same lock-order guarantee as Sowing/Transplant; a concurrent `retire` of that Trolley could then interleave between the (unlocked) validation and the readiness check. `place_trolley_in_chamber` (moving a Trolley between/into a Chamber) is a separate, non-allocating Movement and is deliberately not readiness-gated.
- **Transplant** (`transplant_service._record_transplant_core`) — every destination Carrier (never the source), after the destination validation loop; this one core is shared verbatim by `record_transplant`, `intersalads_transplant_service`, `leafy_production_transfer_service`, `intervines_transplant_service` (whose `grow_cube` destinations are untracked and therefore unaffected), and `transplant_correction_service`'s REPLACEMENT leg — so every one of those composite commands is covered by this single change, with no separate wiring.

**Lock order.** Every one of the callers above genuinely locks the underlying Carrier/Asset row (`SELECT ... FOR UPDATE`) before calling `require_ready_for_allocation`, which then locks only `EquipmentReadinessState` rows — i.e. Carrier/Asset-row-before-readiness-row, consistently, for Sowing, Germination, and Transplant alike. `retire` is the one readiness-transition command that also mutates the underlying Carrier/Asset row (setting registry `status='retired'` in the same commit); it now locks that row first too (reordered by this ticket from its previous readiness-row-first sequence: it resolves the frozen `entity_type`/`asset_id`/`carrier_id` identity via an unlocked read first, since those fields never change, then locks the Carrier/Asset row, then locks the `EquipmentReadinessState` row via the shared `_lock_state`), so no command anywhere acquires these two lock classes in the reverse order — closing an AB-BA deadlock that a reverse order on either side would otherwise create between a concurrent allocation command and a concurrent readiness transition on the same entity. Proven directly for Germination by `test_place_tray_and_retire_on_trolley_serialize_no_deadlock` (barrier-coordinated `place_tray` vs `retire` on the same Trolley, deterministic, no `time.sleep`): no deadlock/timeout, `retire` always completes, and a `place_tray` that loses the race leaves no partial Movement/Occupancy behind.

**Idempotent replay is unaffected.** Every calling command's own pre-existing exact-replay short-circuit (checked, and satisfied, before this new validation ever runs) means the readiness check only ever executes for a genuinely new command — a later readiness change can never turn a valid replay of an already-committed command into a new failure. A reused command id carrying a materially different payload still fails through that command's existing command-reuse rule, unchanged.

## Today on the Farm — Equipment Attention (PART 15)

`equipment_readiness_service.get_equipment_attention` — a live, conservative read-model (never manufactures alerts, mirrors `water_attention_service`'s own documented restraint): open incidents (critical/high first, by `Asset.criticality` then `severity`), Assets/Carriers in `MAINTENANCE`, in `DAMAGED`, `AWAITING_CLEANING`, and `CLEANING_COMPLETED`-but-not-released. Each section independently reports its own loading/error/empty state; a failed section is never rendered as "nothing to do" (LOADING != EMPTY, ERROR != EMPTY, STALE != CURRENT).

## QR integration (PART 21)

`qr_service`'s `asset`/`carrier` `ScanContext.actions` gain conditional entries (View Readiness always; Record Cleaning only when `AWAITING_CLEANING`; Report Damage/Report Incident when not `RETIRED`) — plain navigation links into the pages below, exactly like every other `ScanAction`. Resolving a token never mutates readiness (QR_SCAN_MODEL.md's "Scan ≠ activity" is unchanged).

## Permissions (PART 23)

Two new three-tier permission pairs, mirroring `FARM_WORK_ITEM_READ`/`.MANAGE`/`.EXECUTE`'s established split:

- `equipment_readiness.read` / `.execute` (record cleaning, report damage, mark awaiting cleaning) / `.manage` (mark ready, maintenance transitions, retire)
- `equipment_incident.read` / `.execute` (open/acknowledge an incident, link a Work Item) / `.manage` (assign owner, mark action-in-progress, resolve, close)

Granted the same way `FARM_WORK_ITEM_*` already is: `farm_manager` gets `.read`+`.manage` on both (infrastructure owner, no floor execution); `production_supervisor` gets all three tiers on both (floor oversight + execution, matching its `FARM_WORK_ITEM_*` triple grant); `operator`, `packing_supervisor`, `cold_store_supervisor`, `dispatch_officer` get `.read`+`.execute` (floor execution only, matching their existing `FARM_WORK_ITEM_EXECUTE` tier); `head_grower`, `qc_officer`, `storekeeper`, `auditor`, `read_only` get `.read` only (visibility, no equipment-ownership role today). `tenant_admin` gets everything automatically.

## Audit and corrections (PARTS 24–25)

Every transition (readiness state change, cleaning record, incident open/acknowledge/action/resolve/close, Work Item link) is one `append_audit_event` call in the same transaction as the row mutation — the established atomic-commit pattern, no exceptions. `CleaningEvent`/`EquipmentIncident` history rows are never destructively edited; `EquipmentIncident`'s CURRENT-STATE row only ever moves forward through its lifecycle commands. No first-class reversal/correction command is built for a mis-recorded `CleaningEvent` (mirrors `WaterMeasurement`'s own documented gap — PILOT-WATER-001A) — a wrong entry is corrected by recording a new, later, correct one; this is a genuine, documented gap, not silently patched (`docs/product/OPEN_QUESTIONS.md`).

## Migration (PART 26)

Additive only, one new head on top of `0d62f68527a2` (the current single Alembic head as of this ticket's base commit). New tables: `equipment_readiness_states`, `cleaning_events`, `equipment_incidents`. New columns: `carrier_types.readiness_tracked`/`requires_cleaning`, `asset_types.readiness_tracked`/`requires_cleaning`, `assets.criticality`, `farm_work_items.equipment_incident_id`. Backfill: one `UNKNOWN` `EquipmentReadinessState` row per pre-existing readiness-tracked Asset/Carrier (see above). No occupancy/movement table, trigger, or semantic is touched.

## Known gaps (deliberately not built here)

- **No automatic `IN_USE -> AWAITING_CLEANING` hook on release.** Documented above; wiring every release path (transplant/harvest/disposition/batch-derivation) is a materially larger, cross-cutting change outside this ticket's scope.
- **No correction/void command for a mis-recorded `CleaningEvent`.**
- **Asset `is_in_use` is not computed** — no single authoritative "in active use" signal exists for Assets today.
- **No preventive-maintenance scheduling, spare-parts inventory, vendor management, cost accounting, MTBF/predictive analytics, IoT/controller integration, or notifications** — explicitly out of scope (ticket "OUT OF SCOPE").
