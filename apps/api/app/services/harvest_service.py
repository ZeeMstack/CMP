import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_stage_run import BatchStageRun
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.crop import Crop
from app.models.crop_batch import CropBatch
from app.models.harvest_event import HarvestEvent
from app.models.harvest_source_line import HarvestSourceLine
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.models.variety import Variety
from app.models.workflow import Workflow
from app.models.workflow_stage import WorkflowStage
from app.schemas.crop_batch import CropSummary, StageSummary, VarietySummary, WorkflowSummary
from app.schemas.harvest import (
    MAX_WEIGHT_KG,
    MAX_WHOLE_UNIT_COUNT,
    HarvestedProduceLotRead,
    HarvestEventRead,
    HarvestSourceLineRead,
    canonical_decimal_str,
)
from app.schemas.sowing_event import CarrierSummary, CarrierTypeSummary
from app.services import farm_service, quality_hold_service
from app.services.audit import append_audit_event
from app.services.errors import (
    CarrierNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    DuplicateProduceLotCodeError,
    FarmNotFoundError,
    HarvestCommandReusedWithDifferentPayloadError,
    HarvestEventNotFoundError,
    HarvestedProduceLotNotFoundError,
    HarvestSourceAssignmentNotFoundError,
    HarvestValidationError,
    InvalidHarvestEffectiveTimeError,
    QualityHoldOpenError,
    TooManyHarvestLinesError,
)

MAX_SOURCE_LINES = 500


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


def _compute_harvest_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, batch_id: uuid.UUID,
    effective_time: datetime, produce_lot_code: str, note: str | None, source_lines: list[dict],
) -> str:
    sorted_lines = sorted(source_lines, key=lambda line: str(line["batch_carrier_assignment_id"]))
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(batch_id),
        effective_time.astimezone(timezone.utc).isoformat(), produce_lot_code, note or "",
    ]
    for line in sorted_lines:
        parts.extend(
            [
                str(line["batch_carrier_assignment_id"]), canonical_decimal_str(line["harvested_weight_kg"]),
                str(line["whole_unit_count"]) if line["whole_unit_count"] is not None else "",
                line.get("note") or "",
            ]
        )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_harvest_event(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> HarvestEvent | None:
    return db.execute(
        select(HarvestEvent).where(
            HarvestEvent.tenant_id == tenant_id, HarvestEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


# --- Command ------------------------------------------------------------------------


def record_harvest(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    produce_lot_code: str,
    note: str | None,
    source_lines: list[dict],
) -> HarvestEvent:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidHarvestEffectiveTimeError("effective_time cannot be in the future")
    if len(source_lines) > MAX_SOURCE_LINES:
        raise TooManyHarvestLinesError(f"a harvest command may include at most {MAX_SOURCE_LINES} source lines")

    fingerprint = _compute_harvest_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
        effective_time=effective_time, produce_lot_code=produce_lot_code, note=note, source_lines=source_lines,
    )

    existing = _find_existing_harvest_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise HarvestCommandReusedWithDifferentPayloadError(str(client_command_id))

    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    existing = _find_existing_harvest_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise HarvestCommandReusedWithDifferentPayloadError(str(client_command_id))

    if quality_hold_service.has_open_quality_hold(db, batch_id=batch.id):
        raise QualityHoldOpenError(str(batch_id))

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
    if stage.stage_category != "harvesting":
        raise HarvestValidationError("current workflow stage is not a harvesting stage")

    assignment_ids = sorted({line["batch_carrier_assignment_id"] for line in source_lines})
    assignments = list(
        db.execute(
            select(BatchCarrierAssignment).where(BatchCarrierAssignment.id.in_(assignment_ids))
            .order_by(BatchCarrierAssignment.id).with_for_update()
        ).scalars()
    )
    assignments_by_id = {a.id: a for a in assignments}
    for aid in assignment_ids:
        assignment = assignments_by_id.get(aid)
        if (
            assignment is None or assignment.tenant_id != tenant_id or assignment.farm_id != farm_id
            or assignment.batch_id != batch.id
        ):
            raise HarvestSourceAssignmentNotFoundError(str(aid))
        if assignment.released_effective_time is not None:
            raise HarvestValidationError(f"source assignment {aid} is not active")

    carrier_ids = sorted({a.carrier_id for a in assignments})
    carriers = list(
        db.execute(
            select(Carrier).where(Carrier.id.in_(carrier_ids), Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id)
            .order_by(Carrier.id).with_for_update()
        ).scalars()
    )
    carriers_by_id = {c.id: c for c in carriers}
    for cid in carrier_ids:
        carrier = carriers_by_id.get(cid)
        if carrier is None:
            raise CarrierNotFoundError(str(cid))
        if carrier.status != "active":
            raise HarvestValidationError(f"carrier {cid} is not active")

    if effective_time < batch.created_effective_time:
        raise InvalidHarvestEffectiveTimeError("effective_time precedes the batch's creation effective time")
    if effective_time < active_run.entered_effective_time:
        raise InvalidHarvestEffectiveTimeError("effective_time precedes the current stage run's entry time")
    for aid in assignment_ids:
        if effective_time < assignments_by_id[aid].assigned_effective_time:
            raise InvalidHarvestEffectiveTimeError(
                f"effective_time precedes source assignment {aid}'s assigned_effective_time"
            )

    total_weight: Decimal = sum((line["harvested_weight_kg"] for line in source_lines), Decimal("0"))
    counts = [line["whole_unit_count"] for line in source_lines]
    total_count = sum(counts) if all(c is not None for c in counts) else None

    # Each individual line already passed the same envelope at the Pydantic
    # layer, but the *sum* across many valid lines can still exceed the
    # produce-lot's own bound — reject before any write rather than letting
    # the database CHECK/column-range constraint surface as a raw,
    # untranslated IntegrityError.
    if total_weight >= MAX_WEIGHT_KG:
        raise HarvestValidationError("the sum of source-line weights exceeds the supported total weight range")
    if total_count is not None and total_count > MAX_WHOLE_UNIT_COUNT:
        raise HarvestValidationError("the sum of source-line whole-unit counts exceeds the supported total count range")

    event_id = uuid.uuid4()
    lot_id = uuid.uuid4()
    line_ids = {aid: uuid.uuid4() for aid in assignment_ids}

    try:
        event = HarvestEvent(
            id=event_id, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
            active_batch_stage_run_id=active_run.id, effective_time=effective_time, actor_user_id=actor_user_id,
            client_command_id=client_command_id, request_fingerprint=fingerprint, note=note,
        )
        db.add(event)
        db.flush()

        batch_workflow = db.get(Workflow, batch.workflow_id)
        lot = HarvestedProduceLot(
            id=lot_id, tenant_id=tenant_id, farm_id=farm_id, code=produce_lot_code, harvest_event_id=event.id,
            batch_id=batch.id, workflow_id=batch.workflow_id, workflow_version_id=batch.workflow_version_id,
            crop_id=batch_workflow.crop_id, variety_id=batch_workflow.variety_id,
            total_harvested_weight_kg=total_weight, total_whole_unit_count=total_count, effective_time=effective_time,
        )
        db.add(lot)
        db.flush()

        for line in source_lines:
            aid = line["batch_carrier_assignment_id"]
            db.add(
                HarvestSourceLine(
                    id=line_ids[aid], tenant_id=tenant_id, farm_id=farm_id, harvest_event_id=event.id,
                    batch_carrier_assignment_id=aid, carrier_id=assignments_by_id[aid].carrier_id,
                    harvested_weight_kg=line["harvested_weight_kg"], whole_unit_count=line["whole_unit_count"],
                    note=line.get("note"),
                )
            )
        db.flush()

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.harvested",
            entity_type="harvest_event", entity_id=event.id,
            event_data={
                "harvest_event_id": str(event.id), "produce_lot_id": str(lot.id), "produce_lot_code": lot.code,
                "batch_id": str(batch.id), "batch_stage_run_id": str(active_run.id),
                "effective_time": effective_time.isoformat(), "client_command_id": str(client_command_id),
                "source_assignment_ids": [str(aid) for aid in assignment_ids],
                "source_carrier_ids": [str(assignments_by_id[aid].carrier_id) for aid in assignment_ids],
                "source_line_count": len(source_lines),
                "total_harvested_weight_kg": canonical_decimal_str(total_weight),
                "total_whole_unit_count": total_count,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_harvest_events_tenant_client_command_id":
            replay = _find_existing_harvest_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise HarvestCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_harvested_produce_lots_tenant_code_lower":
            raise DuplicateProduceLotCodeError(f"{tenant_id}:{produce_lot_code}") from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(event)
    return event


# --- Reads ------------------------------------------------------------------------


def _opener_kind_and_id(assignment: BatchCarrierAssignment) -> tuple[str, uuid.UUID]:
    if assignment.opening_sowing_event_id is not None:
        return "sowing", assignment.opening_sowing_event_id
    if assignment.opening_transplant_event_id is not None:
        return "transplant", assignment.opening_transplant_event_id
    return "derivation", assignment.opening_batch_derivation_event_id


def _load_source_lines(db: Session, *, event_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[HarvestSourceLineRead]]:
    grouped: dict[uuid.UUID, list[HarvestSourceLineRead]] = {eid: [] for eid in event_ids}
    if not event_ids:
        return grouped
    rows = db.execute(
        select(HarvestSourceLine, Carrier, CarrierType, BatchCarrierAssignment)
        .join(Carrier, Carrier.id == HarvestSourceLine.carrier_id)
        .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
        .join(BatchCarrierAssignment, BatchCarrierAssignment.id == HarvestSourceLine.batch_carrier_assignment_id)
        .where(HarvestSourceLine.harvest_event_id.in_(event_ids))
        .order_by(Carrier.code, Carrier.id)
    ).all()
    for source_line, carrier, carrier_type, assignment in rows:
        opening_kind, opening_id = _opener_kind_and_id(assignment)
        grouped[source_line.harvest_event_id].append(
            HarvestSourceLineRead(
                id=source_line.id, batch_carrier_assignment_id=source_line.batch_carrier_assignment_id,
                carrier=CarrierSummary(
                    id=carrier.id, code=carrier.code,
                    carrier_type=CarrierTypeSummary(id=carrier_type.id, code=carrier_type.code, name=carrier_type.name),
                ),
                opening_kind=opening_kind, opening_id=opening_id,
                harvested_weight_kg=source_line.harvested_weight_kg, whole_unit_count=source_line.whole_unit_count,
                note=source_line.note,
            )
        )
    return grouped


def _harvest_event_header_query():
    return (
        select(
            HarvestEvent, CropBatch.code.label("batch_code"), CropBatch.workflow_id.label("workflow_id"),
            CropBatch.workflow_version_id.label("workflow_version_id"), Workflow.code.label("workflow_code"),
            Workflow.name.label("workflow_name"), Crop, Variety, WorkflowStage,
            HarvestedProduceLot.id.label("lot_id"), HarvestedProduceLot.code.label("lot_code"),
        )
        .join(CropBatch, CropBatch.id == HarvestEvent.batch_id)
        .join(Workflow, Workflow.id == CropBatch.workflow_id)
        .join(Crop, Crop.id == Workflow.crop_id)
        .outerjoin(Variety, Variety.id == Workflow.variety_id)
        .join(BatchStageRun, BatchStageRun.id == HarvestEvent.active_batch_stage_run_id)
        .join(WorkflowStage, WorkflowStage.id == BatchStageRun.workflow_stage_id)
        .join(HarvestedProduceLot, HarvestedProduceLot.harvest_event_id == HarvestEvent.id)
    )


def _row_to_harvest_event_read(row, source_lines: list[HarvestSourceLineRead]) -> HarvestEventRead:
    event: HarvestEvent = row[0]
    m = row._mapping
    crop: Crop = row[6]
    variety: Variety | None = row[7]
    stage: WorkflowStage = row[8]
    total_weight = sum((line.harvested_weight_kg for line in source_lines), Decimal("0"))
    counts = [line.whole_unit_count for line in source_lines]
    total_count = sum(counts) if all(c is not None for c in counts) else None
    return HarvestEventRead(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id, batch_id=event.batch_id,
        batch_code=m["batch_code"], workflow=WorkflowSummary(id=m["workflow_id"], code=m["workflow_code"], name=m["workflow_name"]),
        workflow_version_id=m["workflow_version_id"], crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
        variety=(VarietySummary(id=variety.id, code=variety.code, name=variety.name) if variety is not None else None),
        stage=StageSummary(id=stage.id, code=stage.code, name=stage.name, is_terminal=stage.is_terminal),
        produce_lot_id=m["lot_id"], produce_lot_code=m["lot_code"], effective_time=event.effective_time,
        recorded_time=event.recorded_time, actor_user_id=event.actor_user_id, client_command_id=event.client_command_id,
        note=event.note, source_lines=source_lines, total_harvested_weight_kg=total_weight,
        total_whole_unit_count=total_count,
    )


def get_harvest_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, harvest_event_id: uuid.UUID
) -> HarvestEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    row = db.execute(
        _harvest_event_header_query().where(
            HarvestEvent.id == harvest_event_id, HarvestEvent.tenant_id == tenant_id, HarvestEvent.batch_id == batch_id
        )
    ).first()
    if row is None:
        raise HarvestEventNotFoundError(str(harvest_event_id))
    source_lines = _load_source_lines(db, event_ids=[harvest_event_id])[harvest_event_id]
    return _row_to_harvest_event_read(row, source_lines)


def list_harvest_events(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> list[HarvestEventRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    rows = db.execute(
        _harvest_event_header_query()
        .where(HarvestEvent.tenant_id == tenant_id, HarvestEvent.batch_id == batch_id)
        .order_by(HarvestEvent.effective_time, HarvestEvent.recorded_time)
    ).all()
    event_ids = [r[0].id for r in rows]
    source_by_event = _load_source_lines(db, event_ids=event_ids)
    return [_row_to_harvest_event_read(r, source_by_event[r[0].id]) for r in rows]


def _produce_lot_header_query():
    return (
        select(
            HarvestedProduceLot, CropBatch.code.label("batch_code"), Workflow.code.label("workflow_code"),
            Workflow.name.label("workflow_name"), Crop, Variety,
        )
        .join(CropBatch, CropBatch.id == HarvestedProduceLot.batch_id)
        .join(Workflow, Workflow.id == HarvestedProduceLot.workflow_id)
        .join(Crop, Crop.id == HarvestedProduceLot.crop_id)
        .outerjoin(Variety, Variety.id == HarvestedProduceLot.variety_id)
    )


def _row_to_produce_lot_read(row, source_lines: list[HarvestSourceLineRead]) -> HarvestedProduceLotRead:
    lot: HarvestedProduceLot = row[0]
    m = row._mapping
    crop: Crop = row[4]
    variety: Variety | None = row[5]
    return HarvestedProduceLotRead(
        id=lot.id, tenant_id=lot.tenant_id, farm_id=lot.farm_id, code=lot.code, harvest_event_id=lot.harvest_event_id,
        batch_id=lot.batch_id, batch_code=m["batch_code"],
        workflow=WorkflowSummary(id=lot.workflow_id, code=m["workflow_code"], name=m["workflow_name"]),
        workflow_version_id=lot.workflow_version_id, crop=CropSummary(id=crop.id, code=crop.code, common_name=crop.common_name),
        variety=(VarietySummary(id=variety.id, code=variety.code, name=variety.name) if variety is not None else None),
        total_harvested_weight_kg=lot.total_harvested_weight_kg, total_whole_unit_count=lot.total_whole_unit_count,
        effective_time=lot.effective_time, recorded_at=lot.recorded_at, source_lines=source_lines,
    )


def get_produce_lot(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, produce_lot_id: uuid.UUID
) -> HarvestedProduceLotRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        _produce_lot_header_query().where(
            HarvestedProduceLot.id == produce_lot_id, HarvestedProduceLot.tenant_id == tenant_id,
            HarvestedProduceLot.farm_id == farm_id,
        )
    ).first()
    if row is None:
        raise HarvestedProduceLotNotFoundError(str(produce_lot_id))
    lot: HarvestedProduceLot = row[0]
    source_lines = _load_source_lines(db, event_ids=[lot.harvest_event_id])[lot.harvest_event_id]
    return _row_to_produce_lot_read(row, source_lines)


def list_produce_lots(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[HarvestedProduceLotRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        _produce_lot_header_query()
        .where(HarvestedProduceLot.tenant_id == tenant_id, HarvestedProduceLot.farm_id == farm_id)
        .order_by(HarvestedProduceLot.code)
    ).all()
    event_ids = [r[0].harvest_event_id for r in rows]
    source_by_event = _load_source_lines(db, event_ids=event_ids)
    return [_row_to_produce_lot_read(r, source_by_event[r[0].harvest_event_id]) for r in rows]
