# Water and Nutrient System Model

PILOT-WATER-001A: the hydroponic water/nutrient DOMAIN/API FOUNDATION.
Manual/human-entered only — no PLC/fertigation-controller integration, no
automatic dosing, no automatic sensor ingestion, no autonomous control.
Operator-facing screens (PILOT-WATER-001B) are not built here.

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
  real, overlapping `WaterDeliveryEvent` (in which case it is labelled
  `RECORDED_DELIVERY_EXPOSURE`, still never "confirmed" in the sense of a
  disease/quality finding — that remains a separate domain, e.g. `CropIssue`).

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

## Crop Water Exposure read model (`app/services/water_exposure_service.py`)

Read-only. No table is written to; no audit event is appended for a read.

- **Forward:** `get_water_exposure_history_for_batch` — given a Batch and
  a time window, which Reservoir(s)/Circuit(s) potentially supplied water
  to it.
- **Reverse:** `get_potentially_exposed_placements_for_circuit` /
  `..._for_reservoir` — given a Circuit/Reservoir and a time window, which
  Batch Placements were potentially exposed.

Both directions intersect two independent histories that must each
overlap the query window: `Occupancy` (which Location a carrier physically
occupied) and `BatchCarrierAssignment` (which Batch that carrier was
assigned to) — never assumed from either alone. A Circuit's eligible
Location scope is its currently/historically mapped `WaterDeliveryPoint`
Location(s), expanded to every descendant Location (a `WITH RECURSIVE`
walk down `locations.parent_location_id`) — so a Circuit mapped to a whole
Zone correctly includes every Table inside it, honestly, without
fabricating narrower precision the topology mapping does not actually
have (section 20).

Two distinct, explicitly labelled exposure kinds:

- `CONFIGURED_TOPOLOGY_EXPOSURE` — the Location was within the Circuit's
  configured scope during the window, regardless of whether a Delivery was
  ever actually recorded.
- `RECORDED_DELIVERY_EXPOSURE` — additionally, at least one real
  `WaterDeliveryEvent` for that Circuit overlaps the window. Strictly
  stronger evidence.

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
Water Delivery Event record. No hard delete anywhere in this domain.

## Corrections

Insert-only tables (`WaterMeasurement`, `InstrumentCalibrationEvent`,
`NutrientMix`/`NutrientMixInput`, `ReservoirEvent`, `WaterDeliveryEvent`)
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

## Out of scope (this ticket)

Operator UI (PILOT-WATER-001B), graphical plumbing diagrams, controller
integration, sensor ingestion, automatic dosing, automatic irrigation,
irrigation optimization, AI nutrient recommendations, AI disease
inference, weather integration, open-field irrigation, a lab module,
inventory auto-consumption, a full maintenance system, alerts/
notifications, offline mode.
