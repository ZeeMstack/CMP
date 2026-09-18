# Harvest Forecast and Capacity Planning Model

PILOT-PLAN-001A: the capacity-aware harvest forecasting domain. Adds planning
intelligence strictly on top of the existing `ProductionRequirement` /
`SeedingProgramLine` / `CropBatch` / `Location` domain (`docs/domain/
SEED_SOWING_MODEL.md`, `docs/domain/LOCATION_MODEL.md`) — no existing table is
touched, and no new demand/coverage storage duplicates `planning_service`'s own
read-model. See `docs/product/OPEN_QUESTIONS.md`'s PILOT-PLAN-001A section for
the judgment calls this document's design choices rest on.

## Frozen accounting distinctions (do not collapse)

```
DEMAND (ProductionRequirement)
  != PRODUCTION PLAN
  != SEEDING PROGRAM (SeedingProgramLine)
  != ACTUAL SOWING (SowingEvent)
  != BATCH (CropBatch)
  != HARVEST FORECAST (BatchHarvestForecast)
  != ACTUAL HARVEST (HarvestEvent / HarvestedProduceLot)
  != PACKED QUANTITY
  != DISPATCHED QUANTITY
```

- **Forecast quantity is not inventory.** `BatchHarvestForecast` never appears
  in any stock/balance calculation.
- **Planned capacity is not physical occupancy.** `ProductionCapacityAllocation`
  never creates, reads as, or substitutes for an `Occupancy` row.
- **A risk signal (open Crop Issue) never automatically adjusts a forecast
  quantity or declares a forecast failed.** It is surfaced for human review only.
- **Protocol timing is not forecast.** See "Forecast basis" below — no
  protocol-derived timing exists in this codebase, so `PROTOCOL_GUIDANCE` is a
  human-asserted classification only, never system-computed.
- **Customer/commercial domain is deferred to PILOT-COMM-001.** No Customer,
  order, or pack-specification model is added here. `ProductionCapacityAllocation`
  links only to `SeedingProgramLine`/`CropBatch` (which already reach
  `ProductionRequirement`), so PILOT-COMM-001 can attach commercial context to
  `ProductionRequirement` later without rebuilding forecast/capacity.

## Part 1 — Batch Harvest Forecast

`batch_harvest_forecasts` (`app/models/batch_harvest_forecast.py`) is an
**insert-only revision chain**, not a mutable row: `harvest_forecast_service.
record_batch_harvest_forecast` either creates the Batch's first forecast
(`revision_number = 1`) or supersedes the current one — it never updates a row
in place. Every past revision remains permanently inspectable (CLAUDE.md rule
7/9); `ux_batch_harvest_forecasts_current_batch` (a partial unique index on
`superseded_at IS NULL`) guarantees exactly one CURRENT forecast per Batch.

Shape: `low_quantity <= expected_quantity <= high_quantity`
(`ck_batch_harvest_forecasts_range_shape`), a farm-local `window_start_date`/
`window_end_date` (inclusive-inclusive — see Time Semantics below), a
`quantity_uom_id` (any `unit_of_measures` row, no kind restriction), `basis`
(`grower_estimate` / `planning_assumption` / `protocol_guidance` — no
`ai_prediction`, per the ticket's explicit "do not build AI yield
prediction"), and `recorded_by_user_id`/`effective_time`/`recorded_time`.
`revision_reason` records why a revision was made. The command never touches
`crop_batches`, `batch_stage_runs`, or `occupancies` — recording a forecast
has zero physical-world side effect.

**Transaction ordering note**: superseding a row requires closing the prior
CURRENT row (`superseded_at`, `superseded_by_forecast_id`) and inserting the
new one in the same transaction, but the two rows reference each other in
opposite directions relative to insert order:

- The partial unique index (`superseded_at IS NULL`) is checked
  *immediately*, per statement — so the prior row must be closed (flushed)
  *before* the new row is inserted, or both rows briefly read as "current."
- The self-referential FK (`fk_batch_harvest_forecasts_tenant_superseded_by`,
  `superseded_by_forecast_id -> id`) would then fail immediately, because the
  prior row's UPDATE points at a new row that doesn't exist yet.

Resolved by making that one FK `DEFERRABLE INITIALLY DEFERRED` (checked at
COMMIT, not at the UPDATE statement) while leaving the partial unique index
non-deferrable (Postgres cannot make a partial unique index into a deferrable
constraint at all) — so the service closes the prior row first (flush), then
inserts the new row (flush); the unique index is satisfied at each step, and
the FK is satisfied by commit time.

## Part 2 — Forecast status / actual comparison (read model)

`harvest_forecast_service.get_forecast_status` (schema
`BatchHarvestForecastStatusRead`) is a pure computed read, never persisted:
current forecast, actual harvested weight to date (`harvested_produce_lots.
total_harvested_weight_kg`, summed — the codebase-wide hardcoded-kg harvest
convention), first/latest harvest date, open Crop Issue count, current stage,
and a best-effort list of currently-assigned Location codes (active
`BatchCarrierAssignment` → active `Occupancy.target_location_id`).

Actual-vs-forecast comparison always goes through
`unit_of_measure_service.resolve_conversion_factor(kg -> forecast_uom)`.
When no conversion path exists (e.g. the forecast is recorded in `EA`),
`comparable_to_forecast_uom = False` and the remaining-quantity fields are
`None` — never a silently invented conversion. The forecast row itself is
never rewritten by this read, whatever it computes.

## Part 3 — Forecast basis

`FORECAST_BASES = ("grower_estimate", "planning_assumption",
"protocol_guidance")` — deliberately no `ai_prediction` value. See
`docs/product/OPEN_QUESTIONS.md` for why `protocol_guidance` has no
system-computed protocol timing behind it in V1 (no such field exists in
`growing_protocol_versions` today).

## Part 4/6 — Capacity grain

**Authoritative capacity source: the existing `locations.capacity` column
(DOMAIN-FARM-002)**, referenced directly by FK — no new capacity field or
table is added to the Location model. `capacity_plan_service._effective_
capacity(location)`:

- If `location.capacity` is set: that value, whatever the Location's
  `occupiable` flag.
- Else if `location.occupiable`: `1` (DOMAIN-FARM-002's own physical-default
  semantics — NULL means exclusive occupancy of 1).
- Else: `None` (UNKNOWN/NOT CONFIGURED) — a non-occupiable Location (e.g. a
  Zone, Span, or a Vines Grow Gutter whose true occupiable leaf is the
  individual Grow-Bag Position) has no authoritative capacity fact unless the
  farm has explicitly configured one on that row.

The unit is always **`position`** (an occupant-slot count, matching
DOMAIN-FARM-002's "configured positive integer count of simultaneously
permitted identified occupants" exactly) — never kilograms, and never a
per-allocation variable field, since the sole V1 grain is unit-invariant.

This lets planning target whichever Location level a farm has configured
real capacity on — typically the Grow Table for Leafy Greens (which already
carries a real `capacity`, e.g. plates per table, per
`CMP_MASTER_SPEC.md` §3.2) or a Grow Gutter for Vines once its own capacity
is set — without inventing a second capacity concept, a crop-specific grain
rule (CLAUDE.md rule 1), or a fabricated child-position-summing calculation.

## Part 5 — Planned Capacity Allocation

`production_capacity_allocations` (`app/models/production_capacity_allocation.py`)
is a current-state row (mirrors `ProductionRequirement`): `location_id`
(required), optional `production_system_id`/`source_seeding_program_line_id`/
`source_crop_batch_id`, `planned_start_date`/`planned_end_date`
(half-open — see Time Semantics), `planned_capacity_amount` (> 0),
`status` (`active`/`cancelled`). It never creates `Occupancy`, never reserves
a `Carrier`, never creates or moves a `CropBatch`.

**Overlap rule** (`capacity_plan_service._check_capacity`):

```
PLANNED USED CAPACITY (for a window)
  = sum(planned_capacity_amount) over ACTIVE allocations for the same
    Location whose window overlaps the given window

AVAILABLE PLANNED CAPACITY
  = authoritative_capacity - planned_used_capacity   (only when known)
```

A create/update is rejected (`CapacityAllocationExceedsAuthoritativeCapacityError`)
only when authoritative capacity is *known* and would be exceeded. When it is
UNKNOWN, the write is allowed (a limit that cannot be proven cannot be
enforced) — the read model surfaces `capacity_status = "unknown"` rather than
fabricating unlimited or zero capacity.

Concurrency: a tenant-scoped Postgres advisory lock keyed by `location_id`
serializes concurrent create/update calls against the same capacity resource
(mirrors `planning_service._next_requirement_code_locked`'s own advisory-lock
shape) — see `docs/product/OPEN_QUESTIONS.md` for why this is service-layer,
not a DB trigger/exclusion constraint, unlike DOMAIN-FARM-002's actual-Occupancy
enforcement.

Revision: full-replace `update` command while `status = 'active'`, `cancel`
to stop consuming planned capacity (never deleted). History is
`AuditEvent` before/after, matching `ProductionRequirement`'s own precedent —
see `docs/product/OPEN_QUESTIONS.md` for why this is not a dedicated
version-chain table like `BatchHarvestForecast`.

## Part 7 — Requirement Harvest Outlook (read model)

`planning_service.compute_requirement_harvest_outlook` (schema
`RequirementHarvestOutlook`, `app/schemas/planning.py`) — a READ MODEL, not a
second demand ledger, kept fully separate from the existing
`RequirementFulfillment` (which this function never touches or recomputes
differently).

Reaches actual Crop Batches through the **existing** FK chain only:
`ProductionRequirement` → `SeedingProgramLine` (FK
`production_requirement_id`) → `SowingEvent.seeding_program_line_id`
(optional, provenance-only, set at sow time) → `SowingEvent.batch_id`. No new
demand/linkage storage is added. Multiple Batches may contribute (the batch
set is just whatever SowingEvents link to any of the Requirement's lines);
ad-hoc, unlinked Sowings are simply not part of the rollup, matching
`docs/domain/SEED_SOWING_MODEL.md`'s existing "planning is never mandatory
for execution" rule.

UOM comparability, both for forecast-vs-requirement and actual-vs-requirement,
always goes through `unit_of_measure_service.resolve_conversion_factor`. When
no conversion path exists, `forecast_comparable`/`actual_harvested_comparable`
is `False` and the paired quantity is `None` — `NOT COMPARABLE`, never a
silent conversion.

## Part 8 — Forecast risk signals

V1 surfaces exactly one signal: `open_crop_issue_count` (`crop_issues` where
`status = 'open'` for the Batch). Never changes the forecast quantity, never
declares forecast failure, never infers disease impact — a pure read-model
overlay, matching `crop_issue_service`'s own existing pattern.

## Part 13 — Time semantics

- `BatchHarvestForecast.window_start_date`/`window_end_date`: **inclusive on
  both ends** — a human date range ("harvest between Sep 20 and Sep 25"), no
  interval arithmetic depends on this shape, so simplicity wins.
- `ProductionCapacityAllocation.planned_start_date`/`planned_end_date`:
  **half-open `[start, end)`** — the allocation covers `planned_start_date`
  through `planned_end_date - 1 day` inclusive. Two windows overlap iff
  `a.start < b.end AND b.start < a.end`. Enforced by
  `ck_production_capacity_allocations_window_shape` (`end > start`).

All dates are farm-local planning dates (`Date` columns, no `TIMESTAMP`
truncation), matching `ProductionRequirement.required_by_date`'s existing
precedent — never naive UTC-date slicing.

## Part 11 — Permissions

Two new pairs in `app/core/permissions.py`, mirroring `PLANNING_READ`/
`PLANNING_MANAGE`'s existing role distribution:

| Permission | farm_manager | head_grower | production_supervisor | auditor / read_only |
|---|---|---|---|---|
| `harvest_forecast.read` | ✓ | ✓ | ✓ | ✓ |
| `harvest_forecast.manage` | | ✓ | ✓ | |
| `capacity_plan.read` | ✓ | ✓ | ✓ | ✓ |
| `capacity_plan.manage` | ✓ | ✓ | | |

`operator`, `storekeeper`, `qc_officer`, `packing_supervisor`,
`cold_store_supervisor`, `dispatch_officer` get neither pair — mirrors
`PLANNING_READ`/`PLANNING_MANAGE`'s existing grant list exactly (`operator`
does not hold `planning.read` today either).

## API surface

- **Forecast**: `POST/GET /farms/{farm_id}/crop-batches/{batch_id}/harvest-forecast`,
  `GET .../harvest-forecast/history`, `GET .../harvest-forecast/status`,
  `GET /farms/{farm_id}/harvest-forecast-summary?window_start_date=&window_end_date=`.
- **Capacity**: `POST /farms/{farm_id}/capacity-allocations`,
  `POST .../{id}/update`, `POST .../{id}/cancel`,
  `GET /farms/{farm_id}/capacity-allocations[?location_id=]`,
  `GET .../{id}`, `GET /farms/{farm_id}/locations/{location_id}/capacity-summary?window_start_date=&window_end_date=`.
- **Coverage**: `GET /farms/{farm_id}/production-requirements/{id}/harvest-outlook`
  (gated on `planning.read`, since it is a `ProductionRequirement`-anchored
  extension).

## Deferred / out of scope

AI yield prediction, ML, weather forecasting, financial revenue forecast,
automatic demand acceptance, optimization/scheduling solvers, controller
integration, new crop catalog, a new Harvest model, frontend planning
dashboard, Customer/CRM, commercial orders, pack specifications — all
explicitly out of scope per the ticket, deferred to PILOT-COMM-001 or a
dedicated future ticket where named.
