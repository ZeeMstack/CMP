# Water and Nutrient System Model

PILOT-WATER-001A: the hydroponic water/nutrient DOMAIN/API FOUNDATION.
Manual/human-entered only — no PLC/fertigation-controller integration, no
automatic dosing, no automatic sensor ingestion, no autonomous control.

PILOT-WATER-001B (this section's additions below): the operator-facing
frontend workspace built on top of the frozen 001A domain. 001B never
redesigns or duplicates the 001A domain — it is UI plus a small number of
additive, read-only backend list endpoints and an optional-timestamp
(HOTFIX-TIME) fix, documented under "PILOT-WATER-001B additions" below.

## Product questions this domain answers

1. Where did this water/nutrient solution come from? — `WaterSource`
2. Which reservoir held it? — `Reservoir`
3. Which irrigation circuit delivered it? — `IrrigationCircuit`
4. Which crop locations were exposed to that circuit? — `WaterDeliveryPoint` + effective-dated links + the exposure read model
5. What was measured? — `WaterMeasurement`
6. Where was it measured? — `SamplingPoint`
7. Which instrument was used? — `WaterInstrument`
8. Was that instrument calibrated? — `InstrumentCalibrationEvent`
9. What nutrient recipe was approved? — `NutrientRecipe` / `NutrientRecipeVersion`
10. What was ACTUALLY mixed? — `NutrientMix` / `NutrientMixInput`
11. What was ACTUALLY delivered? — `WaterDeliveryEvent`
12. What additions/top-ups/flushing/replacement occurred? — `ReservoirEvent`
13. Which Batches may have shared water exposure during a time window? — `water_exposure_service`

## Frozen domain rules

These are never re-derived or silently relaxed by any command in this domain:

- **Water Topology != physical Location hierarchy.** Water Source →
  Reservoir → Irrigation Circuit → Delivery Point → Drainage/Return Point
  → Return Reservoir is a separate graph. It may REFERENCE Locations
  (`WaterDeliveryPoint.location_id`, optional `Reservoir.location_id`/
  `WaterReturnPoint.location_id`); nothing in this domain is ever inserted
  into the Location tree or the `location_types` catalog.
- **Shared Water = potential exposure, never a disease/contamination/
  infection claim.** Every exposure read is labelled `CONFIGURED_TOPOLOGY_
  EXPOSURE` or `RECORDED_DELIVERY_EXPOSURE` — the words "affected",
  "contaminated", "infected" never appear in this domain's data or code.
- **Approved Recipe != actual Mix != actual Delivery.** Three structurally
  independent tables; no command in this domain ever infers one from
  another (activating a Recipe Version never creates a Mix; creating a Mix
  never creates a Delivery).
- **Target != Measurement.** A Recipe Version's `target_ec`/`target_ph` and
  a `WaterMeasurement`'s `value` are different facts in different,
  independently immutable tables. Recording a Measurement never rewrites a
  target; nothing ever copies a target into a Measurement.
- **Measurement != Calibration.** Recording a Measurement never implies,
  and never requires, that the referenced Instrument is currently
  calibrated — calibration status is read only from `InstrumentCalibrationEvent`.
- **Mix Input != Inventory Consumption.** Recording a `NutrientMixInput`
  never writes to `inventory_existence_ledger_entries` or any other Store
  accounting table.
- **Topology Exposure != Confirmed Actual Exposure** unless backed by a
  real, overlapping `WaterDeliveryEvent` on the same Reservoir and Circuit
  (in which case exactly the overlapping interval — never the surrounding
  time — is labelled `RECORDED_DELIVERY_EXPOSURE`, still never "confirmed"
  in the sense of a disease/quality finding — that remains a separate
  domain, e.g. `CropIssue`).

## Water topology

| Entity | Table | Identity |
|---|---|---|
| Water Source | `water_sources` | tenant/farm, code, name, `source_type` (bore/municipal/ro_treated/storage_tank_feed/other) |
| Reservoir | `reservoirs` | tenant/farm, code, name, `reservoir_type` (source_tank/nutrient_reservoir/return_reservoir/mixing_reservoir/other), optional nominal capacity + UOM, optional linked Asset, optional Location |
| Irrigation Circuit | `irrigation_circuits` | tenant/farm, code, name, free-text `system_type` (never a crop name) |
| Water Delivery Point | `water_delivery_points` | tenant/farm, code, name, **mandatory** `location_id` (a real Location — leaf or ancestor, whichever matches the actual plumbing) |
| Water Return Point | `water_return_points` | tenant/farm, code, name, optional `location_id` |

All six carry `status` (`active`/`inactive`) and are managed by
`water_topology_service`. No DB trigger blocks UPDATE/DELETE on these
current-state master-data rows — the owning service is the only path that
ever creates one, and no delete endpoint is exposed (mirrors
`growing_protocols`'s own identical precedent).

## Effective-dated topology connections

Four explicit, typed link tables (deliberately not one generic graph-edge
table — the ticket calls for explicit domain entities over an
unconstrained graph):

| Link | Table | Unique-active side |
|---|---|---|
| Water Source → Reservoir | `water_source_reservoir_links` | one active Source per Reservoir |
| Reservoir → Irrigation Circuit | `reservoir_circuit_links` | one active Reservoir per Circuit |
| Irrigation Circuit → Water Delivery Point | `circuit_delivery_point_links` | one active Circuit per Delivery Point |
| Water Return Point → Return Reservoir | `return_point_reservoir_links` | one active Return Reservoir per Return Point |

Each row carries `effective_from`/`effective_to` (nullable = still active),
`created_by_user_id`, and an optional `reason`. A link is **never**
updated to change its endpoints or re-opened once closed — the only legal
UPDATE is setting `effective_to` from `NULL` to a timestamp, exactly once
(enforced at the DB level by `enforce_water_topology_link_closure_only`,
this ticket's migration, shared by all four tables). Superseding a link
means closing the old row and opening a new one in the same
`water_topology_service` call sequence — "what was connected to what on
September 20" is always answerable by scanning history that was never
overwritten. Drain-to-waste systems simply never get a
`return_point_reservoir_links` row — no Return Reservoir is fabricated
(section 7).

## Sampling Point

`sampling_points`: never free-floating. `point_type` (source/reservoir/
circuit_supply/delivery/drain_return/other) determines exactly which one
of five typed anchor columns (`water_source_id`/`reservoir_id`/
`irrigation_circuit_id`/`water_delivery_point_id`/`water_return_point_id`)
must be populated — enforced by a DB CHECK mirroring `QrIdentifier`'s own
"exactly one of N, matching a discriminator" shape. `point_type = 'other'`
is the one acknowledged residual case with no anchor at all.

## Instrument and Calibration

`water_instruments` deliberately references an existing `Asset` (via
`asset_id`) rather than duplicating a second physical-object catalog —
code, name, serial/model metadata, and active/inactive status all already
live on that Asset row. This ticket adds exactly one new seeded
`asset_types` row (`water_quality_meter`) since none of the five existing
ones (germination_trolley, transfer_trolley, seeding_machine,
weighing_scale, label_printer) represent a water-quality meter; a farm may
also register a `WaterInstrument` against any other existing Asset it
already uses for this role. `supports_ph`/`supports_ec`/
`supports_solution_temperature`/`supports_dissolved_oxygen` are the
instrument's own measurement capabilities (at least one required).

`instrument_calibration_events`: immutable, insert-only calibration
history (`metric`, `effective_at`, `result` [pass/fail/adjusted],
`standard_reference`, `notes`). `water_instrument_service.
instrument_calibration_status` is the one read that answers "is this
instrument currently calibrated" — it looks only at this table's own
history, per metric, never at whether a Measurement happens to exist.

## Water Measurement

`water_measurements`: immutable, insert-only. Anchored to a
`sampling_point_id` (never a bare Farm id), carrying `metric` (PH / EC /
SOLUTION_TEMPERATURE / DISSOLVED_OXYGEN — extensible later to ORP,
alkalinity, flow, source-water/drainage EC/pH without a schema change),
`value`, `unit`, `effective_at`, `recorded_by_user_id`, and an optional
`water_instrument_id`.

`unit` uses a small, local, per-metric controlled mapping
(`CANONICAL_UNIT_BY_METRIC` in `app/models/water_measurement.py`) rather
than the shared `unit_of_measures` catalog — see
`docs/product/OPEN_QUESTIONS.md` "Water and Nutrient System decisions" for
why. Reservoir capacity, Mix volumes, Mix Input quantities, Reservoir
Event quantities, and Delivery volumes all DO use the real
`unit_of_measures` catalog (validated `quantity_kind = 'volume'` at the
service layer).

## Nutrient Recipe

`nutrient_recipes` / `nutrient_recipe_versions`: mirrors
`GrowingProtocol`/`GrowingProtocolVersion`'s own proven versioned-spec
shape almost exactly — `draft -> active -> retired`, ACTIVE-immutable
content, per-command idempotency (`client_command_id`/
`request_fingerprint` pairs for create/activate/retire), and "activating a
draft auto-retires the previously active version in the same transaction."
Unlike a Growing Protocol, `crop_id`/`variety_id`/`production_system_id`
are all optional — a Recipe is frequently crop-agnostic (a baseline
RO/source-water program reused across many crops).

`nutrient_recipe_components`: one TARGET ingredient line on a DRAFT
version only (enforced in `nutrient_recipe_service`, never a DB trigger —
mirrors `growing_protocol_service.add_observation_requirement`'s own
"DRAFT-only" precedent). `component_label` is always populated (a display
name — "Stock A", "Source Water" — even when `inventory_item_id` is also
set); `inventory_item_id` is the preferred, optional link to the existing
`InventoryItem` catalog (no second fertilizer catalog is created).
**`target_quantity` is a target only — adding a component never touches
Store inventory existence.**

## Nutrient Mix

`nutrient_mixes` / `nutrient_mix_inputs`: immutable, insert-only record of
what was ACTUALLY prepared. `nutrient_recipe_version_id` is optional
reference/guidance only. `NutrientMixInput.actual_quantity` is always an
explicit fact the caller supplies — nothing ever auto-copies a Recipe
Component's target quantity as an actual input. Recording a
`NutrientMixInput` never decrements Store inventory (no code path in this
module touches `InventoryExistenceLedgerEntry`/`InventoryMaterialEvent`);
see `docs/product/OPEN_QUESTIONS.md` for the deliberately-not-built
explicit consumption-transaction link.

## Reservoir Event

`reservoir_events`: immutable, insert-only actual operating event
(`NUTRIENT_ADDITION`/`WATER_TOP_UP`/`PH_ADJUSTMENT`/`SOLUTION_REPLACEMENT`/
`FLUSH`/`DRAIN`/`OTHER`). Structurally has no "resulting EC"/"resulting
pH" column and no recommended-dosage column — a `WaterMeasurement` taken
afterward is the only way a result is ever recorded, and it is always a
separate, independent fact.

## Water Delivery Event

`water_delivery_events`: immutable, insert-only actual delivery interval
from a Reservoir through an Irrigation Circuit. `delivered_volume` is
optional — "delivery occurred from X to Y" is a complete, valid fact on
its own where a farm cannot yet measure volume. `effective_end` is
optional too, so a continuously-circulating DWC circuit is one
open-or-closed operating interval, never fabricated discrete pulses.
`nutrient_mix_id` is optional context, never implying that recording a Mix
caused a Delivery or vice versa.

An ongoing delivery is ended only by the UX-OPS-001D0 End Delivery command,
which appends a `water_delivery_end_events` row and never updates the
original row. Every delivery read resolves the domain end as `original
effective_end ?? end-event effective_end ?? NULL` (see "UX-OPS-001D0
additions" below).

## Crop Water Exposure read model (`app/services/water_exposure_service.py`)

Read-only. No table is written to; no audit event is appended for a read.
Rebuilt by UX-OPS-001D0 as one exact interval engine shared by every read
(the PILOT-WATER-001A version labelled the whole query window as recorded
exposure whenever any delivery on the Circuit overlapped it, and aggregated
reservoirs/Locations across non-overlapping evidence).

- **Forward:** a Batch and a time window → its exact exposure intervals, and
  explicit gaps.
- **Reverse:** a Circuit or Reservoir and a time window → the exact exposure
  intervals of every Batch Placement it reached.

**Interval convention: half-open `[start, end)`.** Start is inclusive, end
exclusive; touching intervals do not overlap; no zero-duration interval is
ever emitted; `window_start < window_end` (both timezone-aware) is validated
at the API boundary (422 otherwise). A source interval with no persisted end
(an open Occupancy/Assignment/link, or an ongoing Delivery) is clipped to
`window_end` in the response. The record then has `end_clipped_to_window`
set and names the open sources in `open_ended_sources`. No end is ever
fabricated or persisted. Every timeline response carries `interval_convention
= "HALF_OPEN_START_INCLUSIVE_END_EXCLUSIVE"`.

**Route.** One `reservoir_circuit_links` row joined to one
`circuit_delivery_point_links` row on the same Circuit, active over their
intersection. A route serves its Delivery Point's Location and every
descendant Location (a `WITH RECURSIVE` walk down
`locations.parent_location_id` — parentage is immutable, so the current tree
is exact for any past window). A Circuit mapped to a whole Zone honestly
includes every Table in it (section 20).

**Placement.** A `BatchCarrierAssignment` and an `Occupancy` of the same
Carrier, intersected — never assumed from either alone.

Two distinct, explicitly labelled exposure kinds:

- `RECORDED_DELIVERY_EXPOSURE` — the exact non-empty intersection of
  (1) the query window, (2) the Batch-to-Carrier assignment, (3) that
  Carrier's Occupancy at a Location the route serves, (4) the
  Circuit→Delivery Point link, (5) the Reservoir→Circuit link, and (6) a
  `WaterDeliveryEvent` whose Reservoir AND Circuit both match the route,
  using its resolved end. A delivery on the same Circuit from a Reservoir
  not linked at that time is not evidence for the route. One record per
  delivery event.
- `CONFIGURED_TOPOLOGY_EXPOSURE` — the exact non-empty intersection of
  (1)–(5) where no recorded delivery covers the period. Topology-only time
  is split around recorded deliveries, never upgraded.

Records are split at every assignment, occupancy, link, delivery, closure,
and window boundary; they are never merged across different reservoirs,
circuits, delivery points, Locations, carriers, delivery events, or evidence
kinds, and are not coalesced at all (each carries its full source
provenance: assignment, occupancy, both link ids, delivery event id).

**Gaps (Batch-forward only).** Time within a valid assignment + Occupancy
(inside the window) that no complete Reservoir → Circuit → Delivery Point
route covers is returned in a separate `gaps` collection with reason
`NO_COMPLETE_TOPOLOGY_ROUTE`. A gap is not an exposure kind; topology-only
time is not a gap. Time with no valid assignment or Occupancy is neither.

Neither kind, nor any value this module returns, is ever "affected",
"contaminated", "infected", or "confirmed" in a disease/quality sense —
that determination, if any, belongs entirely to a separate domain (e.g.
`CropIssue`) acting on this evidence, never to this read model itself.

## Authorization

New permissions (see `app/core/permissions.py` for the full grant matrix):

| Permission | Read tier | Manage tier |
|---|---|---|
| `water_topology.*` | broad | farm_manager, head_grower |
| `sampling_point.*` | broad | farm_manager, head_grower |
| `water_instrument.*` (includes Calibration) | broad | farm_manager, head_grower |
| `water_measurement.*` | broad | farm_manager\*, head_grower\*, production_supervisor, operator |
| `nutrient_recipe.*` | broad | farm_manager, head_grower |
| `nutrient_operations.*` (Mix/Reservoir Event/Delivery Event) | broad | farm_manager\*, head_grower\*, production_supervisor, operator |
| `water_exposure.read` | farm_manager, head_grower, production_supervisor, qc_officer, auditor, read_only | — (read-only by design, mirrors `traceability.read`) |

\* farm_manager/head_grower hold the `.read` half of the operator-tier
floor-recording permissions (full oversight visibility) but not
`.manage` — they do not execute routine floor recording themselves,
matching this codebase's existing "supervisory tier doesn't do floor
work" pattern (e.g. `PACKING_MANAGE`).

Reused, not reinvented: "operators read water topology, record permitted
measurements, record mix/delivery/adjustment events; grower/supervisory
manage topology, manage Recipe drafts/activation, manage Sampling Points,
review exposure, manage calibration records" (ticket section 24) maps
directly onto this table.

## Audit

Every mutation appends an `AuditEvent` via the shared `append_audit_event`
helper: topology entity register/status-change, topology link open/close,
Recipe register/version-create/activate/retire/component-add, Measurement
record, Calibration record, Nutrient Mix record, Reservoir Event record,
Water Delivery Event record, Water Delivery Event end
(`water_delivery_event.ended`, UX-OPS-001D0). No hard delete anywhere in
this domain.

## Corrections

Insert-only tables (`WaterMeasurement`, `InstrumentCalibrationEvent`,
`NutrientMix`/`NutrientMixInput`, `ReservoirEvent`, `WaterDeliveryEvent`,
`WaterDeliveryEndEvent`)
reject every UPDATE/DELETE at the database level
(`reject_append_only_mutation`, reused from `c48f21a6b3d9`). A wrong entry
is corrected by recording a new, later, correct one — see
`docs/product/OPEN_QUESTIONS.md` for why a structured
correction/supersession relationship (naming which earlier row a
correction replaces) was not built in this foundation ticket.

## Migration

`0d62f68527a2` (`migrations/versions/0d62f68527a2_water_and_nutrient_domain_foundation.py`),
revises `203d62ed9e9f`. Twenty new tables, entirely additive; one new
seeded `asset_types` row (`water_quality_meter`). No existing table's
data, columns, or constraints are touched. Downgrade is guarded exactly
like every other domain-introducing migration in this codebase: it raises
and makes zero schema change if any row already exists in any of the new
tables, or if any Asset still references the new asset type.

## Known gaps

See `docs/product/OPEN_QUESTIONS.md`, "Water and Nutrient System decisions
(PILOT-WATER-001A)", for the full, explicit list (UOM scope decision, no
create-command idempotency for topology master data, no structured
correction relationship, exposure reverse-lookup scale, no
Store-consumption linking, service-layer-only UOM-kind validation).

## PILOT-WATER-001B additions

### Multi-source / multi-tank shape (never assumed to be singular)

- A Farm may have **many** `WaterSource` rows (bore + municipal + RO, etc.
  simultaneously) — the Overview and System Setup screens list every
  active source, never assume or display exactly one.
- A single `WaterSource` may feed **multiple** `Reservoir`s via multiple
  concurrent `water_source_reservoir_links` rows — the topology tables in
  System Setup never collapse this to a 1:1 picture.
- Different `Reservoir`/Tank rows commonly serve **different** crop areas
  independently (e.g. one Nutrient Reservoir per Zone) — nothing in the
  frontend infers "this Farm's one tank" or renders a tank as farm-wide by
  default.
- A `Reservoir` may serve **one or several** `IrrigationCircuit`s (and
  therefore several Locations) via multiple concurrent
  `reservoir_circuit_links` rows.
- Supply relationships are **effective-dated**: the System Setup Topology
  view and the Exposure views always show current and historical link rows
  together (never only the currently-open one), and exposure queries for a
  past window resolve against the topology that was actually true during
  that window, not only today's.

### Navigation and workspace

`Production → Water & Nutrients` (`/farms/{farmId}/water`) with an in-page
six-tab subnav (`components/water/WaterSubNav.tsx`, mirrors
`StoreSubNav`): Overview / Measurements / Mixing / Delivery / Exposure /
System Setup. `Company catalogs → Nutrient Recipes`
(`/nutrient-recipes`, `/nutrient-recipes/[recipeId]`) is a separate,
tenant-wide catalog page mirroring Growing Protocols' own route shape —
Recipe administration is never nested inside a single Farm's Water
workspace.

### Backend additions (small, additive, read-only unless noted)

- Farm-wide list endpoints that did not exist in 001A, added because the
  UI's farm-wide screens (Overview, System Setup Topology, Measurement
  History, recent Mixes/Reservoir Events/Deliveries, Today's Water
  Attention) need to look across every Reservoir/Circuit at once, not one
  entity at a time: `GET /farms/{farmId}/water-topology-links/*` (all four
  link kinds), `GET /farms/{farmId}/nutrient-mixes`,
  `GET /farms/{farmId}/reservoir-events`,
  `GET /farms/{farmId}/water-delivery-events`,
  `GET /farms/{farmId}/water-measurements` (filterable by metric/
  reservoir/time window).
- `GET /farms/{farmId}/water/attention` (`app/services/
  water_attention_service.py`, new file) — the Today-on-the-Farm "Water
  Attention" read model. Conservative by design: it flags only (a) an
  active Circuit with no currently-open `reservoir_circuit_links` row, (b)
  a `WaterInstrument` with zero `InstrumentCalibrationEvent` rows ever, (c)
  a Measurement whose value falls outside its Recipe Version's target EC/pH
  by more than a documented ±10% tolerance band. It never invents an alert
  rule beyond these three, and never fabricates a status for a condition it
  cannot actually evaluate.
- **HOTFIX-TIME-002 pattern applied to every 001A "floor recording"
  command that previously required an explicit client timestamp**
  (`WaterMeasurementCreate.effective_at`, `CalibrationEventCreate.
  effective_at`, `NutrientMixCreate.effective_at`,
  `ReservoirEventCreate.effective_at`, `WaterDeliveryEventCreate.
  effective_start`): each is now `datetime | None = None`. `None` means
  "record now" and resolves to the server's own `datetime.now(timezone.utc)`
  **after** the idempotency/fingerprint check (never part of the
  fingerprint), so a retried "now" command replays the original row
  instead of duplicating or erroring; a caller-supplied future timestamp is
  rejected. This closes the same browser-clock-skew defect class as
  HOTFIX-TIME-002 elsewhere in the codebase. `effective_to`/
  `effective_end` fields remain conceptually distinct "still open" facts
  and are never resolved to "now" by this change. Frontend forms never
  submit a browser-generated timestamp as the authoritative "now" — they
  either omit the field or, when the operator explicitly back-dates an
  entry, send that exact chosen ISO timestamp.

### Frozen distinctions the UI never blurs

Recipe != Mix != Delivery, Target != Measurement, Calibration !=
Measurement, Mix Input != Store Consumption, Water Topology != Location
hierarchy, Shared Water != Disease (exposure wording stays exactly
"Configured Topology Exposure" / "Recorded Delivery Exposure", never
"Affected/Contaminated/Infected"), and Exposure always follows actual
topology + placement + recorded-delivery evidence, never Farm membership
alone (two tanks/circuits serving different greenhouses on the same Farm
never cross-expose each other in the UI).

### Deferred, not built in 001B

- **QR entity types for Sampling Point / Reservoir / Instrument / Circuit**:
  `qr_identifiers` has a fixed, CHECK-constrained set of entity-type
  columns (migration `29d6697de6d5`). Adding a Water entity type to it is
  a genuine schema change, which conflicts with 001B's "prefer no
  migration" instruction — deferred to a future ticket rather than done
  here. No QR entry points were added for this domain in 001B.
- A structured correction/supersession relationship, topology
  create-command idempotency, exposure reverse-index optimization, and the
  Store-consumption linkage remain exactly as documented under "Known
  gaps" below — 001B did not touch any of them.

## UX-OPS-001D0 additions (water correctness foundation, N06/N07)

Backend and read-model only; no Water UI change (the Water workspace
reorganization is the follow-up UX-OPS-001D).

### End Delivery command (N07)

`POST /farms/{farm_id}/water-delivery-events/{water_delivery_event_id}/end`,
permission `nutrient_operations.manage`. Request:
`{ "effective_end": <tz-aware>, "note": <string|null>, "client_command_id": <uuid> }`.
Operator-approved scope: records only `effective_end` and an optional
`note` — never a final volume, UOM, mix, reservoir, circuit, or start time.
Response: `WaterDeliveryEventRead` with the resolved end (201).

- `water_delivery_end_events` (migration `3686130d89a9`): append-only
  (`reject_append_only_mutation` UPDATE/DELETE triggers); exactly one per
  delivery (`ux_water_delivery_end_events_delivery`); command identity
  unique per tenant; tenant/farm pinned to the delivery by a composite FK
  (backed by the new `uq_water_delivery_events_tenant_farm_id`); a BEFORE
  INSERT trigger rejects ending a delivery created with an end, and an end
  before the delivery's start.
- Command: locks the delivery (`FOR UPDATE`, tenant+farm scoped), validates,
  inserts the end event plus a `water_delivery_event.ended` audit event,
  and commits once. The fingerprint covers farm, delivery, `effective_end`
  (normalized to UTC) and `note` (a null note differs from an empty one).
  Same command + same payload replays (no second row or audit); a different
  payload returns 409; a second command on an ended delivery returns 409;
  end before start or in the future returns 422. Missing, cross-tenant and
  cross-farm targets all return the same 404.
- No backfill: a delivery created with an end keeps its original end as
  authoritative. The original `water_delivery_events` row is never updated.

**Resolved delivery read.** Every delivery read (farm list, circuit list,
the new `GET /farms/{farm_id}/water-delivery-events/{id}` detail, the
command/replay responses, and the exposure engine) returns `effective_end`
as `original ?? end-event ?? null`. Additive fields: `end_source`
(`RECORDED_AT_CREATION` | `END_EVENT` | null), `water_delivery_end_event_id`,
`end_note`.

### Exposure timeline contract (N06)

Additive endpoints (permission `water_exposure.read`, query `farm_id`,
`window_start`, `window_end`):

- `GET /crop-batches/{batch_id}/water-exposure-timeline` →
  `BatchWaterExposureTimelineRead { batch_id, farm_id, window_start,
  window_end, interval_convention, intervals[], gaps[] }`
- `GET /irrigation-circuits/{id}/water-exposure-timeline` and
  `GET /reservoirs/{id}/water-exposure-timeline` →
  `WaterExposureTimelineRead { anchor_type, anchor_id, farm_id,
  window_start, window_end, interval_convention, intervals[] }`

`WaterExposureIntervalRead`: `exposure_kind`, `interval_start`,
`interval_end`, `batch_id`, `carrier_id`, `location_id`, `reservoir_id`,
`irrigation_circuit_id`, `water_delivery_point_id`,
`delivery_point_location_id`, `water_delivery_event_id` (null for topology
only), `batch_carrier_assignment_id`, `occupancy_id`,
`reservoir_circuit_link_id`, `circuit_delivery_point_link_id`,
`start_clipped_to_window`, `end_clipped_to_window`, `open_ended_sources`.
`WaterExposureGapRead`: `reason`, `gap_start`, `gap_end`, placement ids,
the same clipping flags.

The three PILOT-WATER-001A endpoints (`.../exposed-placements` ×2,
`/crop-batches/{id}/water-exposure`) keep their response shapes, with
additive fields only. They are now built from the same engine: one row per
exact interval, and `reservoir_ids`/`location_ids` in the Batch read are
single-element lists, never an aggregate. The current Exposure page keeps
working unchanged, with correct rows.

## Out of scope (both tickets)

Graphical plumbing diagrams, controller integration, sensor ingestion,
automatic dosing, automatic irrigation, irrigation optimization, AI
nutrient recommendations, AI disease inference, weather integration,
open-field irrigation, a lab module, inventory auto-consumption, a full
maintenance system, alerts/notifications, offline mode.
