import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_assignment_transfer import BatchAssignmentTransfer
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_derivation_event import BatchDerivationEvent
from app.models.batch_derivation_output import BatchDerivationOutput
from app.models.batch_derivation_source import BatchDerivationSource
from app.models.batch_stage_run import BatchStageRun
from app.models.batch_stage_transition import BatchStageTransition
from app.models.carrier import Carrier
from app.models.crop_batch import CropBatch
from app.models.sowing_event_line import SowingEventLine
from app.models.transplant_destination_line import TransplantDestinationLine
from app.models.workflow import Workflow
from app.models.workflow_stage import WorkflowStage
from app.schemas.batch_derivation import (
    BatchAssignmentTransferRead,
    BatchDerivationEventRead,
    BatchDerivationOutputRead,
    BatchDerivationSourceRead,
    BatchLineageEventRead,
    BatchLineageRead,
    BatchSummary,
    CarrierRefSummary,
)
from app.schemas.crop_batch import StageSummary, WorkflowSummary
from app.services import farm_service, quality_hold_service
from app.services.audit import append_audit_event
from app.services.errors import (
    BatchDerivationCommandReusedWithDifferentPayloadError,
    BatchDerivationEventNotFoundError,
    BatchDerivationValidationError,
    CarrierNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    DuplicateBatchCodeError,
    FarmNotFoundError,
    InvalidBatchDerivationEffectiveTimeError,
    QualityHoldOpenError,
    SourceAssignmentAlreadyReleasedError,
    SourceAssignmentNotFoundError,
    TooManyBatchDerivationLinesError,
)

MIN_SPLIT_OUTPUTS = 2
MAX_SPLIT_OUTPUTS = 50
MIN_MERGE_SOURCES = 2
MAX_MERGE_SOURCES = 50
MAX_TRANSFERS = 2000


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _find_existing_derivation_event(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> BatchDerivationEvent | None:
    return db.execute(
        select(BatchDerivationEvent).where(
            BatchDerivationEvent.tenant_id == tenant_id, BatchDerivationEvent.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def _compute_split_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, source_batch_id: uuid.UUID,
    effective_time: datetime, note: str | None, outputs: list[dict],
) -> str:
    sorted_outputs = sorted(outputs, key=lambda o: o["output_batch_code"])
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(source_batch_id),
        effective_time.astimezone(timezone.utc).isoformat(), note or "",
    ]
    for o in sorted_outputs:
        parts.append(o["output_batch_code"])
        parts.extend(str(aid) for aid in sorted(o["source_assignment_ids"], key=str))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_merge_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, effective_time: datetime,
    note: str | None, source_batch_ids: list[uuid.UUID], output_batch_code: str,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id),
        effective_time.astimezone(timezone.utc).isoformat(), note or "",
    ]
    parts.extend(str(bid) for bid in sorted(source_batch_ids, key=str))
    parts.append(output_batch_code)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _derive_transferred_quantity(db: Session, assignment: BatchCarrierAssignment) -> int:
    if assignment.opening_sowing_event_id is not None:
        qty = db.execute(
            select(SowingEventLine.sown_site_count).where(
                SowingEventLine.batch_carrier_assignment_id == assignment.id
            )
        ).scalar_one_or_none()
    elif assignment.opening_transplant_event_id is not None:
        qty = db.execute(
            select(TransplantDestinationLine.assigned_plant_count).where(
                TransplantDestinationLine.destination_batch_carrier_assignment_id == assignment.id
            )
        ).scalar_one_or_none()
    else:
        qty = db.execute(
            select(BatchAssignmentTransfer.transferred_plant_count).where(
                BatchAssignmentTransfer.opened_destination_assignment_id == assignment.id
            )
        ).scalar_one_or_none()
    if qty is None:
        raise BatchDerivationValidationError(
            f"no resolvable origin quantity for source assignment {assignment.id}"
        )
    return qty


# --- Shared write phase -------------------------------------------------------------


def _write_derivation(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    derivation_kind: str,
    client_command_id: uuid.UUID,
    fingerprint: str,
    effective_time: datetime,
    note: str | None,
    workflow_id: uuid.UUID,
    workflow_version_id: uuid.UUID,
    inherited_stage_id: uuid.UUID,
    source_batches: list[CropBatch],
    source_runs: dict[uuid.UUID, BatchStageRun],
    outputs: list[dict],
    assignments_by_id: dict[uuid.UUID, BatchCarrierAssignment],
    quantities_by_assignment: dict[uuid.UUID, int],
) -> BatchDerivationEvent:
    try:
        event = BatchDerivationEvent(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, derivation_kind=derivation_kind,
            workflow_id=workflow_id, workflow_version_id=workflow_version_id,
            inherited_workflow_stage_id=inherited_stage_id, effective_time=effective_time,
            actor_user_id=actor_user_id, client_command_id=client_command_id,
            request_fingerprint=fingerprint, note=note,
        )
        db.add(event)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_batch_derivation_events_tenant_client_command_id":
            replay = _find_existing_derivation_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise BatchDerivationCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    try:
        transfers_by_source: dict[uuid.UUID, list[uuid.UUID]] = {b.id: [] for b in source_batches}
        for output in outputs:
            for aid in output["assignment_ids"]:
                transfers_by_source[assignments_by_id[aid].batch_id].append(aid)

        for batch in source_batches:
            aids = transfers_by_source[batch.id]
            db.add(
                BatchDerivationSource(
                    id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, derivation_event_id=event.id,
                    source_batch_id=batch.id, source_batch_stage_run_id=source_runs[batch.id].id,
                    recorded_plant_quantity_total=sum(quantities_by_assignment[aid] for aid in aids),
                    recorded_carrier_assignment_count=len(aids),
                )
            )
        db.flush()

        output_batches: dict[str, CropBatch] = {}
        for output in outputs:
            output_batch = CropBatch(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, code=output["code"],
                workflow_id=workflow_id, workflow_version_id=workflow_version_id, state="active",
                created_effective_time=effective_time, closed_effective_time=None,
                superseded_effective_time=None, superseded_by_batch_derivation_event_id=None,
                created_by_user_id=actor_user_id, created_by_batch_derivation_event_id=event.id,
                client_command_id=None, request_fingerprint=None,
            )
            db.add(output_batch)
            output_batches[output["code"]] = output_batch
        db.flush()

        for output in outputs:
            aids = output["assignment_ids"]
            db.add(
                BatchDerivationOutput(
                    id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, derivation_event_id=event.id,
                    output_batch_id=output_batches[output["code"]].id,
                    recorded_plant_quantity_total=sum(quantities_by_assignment[aid] for aid in aids),
                    recorded_carrier_assignment_count=len(aids),
                )
            )
        db.flush()

        transitions_by_code: dict[str, BatchStageTransition] = {}
        for output in outputs:
            transition = BatchStageTransition(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=output_batches[output["code"]].id,
                workflow_version_id=workflow_version_id, command_kind="derivation_entry",
                source_stage_id=None, destination_stage_id=inherited_stage_id, configured_transition_id=None,
                batch_derivation_event_id=event.id, effective_time=effective_time, actor_user_id=actor_user_id,
                client_command_id=None, request_fingerprint=None, reason=None,
            )
            db.add(transition)
            transitions_by_code[output["code"]] = transition
        db.flush()

        runs_by_code: dict[str, BatchStageRun] = {}
        for output in outputs:
            run = BatchStageRun(
                id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=output_batches[output["code"]].id,
                workflow_version_id=workflow_version_id, workflow_stage_id=inherited_stage_id,
                entered_effective_time=effective_time, exited_effective_time=None,
                opened_by_transition_id=transitions_by_code[output["code"]].id, closed_by_transition_id=None,
                actor_user_id=actor_user_id,
            )
            db.add(run)
            runs_by_code[output["code"]] = run
        db.flush()

        # Source assignments must be released before their carrier's new
        # destination assignment is inserted: the same physical carrier is
        # reused (unlike CMP-011 transplant, where source/destination are
        # always different carriers), and the partial unique index enforcing
        # "one active assignment per carrier" is a plain unique index, not a
        # deferrable constraint — it is checked immediately, so both rows can
        # never be simultaneously active even within one transaction.
        for assignment in assignments_by_id.values():
            assignment.released_effective_time = effective_time
            assignment.released_by_batch_derivation_event_id = event.id
        db.flush()

        new_assignment_by_old: dict[uuid.UUID, BatchCarrierAssignment] = {}
        for output in outputs:
            output_batch = output_batches[output["code"]]
            run = runs_by_code[output["code"]]
            for aid in output["assignment_ids"]:
                old_assignment = assignments_by_id[aid]
                new_assignment = BatchCarrierAssignment(
                    id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=output_batch.id,
                    carrier_id=old_assignment.carrier_id, batch_stage_run_id=run.id,
                    assigned_effective_time=effective_time, released_effective_time=None,
                    opening_sowing_event_id=None, opening_transplant_event_id=None,
                    opening_batch_derivation_event_id=event.id, released_by_transplant_event_id=None,
                    released_by_batch_derivation_event_id=None, actor_user_id=actor_user_id,
                )
                db.add(new_assignment)
                new_assignment_by_old[aid] = new_assignment
        db.flush()

        for output in outputs:
            output_batch = output_batches[output["code"]]
            for aid in output["assignment_ids"]:
                old_assignment = assignments_by_id[aid]
                db.add(
                    BatchAssignmentTransfer(
                        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, derivation_event_id=event.id,
                        source_batch_id=old_assignment.batch_id, output_batch_id=output_batch.id,
                        carrier_id=old_assignment.carrier_id, released_source_assignment_id=old_assignment.id,
                        opened_destination_assignment_id=new_assignment_by_old[aid].id,
                        transferred_plant_count=quantities_by_assignment[aid],
                    )
                )
        db.flush()

        for batch in source_batches:
            batch.state = "superseded"
            batch.superseded_effective_time = effective_time
            batch.superseded_by_batch_derivation_event_id = event.id
        db.flush()

        total_transferred = sum(quantities_by_assignment.values())
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id,
            action="crop_batch.split" if derivation_kind == "split" else "crop_batch.merged",
            entity_type="batch_derivation_event", entity_id=event.id,
            event_data={
                "derivation_event_id": str(event.id), "derivation_kind": derivation_kind,
                "source_batch_ids": [str(b.id) for b in source_batches],
                "output_batch_ids": [str(output_batches[o["code"]].id) for o in outputs],
                "workflow_version_id": str(workflow_version_id), "inherited_stage_id": str(inherited_stage_id),
                "effective_time": effective_time.isoformat(), "client_command_id": str(client_command_id),
                "carrier_transfer_count": sum(len(o["assignment_ids"]) for o in outputs),
                "total_transferred_plant_count": total_transferred,
                "source_count": len(source_batches), "output_count": len(outputs),
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_crop_batches_tenant_code_lower":
            raise DuplicateBatchCodeError(str(exc)) from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(event)
    return event


# --- Split -----------------------------------------------------------------------


def split_batch(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    outputs: list[dict],
) -> BatchDerivationEvent:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidBatchDerivationEffectiveTimeError("effective_time cannot be in the future")
    if not (MIN_SPLIT_OUTPUTS <= len(outputs) <= MAX_SPLIT_OUTPUTS):
        raise BatchDerivationValidationError(
            f"a split command must include between {MIN_SPLIT_OUTPUTS} and {MAX_SPLIT_OUTPUTS} outputs"
        )
    total_requested = sum(len(o["source_assignment_ids"]) for o in outputs)
    if total_requested > MAX_TRANSFERS:
        raise TooManyBatchDerivationLinesError(f"a split command may include at most {MAX_TRANSFERS} transfers")

    fingerprint = _compute_split_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, source_batch_id=batch_id,
        effective_time=effective_time, note=note, outputs=outputs,
    )

    existing = _find_existing_derivation_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise BatchDerivationCommandReusedWithDifferentPayloadError(str(client_command_id))

    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    existing = _find_existing_derivation_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise BatchDerivationCommandReusedWithDifferentPayloadError(str(client_command_id))

    if batch.state != "active":
        raise CropBatchClosedError(str(batch_id))

    if quality_hold_service.has_open_quality_hold(db, batch_id=batch.id):
        raise QualityHoldOpenError(str(batch_id))

    active_run = db.execute(
        select(BatchStageRun)
        .where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if active_run is None:
        raise CropBatchNotFoundError(str(batch_id))

    requested_ids = sorted({aid for o in outputs for aid in o["source_assignment_ids"]})
    assignments = list(
        db.execute(
            select(BatchCarrierAssignment).where(BatchCarrierAssignment.id.in_(requested_ids))
            .order_by(BatchCarrierAssignment.id).with_for_update()
        ).scalars()
    )
    assignments_by_id = {a.id: a for a in assignments}
    for aid in requested_ids:
        assignment = assignments_by_id.get(aid)
        if (
            assignment is None or assignment.tenant_id != tenant_id or assignment.farm_id != farm_id
            or assignment.batch_id != batch.id
        ):
            raise SourceAssignmentNotFoundError(str(aid))
        if assignment.released_effective_time is not None:
            raise SourceAssignmentAlreadyReleasedError(str(aid))

    active_assignment_ids = set(
        db.execute(
            select(BatchCarrierAssignment.id)
            .where(BatchCarrierAssignment.batch_id == batch.id, BatchCarrierAssignment.released_effective_time.is_(None))
            .with_for_update()
        ).scalars()
    )
    if active_assignment_ids != set(requested_ids):
        missing = active_assignment_ids - set(requested_ids)
        extra = set(requested_ids) - active_assignment_ids
        raise BatchDerivationValidationError(
            f"split must map every active source assignment exactly once (missing={sorted(str(a) for a in missing)}, "
            f"extra={sorted(str(a) for a in extra)})"
        )

    carrier_ids = sorted({a.carrier_id for a in assignments})
    carriers = list(
        db.execute(
            select(Carrier).where(Carrier.id.in_(carrier_ids), Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id)
            .order_by(Carrier.id).with_for_update()
        ).scalars()
    )
    if len(carriers) != len(carrier_ids):
        found = {c.id for c in carriers}
        missing = [cid for cid in carrier_ids if cid not in found]
        raise CarrierNotFoundError(str(missing[0]) if missing else "")

    quantities_by_assignment = {aid: _derive_transferred_quantity(db, assignments_by_id[aid]) for aid in requested_ids}

    if effective_time < batch.created_effective_time:
        raise InvalidBatchDerivationEffectiveTimeError("effective_time precedes the source batch's creation effective time")
    if effective_time < active_run.entered_effective_time:
        raise InvalidBatchDerivationEffectiveTimeError("effective_time precedes the current stage run's entry time")
    for aid in requested_ids:
        if effective_time < assignments_by_id[aid].assigned_effective_time:
            raise InvalidBatchDerivationEffectiveTimeError(
                f"effective_time precedes source assignment {aid}'s assigned_effective_time"
            )

    resolved_outputs = [{"code": o["output_batch_code"], "assignment_ids": o["source_assignment_ids"]} for o in outputs]

    return _write_derivation(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, derivation_kind="split",
        client_command_id=client_command_id, fingerprint=fingerprint, effective_time=effective_time, note=note,
        workflow_id=batch.workflow_id, workflow_version_id=batch.workflow_version_id,
        inherited_stage_id=active_run.workflow_stage_id, source_batches=[batch],
        source_runs={batch.id: active_run}, outputs=resolved_outputs, assignments_by_id=assignments_by_id,
        quantities_by_assignment=quantities_by_assignment,
    )


# --- Merge -----------------------------------------------------------------------


def merge_batches(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    source_batch_ids: list[uuid.UUID],
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str | None,
    output_batch_code: str,
) -> BatchDerivationEvent:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidBatchDerivationEffectiveTimeError("effective_time cannot be in the future")
    if not (MIN_MERGE_SOURCES <= len(source_batch_ids) <= MAX_MERGE_SOURCES):
        raise BatchDerivationValidationError(
            f"a merge command must include between {MIN_MERGE_SOURCES} and {MAX_MERGE_SOURCES} source batches"
        )

    fingerprint = _compute_merge_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, effective_time=effective_time,
        note=note, source_batch_ids=source_batch_ids, output_batch_code=output_batch_code,
    )

    existing = _find_existing_derivation_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise BatchDerivationCommandReusedWithDifferentPayloadError(str(client_command_id))

    sorted_source_ids = sorted(set(source_batch_ids))
    source_batches = list(
        db.execute(
            select(CropBatch)
            .where(CropBatch.id.in_(sorted_source_ids), CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
            .order_by(CropBatch.id).with_for_update()
        ).scalars()
    )
    if len(source_batches) != len(sorted_source_ids):
        found = {b.id for b in source_batches}
        missing = [bid for bid in sorted_source_ids if bid not in found]
        raise CropBatchNotFoundError(str(missing[0]))
    source_batches_by_id = {b.id: b for b in source_batches}

    existing = _find_existing_derivation_event(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise BatchDerivationCommandReusedWithDifferentPayloadError(str(client_command_id))

    for batch in source_batches:
        if batch.state != "active":
            raise CropBatchClosedError(str(batch.id))
        if quality_hold_service.has_open_quality_hold(db, batch_id=batch.id):
            raise QualityHoldOpenError(str(batch.id))

    active_runs = list(
        db.execute(
            select(BatchStageRun)
            .where(BatchStageRun.batch_id.in_(sorted_source_ids), BatchStageRun.exited_effective_time.is_(None))
            .order_by(BatchStageRun.id).with_for_update()
        ).scalars()
    )
    source_runs = {r.batch_id: r for r in active_runs}
    for batch in source_batches:
        if batch.id not in source_runs:
            raise CropBatchNotFoundError(str(batch.id))

    workflow_ids = {b.workflow_id for b in source_batches}
    workflow_version_ids = {b.workflow_version_id for b in source_batches}
    stage_ids = {source_runs[b.id].workflow_stage_id for b in source_batches}
    if len(workflow_ids) != 1 or len(workflow_version_ids) != 1 or len(stage_ids) != 1:
        raise BatchDerivationValidationError(
            "merge requires all source batches to share the same workflow, workflow version, and current stage"
        )

    assignments = list(
        db.execute(
            select(BatchCarrierAssignment)
            .where(
                BatchCarrierAssignment.batch_id.in_(sorted_source_ids),
                BatchCarrierAssignment.released_effective_time.is_(None),
            )
            .order_by(BatchCarrierAssignment.id).with_for_update()
        ).scalars()
    )
    assignments_by_id = {a.id: a for a in assignments}
    covered_batches = {a.batch_id for a in assignments}
    for batch in source_batches:
        if batch.id not in covered_batches:
            raise BatchDerivationValidationError(f"source batch {batch.id} has no active carrier assignments")
    if len(assignments) > MAX_TRANSFERS:
        raise TooManyBatchDerivationLinesError(f"a merge command may include at most {MAX_TRANSFERS} transfers")

    carrier_ids = sorted({a.carrier_id for a in assignments})
    carriers = list(
        db.execute(
            select(Carrier).where(Carrier.id.in_(carrier_ids), Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id)
            .order_by(Carrier.id).with_for_update()
        ).scalars()
    )
    if len(carriers) != len(carrier_ids):
        found = {c.id for c in carriers}
        missing = [cid for cid in carrier_ids if cid not in found]
        raise CarrierNotFoundError(str(missing[0]) if missing else "")

    quantities_by_assignment = {
        aid: _derive_transferred_quantity(db, assignment) for aid, assignment in assignments_by_id.items()
    }

    for batch in source_batches:
        if effective_time < batch.created_effective_time:
            raise InvalidBatchDerivationEffectiveTimeError(
                f"effective_time precedes source batch {batch.id}'s creation effective time"
            )
        if effective_time < source_runs[batch.id].entered_effective_time:
            raise InvalidBatchDerivationEffectiveTimeError(
                f"effective_time precedes source batch {batch.id}'s current stage run entry time"
            )
    for assignment in assignments:
        if effective_time < assignment.assigned_effective_time:
            raise InvalidBatchDerivationEffectiveTimeError(
                f"effective_time precedes source assignment {assignment.id}'s assigned_effective_time"
            )

    workflow_id = next(iter(workflow_ids))
    workflow_version_id = next(iter(workflow_version_ids))
    inherited_stage_id = next(iter(stage_ids))
    resolved_outputs = [{"code": output_batch_code, "assignment_ids": list(assignments_by_id.keys())}]

    return _write_derivation(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, derivation_kind="merge",
        client_command_id=client_command_id, fingerprint=fingerprint, effective_time=effective_time, note=note,
        workflow_id=workflow_id, workflow_version_id=workflow_version_id, inherited_stage_id=inherited_stage_id,
        source_batches=source_batches, source_runs=source_runs, outputs=resolved_outputs,
        assignments_by_id=assignments_by_id, quantities_by_assignment=quantities_by_assignment,
    )


# --- Reads -----------------------------------------------------------------------


def get_derivation_event(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, derivation_event_id: uuid.UUID
) -> BatchDerivationEventRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        select(BatchDerivationEvent, Workflow, WorkflowStage)
        .join(Workflow, Workflow.id == BatchDerivationEvent.workflow_id)
        .join(WorkflowStage, WorkflowStage.id == BatchDerivationEvent.inherited_workflow_stage_id)
        .where(
            BatchDerivationEvent.id == derivation_event_id, BatchDerivationEvent.tenant_id == tenant_id,
            BatchDerivationEvent.farm_id == farm_id,
        )
    ).first()
    if row is None:
        raise BatchDerivationEventNotFoundError(str(derivation_event_id))
    event: BatchDerivationEvent = row[0]
    workflow: Workflow = row[1]
    stage: WorkflowStage = row[2]

    source_rows = db.execute(
        select(BatchDerivationSource, CropBatch)
        .join(CropBatch, CropBatch.id == BatchDerivationSource.source_batch_id)
        .where(BatchDerivationSource.derivation_event_id == derivation_event_id)
        .order_by(CropBatch.code, CropBatch.id)
    ).all()
    sources = [
        BatchDerivationSourceRead(
            id=s.id, source_batch=BatchSummary(id=b.id, code=b.code),
            source_batch_stage_run_id=s.source_batch_stage_run_id,
            recorded_plant_quantity_total=s.recorded_plant_quantity_total,
            recorded_carrier_assignment_count=s.recorded_carrier_assignment_count,
        )
        for s, b in source_rows
    ]

    output_rows = db.execute(
        select(BatchDerivationOutput, CropBatch)
        .join(CropBatch, CropBatch.id == BatchDerivationOutput.output_batch_id)
        .where(BatchDerivationOutput.derivation_event_id == derivation_event_id)
        .order_by(CropBatch.code, CropBatch.id)
    ).all()
    outputs = [
        BatchDerivationOutputRead(
            id=o.id, output_batch=BatchSummary(id=b.id, code=b.code),
            recorded_plant_quantity_total=o.recorded_plant_quantity_total,
            recorded_carrier_assignment_count=o.recorded_carrier_assignment_count,
        )
        for o, b in output_rows
    ]

    source_batch_alias = CropBatch
    transfer_rows = db.execute(
        select(BatchAssignmentTransfer, Carrier)
        .join(Carrier, Carrier.id == BatchAssignmentTransfer.carrier_id)
        .where(BatchAssignmentTransfer.derivation_event_id == derivation_event_id)
        .order_by(Carrier.code, Carrier.id)
    ).all()
    batch_ids = {t.source_batch_id for t, _c in transfer_rows} | {t.output_batch_id for t, _c in transfer_rows}
    batches_by_id: dict[uuid.UUID, CropBatch] = {}
    if batch_ids:
        for b in db.execute(select(source_batch_alias).where(source_batch_alias.id.in_(batch_ids))).scalars():
            batches_by_id[b.id] = b
    transfers = [
        BatchAssignmentTransferRead(
            id=t.id, carrier=CarrierRefSummary(id=c.id, code=c.code),
            source_batch=BatchSummary(id=t.source_batch_id, code=batches_by_id[t.source_batch_id].code),
            output_batch=BatchSummary(id=t.output_batch_id, code=batches_by_id[t.output_batch_id].code),
            released_source_assignment_id=t.released_source_assignment_id,
            opened_destination_assignment_id=t.opened_destination_assignment_id,
            transferred_plant_count=t.transferred_plant_count,
        )
        for t, c in transfer_rows
    ]

    return BatchDerivationEventRead(
        id=event.id, tenant_id=event.tenant_id, farm_id=event.farm_id, derivation_kind=event.derivation_kind,
        workflow=WorkflowSummary(id=workflow.id, code=workflow.code, name=workflow.name),
        workflow_version_id=event.workflow_version_id,
        inherited_stage=StageSummary(id=stage.id, code=stage.code, name=stage.name, is_terminal=stage.is_terminal),
        effective_time=event.effective_time, recorded_at=event.recorded_at, actor_user_id=event.actor_user_id,
        client_command_id=event.client_command_id, note=event.note, sources=sources, outputs=outputs,
        transfers=transfers, total_source_plant_count=sum(s.recorded_plant_quantity_total for s in sources),
        total_output_plant_count=sum(o.recorded_plant_quantity_total for o in outputs),
        total_carrier_transfer_count=len(transfers),
    )


def get_batch_lineage(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> BatchLineageRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    batch = db.execute(
        select(CropBatch).where(
            CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    other_batch = CropBatch
    parent_rows = db.execute(
        select(
            BatchAssignmentTransfer.derivation_event_id, BatchDerivationEvent.derivation_kind,
            BatchDerivationEvent.effective_time, other_batch.id, other_batch.code,
            func.sum(BatchAssignmentTransfer.transferred_plant_count),
            func.count(BatchAssignmentTransfer.id),
        )
        .join(BatchDerivationEvent, BatchDerivationEvent.id == BatchAssignmentTransfer.derivation_event_id)
        .join(other_batch, other_batch.id == BatchAssignmentTransfer.source_batch_id)
        .where(BatchAssignmentTransfer.output_batch_id == batch_id, BatchAssignmentTransfer.tenant_id == tenant_id)
        .group_by(
            BatchAssignmentTransfer.derivation_event_id, BatchDerivationEvent.derivation_kind,
            BatchDerivationEvent.effective_time, other_batch.id, other_batch.code,
        )
        .order_by(other_batch.code, other_batch.id)
    ).all()
    parents = [
        BatchLineageEventRead(
            derivation_event_id=eid, derivation_kind=kind, effective_time=eff,
            batch=BatchSummary(id=bid, code=code), recorded_plant_quantity_total=qty,
            recorded_carrier_assignment_count=count,
        )
        for eid, kind, eff, bid, code, qty, count in parent_rows
    ]

    child_rows = db.execute(
        select(
            BatchAssignmentTransfer.derivation_event_id, BatchDerivationEvent.derivation_kind,
            BatchDerivationEvent.effective_time, other_batch.id, other_batch.code,
            func.sum(BatchAssignmentTransfer.transferred_plant_count),
            func.count(BatchAssignmentTransfer.id),
        )
        .join(BatchDerivationEvent, BatchDerivationEvent.id == BatchAssignmentTransfer.derivation_event_id)
        .join(other_batch, other_batch.id == BatchAssignmentTransfer.output_batch_id)
        .where(BatchAssignmentTransfer.source_batch_id == batch_id, BatchAssignmentTransfer.tenant_id == tenant_id)
        .group_by(
            BatchAssignmentTransfer.derivation_event_id, BatchDerivationEvent.derivation_kind,
            BatchDerivationEvent.effective_time, other_batch.id, other_batch.code,
        )
        .order_by(other_batch.code, other_batch.id)
    ).all()
    children = [
        BatchLineageEventRead(
            derivation_event_id=eid, derivation_kind=kind, effective_time=eff,
            batch=BatchSummary(id=bid, code=code), recorded_plant_quantity_total=qty,
            recorded_carrier_assignment_count=count,
        )
        for eid, kind, eff, bid, code, qty, count in child_rows
    ]

    return BatchLineageRead(batch_id=batch_id, parents=parents, children=children)
