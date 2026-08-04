import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.dev_auth import DevTenantContext, require_dev_tenant_context
from app.schemas.batch_stage_transition import BatchStageTransitionCreate, BatchStageTransitionRead
from app.schemas.crop_batch import (
    BatchStageRunRead,
    CropBatchCreate,
    CropBatchRead,
    CurrentStageRead,
    StageSummary,
)
from app.services import crop_batch_service
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

router = APIRouter(tags=["crop-batches"])


@router.post(
    "/farms/{farm_id}/crop-batches", response_model=CropBatchRead, status_code=status.HTTP_201_CREATED
)
def create_crop_batch(
    farm_id: uuid.UUID,
    payload: CropBatchCreate,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> CropBatchRead:
    try:
        batch = crop_batch_service.create_batch(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            code=payload.code,
            workflow_id=payload.workflow_id,
            effective_time=payload.effective_time,
        )
    except (FarmNotFoundError, WorkflowNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (DuplicateBatchCodeError, BatchCommandReusedWithDifferentPayloadError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (WorkflowInactiveError, WorkflowHasNoPublishedVersionError, BatchCreationValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InvalidBatchEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return crop_batch_service.get_batch(db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch.id)


@router.get("/farms/{farm_id}/crop-batches", response_model=list[CropBatchRead])
def list_crop_batches(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> list[CropBatchRead]:
    try:
        return crop_batch_service.list_batches(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc


@router.get("/farms/{farm_id}/crop-batches/{batch_id}", response_model=CropBatchRead)
def get_crop_batch(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> CropBatchRead:
    try:
        return crop_batch_service.get_batch(db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id)
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/stage-transitions",
    response_model=BatchStageTransitionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_stage_transition(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: BatchStageTransitionCreate,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> BatchStageTransitionRead:
    try:
        transition = crop_batch_service.transition_stage(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            batch_id=batch_id,
            client_command_id=payload.client_command_id,
            configured_transition_id=payload.configured_transition_id,
            effective_time=payload.effective_time,
            reason=payload.reason,
        )
    except (FarmNotFoundError, CropBatchNotFoundError, ConfiguredTransitionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        CropBatchClosedError,
        StageMismatchError,
        BatchCommandReusedWithDifferentPayloadError,
        QualityHoldOpenError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidBatchEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return BatchStageTransitionRead.model_validate(transition)


@router.get("/farms/{farm_id}/crop-batches/{batch_id}/current-stage", response_model=CurrentStageRead)
def get_current_stage(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> CurrentStageRead:
    try:
        _batch, run, stage = crop_batch_service.get_current_stage(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return CurrentStageRead(
        batch_id=batch_id,
        current_stage=StageSummary(id=stage.id, code=stage.code, name=stage.name, is_terminal=stage.is_terminal),
        entered_effective_time=run.entered_effective_time,
    )


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/stage-history", response_model=list[BatchStageRunRead]
)
def get_stage_history(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> list[BatchStageRunRead]:
    try:
        rows = crop_batch_service.get_stage_history(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [
        BatchStageRunRead(
            id=run.id,
            stage=StageSummary(id=stage.id, code=stage.code, name=stage.name, is_terminal=stage.is_terminal),
            entered_effective_time=run.entered_effective_time,
            exited_effective_time=run.exited_effective_time,
        )
        for run, stage in rows
    ]


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/stage-transitions/{transition_id}",
    response_model=BatchStageTransitionRead,
)
def get_stage_transition(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    transition_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> BatchStageTransitionRead:
    try:
        transition = crop_batch_service.get_stage_transition(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, transition_id=transition_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return BatchStageTransitionRead.model_validate(transition)
