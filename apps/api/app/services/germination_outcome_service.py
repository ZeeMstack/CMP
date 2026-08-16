"""NURSERY-OPS-002B: modern, INDIVIDUAL-SEEDLING-based Germination outcome.

Thin, dedicated orchestration layer over the existing, unmodified
`observation_service.record_observation` -- reuses the SAME `ObservationEvent`
immutable header (tenant/farm/batch scope, actor, effective_time,
`client_command_id`/`request_fingerprint` idempotency, audit) verbatim; no
second event-header framework. This module exists to give the operator a
narrow, dedicated request/response shape that never exposes the generic
Observation `values`/legacy site-based `germination_checks` payload, and to
provide the modern "current outcome" / Batch-aggregate reads (section 29/30
of the ticket) with no N+1.

Distinct from the legacy site-based `GerminationCheck` (`germination_check.py`
model, `observation_service.py`'s own `germination_checks` handling) in every
respect: individual seedlings, not sites; anchored to `SowingEventLine.seed_count`,
never `sown_site_count`; abnormal seedlings are LIVING, never a loss; the
seed-to-living gap is deliberately left uncategorized (no NON_GERMINATION or
other loss-category inference belongs here)."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.observation_event import ObservationEvent
from app.schemas.germination_outcome import (
    GerminationOutcomeBatchAggregateRead,
    GerminationOutcomeCommandRead,
    GerminationOutcomeCurrentRead,
    GerminationOutcomeSnapshotRead,
)
from app.schemas.sowing_event import CarrierSummary, CarrierTypeSummary
from app.services import observation_service
from app.services.errors import CropBatchNotFoundError


def record_germination_outcomes(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    outcomes: list[dict],
) -> ObservationEvent:
    """Delegates entirely to `observation_service.record_observation` with
    empty legacy `values`/`germination_checks` lists -- the modern outcome
    reuses that function's idempotency/concurrency/audit machinery verbatim,
    adding no second physical-command engine."""
    return observation_service.record_observation(
        db,
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
        client_command_id=client_command_id, effective_time=effective_time, note=note,
        values=[], germination_checks=[], germination_outcomes=outcomes,
    )


def _carrier_summary(tray_id, tray_code, carrier_type_id, carrier_type_code, carrier_type_name) -> CarrierSummary:
    return CarrierSummary(
        id=tray_id, code=tray_code,
        carrier_type=CarrierTypeSummary(id=carrier_type_id, code=carrier_type_code, name=carrier_type_name),
    )


def describe_germination_outcome_command(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, event: ObservationEvent
) -> GerminationOutcomeCommandRead:
    rows = db.execute(
        text(
            "SELECT gos.id, gos.batch_carrier_assignment_id, gos.normal_seedling_count, "
            "gos.abnormal_seedling_count, gos.assessment_complete, gos.note, "
            "carrier.id AS tray_id, carrier.code AS tray_code, ct.id AS carrier_type_id, "
            "ct.code AS carrier_type_code, ct.name AS carrier_type_name "
            "FROM germination_outcome_snapshots gos "
            "JOIN batch_carrier_assignments bca ON bca.id = gos.batch_carrier_assignment_id "
            "JOIN carriers carrier ON carrier.id = bca.carrier_id "
            "JOIN carrier_types ct ON ct.id = carrier.carrier_type_id "
            "WHERE gos.observation_event_id = :eid "
            "ORDER BY carrier.code"
        ),
        {"eid": event.id},
    ).mappings().all()
    snapshots = [
        GerminationOutcomeSnapshotRead(
            id=r["id"], observation_event_id=event.id,
            tray=_carrier_summary(
                r["tray_id"], r["tray_code"], r["carrier_type_id"], r["carrier_type_code"], r["carrier_type_name"]
            ),
            batch_carrier_assignment_id=r["batch_carrier_assignment_id"],
            normal_seedling_count=r["normal_seedling_count"], abnormal_seedling_count=r["abnormal_seedling_count"],
            living_seedling_count=r["normal_seedling_count"] + r["abnormal_seedling_count"],
            assessment_complete=r["assessment_complete"], note=r["note"],
            effective_time=event.effective_time, recorded_time=event.recorded_time,
            actor_user_id=event.actor_user_id,
        )
        for r in rows
    ]
    return GerminationOutcomeCommandRead(
        observation_event_id=event.id, client_command_id=event.client_command_id, batch_id=event.batch_id,
        effective_time=event.effective_time, note=event.note, snapshots=snapshots,
    )


def list_germination_outcome_history(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> list[GerminationOutcomeSnapshotRead]:
    """Full raw history -- every snapshot ever recorded for this Batch's
    Trays, across every event, in chronological order. Never reduced to
    "current"; see `get_current_germination_outcomes` for that."""
    batch_row = db.execute(
        text("SELECT id FROM crop_batches WHERE id = :bid AND tenant_id = :tid AND farm_id = :fid"),
        {"bid": batch_id, "tid": tenant_id, "fid": farm_id},
    ).first()
    if batch_row is None:
        raise CropBatchNotFoundError(str(batch_id))

    rows = db.execute(
        text(
            "SELECT gos.id, gos.observation_event_id, gos.batch_carrier_assignment_id, "
            "gos.normal_seedling_count, gos.abnormal_seedling_count, gos.assessment_complete, gos.note, "
            "oe.effective_time, oe.recorded_time, oe.actor_user_id, "
            "carrier.id AS tray_id, carrier.code AS tray_code, ct.id AS carrier_type_id, "
            "ct.code AS carrier_type_code, ct.name AS carrier_type_name "
            "FROM germination_outcome_snapshots gos "
            "JOIN observation_events oe ON oe.id = gos.observation_event_id "
            "JOIN batch_carrier_assignments bca ON bca.id = gos.batch_carrier_assignment_id "
            "JOIN carriers carrier ON carrier.id = bca.carrier_id "
            "JOIN carrier_types ct ON ct.id = carrier.carrier_type_id "
            "WHERE gos.tenant_id = :tid AND gos.farm_id = :fid AND oe.batch_id = :bid "
            "ORDER BY oe.effective_time, oe.recorded_time, carrier.code"
        ),
        {"tid": tenant_id, "fid": farm_id, "bid": batch_id},
    ).mappings().all()
    return [
        GerminationOutcomeSnapshotRead(
            id=r["id"], observation_event_id=r["observation_event_id"],
            tray=_carrier_summary(
                r["tray_id"], r["tray_code"], r["carrier_type_id"], r["carrier_type_code"], r["carrier_type_name"]
            ),
            batch_carrier_assignment_id=r["batch_carrier_assignment_id"],
            normal_seedling_count=r["normal_seedling_count"], abnormal_seedling_count=r["abnormal_seedling_count"],
            living_seedling_count=r["normal_seedling_count"] + r["abnormal_seedling_count"],
            assessment_complete=r["assessment_complete"], note=r["note"],
            effective_time=r["effective_time"], recorded_time=r["recorded_time"], actor_user_id=r["actor_user_id"],
        )
        for r in rows
    ]


def get_current_germination_outcomes(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> GerminationOutcomeBatchAggregateRead:
    """Section 29/30: truthful per-Tray current state plus a Batch
    aggregate that never hides which Trays remain unresolved. Two queries
    total (base Tray context + all snapshots), reduced to latest/latest-
    completed in Python -- no N+1 regardless of Tray count."""
    batch_row = db.execute(
        text("SELECT id, code FROM crop_batches WHERE id = :bid AND tenant_id = :tid AND farm_id = :fid"),
        {"bid": batch_id, "tid": tenant_id, "fid": farm_id},
    ).mappings().first()
    if batch_row is None:
        raise CropBatchNotFoundError(str(batch_id))

    tray_rows = db.execute(
        text(
            "SELECT bca.id AS assignment_id, carrier.id AS tray_id, carrier.code AS tray_code, "
            "ct.id AS carrier_type_id, ct.code AS carrier_type_code, ct.name AS carrier_type_name, "
            "sel.seed_count, sel.sown_site_count, "
            "occ.id AS occupancy_id, trolley.id AS trolley_id, "
            "chamber.id AS chamber_id, chamber.code AS chamber_code, chamber_gh.greenhouse_classification "
            "FROM batch_carrier_assignments bca "
            "JOIN carriers carrier ON carrier.id = bca.carrier_id "
            "JOIN carrier_types ct ON ct.id = carrier.carrier_type_id AND ct.code = 'seed_tray' "
            "JOIN sowing_event_lines sel ON sel.batch_carrier_assignment_id = bca.id "
            "LEFT JOIN occupancies occ ON occ.occupant_carrier_id = carrier.id AND occ.end_time IS NULL "
            "LEFT JOIN asset_positions slot ON slot.id = occ.target_asset_position_id "
            "LEFT JOIN assets trolley ON trolley.id = slot.asset_id "
            "LEFT JOIN occupancies trolley_occ ON trolley_occ.occupant_asset_id = trolley.id AND trolley_occ.end_time IS NULL "
            "LEFT JOIN locations chamber ON chamber.id = trolley_occ.target_location_id "
            "LEFT JOIN location_types chamber_lt ON chamber_lt.id = chamber.location_type_id AND chamber_lt.code = 'germination_chamber' "
            "LEFT JOIN locations chamber_gh ON chamber_gh.id = chamber.parent_location_id "
            "WHERE bca.tenant_id = :tid AND bca.farm_id = :fid AND bca.batch_id = :bid "
            "ORDER BY carrier.code"
        ),
        {"tid": tenant_id, "fid": farm_id, "bid": batch_id},
    ).mappings().all()

    assignment_ids = [r["assignment_id"] for r in tray_rows]
    snapshot_rows = []
    if assignment_ids:
        snapshot_rows = db.execute(
            text(
                "SELECT gos.id, gos.batch_carrier_assignment_id, gos.normal_seedling_count, "
                "gos.abnormal_seedling_count, gos.assessment_complete, gos.note, "
                "oe.id AS observation_event_id, oe.effective_time, oe.recorded_time, oe.actor_user_id "
                "FROM germination_outcome_snapshots gos "
                "JOIN observation_events oe ON oe.id = gos.observation_event_id "
                "WHERE gos.tenant_id = :tid AND gos.farm_id = :fid "
                "AND gos.batch_carrier_assignment_id = ANY(:aids) "
                "ORDER BY gos.batch_carrier_assignment_id, oe.effective_time, oe.recorded_time"
            ),
            {"tid": tenant_id, "fid": farm_id, "aids": assignment_ids},
        ).mappings().all()

    snapshots_by_assignment: dict[uuid.UUID, list] = {aid: [] for aid in assignment_ids}
    for r in snapshot_rows:
        snapshots_by_assignment[r["batch_carrier_assignment_id"]].append(r)

    trays: list[GerminationOutcomeCurrentRead] = []
    authoritative_total = 0
    completed_count = 0
    for r in tray_rows:
        aid = r["assignment_id"]
        rows_for_tray = snapshots_by_assignment.get(aid, [])
        latest = rows_for_tray[-1] if rows_for_tray else None
        completed_rows = [s for s in rows_for_tray if s["assessment_complete"]]
        latest_completed = completed_rows[-1] if completed_rows else None

        def _to_read(s) -> GerminationOutcomeSnapshotRead:
            return GerminationOutcomeSnapshotRead(
                id=s["id"], observation_event_id=s["observation_event_id"],
                tray=_carrier_summary(
                    r["tray_id"], r["tray_code"], r["carrier_type_id"], r["carrier_type_code"], r["carrier_type_name"]
                ),
                batch_carrier_assignment_id=aid,
                normal_seedling_count=s["normal_seedling_count"], abnormal_seedling_count=s["abnormal_seedling_count"],
                living_seedling_count=s["normal_seedling_count"] + s["abnormal_seedling_count"],
                assessment_complete=s["assessment_complete"], note=s["note"],
                effective_time=s["effective_time"], recorded_time=s["recorded_time"], actor_user_id=s["actor_user_id"],
            )

        latest_read = _to_read(latest) if latest is not None else None
        latest_completed_read = _to_read(latest_completed) if latest_completed is not None else None

        in_germination = (
            r["occupancy_id"] is not None and r["trolley_id"] is not None and r["chamber_id"] is not None
            and r["chamber_code"] is not None and r["greenhouse_classification"] == "nursery"
        )
        if in_germination:
            placement = "in_germination"
        elif r["occupancy_id"] is None:
            placement = "awaiting_placement"
        else:
            placement = "elsewhere"

        authoritative_living = (
            latest_completed_read.living_seedling_count if latest_completed_read is not None else None
        )
        if authoritative_living is not None:
            authoritative_total += authoritative_living
            completed_count += 1

        yield_percent = (
            (Decimal(latest_read.living_seedling_count) / Decimal(r["seed_count"])) * Decimal(100)
            if latest_read is not None
            else None
        )

        trays.append(
            GerminationOutcomeCurrentRead(
                batch_carrier_assignment_id=aid,
                tray=_carrier_summary(
                    r["tray_id"], r["tray_code"], r["carrier_type_id"], r["carrier_type_code"], r["carrier_type_name"]
                ),
                batch_id=batch_row["id"], batch_code=batch_row["code"],
                seeds_sown=r["seed_count"], sown_site_count=r["sown_site_count"],
                current_placement=placement,
                latest_snapshot=latest_read, latest_completed_snapshot=latest_completed_read,
                current_normal_seedling_count=latest_read.normal_seedling_count if latest_read else None,
                current_abnormal_seedling_count=latest_read.abnormal_seedling_count if latest_read else None,
                current_living_seedling_count=latest_read.living_seedling_count if latest_read else None,
                current_seed_to_living_gap_count=(
                    r["seed_count"] - latest_read.living_seedling_count if latest_read else None
                ),
                living_seedling_yield_percent=yield_percent,
                assessment_complete=latest_read.assessment_complete if latest_read else False,
                authoritative_living_seedling_count=authoritative_living,
                latest_effective_time=latest_read.effective_time if latest_read else None,
                historical_snapshot_count=len(rows_for_tray),
            )
        )

    unresolved_count = len(trays) - completed_count
    return GerminationOutcomeBatchAggregateRead(
        batch_id=batch_row["id"], batch_code=batch_row["code"], trays=trays,
        authoritative_living_seedling_total=authoritative_total, completed_tray_count=completed_count,
        unresolved_tray_count=unresolved_count, all_resolved=(len(trays) > 0 and unresolved_count == 0),
    )
