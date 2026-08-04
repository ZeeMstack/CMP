import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_stage_run import BatchStageRun
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.crop import Crop
from app.models.crop_batch import CropBatch
from app.models.seed_lot import SeedLot
from app.models.sowing_event_line import SowingEventLine
from app.models.transplant_allocation import TransplantAllocation
from app.models.transplant_destination_line import TransplantDestinationLine
from app.models.transplant_event import TransplantEvent
from app.models.transplant_source_line import TransplantSourceLine
from app.models.variety import Variety
from app.models.workflow_stage import WorkflowStage
from app.schemas.crop_batch import StageSummary
from app.schemas.sowing_event import CarrierSummary, CarrierTypeSummary, CropSummary, SeedLotSummary, VarietySummary
from app.schemas.transplant_event import (
    TransplantAllocationRead,
    TransplantDestinationLineRead,
    TransplantEventRead,
    TransplantSourceLineRead,
)
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    CarrierNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    DestinationCarrierAlreadyAssignedError,
    FarmNotFoundError,
    InvalidTransplantEffectiveTimeError,
    SourceAssignmentAlreadyReleasedError,
    SourceAssignmentNotFoundError,
    TooManyTransplantLinesError,
    TransplantCommandReusedWithDifferentPayloadError,
    TransplantEventNotFoundError,
    TransplantValidationError,
)

MAX_SOURCE_LINES = 200
MAX_DESTINATION_LINES = 500
MAX_ALLOCATIONS = 2000


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _get_batch_row(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID) -> CropBatch:
    batch = db.execute(
        select(CropBatch).where(
            CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))
    return batch


# --- Idempotency ------------------------------------------------------------------


def _compute_transplant_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, batch_id: uuid.UUID,
    effective_time: datetime, note: str | None, source_lines: list[dict], destination_lines: list[dict],
    allocations: list[dict],
) -> str:
    sorted_sources = sorted(source_lines, key=lambda line: str(line["source_assignment_id"]))
    sorted_destinations = sorted(destination_lines, key=lambda line: str(line["destination_carrier_id"]))
    sorted_allocations = sorted(
        allocations, key=lambda a: (str(a["source_assignment_id"]), str(a["destination_carrier_id"]))
    )
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(batch_id),
        effective_time.astimezone(timezone.utc).isoformat(), note or "",
    ]
    for line in sorted_sources:
        parts.extend(
            [
                str(line["source_assignment_id"]), str(line["source_plant_count"]),
                str(line["discarded_plant_count"]), line.get("note") or "",
            ]
        )
    for line in sorted_destinations:
        parts.extend(
            [str(line["destination_carrier_id"]), str(line["assigned_plant_count"]), line.get("note") or ""]
        )
    for a in sorted_allocations:
        parts.extend(
            [str(a["source_assignment_id"]), str(a["destination_carrier_id"]), str(a["allocated_plant_count"])]
        )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_transplant_event(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> TransplantEvent | None:
    return db.execute(
        select(TransplantEvent).where(
            TransplantEvent.tenant_id == tenant_id, TransplantEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


# --- Command ------------------------------------------------------------------------


def record_transplant(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    source_lines: list[dict],
    destination_lines: list[dict],
    allocations: list[dict],
) -> TransplantEvent:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidTransplantEffectiveTimeError("effective_time cannot be in the future")
    if len(source_lines) > MAX_SOURCE_LINES:
        raise TooManyTransplantLinesError(f"a transplant command may include at most {MAX_SOURCE_LINES} source lines")
    if len(destination_lines) > MAX_DESTINATION_LINES:
        raise TooManyTransplantLinesError(
            f"a transplant command may include at most {MAX_DESTINATION_LINES} destination lines"
        )
    if len(allocations) > MAX_ALLOCATIONS:
        raise TooManyTransplantLinesError(f"a transplant command may include at most {MAX_ALLOCATIONS} allocations")

    fingerprint = _compute_transplant_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
        effective_time=effective_time, note=note, source_lines=source_lines,
        destination_lines=destination_lines, allocations=allocations,
    )

    existing = _find_existing_transplant_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise TransplantCommandReusedWithDifferentPayloadError(str(client_command_id))

    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    existing = _find_existing_transplant_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise TransplantCommandReusedWithDifferentPayloadError(str(client_command_id))

    if batch.state != "active":
        raise CropBatchClosedError(str(batch_id))

    active_run = db.execute(
        select(BatchStageRun)
        .where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if active_run is None:
        raise CropBatchNotFoundError(str(batch_id))

    stage = db.get(WorkflowStage, active_run.workflow_stage_id)
    if stage.stage_category != "transplanting":
        raise TransplantValidationError("current workflow stage is not a transplanting stage")
    if stage.required_carrier_type_id is None:
        raise TransplantValidationError(
            "current transplanting stage has no required destination carrier type configured"
        )

    if effective_time < batch.created_effective_time:
        raise InvalidTransplantEffectiveTimeError("effective_time precedes the batch's creation effective time")
    if effective_time < active_run.entered_effective_time:
        raise InvalidTransplantEffectiveTimeError("effective_time precedes the current stage run's entry time")

    # Source carriers are derived from (immutable) assignment.carrier_id via an
    # unlocked read — safe because carrier_id never changes after insert.
    source_assignment_ids = sorted({line["source_assignment_id"] for line in source_lines})
    unlocked_source_assignments = list(
        db.execute(
            select(BatchCarrierAssignment).where(BatchCarrierAssignment.id.in_(source_assignment_ids))
        ).scalars()
    )
    unlocked_by_id = {a.id: a for a in unlocked_source_assignments}
    for aid in source_assignment_ids:
        if aid not in unlocked_by_id:
            raise SourceAssignmentNotFoundError(str(aid))

    destination_carrier_ids = sorted({line["destination_carrier_id"] for line in destination_lines})
    source_carrier_ids = sorted({unlocked_by_id[aid].carrier_id for aid in source_assignment_ids})

    overlap = set(source_carrier_ids) & set(destination_carrier_ids)
    if overlap:
        raise TransplantValidationError(f"carrier(s) {sorted(overlap)} cannot be both source and destination")

    all_carrier_ids = sorted(set(source_carrier_ids) | set(destination_carrier_ids))
    carriers = list(
        db.execute(
            select(Carrier)
            .where(Carrier.id.in_(all_carrier_ids), Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id)
            .order_by(Carrier.id)
            .with_for_update()
        ).scalars()
    )
    carriers_by_id = {c.id: c for c in carriers}
    for cid in all_carrier_ids:
        if cid not in carriers_by_id:
            raise CarrierNotFoundError(str(cid))

    active_assignment_carrier_ids = set(
        db.execute(
            select(BatchCarrierAssignment.carrier_id).where(
                BatchCarrierAssignment.tenant_id == tenant_id,
                BatchCarrierAssignment.carrier_id.in_(destination_carrier_ids),
                BatchCarrierAssignment.released_effective_time.is_(None),
            )
        ).scalars()
    )
    for cid in destination_carrier_ids:
        carrier = carriers_by_id[cid]
        if carrier.status != "active":
            raise TransplantValidationError(f"destination carrier {cid} is not active")
        if carrier.carrier_type_id != stage.required_carrier_type_id:
            raise TransplantValidationError(
                f"destination carrier {cid} does not match the transplanting stage's required carrier type"
            )
        if cid in active_assignment_carrier_ids:
            raise DestinationCarrierAlreadyAssignedError(str(cid))

    # Lock source assignments in deterministic order and re-validate under lock.
    assignments = list(
        db.execute(
            select(BatchCarrierAssignment)
            .where(BatchCarrierAssignment.id.in_(source_assignment_ids))
            .order_by(BatchCarrierAssignment.id)
            .with_for_update()
        ).scalars()
    )
    assignments_by_id = {a.id: a for a in assignments}

    for aid in source_assignment_ids:
        assignment = assignments_by_id[aid]
        if assignment.tenant_id != tenant_id or assignment.farm_id != farm_id or assignment.batch_id != batch.id:
            raise SourceAssignmentNotFoundError(str(aid))
        if assignment.released_effective_time is not None:
            raise SourceAssignmentAlreadyReleasedError(str(aid))
        if assignment.opening_sowing_event_id is None:
            raise TransplantValidationError(f"source assignment {aid} did not originate from sowing")
        if effective_time < assignment.assigned_effective_time:
            raise InvalidTransplantEffectiveTimeError(
                f"effective_time precedes source assignment {aid}'s assigned_effective_time"
            )
        carrier = carriers_by_id[assignment.carrier_id]
        if carrier.status != "active":
            raise TransplantValidationError(f"source carrier {assignment.carrier_id} is not active")

    sown_counts = dict(
        db.execute(
            select(SowingEventLine.batch_carrier_assignment_id, SowingEventLine.sown_site_count).where(
                SowingEventLine.batch_carrier_assignment_id.in_(source_assignment_ids)
            )
        ).all()
    )
    for line in source_lines:
        aid = line["source_assignment_id"]
        sown_count = sown_counts.get(aid)
        if sown_count is None:
            raise TransplantValidationError(f"no sowing line found for source assignment {aid}")
        if line["source_plant_count"] > sown_count:
            raise TransplantValidationError(
                f"source_plant_count for assignment {aid} cannot exceed its original sown_site_count"
            )

    # In-memory reconciliation.
    allocated_by_source: dict[uuid.UUID, int] = {}
    allocated_by_destination: dict[uuid.UUID, int] = {}
    for a in allocations:
        allocated_by_source[a["source_assignment_id"]] = (
            allocated_by_source.get(a["source_assignment_id"], 0) + a["allocated_plant_count"]
        )
        allocated_by_destination[a["destination_carrier_id"]] = (
            allocated_by_destination.get(a["destination_carrier_id"], 0) + a["allocated_plant_count"]
        )

    for line in source_lines:
        aid = line["source_assignment_id"]
        allocated = allocated_by_source.get(aid, 0)
        if allocated + line["discarded_plant_count"] != line["source_plant_count"]:
            raise TransplantValidationError(
                f"source assignment {aid} does not reconcile: allocated {allocated} + discarded "
                f"{line['discarded_plant_count']} != source_plant_count {line['source_plant_count']}"
            )

    for line in destination_lines:
        cid = line["destination_carrier_id"]
        allocated = allocated_by_destination.get(cid, 0)
        if allocated != line["assigned_plant_count"]:
            raise TransplantValidationError(
                f"destination carrier {cid} does not reconcile: allocated {allocated} != "
                f"assigned_plant_count {line['assigned_plant_count']}"
            )

    total_source = sum(line["source_plant_count"] for line in source_lines)
    total_destination = sum(line["assigned_plant_count"] for line in destination_lines)
    total_discarded = sum(line["discarded_plant_count"] for line in source_lines)
    if total_source != total_destination + total_discarded:
        raise TransplantValidationError("transplant event totals do not reconcile")

    # --- Writes -------------------------------------------------------------------
    # Rollback protection starts before the event insert: a duplicate
    # client_command_id surfaces as an IntegrityError (replay-or-reject); any
    # other failure at any later point rolls back the whole command.
    try:
        event = TransplantEvent(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
            active_batch_stage_run_id=active_run.id, effective_time=effective_time, actor_user_id=actor_user_id,
            client_command_id=client_command_id, request_fingerprint=fingerprint, note=note,
        )
        db.add(event)
        db.flush()

        source_line_by_assignment: dict[uuid.UUID, TransplantSourceLine] = {}
        for line in source_lines:
            aid = line["source_assignment_id"]
            source_line = TransplantSourceLine(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, transplant_event_id=event.id,
                source_batch_carrier_assignment_id=aid, source_carrier_id=assignments_by_id[aid].carrier_id,
                source_plant_count=line["source_plant_count"], discarded_plant_count=line["discarded_plant_count"],
                note=line.get("note"),
            )
            db.add(source_line)
            source_line_by_assignment[aid] = source_line
        db.flush()

        for aid, assignment in assignments_by_id.items():
            assignment.released_effective_time = effective_time
            assignment.released_by_transplant_event_id = event.id
        db.flush()

        destination_assignment_by_carrier: dict[uuid.UUID, BatchCarrierAssignment] = {}
        for line in destination_lines:
            cid = line["destination_carrier_id"]
            destination_assignment = BatchCarrierAssignment(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id, carrier_id=cid,
                batch_stage_run_id=active_run.id, assigned_effective_time=effective_time,
                released_effective_time=None, opening_sowing_event_id=None,
                opening_transplant_event_id=event.id, released_by_transplant_event_id=None,
                actor_user_id=actor_user_id,
            )
            db.add(destination_assignment)
            destination_assignment_by_carrier[cid] = destination_assignment
        db.flush()

        destination_line_by_carrier: dict[uuid.UUID, TransplantDestinationLine] = {}
        for line in destination_lines:
            cid = line["destination_carrier_id"]
            destination_line = TransplantDestinationLine(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, transplant_event_id=event.id,
                destination_batch_carrier_assignment_id=destination_assignment_by_carrier[cid].id,
                destination_carrier_id=cid, assigned_plant_count=line["assigned_plant_count"],
                note=line.get("note"),
            )
            db.add(destination_line)
            destination_line_by_carrier[cid] = destination_line
        db.flush()

        for a in allocations:
            db.add(
                TransplantAllocation(
                    id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, transplant_event_id=event.id,
                    source_line_id=source_line_by_assignment[a["source_assignment_id"]].id,
                    destination_line_id=destination_line_by_carrier[a["destination_carrier_id"]].id,
                    allocated_plant_count=a["allocated_plant_count"],
                )
            )
        db.flush()

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.transplanted",
            entity_type="transplant_event", entity_id=event.id,
            event_data={
                "transplant_event_id": str(event.id), "batch_id": str(batch.id),
                "batch_stage_run_id": str(active_run.id), "effective_time": effective_time.isoformat(),
                "client_command_id": str(client_command_id),
                "source_assignment_ids": [str(aid) for aid in source_assignment_ids],
                "source_carrier_ids": [str(cid) for cid in source_carrier_ids],
                "destination_assignment_ids": [
                    str(destination_assignment_by_carrier[cid].id) for cid in destination_carrier_ids
                ],
                "destination_carrier_ids": [str(cid) for cid in destination_carrier_ids],
                "source_line_count": len(source_lines), "destination_line_count": len(destination_lines),
                "allocation_count": len(allocations), "total_source_plant_count": total_source,
                "total_destination_plant_count": total_destination, "total_discarded_plant_count": total_discarded,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_transplant_events_tenant_client_command_id":
            replay = _find_existing_transplant_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise TransplantCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(event)
    return event


# --- Reads ------------------------------------------------------------------------


def _transplant_event_header_query():
    return (
        select(
            TransplantEvent,
            CropBatch.code.label("batch_code"),
            CropBatch.workflow_version_id.label("workflow_version_id"),
            WorkflowStage,
        )
        .join(CropBatch, CropBatch.id == TransplantEvent.batch_id)
        .join(BatchStageRun, BatchStageRun.id == TransplantEvent.active_batch_stage_run_id)
        .join(WorkflowStage, WorkflowStage.id == BatchStageRun.workflow_stage_id)
    )


def _load_source_lines(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    grouped: dict[uuid.UUID, list] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    # Aggregate manually since multiple allocations may share a source line.
    totals: dict[uuid.UUID, int] = {}
    for row in db.execute(
        select(TransplantAllocation.source_line_id, TransplantAllocation.allocated_plant_count)
    ).all():
        totals[row[0]] = totals.get(row[0], 0) + row[1]

    rows = db.execute(
        select(TransplantSourceLine, Carrier, CarrierType, SeedLot, Crop, Variety, SowingEventLine.sowing_event_id)
        .join(Carrier, Carrier.id == TransplantSourceLine.source_carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .join(SowingEventLine, SowingEventLine.batch_carrier_assignment_id == TransplantSourceLine.source_batch_carrier_assignment_id)
        .join(SeedLot, SeedLot.id == SowingEventLine.seed_lot_id)
        .join(Crop, Crop.id == SeedLot.crop_id)
        .join(Variety, Variety.id == SeedLot.variety_id)
        .where(TransplantSourceLine.transplant_event_id.in_(event_ids))
        .order_by(Carrier.code, Carrier.id)
    ).all()
    for source_line, carrier, carrier_type, seed_lot, crop, variety, sowing_event_id in rows:
        grouped[source_line.transplant_event_id].append(
            TransplantSourceLineRead(
                id=source_line.id,
                source_batch_carrier_assignment_id=source_line.source_batch_carrier_assignment_id,
                carrier=CarrierSummary(
                    id=carrier.id, code=carrier.code,
                    carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
                ),
                seed_lot=SeedLotSummary(
                    id=seed_lot.id, code=seed_lot.code, supplier_lot_reference=seed_lot.supplier_lot_reference,
                    crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
                    variety=VarietySummary(id=variety.id, code=variety.code, name=variety.name),
                ),
                sowing_event_id=sowing_event_id,
                source_plant_count=source_line.source_plant_count,
                discarded_plant_count=source_line.discarded_plant_count,
                allocated_plant_count=totals.get(source_line.id, 0),
                note=source_line.note,
            )
        )
    return grouped


def _load_destination_lines(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    grouped: dict[uuid.UUID, list] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    totals: dict[uuid.UUID, int] = {}
    for row in db.execute(
        select(TransplantAllocation.destination_line_id, TransplantAllocation.allocated_plant_count)
    ).all():
        totals[row[0]] = totals.get(row[0], 0) + row[1]

    rows = db.execute(
        select(TransplantDestinationLine, Carrier, CarrierType)
        .join(Carrier, Carrier.id == TransplantDestinationLine.destination_carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .where(TransplantDestinationLine.transplant_event_id.in_(event_ids))
        .order_by(Carrier.code, Carrier.id)
    ).all()
    for destination_line, carrier, carrier_type in rows:
        grouped[destination_line.transplant_event_id].append(
            TransplantDestinationLineRead(
                id=destination_line.id,
                destination_batch_carrier_assignment_id=destination_line.destination_batch_carrier_assignment_id,
                carrier=CarrierSummary(
                    id=carrier.id, code=carrier.code,
                    carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
                ),
                assigned_plant_count=destination_line.assigned_plant_count,
                allocated_plant_count=totals.get(destination_line.id, 0),
                note=destination_line.note,
            )
        )
    return grouped


def _load_allocations(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list]:
    grouped: dict[uuid.UUID, list] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(
            TransplantAllocation,
            TransplantSourceLine.source_carrier_id,
            TransplantDestinationLine.destination_carrier_id,
        )
        .join(TransplantSourceLine, TransplantSourceLine.id == TransplantAllocation.source_line_id)
        .join(TransplantDestinationLine, TransplantDestinationLine.id == TransplantAllocation.destination_line_id)
        .where(TransplantAllocation.transplant_event_id.in_(event_ids))
    ).all()
    carrier_ids = {r[1] for r in rows} | {r[2] for r in rows}
    carriers_by_id: dict[uuid.UUID, tuple[Carrier, CarrierType]] = {}
    if carrier_ids:
        for carrier, carrier_type in db.execute(
            select(Carrier, CarrierType)
            .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
            .where(Carrier.id.in_(carrier_ids))
        ).all():
            carriers_by_id[carrier.id] = (carrier, carrier_type)

    def _summary(cid: uuid.UUID) -> CarrierSummary:
        carrier, carrier_type = carriers_by_id[cid]
        return CarrierSummary(
            id=carrier.id, code=carrier.code,
            carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
        )

    for allocation, source_carrier_id, destination_carrier_id in rows:
        grouped[allocation.transplant_event_id].append(
            TransplantAllocationRead(
                id=allocation.id, source_carrier=_summary(source_carrier_id),
                destination_carrier=_summary(destination_carrier_id),
                allocated_plant_count=allocation.allocated_plant_count,
            )
        )
    for event_id in grouped:
        grouped[event_id].sort(key=lambda a: (a.source_carrier.code, a.destination_carrier.code))
    return grouped


def _row_to_transplant_event_read(row, source_lines: list, destination_lines: list, allocations: list) -> TransplantEventRead:
    event: TransplantEvent = row[0]
    m = row._mapping
    stage: WorkflowStage = row[3]
    return TransplantEventRead(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id, batch_id=event.batch_id,
        batch_code=m["batch_code"], workflow_version_id=m["workflow_version_id"],
        stage=StageSummary(id=stage.id, code=stage.code, name=stage.name, is_terminal=stage.is_terminal),
        effective_time=event.effective_time, recorded_time=event.recorded_time,
        actor_user_id=event.actor_user_id, client_command_id=event.client_command_id, note=event.note,
        source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        total_source_plant_count=sum(line.source_plant_count for line in source_lines),
        total_destination_plant_count=sum(line.assigned_plant_count for line in destination_lines),
        total_discarded_plant_count=sum(line.discarded_plant_count for line in source_lines),
    )


def get_transplant_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, transplant_event_id: uuid.UUID
) -> TransplantEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    row = db.execute(
        _transplant_event_header_query().where(
            TransplantEvent.id == transplant_event_id, TransplantEvent.tenant_id == tenant_id,
            TransplantEvent.batch_id == batch_id,
        )
    ).first()
    if row is None:
        raise TransplantEventNotFoundError(str(transplant_event_id))
    source_lines = _load_source_lines(db, event_ids=[transplant_event_id])[transplant_event_id]
    destination_lines = _load_destination_lines(db, event_ids=[transplant_event_id])[transplant_event_id]
    allocations = _load_allocations(db, event_ids=[transplant_event_id])[transplant_event_id]
    return _row_to_transplant_event_read(row, source_lines, destination_lines, allocations)


def list_transplant_events(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> list[TransplantEventRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    rows = db.execute(
        _transplant_event_header_query()
        .where(TransplantEvent.tenant_id == tenant_id, TransplantEvent.batch_id == batch_id)
        .order_by(TransplantEvent.effective_time, TransplantEvent.recorded_time)
    ).all()
    event_ids = [r[0].id for r in rows]
    source_by_event = _load_source_lines(db, event_ids=event_ids)
    destination_by_event = _load_destination_lines(db, event_ids=event_ids)
    allocations_by_event = _load_allocations(db, event_ids=event_ids)
    return [
        _row_to_transplant_event_read(
            r, source_by_event[r[0].id], destination_by_event[r[0].id], allocations_by_event[r[0].id]
        )
        for r in rows
    ]
