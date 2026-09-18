import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.harvest_forecast import (
    BatchHarvestForecastRead,
    BatchHarvestForecastStatusRead,
    RecordBatchHarvestForecast,
)
from app.services import harvest_forecast_service
from app.services.errors import (
    BatchHarvestForecastCommandReusedWithDifferentPayloadError,
    BatchHarvestForecastNotFoundError,
    CropBatchNotFoundError,
    FarmNotFoundError,
    UnitOfMeasureNotFoundError,
)

router = APIRouter(tags=["harvest-forecasts"])


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/harvest-forecast",
    response_model=BatchHarvestForecastRead,
    status_code=status.HTTP_201_CREATED,
)
def record_batch_harvest_forecast(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: RecordBatchHarvestForecast,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_FORECAST_MANAGE)),
) -> BatchHarvestForecastRead:
    try:
        harvest_forecast_service.record_batch_harvest_forecast(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, batch_id=batch_id,
            client_command_id=payload.client_command_id, window_start_date=payload.window_start_date,
            window_end_date=payload.window_end_date, low_quantity=payload.low_quantity,
            expected_quantity=payload.expected_quantity, high_quantity=payload.high_quantity,
            quantity_uom_id=payload.quantity_uom_id, basis=payload.basis, effective_time=payload.effective_time,
            notes=payload.notes, revision_reason=payload.revision_reason,
        )
    except (FarmNotFoundError, CropBatchNotFoundError, UnitOfMeasureNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except BatchHarvestForecastCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return harvest_forecast_service.get_current_forecast(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
    )


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/harvest-forecast", response_model=BatchHarvestForecastRead
)
def get_current_forecast(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_FORECAST_READ)),
) -> BatchHarvestForecastRead:
    try:
        return harvest_forecast_service.get_current_forecast(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError, BatchHarvestForecastNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/harvest-forecast/history",
    response_model=list[BatchHarvestForecastRead],
)
def get_forecast_history(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_FORECAST_READ)),
) -> list[BatchHarvestForecastRead]:
    try:
        return harvest_forecast_service.list_forecast_history(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/harvest-forecast/status",
    response_model=BatchHarvestForecastStatusRead,
)
def get_forecast_status(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_FORECAST_READ)),
) -> BatchHarvestForecastStatusRead:
    try:
        return harvest_forecast_service.get_forecast_status(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/harvest-forecast-summary", response_model=list[BatchHarvestForecastStatusRead]
)
def get_farm_forecast_summary(
    farm_id: uuid.UUID,
    window_start_date: date = Query(...),
    window_end_date: date = Query(...),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.HARVEST_FORECAST_READ)),
) -> list[BatchHarvestForecastStatusRead]:
    try:
        return harvest_forecast_service.list_farm_forecast_summary(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, window_start_date=window_start_date,
            window_end_date=window_end_date,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
