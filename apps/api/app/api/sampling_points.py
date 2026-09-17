import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.sampling_point import SamplingPointCreate, SamplingPointRead
from app.services import sampling_point_service
from app.services.errors import (
    DuplicateSamplingPointCodeError,
    FarmNotFoundError,
    IrrigationCircuitNotFoundError,
    ReservoirNotFoundError,
    SamplingPointNotFoundError,
    SamplingPointValidationError,
    WaterDeliveryPointNotFoundError,
    WaterReturnPointNotFoundError,
    WaterSourceNotFoundError,
)

router = APIRouter(tags=["sampling-points"])

_ANCHOR_NOT_FOUND_ERRORS = (
    WaterSourceNotFoundError, ReservoirNotFoundError, IrrigationCircuitNotFoundError,
    WaterDeliveryPointNotFoundError, WaterReturnPointNotFoundError,
)


@router.post(
    "/farms/{farm_id}/sampling-points", response_model=SamplingPointRead, status_code=status.HTTP_201_CREATED
)
def register_sampling_point(
    farm_id: uuid.UUID,
    payload: SamplingPointCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SAMPLING_POINT_MANAGE)),
) -> SamplingPointRead:
    try:
        return sampling_point_service.register_sampling_point(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, code=payload.code,
            name=payload.name, point_type=payload.point_type, anchor_id=payload.anchor_id, notes=payload.notes,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    except _ANCHOR_NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Anchor not found") from exc
    except SamplingPointValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except DuplicateSamplingPointCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Sampling point code already exists") from exc


@router.get("/farms/{farm_id}/sampling-points", response_model=list[SamplingPointRead])
def list_sampling_points(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SAMPLING_POINT_READ)),
) -> list[SamplingPointRead]:
    return sampling_point_service.list_sampling_points(db, tenant_id=ctx.tenant_id, farm_id=farm_id)


@router.get("/sampling-points/{sampling_point_id}", response_model=SamplingPointRead)
def get_sampling_point(
    sampling_point_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SAMPLING_POINT_READ)),
) -> SamplingPointRead:
    try:
        return sampling_point_service.get_sampling_point(db, tenant_id=ctx.tenant_id, sampling_point_id=sampling_point_id)
    except SamplingPointNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sampling point not found") from exc
