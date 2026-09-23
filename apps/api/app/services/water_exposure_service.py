"""Read-only CROP WATER EXPOSURE model (PILOT-WATER-001A sections 19-21,
rebuilt as an exact interval engine by UX-OPS-001D0 / N06).

Answers, in both directions:
  - Batch + time window -> over which exact intervals, and via which
    Reservoir -> Circuit -> Delivery Point route, could it have received
    water? (forward, with explicit gaps)
  - Reservoir/Circuit + time window -> which Batch Placements, over which
    exact intervals? (reverse)

This is POTENTIAL EXPOSURE, never a disease/contamination/infection claim
-- those words never appear here or in any value this module returns.

Interval convention: every interval is HALF-OPEN, `[start, end)` -- start
inclusive, end exclusive. Touching intervals do not overlap, and no
zero-duration interval is ever emitted. A source interval with no persisted
end (an open Occupancy, Assignment, topology link, or an ongoing Delivery)
is clipped to the query `window_end` in the response and named in
`open_ended_sources`; no end is ever fabricated or persisted.

One engine (`_compute`) serves the forward and both reverse reads, so they
always agree on the same interval facts. A ROUTE is one
`reservoir_circuit_links` row joined to one `circuit_delivery_point_links`
row on the same Circuit, active over their intersection. A route serves its
Delivery Point's Location and every descendant Location (a `WITH RECURSIVE`
walk down `locations.parent_location_id`) -- a Circuit mapped to a whole
Zone honestly includes every Table in it, never narrowed without evidence.

Two explicitly labelled exposure kinds:
  - `RECORDED_DELIVERY_EXPOSURE`: the exact non-empty intersection of
    (1) the query window, (2) a Batch-to-Carrier assignment, (3) that
    Carrier's Occupancy at a Location the route serves, (4) the
    Circuit-to-Delivery-Point link, (5) the Reservoir-to-Circuit link, and
    (6) a `WaterDeliveryEvent` on the SAME Reservoir AND Circuit as the
    route, using its resolved end (original end, else End Delivery event
    end, else open). One record per delivery event.
  - `CONFIGURED_TOPOLOGY_EXPOSURE`: the exact non-empty intersection of
    (1)-(5) with no recorded delivery covering it. Topology-only time is
    split around recorded deliveries, never upgraded.

Records are never merged across different reservoirs, circuits, delivery
points, Locations, carriers, delivery events, or evidence kinds -- nor
coalesced at all (each record carries its full source provenance).
Non-contiguous evidence stays as separate records.

Gaps (Batch-forward only): time inside a valid Batch assignment + Occupancy
(clipped to the window) that no complete Reservoir -> Circuit -> Delivery
Point route covers, reason `NO_COMPLETE_TOPOLOGY_ROUTE`. A gap is not an
exposure kind. Time with no valid assignment/Occupancy is neither exposure
nor gap.

No table is written to. No audit event is appended for a read."""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

CONFIGURED_TOPOLOGY = "CONFIGURED_TOPOLOGY_EXPOSURE"
RECORDED_DELIVERY = "RECORDED_DELIVERY_EXPOSURE"

INTERVAL_CONVENTION = "HALF_OPEN_START_INCLUSIVE_END_EXCLUSIVE"
GAP_NO_COMPLETE_TOPOLOGY_ROUTE = "NO_COMPLETE_TOPOLOGY_ROUTE"

SOURCE_ASSIGNMENT = "BATCH_CARRIER_ASSIGNMENT"
SOURCE_OCCUPANCY = "OCCUPANCY"
SOURCE_RESERVOIR_CIRCUIT_LINK = "RESERVOIR_CIRCUIT_LINK"
SOURCE_CIRCUIT_DELIVERY_POINT_LINK = "CIRCUIT_DELIVERY_POINT_LINK"
SOURCE_WATER_DELIVERY_EVENT = "WATER_DELIVERY_EVENT"


class ExposureWindowError(ValueError):
    """`window_start` must be strictly before `window_end`, both timezone-aware."""


def validate_window(window_start: datetime, window_end: datetime) -> None:
    if window_start.tzinfo is None or window_end.tzinfo is None:
        raise ExposureWindowError("window_start and window_end must be timezone-aware")
    if not window_start < window_end:
        raise ExposureWindowError("window_start must be before window_end")


@dataclass(frozen=True)
class _Placement:
    batch_id: uuid.UUID
    carrier_id: uuid.UUID
    location_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    occupancy_id: uuid.UUID
    assignment_start: datetime
    assignment_end: datetime | None
    occupancy_start: datetime
    occupancy_end: datetime | None


@dataclass(frozen=True)
class _Route:
    reservoir_id: uuid.UUID
    irrigation_circuit_id: uuid.UUID
    water_delivery_point_id: uuid.UUID
    delivery_point_location_id: uuid.UUID
    reservoir_circuit_link_id: uuid.UUID
    circuit_delivery_point_link_id: uuid.UUID
    rcl_start: datetime
    rcl_end: datetime | None
    cdl_start: datetime
    cdl_end: datetime | None


@dataclass(frozen=True)
class _Delivery:
    id: uuid.UUID
    reservoir_id: uuid.UUID
    irrigation_circuit_id: uuid.UUID
    start: datetime
    end: datetime | None  # RESOLVED end


def _placements(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, window_start: datetime, window_end: datetime,
    batch_id: uuid.UUID | None,
) -> list[_Placement]:
    """Every (Assignment, Occupancy) pair for the same Carrier whose
    half-open intervals overlap each other AND the window -- the two
    independent histories are intersected, never assumed from either
    alone."""
    rows = db.execute(
        text(
            """
            SELECT bca.batch_id, bca.carrier_id, o.target_location_id AS location_id,
                   bca.id AS batch_carrier_assignment_id, o.id AS occupancy_id,
                   bca.assigned_effective_time AS assignment_start,
                   bca.released_effective_time AS assignment_end,
                   o.effective_time AS occupancy_start, o.end_time AS occupancy_end
            FROM batch_carrier_assignments bca
            JOIN occupancies o
              ON o.tenant_id = bca.tenant_id AND o.farm_id = bca.farm_id AND o.occupant_carrier_id = bca.carrier_id
            WHERE bca.tenant_id = :tenant_id AND bca.farm_id = :farm_id
              AND (CAST(:batch_id AS uuid) IS NULL OR bca.batch_id = CAST(:batch_id AS uuid))
              AND o.target_location_id IS NOT NULL
              AND bca.assigned_effective_time < :window_end
              AND (bca.released_effective_time IS NULL OR bca.released_effective_time > :window_start)
              AND o.effective_time < :window_end
              AND (o.end_time IS NULL OR o.end_time > :window_start)
              AND o.effective_time < COALESCE(bca.released_effective_time, 'infinity'::timestamptz)
              AND bca.assigned_effective_time < COALESCE(o.end_time, 'infinity'::timestamptz)
            """
        ),
        {
            "tenant_id": tenant_id, "farm_id": farm_id, "batch_id": str(batch_id) if batch_id else None,
            "window_start": window_start, "window_end": window_end,
        },
    ).mappings().all()
    return [_Placement(**row) for row in rows]


def _routes(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, window_start: datetime, window_end: datetime,
    irrigation_circuit_id: uuid.UUID | None, reservoir_id: uuid.UUID | None,
) -> list[_Route]:
    rows = db.execute(
        text(
            """
            SELECT rcl.reservoir_id, rcl.irrigation_circuit_id, cdl.water_delivery_point_id,
                   wdp.location_id AS delivery_point_location_id,
                   rcl.id AS reservoir_circuit_link_id, cdl.id AS circuit_delivery_point_link_id,
                   rcl.effective_from AS rcl_start, rcl.effective_to AS rcl_end,
                   cdl.effective_from AS cdl_start, cdl.effective_to AS cdl_end
            FROM reservoir_circuit_links rcl
            JOIN circuit_delivery_point_links cdl
              ON cdl.tenant_id = rcl.tenant_id AND cdl.farm_id = rcl.farm_id
             AND cdl.irrigation_circuit_id = rcl.irrigation_circuit_id
            JOIN water_delivery_points wdp
              ON wdp.id = cdl.water_delivery_point_id AND wdp.tenant_id = cdl.tenant_id AND wdp.farm_id = cdl.farm_id
            WHERE rcl.tenant_id = :tenant_id AND rcl.farm_id = :farm_id
              AND (CAST(:circuit_id AS uuid) IS NULL OR rcl.irrigation_circuit_id = CAST(:circuit_id AS uuid))
              AND (CAST(:reservoir_id AS uuid) IS NULL OR rcl.reservoir_id = CAST(:reservoir_id AS uuid))
              AND rcl.effective_from < :window_end
              AND (rcl.effective_to IS NULL OR rcl.effective_to > :window_start)
              AND cdl.effective_from < :window_end
              AND (cdl.effective_to IS NULL OR cdl.effective_to > :window_start)
              AND rcl.effective_from < COALESCE(cdl.effective_to, 'infinity'::timestamptz)
              AND cdl.effective_from < COALESCE(rcl.effective_to, 'infinity'::timestamptz)
            """
        ),
        {
            "tenant_id": tenant_id, "farm_id": farm_id,
            "circuit_id": str(irrigation_circuit_id) if irrigation_circuit_id else None,
            "reservoir_id": str(reservoir_id) if reservoir_id else None,
            "window_start": window_start, "window_end": window_end,
        },
    ).mappings().all()
    return [_Route(**row) for row in rows]


def _descendants_by_root(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, root_ids: set[uuid.UUID]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """Each Delivery Point Location mapped to itself plus every descendant
    Location, tenant- and farm-scoped."""
    if not root_ids:
        return {}
    rows = db.execute(
        text(
            """
            WITH RECURSIVE descendants(root_id, id) AS (
                SELECT id, id FROM locations
                WHERE id = ANY(:root_ids) AND tenant_id = :tenant_id AND farm_id = :farm_id
                UNION
                SELECT d.root_id, l.id FROM locations l JOIN descendants d ON l.parent_location_id = d.id
                WHERE l.tenant_id = :tenant_id AND l.farm_id = :farm_id
            )
            SELECT root_id, id FROM descendants
            """
        ),
        {"root_ids": list(root_ids), "tenant_id": tenant_id, "farm_id": farm_id},
    )
    scope: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for root_id, location_id in rows:
        scope[root_id].add(location_id)
    return scope


def _deliveries(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, window_start: datetime, window_end: datetime,
    circuit_ids: set[uuid.UUID],
) -> dict[tuple[uuid.UUID, uuid.UUID], list[_Delivery]]:
    """Deliveries keyed by (reservoir, circuit), with the RESOLVED end:
    original `effective_end`, else the End Delivery event's end, else open."""
    if not circuit_ids:
        return {}
    rows = db.execute(
        text(
            """
            SELECT d.id, d.reservoir_id, d.irrigation_circuit_id, d.effective_start AS start,
                   COALESCE(d.effective_end, e.effective_end) AS "end"
            FROM water_delivery_events d
            LEFT JOIN water_delivery_end_events e
              ON e.water_delivery_event_id = d.id AND e.tenant_id = d.tenant_id AND e.farm_id = d.farm_id
            WHERE d.tenant_id = :tenant_id AND d.farm_id = :farm_id
              AND d.irrigation_circuit_id = ANY(:circuit_ids)
              AND d.effective_start < :window_end
              AND COALESCE(d.effective_end, e.effective_end, 'infinity'::timestamptz) > :window_start
            """
        ),
        {
            "tenant_id": tenant_id, "farm_id": farm_id, "circuit_ids": list(circuit_ids),
            "window_start": window_start, "window_end": window_end,
        },
    ).mappings().all()
    by_route: dict[tuple[uuid.UUID, uuid.UUID], list[_Delivery]] = defaultdict(list)
    for row in rows:
        delivery = _Delivery(**row)
        by_route[(delivery.reservoir_id, delivery.irrigation_circuit_id)].append(delivery)
    return by_route


def _intersect(window_start: datetime, window_end: datetime, *bounds: tuple[datetime, datetime | None]):
    """Half-open intersection of the window and every `(start, end|None)`
    bound. Returns `(start, end)` or `None` when empty."""
    start = max([window_start, *(b[0] for b in bounds)])
    end = min([window_end, *(b[1] for b in bounds if b[1] is not None)])
    return (start, end) if start < end else None


def _subtract(base: tuple[datetime, datetime], covered: list[tuple[datetime, datetime]]):
    """`base` minus the union of `covered`, as sorted non-empty half-open
    pieces."""
    pieces: list[tuple[datetime, datetime]] = []
    cursor = base[0]
    for start, end in sorted(covered):
        if start > cursor:
            pieces.append((cursor, min(start, base[1])))
        cursor = max(cursor, end)
        if cursor >= base[1]:
            break
    if cursor < base[1]:
        pieces.append((cursor, base[1]))
    return [p for p in pieces if p[0] < p[1]]


def _edge_flags(
    start: datetime, end: datetime, window_start: datetime, window_end: datetime,
    sources: list[tuple[str, datetime | None]],
) -> dict:
    """`open_ended_sources` names each contributing source with no
    persisted end -- only when the record was clipped at `window_end`,
    which is exactly when an open source determined the reported end."""
    end_clipped = end == window_end
    return {
        "start_clipped_to_window": start == window_start,
        "end_clipped_to_window": end_clipped,
        "open_ended_sources": sorted({name for name, source_end in sources if source_end is None}) if end_clipped else [],
    }


def _compute(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, window_start: datetime, window_end: datetime,
    batch_id: uuid.UUID | None = None, irrigation_circuit_id: uuid.UUID | None = None,
    reservoir_id: uuid.UUID | None = None, include_gaps: bool = False,
) -> tuple[list[dict], list[dict]]:
    validate_window(window_start, window_end)
    placements = _placements(
        db, tenant_id=tenant_id, farm_id=farm_id, window_start=window_start, window_end=window_end, batch_id=batch_id
    )
    if not placements:
        return [], []
    routes = _routes(
        db, tenant_id=tenant_id, farm_id=farm_id, window_start=window_start, window_end=window_end,
        irrigation_circuit_id=irrigation_circuit_id, reservoir_id=reservoir_id,
    )
    scope = _descendants_by_root(
        db, tenant_id=tenant_id, farm_id=farm_id, root_ids={r.delivery_point_location_id for r in routes}
    )
    deliveries = _deliveries(
        db, tenant_id=tenant_id, farm_id=farm_id, window_start=window_start, window_end=window_end,
        circuit_ids={r.irrigation_circuit_id for r in routes},
    )
    routes_by_location: dict[uuid.UUID, list[_Route]] = defaultdict(list)
    for route in routes:
        for location_id in scope.get(route.delivery_point_location_id, ()):
            routes_by_location[location_id].append(route)

    intervals: list[dict] = []
    gaps: list[dict] = []
    for p in placements:
        placement_bounds = [(p.assignment_start, p.assignment_end), (p.occupancy_start, p.occupancy_end)]
        placement_sources = [(SOURCE_ASSIGNMENT, p.assignment_end), (SOURCE_OCCUPANCY, p.occupancy_end)]
        placement_ids = {
            "batch_id": p.batch_id, "carrier_id": p.carrier_id, "location_id": p.location_id,
            "batch_carrier_assignment_id": p.batch_carrier_assignment_id, "occupancy_id": p.occupancy_id,
        }
        placement_span = _intersect(window_start, window_end, *placement_bounds)
        if placement_span is None:
            continue
        route_spans: list[tuple[datetime, datetime]] = []
        for r in routes_by_location.get(p.location_id, ()):
            base = _intersect(
                window_start, window_end, *placement_bounds, (r.rcl_start, r.rcl_end), (r.cdl_start, r.cdl_end)
            )
            if base is None:
                continue
            route_spans.append(base)
            route_ids = {
                "reservoir_id": r.reservoir_id, "irrigation_circuit_id": r.irrigation_circuit_id,
                "water_delivery_point_id": r.water_delivery_point_id,
                "delivery_point_location_id": r.delivery_point_location_id,
                "reservoir_circuit_link_id": r.reservoir_circuit_link_id,
                "circuit_delivery_point_link_id": r.circuit_delivery_point_link_id,
            }
            topology_sources = placement_sources + [
                (SOURCE_RESERVOIR_CIRCUIT_LINK, r.rcl_end), (SOURCE_CIRCUIT_DELIVERY_POINT_LINK, r.cdl_end),
            ]
            covered: list[tuple[datetime, datetime]] = []
            for d in deliveries.get((r.reservoir_id, r.irrigation_circuit_id), ()):
                recorded = _intersect(base[0], base[1], (d.start, d.end))
                if recorded is None:
                    continue
                covered.append(recorded)
                intervals.append(
                    {
                        "exposure_kind": RECORDED_DELIVERY, **placement_ids, **route_ids,
                        "water_delivery_event_id": d.id,
                        "interval_start": recorded[0], "interval_end": recorded[1],
                        **_edge_flags(
                            recorded[0], recorded[1], window_start, window_end,
                            topology_sources + [(SOURCE_WATER_DELIVERY_EVENT, d.end)],
                        ),
                    }
                )
            for start, end in _subtract(base, covered):
                intervals.append(
                    {
                        "exposure_kind": CONFIGURED_TOPOLOGY, **placement_ids, **route_ids,
                        "water_delivery_event_id": None,
                        "interval_start": start, "interval_end": end,
                        **_edge_flags(start, end, window_start, window_end, topology_sources),
                    }
                )
        if include_gaps:
            for start, end in _subtract(placement_span, route_spans):
                gaps.append(
                    {
                        "reason": GAP_NO_COMPLETE_TOPOLOGY_ROUTE, **placement_ids,
                        "gap_start": start, "gap_end": end,
                        **_edge_flags(start, end, window_start, window_end, placement_sources),
                    }
                )

    intervals.sort(
        key=lambda i: (
            i["interval_start"], i["interval_end"], str(i["batch_id"]), str(i["carrier_id"]), str(i["location_id"]),
            str(i["reservoir_id"]), str(i["irrigation_circuit_id"]), str(i["water_delivery_point_id"]),
            i["exposure_kind"], str(i["water_delivery_event_id"]),
        )
    )
    gaps.sort(key=lambda g: (g["gap_start"], g["gap_end"], str(g["carrier_id"]), str(g["location_id"])))
    return intervals, gaps


# --- Timeline reads (UX-OPS-001D0 contract) ---------------------------------------------


def get_batch_water_exposure_timeline(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, window_start: datetime,
    window_end: datetime,
) -> dict:
    """Forward: every exact exposure interval for the Batch, plus explicit
    `NO_COMPLETE_TOPOLOGY_ROUTE` gaps within its valid placement time."""
    intervals, gaps = _compute(
        db, tenant_id=tenant_id, farm_id=farm_id, window_start=window_start, window_end=window_end,
        batch_id=batch_id, include_gaps=True,
    )
    return {
        "batch_id": batch_id, "farm_id": farm_id, "window_start": window_start, "window_end": window_end,
        "interval_convention": INTERVAL_CONVENTION, "intervals": intervals, "gaps": gaps,
    }


def get_circuit_water_exposure_timeline(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, irrigation_circuit_id: uuid.UUID,
    window_start: datetime, window_end: datetime,
) -> dict:
    intervals, _ = _compute(
        db, tenant_id=tenant_id, farm_id=farm_id, window_start=window_start, window_end=window_end,
        irrigation_circuit_id=irrigation_circuit_id,
    )
    return {
        "anchor_type": "IRRIGATION_CIRCUIT", "anchor_id": irrigation_circuit_id, "farm_id": farm_id,
        "window_start": window_start, "window_end": window_end, "interval_convention": INTERVAL_CONVENTION,
        "intervals": intervals,
    }


def get_reservoir_water_exposure_timeline(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, reservoir_id: uuid.UUID, window_start: datetime,
    window_end: datetime,
) -> dict:
    intervals, _ = _compute(
        db, tenant_id=tenant_id, farm_id=farm_id, window_start=window_start, window_end=window_end,
        reservoir_id=reservoir_id,
    )
    return {
        "anchor_type": "RESERVOIR", "anchor_id": reservoir_id, "farm_id": farm_id,
        "window_start": window_start, "window_end": window_end, "interval_convention": INTERVAL_CONVENTION,
        "intervals": intervals,
    }


# --- Legacy list reads, rebuilt on the same engine ---------------------------------------
#
# The PILOT-WATER-001A/B response shapes are kept (plus additive fields) so
# current clients keep working, but every row is now ONE exact interval --
# never "any overlap upgrades the whole window", never an aggregate of
# non-overlapping reservoirs or Locations.


def _legacy_placement_row(interval: dict) -> dict:
    return {
        "batch_id": interval["batch_id"], "carrier_id": interval["carrier_id"],
        "location_id": interval["location_id"], "irrigation_circuit_id": interval["irrigation_circuit_id"],
        "exposure_kind": interval["exposure_kind"], "overlap_start": interval["interval_start"],
        "overlap_end": interval["interval_end"], "reservoir_id": interval["reservoir_id"],
        "water_delivery_point_id": interval["water_delivery_point_id"],
        "water_delivery_event_id": interval["water_delivery_event_id"],
        "end_clipped_to_window": interval["end_clipped_to_window"],
        "open_ended_sources": interval["open_ended_sources"],
    }


def get_potentially_exposed_placements_for_circuit(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, irrigation_circuit_id: uuid.UUID,
    window_start: datetime, window_end: datetime,
) -> list[dict]:
    intervals, _ = _compute(
        db, tenant_id=tenant_id, farm_id=farm_id, window_start=window_start, window_end=window_end,
        irrigation_circuit_id=irrigation_circuit_id,
    )
    return [_legacy_placement_row(i) for i in intervals]


def get_potentially_exposed_placements_for_reservoir(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, reservoir_id: uuid.UUID, window_start: datetime,
    window_end: datetime,
) -> list[dict]:
    intervals, _ = _compute(
        db, tenant_id=tenant_id, farm_id=farm_id, window_start=window_start, window_end=window_end,
        reservoir_id=reservoir_id,
    )
    return [_legacy_placement_row(i) for i in intervals]


def get_water_exposure_history_for_batch(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, window_start: datetime,
    window_end: datetime,
) -> list[dict]:
    """One row per exact interval: `reservoir_ids`/`location_ids` are
    single-element lists (kept for shape compatibility), never an aggregate
    across non-overlapping evidence."""
    intervals, _ = _compute(
        db, tenant_id=tenant_id, farm_id=farm_id, window_start=window_start, window_end=window_end,
        batch_id=batch_id,
    )
    return [
        {
            "irrigation_circuit_id": i["irrigation_circuit_id"], "reservoir_ids": [i["reservoir_id"]],
            "location_ids": [i["location_id"]], "exposure_kind": i["exposure_kind"],
            "carrier_id": i["carrier_id"], "water_delivery_point_id": i["water_delivery_point_id"],
            "water_delivery_event_id": i["water_delivery_event_id"], "interval_start": i["interval_start"],
            "interval_end": i["interval_end"], "end_clipped_to_window": i["end_clipped_to_window"],
            "open_ended_sources": i["open_ended_sources"],
        }
        for i in intervals
    ]
