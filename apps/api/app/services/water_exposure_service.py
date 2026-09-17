"""PILOT-WATER-001A sections 19-21: read-only CROP WATER EXPOSURE model.

Answers, in both directions:
  - Batch/Placement + time window -> which Reservoir(s)/Circuit(s)
    potentially supplied water to it?
  - Reservoir/Circuit + time window -> which Batch Placements were
    potentially exposed?

This is POTENTIAL EXPOSURE, never a disease/contamination/infection claim
(rule 2) -- the words "affected"/"contaminated"/"infected" never appear
here or in any value this module returns.

Two distinct, explicitly labelled exposure kinds (section 20), since
conflating them would overstate precision:
  - `CONFIGURED_TOPOLOGY`: the location was within a Circuit's configured
    delivery-point scope (expanded to every descendant Location under the
    mapped Location) during the window, REGARDLESS of whether a Delivery
    was ever actually recorded. This is topology-only evidence.
  - `RECORDED_DELIVERY`: additionally, at least one actual
    `WaterDeliveryEvent` for that Circuit overlaps the window. Strictly
    stronger evidence than `CONFIGURED_TOPOLOGY` alone.
A row never claims `RECORDED_DELIVERY` without a real overlapping
`WaterDeliveryEvent`; `CONFIGURED_TOPOLOGY` never claims more precision
than the topology mapping itself actually has (ticket section 20's "GH-01
mapped, several Tables inside" case: every Table in GH-01 is eligible,
honestly, not narrowed to one without evidence).

No table is written to. No audit event is appended for a read."""

import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

CONFIGURED_TOPOLOGY = "CONFIGURED_TOPOLOGY_EXPOSURE"
RECORDED_DELIVERY = "RECORDED_DELIVERY_EXPOSURE"

_DESCENDANT_LOCATIONS_CTE = """
    WITH RECURSIVE descendants AS (
        SELECT id FROM locations WHERE id = ANY(:root_ids) AND tenant_id = :tenant_id AND farm_id = :farm_id
        UNION ALL
        SELECT l.id FROM locations l JOIN descendants d ON l.parent_location_id = d.id
        WHERE l.tenant_id = :tenant_id AND l.farm_id = :farm_id
    )
    SELECT id FROM descendants
"""


def _circuit_delivery_locations(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, circuit_id: uuid.UUID, window_start: datetime,
    window_end: datetime,
) -> set[uuid.UUID]:
    """Every Location (including descendants) a Circuit's mapped Delivery
    Points reached during the window, per the CURRENT/historical topology
    link record -- this is the `CONFIGURED_TOPOLOGY` scope."""
    root_ids = [
        row[0]
        for row in db.execute(
            text(
                """
                SELECT DISTINCT wdp.location_id
                FROM circuit_delivery_point_links l
                JOIN water_delivery_points wdp ON wdp.id = l.water_delivery_point_id
                WHERE l.tenant_id = :tenant_id AND l.farm_id = :farm_id AND l.irrigation_circuit_id = :circuit_id
                  AND l.effective_from <= :window_end
                  AND (l.effective_to IS NULL OR l.effective_to >= :window_start)
                """
            ),
            {
                "tenant_id": tenant_id, "farm_id": farm_id, "circuit_id": circuit_id, "window_start": window_start,
                "window_end": window_end,
            },
        )
    ]
    if not root_ids:
        return set()
    rows = db.execute(
        text(_DESCENDANT_LOCATIONS_CTE),
        {"root_ids": root_ids, "tenant_id": tenant_id, "farm_id": farm_id},
    )
    return {row[0] for row in rows}


def _circuits_fed_by_reservoir(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, reservoir_id: uuid.UUID, window_start: datetime,
    window_end: datetime,
) -> list[uuid.UUID]:
    return [
        row[0]
        for row in db.execute(
            text(
                """
                SELECT DISTINCT irrigation_circuit_id FROM reservoir_circuit_links
                WHERE tenant_id = :tenant_id AND farm_id = :farm_id AND reservoir_id = :reservoir_id
                  AND effective_from <= :window_end AND (effective_to IS NULL OR effective_to >= :window_start)
                """
            ),
            {
                "tenant_id": tenant_id, "farm_id": farm_id, "reservoir_id": reservoir_id,
                "window_start": window_start, "window_end": window_end,
            },
        )
    ]


def _recorded_delivery_overlaps(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, circuit_id: uuid.UUID, window_start: datetime,
    window_end: datetime,
) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM water_delivery_events
            WHERE tenant_id = :tenant_id AND farm_id = :farm_id AND irrigation_circuit_id = :circuit_id
              AND effective_start <= :window_end
              AND (effective_end IS NULL OR effective_end >= :window_start)
            LIMIT 1
            """
        ),
        {
            "tenant_id": tenant_id, "farm_id": farm_id, "circuit_id": circuit_id, "window_start": window_start,
            "window_end": window_end,
        },
    ).first()
    return row is not None


def _placements_in_locations(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_ids: set[uuid.UUID], window_start: datetime,
    window_end: datetime,
) -> list[dict]:
    """Every (batch, carrier, location, overlap window) where the carrier
    physically occupied one of `location_ids` AND was assigned to that
    batch, during any part of the query window -- the two independent
    histories (Occupancy, BatchCarrierAssignment) are intersected, never
    assumed from either alone."""
    if not location_ids:
        return []
    rows = db.execute(
        text(
            """
            SELECT bca.batch_id, o.occupant_carrier_id AS carrier_id, o.target_location_id AS location_id,
                   GREATEST(o.effective_time, bca.assigned_effective_time, :window_start) AS overlap_start,
                   LEAST(
                       COALESCE(o.end_time, 'infinity'::timestamptz),
                       COALESCE(bca.released_effective_time, 'infinity'::timestamptz),
                       :window_end
                   ) AS overlap_end
            FROM occupancies o
            JOIN batch_carrier_assignments bca
              ON bca.tenant_id = o.tenant_id AND bca.farm_id = o.farm_id AND bca.carrier_id = o.occupant_carrier_id
            WHERE o.tenant_id = :tenant_id AND o.farm_id = :farm_id
              AND o.occupant_carrier_id IS NOT NULL
              AND o.target_location_id = ANY(:location_ids)
              AND o.effective_time <= :window_end AND (o.end_time IS NULL OR o.end_time >= :window_start)
              AND bca.assigned_effective_time <= :window_end
              AND (bca.released_effective_time IS NULL OR bca.released_effective_time >= :window_start)
            """
        ),
        {
            "tenant_id": tenant_id, "farm_id": farm_id, "location_ids": list(location_ids),
            "window_start": window_start, "window_end": window_end,
        },
    ).mappings().all()
    return [
        row for row in rows if row["overlap_start"] <= row["overlap_end"]
    ]


def get_potentially_exposed_placements_for_circuit(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, irrigation_circuit_id: uuid.UUID,
    window_start: datetime, window_end: datetime,
) -> list[dict]:
    """Reverse direction (section 19): given a Circuit + window, which
    Batch Placements were potentially exposed. Every row is labelled
    `CONFIGURED_TOPOLOGY_EXPOSURE`, and additionally `RECORDED_DELIVERY_
    EXPOSURE` when a real `WaterDeliveryEvent` for this Circuit overlaps
    the window (section 20)."""
    locations = _circuit_delivery_locations(
        db, tenant_id=tenant_id, farm_id=farm_id, circuit_id=irrigation_circuit_id, window_start=window_start,
        window_end=window_end,
    )
    placements = _placements_in_locations(
        db, tenant_id=tenant_id, farm_id=farm_id, location_ids=locations, window_start=window_start,
        window_end=window_end,
    )
    has_recorded_delivery = _recorded_delivery_overlaps(
        db, tenant_id=tenant_id, farm_id=farm_id, circuit_id=irrigation_circuit_id, window_start=window_start,
        window_end=window_end,
    )
    exposure_kind = RECORDED_DELIVERY if has_recorded_delivery else CONFIGURED_TOPOLOGY
    return [
        {
            "batch_id": p["batch_id"], "carrier_id": p["carrier_id"], "location_id": p["location_id"],
            "irrigation_circuit_id": irrigation_circuit_id, "exposure_kind": exposure_kind,
            "overlap_start": p["overlap_start"], "overlap_end": p["overlap_end"],
        }
        for p in placements
    ]


def get_potentially_exposed_placements_for_reservoir(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, reservoir_id: uuid.UUID, window_start: datetime,
    window_end: datetime,
) -> list[dict]:
    """Same as the Circuit-scoped read, expanded across every Circuit that
    drew from this Reservoir at any point during the window."""
    circuit_ids = _circuits_fed_by_reservoir(
        db, tenant_id=tenant_id, farm_id=farm_id, reservoir_id=reservoir_id, window_start=window_start,
        window_end=window_end,
    )
    results: list[dict] = []
    for circuit_id in circuit_ids:
        results.extend(
            get_potentially_exposed_placements_for_circuit(
                db, tenant_id=tenant_id, farm_id=farm_id, irrigation_circuit_id=circuit_id,
                window_start=window_start, window_end=window_end,
            )
        )
    return results


def get_water_exposure_history_for_batch(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, window_start: datetime,
    window_end: datetime,
) -> list[dict]:
    """Forward direction (section 19): given a Batch + window, which
    Reservoir(s)/Circuit(s) potentially supplied water to it. Walks every
    Circuit in the farm rather than assuming a small fixed set -- a
    foundation-scale farm is expected to have few enough Circuits that
    this is a cheap, correct starting point; a future ticket may add a
    location-indexed reverse lookup if farm scale ever makes this a
    bottleneck (see docs/domain/WATER_NUTRIENT_SYSTEM_MODEL.md "Known
    gaps")."""
    batch_placement_rows = db.execute(
        text(
            """
            SELECT o.target_location_id AS location_id,
                   GREATEST(o.effective_time, bca.assigned_effective_time, :window_start) AS overlap_start,
                   LEAST(
                       COALESCE(o.end_time, 'infinity'::timestamptz),
                       COALESCE(bca.released_effective_time, 'infinity'::timestamptz),
                       :window_end
                   ) AS overlap_end
            FROM batch_carrier_assignments bca
            JOIN occupancies o
              ON o.tenant_id = bca.tenant_id AND o.farm_id = bca.farm_id AND o.occupant_carrier_id = bca.carrier_id
            WHERE bca.tenant_id = :tenant_id AND bca.farm_id = :farm_id AND bca.batch_id = :batch_id
              AND o.target_location_id IS NOT NULL
              AND bca.assigned_effective_time <= :window_end
              AND (bca.released_effective_time IS NULL OR bca.released_effective_time >= :window_start)
              AND o.effective_time <= :window_end AND (o.end_time IS NULL OR o.end_time >= :window_start)
            """
        ),
        {"tenant_id": tenant_id, "farm_id": farm_id, "batch_id": batch_id, "window_start": window_start, "window_end": window_end},
    ).mappings().all()
    batch_locations = {row["location_id"] for row in batch_placement_rows if row["overlap_start"] <= row["overlap_end"]}
    if not batch_locations:
        return []

    circuit_ids = [
        row[0]
        for row in db.execute(
            text(
                "SELECT id FROM irrigation_circuits WHERE tenant_id = :tenant_id AND farm_id = :farm_id"
            ),
            {"tenant_id": tenant_id, "farm_id": farm_id},
        )
    ]

    results: list[dict] = []
    for circuit_id in circuit_ids:
        circuit_locations = _circuit_delivery_locations(
            db, tenant_id=tenant_id, farm_id=farm_id, circuit_id=circuit_id, window_start=window_start,
            window_end=window_end,
        )
        overlap_locations = batch_locations & circuit_locations
        if not overlap_locations:
            continue
        has_recorded_delivery = _recorded_delivery_overlaps(
            db, tenant_id=tenant_id, farm_id=farm_id, circuit_id=circuit_id, window_start=window_start,
            window_end=window_end,
        )
        reservoir_ids = [
            row[0]
            for row in db.execute(
                text(
                    """
                    SELECT DISTINCT reservoir_id FROM reservoir_circuit_links
                    WHERE tenant_id = :tenant_id AND farm_id = :farm_id AND irrigation_circuit_id = :circuit_id
                      AND effective_from <= :window_end AND (effective_to IS NULL OR effective_to >= :window_start)
                    """
                ),
                {
                    "tenant_id": tenant_id, "farm_id": farm_id, "circuit_id": circuit_id,
                    "window_start": window_start, "window_end": window_end,
                },
            )
        ]
        results.append(
            {
                "irrigation_circuit_id": circuit_id, "reservoir_ids": reservoir_ids,
                "location_ids": sorted(overlap_locations),
                "exposure_kind": RECORDED_DELIVERY if has_recorded_delivery else CONFIGURED_TOPOLOGY,
            }
        )
    return results
