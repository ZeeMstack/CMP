import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.batch_derivation import BatchDerivationEventRead, BatchLineageRead, BatchMergeCreate, BatchSplitCreate
from app.services import batch_derivation_service
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

router = APIRouter(tags=["batch-derivations"])


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/split",
    response_model=BatchDerivationEventRead,
    status_code=status.HTTP_201_CREATED,
)
def split_crop_batch(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: BatchSplitCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.BATCH_DERIVATION_MANAGE)),
) -> BatchDerivationEventRead:
    outputs = [
        {"output_batch_code": o.output_batch_code, "source_assignment_ids": o.source_assignment_ids}
        for o in payload.outputs
    ]
    try:
        event = batch_derivation_service.split_batch(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            batch_id=batch_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            note=payload.note,
            outputs=outputs,
        )
    except (FarmNotFoundError, CropBatchNotFoundError, SourceAssignmentNotFoundError, CarrierNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        CropBatchClosedError,
        QualityHoldOpenError,
        SourceAssignmentAlreadyReleasedError,
        BatchDerivationCommandReusedWithDifferentPayloadError,
        DuplicateBatchCodeError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        BatchDerivationValidationError,
        InvalidBatchDerivationEffectiveTimeError,
        TooManyBatchDerivationLinesError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return batch_derivation_service.get_derivation_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, derivation_event_id=event.id
    )


@router.post(
    "/farms/{farm_id}/crop-batch-merges",
    response_model=BatchDerivationEventRead,
    status_code=status.HTTP_201_CREATED,
)
def merge_crop_batches(
    farm_id: uuid.UUID,
    payload: BatchMergeCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.BATCH_DERIVATION_MANAGE)),
) -> BatchDerivationEventRead:
    try:
        event = batch_derivation_service.merge_batches(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            source_batch_ids=payload.source_batch_ids,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            note=payload.note,
            output_batch_code=payload.output_batch_code,
        )
    except (FarmNotFoundError, CropBatchNotFoundError, CarrierNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        CropBatchClosedError,
        QualityHoldOpenError,
        BatchDerivationCommandReusedWithDifferentPayloadError,
        DuplicateBatchCodeError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        BatchDerivationValidationError,
        InvalidBatchDerivationEffectiveTimeError,
        TooManyBatchDerivationLinesError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return batch_derivation_service.get_derivation_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, derivation_event_id=event.id
    )


@router.get(
    "/farms/{farm_id}/batch-derivations/{derivation_event_id}", response_model=BatchDerivationEventRead
)
def get_batch_derivation(
    farm_id: uuid.UUID,
    derivation_event_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.BATCH_DERIVATION_READ)),
) -> BatchDerivationEventRead:
    try:
        return batch_derivation_service.get_derivation_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, derivation_event_id=derivation_event_id
        )
    except (FarmNotFoundError, BatchDerivationEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/crop-batches/{batch_id}/lineage", response_model=BatchLineageRead)
def get_crop_batch_lineage(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.BATCH_DERIVATION_READ)),
) -> BatchLineageRead:
    try:
        return batch_derivation_service.get_batch_lineage(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
