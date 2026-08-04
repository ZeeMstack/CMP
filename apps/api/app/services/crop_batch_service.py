import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.models.batch_stage_run import BatchStageRun
from app.models.batch_stage_transition import BatchStageTransition
from app.models.crop import Crop
from app.models.crop_batch import CropBatch
from app.models.production_system import ProductionSystem
from app.models.variety import Variety
from app.models.workflow import Workflow
from app.models.workflow_stage import WorkflowStage
from app.models.workflow_transition import WorkflowTransition
from app.models.workflow_version import WorkflowVersion
from app.schemas.crop_batch import (
    CropBatchRead,
    CropSummary,
    ProductionSystemSummary,
    StageSummary,
    VarietySummary,
    WorkflowSummary,
)
from app.services import farm_service, quality_hold_service
from app.services.audit import append_audit_event
from app.services.errors import (
    BatchCommandReusedWithDifferentPayloadError,
    BatchCreationValidationError,
    ConfiguredTransitionNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    DuplicateBatchCodeError,
    FarmNotFoundError,
    InvalidBatchEffectiveTimeError,
    QualityHoldOpenError,
    StageMismatchError,
    WorkflowHasNoPublishedVersionError,
    WorkflowInactiveError,
    WorkflowNotFoundError,
)


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> None:
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _compute_creation_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, code: str,
    workflow_id: uuid.UUID, effective_time: datetime,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), code, str(workflow_id),
        effective_time.astimezone(timezone.utc).isoformat(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _compute_transition_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, batch_id: uuid.UUID,
    configured_transition_id: uuid.UUID, effective_time: datetime, reason: str | None,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(batch_id), str(configured_transition_id),
        effective_time.astimezone(timezone.utc).isoformat(), reason or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_batch(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> CropBatch | None:
    return db.execute(
        select(CropBatch).where(
            CropBatch.tenant_id == tenant_id, CropBatch.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def _find_existing_transition(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> BatchStageTransition | None:
    return db.execute(
        select(BatchStageTransition).where(
            BatchStageTransition.tenant_id == tenant_id,
            BatchStageTransition.command_kind == "stage_transition",
            BatchStageTransition.client_command_id == client_command_id,
        )
    ).scalar_one_or_none()


def _get_batch_row(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID) -> CropBatch:
    batch = db.execute(
        select(CropBatch).where(
            CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))
    return batch


# --- Batch creation --------------------------------------------------------------


def create_batch(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    code: str,
    workflow_id: uuid.UUID,
    effective_time: datetime,
) -> CropBatch:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidBatchEffectiveTimeError("effective_time cannot be in the future")

    fingerprint = _compute_creation_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, code=code,
        workflow_id=workflow_id, effective_time=effective_time,
    )

    existing = _find_existing_batch(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise BatchCommandReusedWithDifferentPayloadError(str(client_command_id))

    # Lock the workflow row: serializes concurrent creators (racing retries
    # or racing distinct codes) behind one another.
    workflow = db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id).with_for_update()
    ).scalar_one_or_none()
    if workflow is None:
        raise WorkflowNotFoundError(str(workflow_id))

    # Re-check idempotency now that we're serialized behind the workflow
    # lock — a losing concurrent duplicate must resolve as a replay here.
    existing = _find_existing_batch(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise BatchCommandReusedWithDifferentPayloadError(str(client_command_id))

    if workflow.status != "active":
        raise WorkflowInactiveError(str(workflow_id))

    version = db.execute(
        select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow.id, WorkflowVersion.state == "published"
        )
    ).scalar_one_or_none()
    if version is None:
        raise WorkflowHasNoPublishedVersionError(str(workflow_id))

    crop = db.get(Crop, workflow.crop_id)
    if crop is None or crop.status != "active":
        raise BatchCreationValidationError("referenced crop is not active")

    if workflow.variety_id is not None:
        variety = db.get(Variety, workflow.variety_id)
        if variety is None or variety.status != "active":
            raise BatchCreationValidationError("referenced variety is not active")

    production_system = db.get(ProductionSystem, workflow.production_system_id)
    if production_system is None or production_system.status != "active":
        raise BatchCreationValidationError("referenced production system is not active")

    stages = list(
        db.execute(select(WorkflowStage).where(WorkflowStage.workflow_version_id == version.id)).scalars()
    )
    start_stages = [s for s in stages if s.is_start]
    if len(start_stages) != 1:
        raise BatchCreationValidationError("published workflow version does not have exactly one start stage")
    start_stage = start_stages[0]

    batch = CropBatch(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, code=code,
        workflow_id=workflow.id, workflow_version_id=version.id, state="active",
        created_effective_time=effective_time, closed_effective_time=None,
        created_by_user_id=actor_user_id, client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(batch)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_crop_batches_tenant_client_command_id":
            replay = _find_existing_batch(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise BatchCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_crop_batches_tenant_code_lower":
            raise DuplicateBatchCodeError(f"{tenant_id}:{code}") from exc
        raise

    # Everything from here on operates on an already-flushed `batch` row. Any
    # failure — expected or not — must roll back this whole command; letting
    # the session carry a partially-flushed, uncommitted batch/transition/run
    # into the caller's next query (or leaving it in a failed-transaction
    # state after a later IntegrityError) is not acceptable.
    try:
        # The stage run's opening transition must exist before the run does.
        initial_transition = BatchStageTransition(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
            workflow_version_id=version.id, command_kind="initial_entry",
            source_stage_id=None, destination_stage_id=start_stage.id, configured_transition_id=None,
            effective_time=effective_time, actor_user_id=actor_user_id,
            client_command_id=client_command_id, request_fingerprint=fingerprint, reason=None,
        )
        db.add(initial_transition)
        db.flush()

        initial_run = BatchStageRun(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
            workflow_version_id=version.id, workflow_stage_id=start_stage.id,
            entered_effective_time=effective_time, exited_effective_time=None,
            opened_by_transition_id=initial_transition.id, closed_by_transition_id=None,
            actor_user_id=actor_user_id,
        )
        db.add(initial_run)
        db.flush()

        batch_closed = False
        if start_stage.is_terminal:
            batch.state = "closed"
            batch.closed_effective_time = effective_time
            db.flush()
            batch_closed = True

        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.created",
            entity_type="crop_batch", entity_id=batch.id,
            event_data={
                "batch_id": str(batch.id), "code": batch.code, "farm_id": str(farm_id),
                "workflow_id": str(workflow.id), "workflow_version_id": str(version.id),
                "version_number": version.version_number, "initial_stage_id": str(start_stage.id),
                "client_command_id": str(client_command_id), "batch_closed": batch_closed,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(batch)
    return batch


# --- Stage progression -----------------------------------------------------------


def transition_stage(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    configured_transition_id: uuid.UUID,
    effective_time: datetime,
    reason: str | None,
) -> BatchStageTransition:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidBatchEffectiveTimeError("effective_time cannot be in the future")

    fingerprint = _compute_transition_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
        configured_transition_id=configured_transition_id, effective_time=effective_time, reason=reason,
    )

    existing = _find_existing_transition(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise BatchCommandReusedWithDifferentPayloadError(str(client_command_id))

    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    # Re-check idempotency now that we're serialized behind the batch lock.
    existing = _find_existing_transition(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise BatchCommandReusedWithDifferentPayloadError(str(client_command_id))

    # A genuinely new transition (not a replay) is blocked while any
    # CMP-010 quality hold on this batch remains open. Checked after the
    # idempotency replay above so an exact retry of an already-successful
    # transition still returns its original result even if a hold was
    # placed afterward.
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

    if effective_time < active_run.entered_effective_time:
        raise InvalidBatchEffectiveTimeError("effective_time precedes the current stage run's entry time")

    configured_transition = db.execute(
        select(WorkflowTransition).where(
            WorkflowTransition.id == configured_transition_id,
            WorkflowTransition.tenant_id == tenant_id,
            WorkflowTransition.workflow_version_id == batch.workflow_version_id,
        )
    ).scalar_one_or_none()
    if configured_transition is None:
        raise ConfiguredTransitionNotFoundError(str(configured_transition_id))

    if configured_transition.from_stage_id != active_run.workflow_stage_id:
        raise StageMismatchError(str(configured_transition_id))

    transition = BatchStageTransition(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
        workflow_version_id=batch.workflow_version_id, command_kind="stage_transition",
        source_stage_id=configured_transition.from_stage_id,
        destination_stage_id=configured_transition.to_stage_id,
        configured_transition_id=configured_transition.id,
        effective_time=effective_time, actor_user_id=actor_user_id,
        client_command_id=client_command_id, request_fingerprint=fingerprint, reason=reason,
    )
    db.add(transition)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_batch_stage_transitions_tenant_kind_client_id":
            replay = _find_existing_transition(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise BatchCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    # Everything from here on operates on an already-flushed `transition` row.
    # Any failure — expected or not — must roll back this whole command; the
    # prior stage run must not end up closed (or the new one open) without
    # the rest of the command having also succeeded.
    try:
        active_run.exited_effective_time = effective_time
        active_run.closed_by_transition_id = transition.id
        db.flush()

        destination_stage = db.get(WorkflowStage, configured_transition.to_stage_id)
        new_run = BatchStageRun(
            id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
            workflow_version_id=batch.workflow_version_id, workflow_stage_id=destination_stage.id,
            entered_effective_time=effective_time, exited_effective_time=None,
            opened_by_transition_id=transition.id, closed_by_transition_id=None,
            actor_user_id=actor_user_id,
        )
        db.add(new_run)
        db.flush()

        batch_closed = False
        if destination_stage.is_terminal:
            batch.state = "closed"
            batch.closed_effective_time = effective_time
            db.flush()
            batch_closed = True

        if batch_closed:
            append_audit_event(
                db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.closed",
                entity_type="crop_batch", entity_id=batch.id,
                event_data={
                    "batch_id": str(batch.id),
                    "batch_stage_transition_id": str(transition.id),
                    "configured_transition_id": str(configured_transition.id),
                    "source_stage_id": str(transition.source_stage_id),
                    "final_stage_id": str(destination_stage.id),
                    "effective_time": effective_time.isoformat(),
                    "client_command_id": str(client_command_id),
                    "reason": reason,
                    "batch_closed": True,
                    "closed_effective_time": effective_time.isoformat(),
                },
            )
        else:
            append_audit_event(
                db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.stage_transitioned",
                entity_type="crop_batch", entity_id=batch.id,
                event_data={
                    "batch_id": str(batch.id),
                    "batch_stage_transition_id": str(transition.id),
                    "configured_transition_id": str(configured_transition.id),
                    "source_stage_id": str(transition.source_stage_id),
                    "destination_stage_id": str(destination_stage.id),
                    "effective_time": effective_time.isoformat(),
                    "client_command_id": str(client_command_id),
                    "reason": reason,
                    "batch_closed": False,
                },
            )

        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(transition)
    return transition


# --- Reads ------------------------------------------------------------------------


def _batch_detail_query():
    run = aliased(BatchStageRun)
    stage = aliased(WorkflowStage)
    return (
        select(
            CropBatch,
            Workflow.id.label("workflow_id"),
            Workflow.code.label("workflow_code"),
            Workflow.name.label("workflow_name"),
            WorkflowVersion.version_number.label("version_number"),
            Crop.id.label("crop_id"),
            Crop.code.label("crop_code"),
            Crop.common_name.label("crop_common_name"),
            Variety.id.label("variety_id"),
            Variety.code.label("variety_code"),
            Variety.name.label("variety_name"),
            ProductionSystem.id.label("ps_id"),
            ProductionSystem.code.label("ps_code"),
            ProductionSystem.name.label("ps_name"),
            stage.id.label("stage_id"),
            stage.code.label("stage_code"),
            stage.name.label("stage_name"),
            stage.is_terminal.label("stage_is_terminal"),
        )
        .join(Workflow, Workflow.id == CropBatch.workflow_id)
        .join(WorkflowVersion, WorkflowVersion.id == CropBatch.workflow_version_id)
        .join(Crop, Crop.id == Workflow.crop_id)
        .outerjoin(Variety, Variety.id == Workflow.variety_id)
        .join(ProductionSystem, ProductionSystem.id == Workflow.production_system_id)
        .outerjoin(run, (run.batch_id == CropBatch.id) & (run.exited_effective_time.is_(None)))
        .outerjoin(stage, stage.id == run.workflow_stage_id)
    )


def _row_to_batch_read(row) -> CropBatchRead:
    batch: CropBatch = row[0]
    m = row._mapping
    return CropBatchRead(
        id=batch.id,
        tenant_id=batch.tenant_id,
        farm_id=batch.farm_id,
        code=batch.code,
        workflow=WorkflowSummary(id=m["workflow_id"], code=m["workflow_code"], name=m["workflow_name"]),
        workflow_version_id=batch.workflow_version_id,
        version_number=m["version_number"],
        crop=CropSummary(id=m["crop_id"], code=m["crop_code"], common_name=m["crop_common_name"]),
        variety=(
            VarietySummary(id=m["variety_id"], code=m["variety_code"], name=m["variety_name"])
            if m["variety_id"] is not None
            else None
        ),
        production_system=ProductionSystemSummary(id=m["ps_id"], code=m["ps_code"], name=m["ps_name"]),
        state=batch.state,
        current_stage=StageSummary(
            id=m["stage_id"], code=m["stage_code"], name=m["stage_name"], is_terminal=m["stage_is_terminal"]
        ),
        created_effective_time=batch.created_effective_time,
        created_at=batch.created_at,
        closed_effective_time=batch.closed_effective_time,
        superseded_effective_time=batch.superseded_effective_time,
        superseded_by_batch_derivation_event_id=batch.superseded_by_batch_derivation_event_id,
        created_by_batch_derivation_event_id=batch.created_by_batch_derivation_event_id,
    )


def get_batch(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID) -> CropBatchRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    row = db.execute(
        _batch_detail_query().where(
            CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id
        )
    ).first()
    if row is None:
        raise CropBatchNotFoundError(str(batch_id))
    return _row_to_batch_read(row)


def list_batches(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> list[CropBatchRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    rows = db.execute(
        _batch_detail_query()
        .where(CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .order_by(CropBatch.code)
    ).all()
    return [_row_to_batch_read(r) for r in rows]


def get_current_stage(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> tuple[CropBatch, BatchStageRun, WorkflowStage]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    batch = _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    run = db.execute(
        select(BatchStageRun).where(
            BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None)
        )
    ).scalar_one_or_none()
    stage = db.get(WorkflowStage, run.workflow_stage_id)
    return batch, run, stage


def get_stage_history(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> list[tuple[BatchStageRun, WorkflowStage]]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    rows = db.execute(
        select(BatchStageRun, WorkflowStage)
        .join(WorkflowStage, WorkflowStage.id == BatchStageRun.workflow_stage_id)
        .where(BatchStageRun.batch_id == batch_id)
        .order_by(BatchStageRun.entered_effective_time, BatchStageRun.recorded_at, BatchStageRun.id)
    ).all()
    return [(r[0], r[1]) for r in rows]


def get_stage_transition(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, transition_id: uuid.UUID
) -> BatchStageTransition:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    transition = db.execute(
        select(BatchStageTransition).where(
            BatchStageTransition.id == transition_id,
            BatchStageTransition.tenant_id == tenant_id,
            BatchStageTransition.batch_id == batch_id,
        )
    ).scalar_one_or_none()
    if transition is None:
        raise CropBatchNotFoundError(str(transition_id))
    return transition
