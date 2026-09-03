# Seed Lot, Sowing, and Initial Carrier Assignment Model

Full detail: `CMP_MASTER_SPEC.md` §2, §8; `CLAUDE.md` rules 1, 3, 4, 5, 7, 10, 12. This document summarizes the approved model as implemented in CMP-009; it does not restate the spec.

## Scope

CMP-009 connects an active, seeding-stage crop batch (CMP-008) to its first physical carriers and records where its seed came from. It proves traceability and per-carrier quantities only — no seed-inventory balance, no capacity, no release/reassignment, no occupancy or movement. Sowing never creates, closes, or infers a CMP-006 occupancy row; assignment answers "what crop batch does this carrier contain", occupancy answers "where is it physically" — the two never intersect in this ticket.

## Seed lots

A `seed_lot` is tenant- and farm-owned identity for a supplier seed source: crop, variety, a normalized tenant-wide-unique code, optional supplier name/lot reference, optional received/expiry dates, and `active`/`inactive` status. It carries no quantity-on-hand, cost, or germination-test data — that is deferred to a later input-store ledger ticket. `supplier_lot_reference` is optional: many suppliers never issue one, and the internal `code` already gives identity, so requiring it would force a fabricated value.

## Variety-specific sowing

CMP-007 permits variety-agnostic workflows (`workflows.variety_id` nullable), but a seed lot always identifies one variety. Rather than adding an operational-variety column to `crop_batches`, CMP-009 requires the batch's permanently bound workflow to already carry a non-null, active `variety_id` as a precondition of sowing — checked at sowing time, not creation time. This is the smaller design: it needs no schema change to `crop_batches`, and the batch's variety remains derivable, as it always has been, through `crop_batch → workflow_version → workflow → variety`. A batch whose workflow has no variety restriction simply cannot be sown until re-created against a variety-specific workflow. A sowing line is also rejected if its seed lot's crop or variety differs from the batch's workflow-derived crop/variety — this is what prevents a batch from ever holding two varieties.

## Batch carrier assignment

A `batch_carrier_assignment` is the immutable-history record answering "what batch does this carrier hold right now". One carrier has at most one active (`released_effective_time IS NULL`) assignment at a time, enforced by a partial unique index on `(tenant_id, carrier_id)`; one batch may have many active carriers. `released_effective_time` is a reserved nullable column: no CMP-009 command ever populates it, and every UPDATE/DELETE on the table is rejected outright by a DB trigger — there is no closure logic yet. A future release/transformation ticket adds a typed closing-command reference and replaces this trigger with a closure-only variant, so that migration is additive rather than a rewrite of already-populated history.

## Sowing events and lines

One `sowing_event` is one command: it is tied, by trigger, to the exact `batch_stage_run` that was active and unclosed at the moment it executed, and that run's stage must be `seeding`-category with a configured `required_carrier_type_id` — CMP-009 never hardcodes a carrier type code; the requirement is read from `workflow_stages.required_carrier_type_id` (already present since CMP-007). Each event carries one or more `sowing_event_lines`, one row per carrier: seed-lot id, sown-site count, seed count (`seed_count >= sown_site_count > 0`), and exactly one line per assignment (`UNIQUE(batch_carrier_assignment_id)`). ~~A batch may be sown multiple times as separate carriers become ready~~ **superseded by NURSERY-OPS-001** — see the addendum below: at most one Sowing Event per Crop Batch, ever. A command is capped at 500 lines — a technical API limit, not a greenhouse-capacity statement (carrier capacity is not configured yet).

## Idempotency and concurrency

`UNIQUE(tenant_id, client_command_id)` on `sowing_events`. The fingerprint covers tenant, farm, actor, batch, UTC effective time, normalized note, and lines sorted by carrier id — it deliberately excludes the active stage-run id, current carrier-assignment state, seed-lot status, and workflow state, all of which can legitimately change between the original command and a retry; a retry must still return the original event after the batch has progressed, carriers are assigned, or a seed lot goes inactive. Locking order for a genuinely new command: the batch row, its active stage run, then carriers, then seed lots — each of the latter two in sorted-UUID order, preventing deadlocks across overlapping carrier lists and letting a losing concurrent duplicate resolve as an idempotent replay rather than a raw constraint failure.

## Farm-local date validation

Seed-lot `received_date`/`expiry_date` are farm-local calendar dates, not UTC instants. Sowing converts the UTC `effective_time` into the farm's IANA timezone (`farms.timezone`) and compares the resulting local date — inclusive on both bounds — rather than comparing a UTC date directly against a farm-local date, which would misclassify sowings near local midnight.

## Database protection

Composite foreign keys prove tenant/farm/batch consistency structurally, reusing CMP-008's `(tenant_id, farm_id, batch_id, id)`-style composite-FK pattern (now also applied to `batch_stage_runs` and `carriers`, added as additive constraints). Triggers cover the cross-row rules a CHECK cannot express: a `sowing_event`'s stage run must actually be the batch's own currently-open, seeding-category run with a configured carrier type; a `batch_carrier_assignment` must match its opening event's batch/stage-run/effective-time and the carrier's type must equal the stage's required type; a `sowing_event_line`'s assignment must belong to the same event and carrier, and its seed lot's crop/variety must match the batch's workflow-derived crop/variety. Append-only/no-delete triggers (`reject_append_only_mutation`, `reject_hard_delete`, both shared with CMP-008) protect all four new tables.

## Deferred

Seed inventory balances, material issues, stock deduction, costing, germination observations, carrier-capacity configuration, carrier release, reassignment, transplanting, transformations, quality, harvest, packing, QR identities, labels, frontend, RLS, role-specific authorization.

Carrier release/reassignment (transplanting, CMP-011) and split/merge (CMP-012) are both now implemented — see `docs/domain/TRANSPLANTATION_MODEL.md` and `docs/domain/BATCH_DERIVATION_MODEL.md`. Both amend the `batch_carrier_assignment` shape described here (adding typed openers/releasers) rather than replacing it.

## NURSERY-OPS-001 addendum: the operator-facing Sowing command

CMP-009 built the domain tables and a generic, two-step API (`POST /crop-batches` to create a batch against an explicit `workflow_id`, then `POST /crop-batches/{id}/sowings` to sow it) but no frontend and no single atomic operator command — its own "Deferred" list named the frontend explicitly. NURSERY-OPS-001 adds exactly that layer, reusing every table/trigger/service function above verbatim; nothing in this addendum replaces anything above it except the two items below.

**One Sowing command, one Crop Batch, one Sowing Event, ever (deliberate rule change).** `POST /farms/{farm_id}/nursery/sowings` (`nursery_service.sow_new_batch`) creates the Crop Batch and its Sowing Event atomically, in one transaction: it composes newly-extracted `crop_batch_service._create_batch_core` and `sowing_service._sow_batch_core` (validate+insert+flush, no commit/audit — the exact `_*_core` extraction pattern FARM-SETUP-001 established for `location_service`/`asset_service`) behind one idempotency check, one `pg_advisory_xact_lock`, one audit event, one commit. A new `UNIQUE(batch_id)` constraint on `sowing_events` (`ux_sowing_events_batch_id`, migration `a7e4f2c9b381`) makes "at most one Sowing Event per Crop Batch" a system-wide, DB-enforced invariant — this is a deliberate product decision, not an oversight, and it does supersede this document's own earlier "a batch may be sown multiple times as separate carriers become ready" line. The generic two-step API above still exists and is otherwise unchanged (a batch created via the generic `POST /crop-batches` can still be sown exactly once via `POST /crop-batches/{id}/sowings`); it simply can no longer be sown a second time, by either path.

**Workflow auto-resolution.** The operator-facing command never asks for a `workflow_id` — `nursery_service._resolve_sowing_workflow` looks up the one active Workflow (published version, seeding-category start stage, `required_carrier_type_id = seed_tray`) whose `(crop_id, variety_id)` match the selected Seed Lot's own. Zero or more than one match is a real configuration gap (`NoSowingWorkflowFoundError`/`AmbiguousSowingWorkflowError`), reported plainly rather than guessed — this never silently picks a workflow.

**Batch code generation.** `crop_batches.code` remains a plain, user-supplied field on the generic `create_batch` API (unchanged). The Sowing command generates its own: `CB-YYYYMMDD-NNN`, sequential per tenant per local sowing date, serialized by a `pg_advisory_xact_lock` keyed on `(tenant_id, date)` — matching the code's actual tenant-wide (not per-farm) uniqueness scope. No new sequence table.

**Seeding Station / Seeding Machine provenance.** `sowing_events` gains two new nullable columns (same migration): `seeding_station_id` (validated: an active `seeding_station` location under a Nursery-classified Greenhouse, in this tenant/farm) and optional `seeding_machine_id` (validated: an active `seeding_machine` asset in this tenant/farm — farm-level equipment, event provenance only, never Nursery-owned; matches FARM-SETUP-001.1's Trolley/Seeding Machine review). Neither creates or implies any Occupancy/Movement — Sowing still never touches occupancy, exactly as this document's Scope section already states. Both are `NULL` on every event predating this ticket.

**Available Seed Trays.** `GET /farms/{farm_id}/nursery/seed-trays/available` (gated on `carrier.read`, the resource actually being read) lists active `seed_tray` Carriers with no active `batch_carrier_assignment` — it does not and cannot infer physical location, since CMP does not track where a reusable tray currently sits.

**Authorization.** The new command is gated on `Permission.SOWING_MANAGE` alone — the existing, correct permission (already held by `operator`, `production_supervisor`, `tenant_admin`); no new permission was created.

## NURSERY-OPS-001.1 addendum: Seed-Lot integrity and Sowing semantic closure

A narrow domain-integrity closure on the above: two real gaps existed in CMP-009's original per-line design, closed here at the DB layer, not just the service layer.

**One Crop Batch, one canonical Seed Lot -- now DB-enforced, not just implied.** CMP-009 put `seed_lot_id` only on each `SowingEventLine`, with no constraint requiring every line of one event to agree. Both the new Nursery command (single top-level `seed_lot_id`) AND the general/legacy `POST /crop-batches/{id}/sowings` route (per-line `seed_lot_id`) could otherwise -- the legacy route genuinely could, proven by `test_sowing_api_rejects_mixed_seed_lot_lines` before the fix -- insert two lines of one event against two different Seed Lots of the same crop/variety. `sowing_events` now carries a canonical, NOT NULL `seed_lot_id` (migration `a7e4f2c9b381`, backfilled from existing line data on upgrade, guarded against pre-existing mixed data); `enforce_sowing_event_line_insert_integrity` (CMP-009's own trigger, replaced via `CREATE OR REPLACE FUNCTION` rather than editing the historical migration, mirroring CMP-011's precedent) now also rejects any line whose `seed_lot_id` disagrees with its event's canonical one. `sowing_service._sow_batch_core` rejects mixed lines itself before writing anything (`MixedSeedLotInSowingCommandError`), so the DB trigger is defense-in-depth, not the only enforcement. Direct-SQL proof: `test_direct_sql_mixed_seed_lot_lines_rejected`.

**Seeds Sown vs. sown sites -- no longer conflated.** `sowing_event_lines.sown_site_count` (same migration) is now nullable. The Nursery command only ever collects Seeds Sown (`seed_count`) from the operator; it used to silently set `sown_site_count = seed_count`, fabricating an unobserved one-seed-per-site assumption. It now records `sown_site_count = NULL` ("not recorded") -- honest, never guessed. The general/legacy route's own request schema (`SowingEventLineIn.sown_site_count`) is unchanged (still a required, separately-observed field for callers who genuinely know it); only the DB column and the Nursery command's own behavior changed. `SowingEventRead`'s `total_seeds_sown` was always `seed_count`-based, never `sown_site_count`-based, so no read-side behavior changed.

**Root Sown Batch vs. derived Batch -- Seed Lot lineage placement confirmed correct, not changed.** A root Batch's Seed Lot identity now lives on its one `SowingEvent` (above), never on `CropBatch` itself -- deliberately, since a Batch created by split/merge derivation has no `SowingEvent` of its own and must never get a naive, wrong single Seed Lot value. Derived-batch Seed Lot provenance is traced dynamically through derivation ancestry by CMP-019's existing `lineage_traversal._seed_origins_for_batches` (unchanged, not touched by this ticket) -- confirmed the correct, already-proven mechanism for that case, not reimplemented here.

**Workflow resolution is re-run only for genuinely new commands.** `_resolve_sowing_workflow` was already called after the exact-replay check in `nursery_service.sow_new_batch`, so an exact replay of an already-succeeded command was already safe from workflow-configuration drift -- `test_replay_does_not_rerun_workflow_resolution_and_stays_on_original_workflow` makes this explicit and regression-proof. `test_new_command_after_workflow_config_change_uses_current_rules_not_frozen_history` proves the converse: a genuinely new `client_command_id` resolves against current configuration, never reusing an earlier command's stale resolution.

**Multiple Seeding Stations per Nursery -- never silently resolved to one.** `GET /farms/{farm_id}/farm-setup/greenhouses/{id}` previously returned `nursery_seeding_station` (singular, silently the first found) even though the generic `POST /farms/{farm_id}/locations` route has no cardinality guard preventing a second `seeding_station` location under one Nursery Greenhouse (only the Farm Setup wizard itself is limited to at most one). It now returns `nursery_seeding_stations` (the full list). `SowingForm` auto-selects only when exactly one station exists; with zero, an actionable "no Seeding Station configured" message is shown; with more than one, the operator must choose explicitly via a real `<select>` -- never guessed.

## NURSERY-OPS-002A / PILOT-UX-001B addendum: Germination Placement (physical only)

A Sown Seed Tray has a `batch_carrier_assignment` (this document, above) but -- deliberately, per this document's own Scope section -- no CMP-006 Occupancy from Sowing itself: "what batch does this carrier hold" and "where is it physically" remain separate facts. NURSERY-OPS-002A closes the physical-placement half for the Nursery's Germination stage only, without touching anything above: a Trolley Asset is placed into a Germination Chamber Location, and a Sown Tray is then placed directly onto one of that Trolley's Levels (new model, `direct_level`, PILOT-UX-001B) or into one of that Level's legacy child Slot `AssetPosition`s (`legacy_level`) (see `OCCUPANCY_MOVEMENT_MODEL.md`, `LOCATION_MODEL.md`). Placement never rewrites, closes, or infers a `batch_carrier_assignment` row -- moving a Tray's physical Occupancy leaves its Batch, Seed Lot, and Seeds Sown exactly as Sowing recorded them; a regression test proves the assignment row (`id`, `batch_id`, `opening_sowing_event_id`, `released_effective_time`) is byte-for-byte unchanged after a Tray placement.

**Seeding Station is not a Tray's physical location.** `sowing_events.seeding_station_id` (above) is event provenance only -- where the Sowing *happened* -- never a fixed/current placement; a just-sown Tray has no physical Occupancy at all until explicitly placed onto a Trolley Level/Slot (`AWAITING_PLACEMENT`, see below). The first placement's Movement source is therefore always "none", resolved server-side by the existing generic `movement_service.execute_movement` -- Germination Placement fabricates no synthetic Seeding-Station-origin Occupancy row to bridge the gap.

**Tray placement state (derived, never persisted).** `GET /farms/{farm_id}/germination/trays` classifies every actively-assigned Sown Tray into `awaiting_placement` (no Occupancy at all), `elsewhere` (occupies something that does not currently resolve through a Trolley sitting in a Nursery Germination Chamber), or `in_germination` (occupies a Level or Slot on a Trolley that currently does) -- computed fresh from live Occupancy state on every read, exactly like `movement_service.get_resolved_location`'s own approach; there is no persisted status column to drift out of sync.

**Still deferred (unchanged from this document's own "Deferred" list above).** Germination *observations* -- `GerminationCheck`, germination percentage/rate, normal/abnormal/failed counts, `NON_GERMINATION`, biological loss/quantity reconciliation, and any automatic workflow-stage transition on placement -- remain entirely out of scope of NURSERY-OPS-002A and untouched by it. Physical placement is not evidence of germination success; it is Germination-*stage* logistics only. That biological layer is NURSERY-OPS-002B.

## NURSERY-OPS-002B addendum: Seeds vs. Sites, extended to the biological outcome

`seed_count` (this document, CMP-009) and `sown_site_count` (NURSERY-OPS-001.1 addendum, above) remain exactly as documented -- two genuinely separate, optionally-independent facts; `sown_site_count` may still be `NULL`, and the example `Seeds Sown = 210, Sown Sites = 200` remains valid. NURSERY-OPS-002B does not change either column or their relationship. It adds a **third**, independent axis: the modern biological Germination outcome (`germination_outcome_snapshots`, see `OBSERVATION_QUALITY_MODEL.md`'s own addendum for full semantics) anchors to `seed_count` specifically -- never `sown_site_count` -- because the frozen product decision is that operators count individual emerged seedlings, a fact `seed_count` already represents at Sowing time; `sown_site_count`, being a site/cell count, is not the right unit for a seedling-based observation and is shown to the operator only as separate, honestly-nullable context. The legacy `germination_checks` table continues to anchor to `sown_site_count` exclusively, as it always has -- neither model borrows the other's denominator.

## CARRIER-CONFIG-001B addendum: Seed Tray sowing capacity

Three genuinely distinct quantities are now all in play at Sowing time:

```text
CarrierSpecification.biological_position_count -- physical design capacity
                                                     (see CMP_MASTER_SPEC.md §2;
                                                     the reusable Seed Tray DESIGN's
                                                     physical cell/hole count)
SowingEventLine.sown_site_count                 -- physical sites actually used
                                                     in THIS Sowing
SowingEventLine.seed_count                       -- seeds actually placed in
                                                     THIS Sowing
```

**`sown_site_count` is now always captured on the operator-facing command,
superseding the NURSERY-OPS-001.1 addendum's deliberate `NULL`.** The
Nursery Sowing command (`POST /farms/{farm_id}/nursery/sowings`,
`SowNewBatchTrayIn`) now requires a positive `sown_site_count` per tray, in
addition to the existing `seeds_sown` (`seed_count`) -- both fields are
independently, honestly operator-supplied, never one fabricated from the
other. The general/legacy route's own request schema
(`SowingEventLineIn.sown_site_count`) is unchanged -- it already required
this field since CMP-009. Every Sowing Event Line recorded *before* this
ticket via the Nursery command keeps its historical `sown_site_count =
NULL` untouched -- this is not backfilled, matching this document's own
immutable-history discipline throughout.

**Capacity enforcement: `sown_site_count <= biological_position_count`,
when both facts are known.** Enforced once, in the shared
`sowing_service._sow_batch_core` (used by both the legacy/general and the
Nursery Sowing command), immediately alongside the existing
carrier-type-match check -- never duplicated between the two entry
points. A violation raises `SowingCapacityExceededError` (HTTP 422) before
any row is written, so a capacity-invalid tray in a multi-tray command
fails the whole command atomically, exactly like every other Sowing
rejection reason.

**`seed_count`/`seeds_sown` is never compared against
`biological_position_count`.** Multiple seeds may legitimately occupy one
planting position (e.g. `biological_position_count = 200, sown_site_count
= 200, seed_count = 250` is valid) -- this ticket introduces no such
comparison, anywhere.

**The rule is skipped, never fabricated, whenever CMP has no physical
capacity fact to compare against:**

- a Carrier with `specification_id IS NULL` -- every historical (pre-
  CARRIER-CONFIG-001A) Seed Tray Carrier, intentionally preserved as
  still-valid by that ticket, remains fully sowable; capacity enforcement
  is simply not reachable for it.
- a `CarrierSpecification` with `biological_position_count IS NULL` --
  can no longer be produced for a NEW `seed_tray` specification (see
  below), but a historical one, if it exists, remains a valid record and
  does not block Sowing.

**New Seed Tray Carrier Specifications must define a positive
`biological_position_count`.** `seed_tray.requires_specification = true`
since CARRIER-CONFIG-001A, so this is enforced by the SAME existing,
generic, CarrierType-driven service-layer rule
(`carrier_specification_service._require_minimum_fields_if_specification_required`)
that already required `length_mm`/`width_mm`/`biological_position_count`
for any specification-required CarrierType -- no new production code, no
database trigger; this ticket only adds explicit `seed_tray`-specific test
coverage of a rule that already existed. Unrelated CarrierTypes are
untouched: a type that does not require a specification still allows a
fully unset `biological_position_count`, exactly as before.

**Frontend.** The Nursery Sowing operator screen now shows each selected
Seed Tray's known capacity (via the extended
`GET /farms/{farm_id}/nursery/seed-trays/available` response, which now
carries `specification_id`/`specification.biological_position_count`
alongside the existing `carrier_type`), collects `sown_site_count`
alongside `seeds_sown`, and client-side prevents submitting a
`sown_site_count` above a known capacity -- a convenience check only; the
backend remains authoritative. A legacy tray with unknown capacity shows
"Capacity unknown" and is never blocked on that basis alone.
