import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.water_measurement import WaterMeasurementCreate, WaterMeasurementRead
from app.services import water_instrument_service
from app.services.errors import (
    SamplingPointNotFoundError,
    WaterInstrumentNotFoundError,
    WaterMeasurementValidationError,
)

router = APIRouter(tags=["water-measurements"])


@router.post(
    "/farms/{farm_id}/sampling-points/{sampling_point_id}/measurements", response_model=WaterMeasurementRead,
    status_code=status.HTTP_201_CREATED,
)
def record_measurement(
    farm_id: uuid.UUID,
    sampling_point_id: uuid.UUID,
    payload: WaterMeasurementCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_MEASUREMENT_MANAGE)),
) -> WaterMeasurementRead:
    try:
        return water_instrument_service.record_measurement(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            sampling_point_id=sampling_point_id, metric=payload.metric, value=payload.value, unit=payload.unit,
            effective_at=payload.effective_at, water_instrument_id=payload.water_instrument_id, notes=payload.notes,
            client_command_id=payload.client_command_id,
        )
    except SamplingPointNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sampling point not found") from exc
    except WaterInstrumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Water instrument not found") from exc
    except WaterMeasurementValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get(
    "/sampling-points/{sampling_point_id}/measurements", response_model=list[WaterMeasurementRead]
)
def list_measurements(
    sampling_point_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_MEASUREMENT_READ)),
) -> list[WaterMeasurementRead]:
    return water_instrument_service.list_measurements(db, tenant_id=ctx.tenant_id, sampling_point_id=sampling_point_id)


@router.get("/farms/{farm_id}/water-measurements", response_model=list[WaterMeasurementRead])
def list_measurements_for_farm(
    farm_id: uuid.UUID,
    metric: str | None = Query(default=None),
    reservoir_id: uuid.UUID | None = Query(default=None),
    window_start: datetime | None = Query(default=None),
    window_end: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_MEASUREMENT_READ)),
) -> list[WaterMeasurementRead]:
    return water_instrument_service.list_measurements_for_farm(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, metric=metric, reservoir_id=reservoir_id,
        window_start=window_start, window_end=window_end,
    )
