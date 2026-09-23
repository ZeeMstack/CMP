import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.water_exposure import (
    BatchWaterExposureRead,
    BatchWaterExposureTimelineRead,
    ExposedPlacementRead,
    WaterExposureTimelineRead,
)
from app.services import water_exposure_service

router = APIRouter(tags=["water-exposure"])


def _window(
    window_start: datetime = Query(..., description="Inclusive, timezone-aware."),
    window_end: datetime = Query(..., description="Exclusive, timezone-aware; must be after window_start."),
) -> tuple[datetime, datetime]:
    """Half-open query window `[window_start, window_end)`, validated at the
    API boundary."""
    try:
        water_exposure_service.validate_window(window_start, window_end)
    except water_exposure_service.ExposureWindowError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return window_start, window_end


@router.get(
    "/irrigation-circuits/{irrigation_circuit_id}/exposed-placements", response_model=list[ExposedPlacementRead]
)
def get_exposed_placements_for_circuit(
    irrigation_circuit_id: uuid.UUID,
    farm_id: uuid.UUID,
    window: tuple[datetime, datetime] = Depends(_window),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_EXPOSURE_READ)),
) -> list[ExposedPlacementRead]:
    return water_exposure_service.get_potentially_exposed_placements_for_circuit(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, irrigation_circuit_id=irrigation_circuit_id,
        window_start=window[0], window_end=window[1],
    )


@router.get("/reservoirs/{reservoir_id}/exposed-placements", response_model=list[ExposedPlacementRead])
def get_exposed_placements_for_reservoir(
    reservoir_id: uuid.UUID,
    farm_id: uuid.UUID,
    window: tuple[datetime, datetime] = Depends(_window),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_EXPOSURE_READ)),
) -> list[ExposedPlacementRead]:
    return water_exposure_service.get_potentially_exposed_placements_for_reservoir(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, reservoir_id=reservoir_id, window_start=window[0],
        window_end=window[1],
    )


@router.get("/crop-batches/{batch_id}/water-exposure", response_model=list[BatchWaterExposureRead])
def get_water_exposure_history_for_batch(
    batch_id: uuid.UUID,
    farm_id: uuid.UUID,
    window: tuple[datetime, datetime] = Depends(_window),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_EXPOSURE_READ)),
) -> list[BatchWaterExposureRead]:
    return water_exposure_service.get_water_exposure_history_for_batch(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, window_start=window[0],
        window_end=window[1],
    )


# --- UX-OPS-001D0 exact interval timelines ------------------------------------------------


@router.get("/crop-batches/{batch_id}/water-exposure-timeline", response_model=BatchWaterExposureTimelineRead)
def get_batch_water_exposure_timeline(
    batch_id: uuid.UUID,
    farm_id: uuid.UUID,
    window: tuple[datetime, datetime] = Depends(_window),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_EXPOSURE_READ)),
) -> BatchWaterExposureTimelineRead:
    return water_exposure_service.get_batch_water_exposure_timeline(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, window_start=window[0],
        window_end=window[1],
    )


@router.get(
    "/irrigation-circuits/{irrigation_circuit_id}/water-exposure-timeline", response_model=WaterExposureTimelineRead
)
def get_circuit_water_exposure_timeline(
    irrigation_circuit_id: uuid.UUID,
    farm_id: uuid.UUID,
    window: tuple[datetime, datetime] = Depends(_window),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_EXPOSURE_READ)),
) -> WaterExposureTimelineRead:
    return water_exposure_service.get_circuit_water_exposure_timeline(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, irrigation_circuit_id=irrigation_circuit_id,
        window_start=window[0], window_end=window[1],
    )


@router.get("/reservoirs/{reservoir_id}/water-exposure-timeline", response_model=WaterExposureTimelineRead)
def get_reservoir_water_exposure_timeline(
    reservoir_id: uuid.UUID,
    farm_id: uuid.UUID,
    window: tuple[datetime, datetime] = Depends(_window),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_EXPOSURE_READ)),
) -> WaterExposureTimelineRead:
    return water_exposure_service.get_reservoir_water_exposure_timeline(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, reservoir_id=reservoir_id, window_start=window[0],
        window_end=window[1],
    )
