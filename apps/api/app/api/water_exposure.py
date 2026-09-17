import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.water_exposure import BatchWaterExposureRead, ExposedPlacementRead
from app.services import water_exposure_service

router = APIRouter(tags=["water-exposure"])


@router.get(
    "/irrigation-circuits/{irrigation_circuit_id}/exposed-placements", response_model=list[ExposedPlacementRead]
)
def get_exposed_placements_for_circuit(
    irrigation_circuit_id: uuid.UUID,
    farm_id: uuid.UUID,
    window_start: datetime = Query(...),
    window_end: datetime = Query(...),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_EXPOSURE_READ)),
) -> list[ExposedPlacementRead]:
    return water_exposure_service.get_potentially_exposed_placements_for_circuit(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, irrigation_circuit_id=irrigation_circuit_id,
        window_start=window_start, window_end=window_end,
    )


@router.get("/reservoirs/{reservoir_id}/exposed-placements", response_model=list[ExposedPlacementRead])
def get_exposed_placements_for_reservoir(
    reservoir_id: uuid.UUID,
    farm_id: uuid.UUID,
    window_start: datetime = Query(...),
    window_end: datetime = Query(...),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_EXPOSURE_READ)),
) -> list[ExposedPlacementRead]:
    return water_exposure_service.get_potentially_exposed_placements_for_reservoir(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, reservoir_id=reservoir_id, window_start=window_start,
        window_end=window_end,
    )


@router.get("/crop-batches/{batch_id}/water-exposure", response_model=list[BatchWaterExposureRead])
def get_water_exposure_history_for_batch(
    batch_id: uuid.UUID,
    farm_id: uuid.UUID,
    window_start: datetime = Query(...),
    window_end: datetime = Query(...),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_EXPOSURE_READ)),
) -> list[BatchWaterExposureRead]:
    return water_exposure_service.get_water_exposure_history_for_batch(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, window_start=window_start,
        window_end=window_end,
    )
