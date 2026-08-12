import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext, require_tenant_context
from app.core.permissions import Permission, require_permission
from app.schemas.quality_hold import QualityHoldCreate, QualityHoldRead, QualityHoldReleaseCreate
from app.services import quality_hold_service
from app.services.errors import (
    CropBatchClosedError,
    CropBatchNotFoundError,
    FarmNotFoundError,
    InvalidQualityHoldEffectiveTimeError,
    ObservationEventNotFoundError,
    QualityHoldAlreadyReleasedError,
    QualityHoldCommandReusedWithDifferentPayloadError,
    QualityHoldNotFoundError,
    QualityHoldValidationError,
)

router = APIRouter(tags=["quality-holds"])


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/quality-holds",
    response_model=QualityHoldRead,
    status_code=status.HTTP_201_CREATED,
)
def place_quality_hold(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: QualityHoldCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> QualityHoldRead:
    try:
        hold = quality_hold_service.place_quality_hold(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            batch_id=batch_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            source_observation_event_id=payload.source_observation_event_id,
            reason_code=payload.reason_code,
            reason_text=payload.reason_text,
        )
    except (FarmNotFoundError, CropBatchNotFoundError, ObservationEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (CropBatchClosedError, QualityHoldCommandReusedWithDifferentPayloadError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (InvalidQualityHoldEffectiveTimeError, QualityHoldValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return quality_hold_service.get_quality_hold(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, hold_id=hold.id
    )


@router.get("/farms/{farm_id}/crop-batches/{batch_id}/quality-holds", response_model=list[QualityHoldRead])
def list_quality_holds(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.QUALITY_HOLD_READ)),
) -> list[QualityHoldRead]:
    try:
        return quality_hold_service.list_quality_holds(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/quality-holds/{hold_id}", response_model=QualityHoldRead
)
def get_quality_hold(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    hold_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.QUALITY_HOLD_READ)),
) -> QualityHoldRead:
    try:
        return quality_hold_service.get_quality_hold(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, hold_id=hold_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError, QualityHoldNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/quality-holds/{hold_id}/release",
    response_model=QualityHoldRead,
    status_code=status.HTTP_201_CREATED,
)
def release_quality_hold(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    hold_id: uuid.UUID,
    payload: QualityHoldReleaseCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> QualityHoldRead:
    try:
        quality_hold_service.release_quality_hold(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            batch_id=batch_id,
            hold_id=hold_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            release_reason=payload.release_reason,
        )
    except (FarmNotFoundError, CropBatchNotFoundError, QualityHoldNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        CropBatchClosedError,
        QualityHoldAlreadyReleasedError,
        QualityHoldCommandReusedWithDifferentPayloadError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidQualityHoldEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return quality_hold_service.get_quality_hold(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, hold_id=hold_id
    )
