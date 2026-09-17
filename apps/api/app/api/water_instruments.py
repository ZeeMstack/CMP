import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.water_instrument import (
    CalibrationEventCreate,
    CalibrationEventRead,
    WaterInstrumentCreate,
    WaterInstrumentRead,
)
from app.services import water_instrument_service
from app.services.errors import (
    AssetNotFoundError,
    DuplicateWaterInstrumentAssetError,
    InstrumentCalibrationValidationError,
    WaterInstrumentNotFoundError,
    WaterInstrumentValidationError,
)

router = APIRouter(tags=["water-instruments"])


@router.post(
    "/farms/{farm_id}/water-instruments", response_model=WaterInstrumentRead, status_code=status.HTTP_201_CREATED
)
def register_water_instrument(
    farm_id: uuid.UUID,
    payload: WaterInstrumentCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_INSTRUMENT_MANAGE)),
) -> WaterInstrumentRead:
    try:
        return water_instrument_service.register_water_instrument(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, asset_id=payload.asset_id,
            supports_ph=payload.supports_ph, supports_ec=payload.supports_ec,
            supports_solution_temperature=payload.supports_solution_temperature,
            supports_dissolved_oxygen=payload.supports_dissolved_oxygen,
        )
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Asset not found") from exc
    except WaterInstrumentValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except DuplicateWaterInstrumentAssetError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This asset is already registered as a water instrument"
        ) from exc


@router.get("/farms/{farm_id}/water-instruments", response_model=list[WaterInstrumentRead])
def list_water_instruments(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_INSTRUMENT_READ)),
) -> list[WaterInstrumentRead]:
    return water_instrument_service.list_water_instruments(db, tenant_id=ctx.tenant_id, farm_id=farm_id)


@router.get("/water-instruments/{water_instrument_id}", response_model=WaterInstrumentRead)
def get_water_instrument(
    water_instrument_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_INSTRUMENT_READ)),
) -> WaterInstrumentRead:
    try:
        return water_instrument_service.get_water_instrument(
            db, tenant_id=ctx.tenant_id, water_instrument_id=water_instrument_id
        )
    except WaterInstrumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Water instrument not found") from exc


@router.post(
    "/farms/{farm_id}/water-instruments/{water_instrument_id}/calibrations", response_model=CalibrationEventRead,
    status_code=status.HTTP_201_CREATED,
)
def record_calibration(
    farm_id: uuid.UUID,
    water_instrument_id: uuid.UUID,
    payload: CalibrationEventCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_INSTRUMENT_MANAGE)),
) -> CalibrationEventRead:
    try:
        return water_instrument_service.record_calibration(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            water_instrument_id=water_instrument_id, metric=payload.metric, effective_at=payload.effective_at,
            result=payload.result, standard_reference=payload.standard_reference, notes=payload.notes,
            client_command_id=payload.client_command_id,
        )
    except WaterInstrumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Water instrument not found") from exc
    except InstrumentCalibrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/water-instruments/{water_instrument_id}/calibrations", response_model=list[CalibrationEventRead]
)
def list_calibrations(
    water_instrument_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_INSTRUMENT_READ)),
) -> list[CalibrationEventRead]:
    try:
        return water_instrument_service.list_calibration_events(
            db, tenant_id=ctx.tenant_id, water_instrument_id=water_instrument_id
        )
    except WaterInstrumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Water instrument not found") from exc


@router.get("/water-instruments/{water_instrument_id}/calibration-status")
def get_calibration_status(
    water_instrument_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_INSTRUMENT_READ)),
) -> dict:
    try:
        return water_instrument_service.instrument_calibration_status(
            db, tenant_id=ctx.tenant_id, water_instrument_id=water_instrument_id
        )
    except WaterInstrumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Water instrument not found") from exc
