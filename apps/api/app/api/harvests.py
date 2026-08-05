import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.dev_auth import DevTenantContext, require_dev_tenant_context
from app.schemas.harvest import HarvestedProduceLotRead, HarvestEventCreate, HarvestEventRead
from app.services import harvest_service
from app.services.errors import (
    CarrierNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    DuplicateProduceLotCodeError,
    FarmNotFoundError,
    HarvestCommandReusedWithDifferentPayloadError,
    HarvestedProduceLotNotFoundError,
    HarvestEventNotFoundError,
    HarvestSourceAssignmentNotFoundError,
    HarvestValidationError,
    InvalidHarvestEffectiveTimeError,
    QualityHoldOpenError,
    TooManyHarvestLinesError,
)

router = APIRouter(tags=["harvests"])


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/harvests",
    response_model=HarvestEventRead,
    status_code=status.HTTP_201_CREATED,
)
def record_harvest(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: HarvestEventCreate,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> HarvestEventRead:
    source_lines = [
        {
            "batch_carrier_assignment_id": line.batch_carrier_assignment_id,
            "harvested_weight_kg": line.harvested_weight_kg,
            "whole_unit_count": line.whole_unit_count,
            "note": line.note,
        }
        for line in payload.source_lines
    ]
    try:
        event = harvest_service.record_harvest(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            batch_id=batch_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            produce_lot_code=payload.produce_lot_code,
            note=payload.note,
            source_lines=source_lines,
        )
    except (
        FarmNotFoundError,
        CropBatchNotFoundError,
        HarvestSourceAssignmentNotFoundError,
        CarrierNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        CropBatchClosedError,
        QualityHoldOpenError,
        HarvestCommandReusedWithDifferentPayloadError,
        DuplicateProduceLotCodeError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        HarvestValidationError,
        InvalidHarvestEffectiveTimeError,
        TooManyHarvestLinesError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return harvest_service.get_harvest_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, harvest_event_id=event.id
    )


@router.get("/farms/{farm_id}/crop-batches/{batch_id}/harvests", response_model=list[HarvestEventRead])
def list_harvests(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> list[HarvestEventRead]:
    try:
        return harvest_service.list_harvest_events(db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id)
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/harvests/{harvest_event_id}", response_model=HarvestEventRead
)
def get_harvest(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    harvest_event_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> HarvestEventRead:
    try:
        return harvest_service.get_harvest_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, harvest_event_id=harvest_event_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError, HarvestEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/harvested-produce-lots", response_model=list[HarvestedProduceLotRead])
def list_harvested_produce_lots(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> list[HarvestedProduceLotRead]:
    try:
        return harvest_service.list_produce_lots(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/harvested-produce-lots/{produce_lot_id}", response_model=HarvestedProduceLotRead
)
def get_harvested_produce_lot(
    farm_id: uuid.UUID,
    produce_lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> HarvestedProduceLotRead:
    try:
        return harvest_service.get_produce_lot(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, produce_lot_id=produce_lot_id
        )
    except (FarmNotFoundError, HarvestedProduceLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
