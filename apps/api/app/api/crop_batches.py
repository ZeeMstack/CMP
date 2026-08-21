import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.db import get_db, get_engine
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.batch_stage_transition import BatchStageTransitionCreate, BatchStageTransitionRead
from app.schemas.crop_batch import (
    BatchStageRunRead,
    CropBatchCreate,
    CropBatchRead,
    CurrentStageRead,
    StageSummary,
)
from app.schemas.operational_read import BatchOperationalContext
from app.services import crop_batch_service, operational_read_service
from app.services.errors import (
    BatchCommandReusedWithDifferentPayloadError,
    BatchCreationValidationError,
    BatchStageHasUnresolvedSeedlingRemainderError,
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
from app.services.lineage_traversal import _snapshot_connection

router = APIRouter(tags=["crop-batches"])


@router.post(
    "/farms/{farm_id}/crop-batches", response_model=CropBatchRead, status_code=status.HTTP_201_CREATED
)
def create_crop_batch(
    farm_id: uuid.UUID,
    payload: CropBatchCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_BATCH_MANAGE)),
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
    ctx: TenantContext = Depends(require_permission(Permission.CROP_BATCH_READ)),
) -> list[CropBatchRead]:
    try:
        return crop_batch_service.list_batches(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc


@router.get(
    "/farms/{farm_id}/crop-batches/operational-summary", response_model=list[BatchOperationalContext]
)
def get_crop_batches_operational_summary(
    farm_id: uuid.UUID,
    state: Literal["active", "all"] = "active",
    ctx: TenantContext = Depends(require_permission(Permission.CROP_BATCH_READ)),
    db_engine: Engine = Depends(get_engine),
) -> list[BatchOperationalContext]:
    """CMP-FE-002A: bounded, farm-wide operational read model -- one
    coherent snapshot covering sowing origin, current placement, and open
    quality-hold count per batch, powering both Home (`state` omitted,
    active-only) and the Batch Register (`state=all`, every legitimate
    `crop_batches.state`: active, closed, superseded)."""
    try:
        with _snapshot_connection(db_engine) as conn:
            batch_ids = operational_read_service.resolve_batch_ids_by_state(
                conn, tenant_id=ctx.tenant_id, farm_id=farm_id, state_filter=state
            )
            return operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_ids=batch_ids
            )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/operational-context", response_model=BatchOperationalContext
)
def get_crop_batch_operational_context(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission(Permission.CROP_BATCH_READ)),
    db_engine: Engine = Depends(get_engine),
) -> BatchOperationalContext:
    """Single-batch counterpart of the operational-summary list -- same
    shared service function, `{batch_id}` only, so Batch Detail never has
    to download the whole farm's payload for one batch's operational
    context. Resolves regardless of state (active/closed/superseded)."""
    try:
        with _snapshot_connection(db_engine) as conn:
            results = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_ids=[batch_id]
            )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    if not results:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return results[0]


@router.get("/farms/{farm_id}/crop-batches/{batch_id}", response_model=CropBatchRead)
def get_crop_batch(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_BATCH_READ)),
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
    ctx: TenantContext = Depends(require_permission(Permission.CROP_BATCH_MANAGE)),
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
    except BatchStageHasUnresolvedSeedlingRemainderError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "unresolved_source_count": exc.unresolved_source_count,
                "total_unresolved_living_count": exc.total_unresolved_living_count,
            },
        ) from exc
    except InvalidBatchEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return BatchStageTransitionRead.model_validate(transition)


@router.get("/farms/{farm_id}/crop-batches/{batch_id}/current-stage", response_model=CurrentStageRead)
def get_current_stage(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_BATCH_READ)),
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
    ctx: TenantContext = Depends(require_permission(Permission.CROP_BATCH_READ)),
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
    ctx: TenantContext = Depends(require_permission(Permission.CROP_BATCH_READ)),
) -> BatchStageTransitionRead:
    try:
        transition = crop_batch_service.get_stage_transition(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, transition_id=transition_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return BatchStageTransitionRead.model_validate(transition)
