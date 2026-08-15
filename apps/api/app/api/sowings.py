import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.sowing_event import BatchCarrierAssignmentRead, SowingEventCreate, SowingEventRead
from app.services import sowing_service
from app.services.errors import (
    BatchAlreadySownError,
    CarrierAlreadyAssignedError,
    CarrierNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    FarmNotFoundError,
    InvalidSowingEffectiveTimeError,
    MixedSeedLotInSowingCommandError,
    SeedLotNotFoundError,
    SowingCommandReusedWithDifferentPayloadError,
    SowingEventNotFoundError,
    SowingValidationError,
    TooManySowingLinesError,
)

router = APIRouter(tags=["sowings"])


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/sowings",
    response_model=SowingEventRead,
    status_code=status.HTTP_201_CREATED,
)
def sow_batch(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: SowingEventCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_MANAGE)),
) -> SowingEventRead:
    lines = [
        {
            "carrier_id": line.carrier_id,
            "seed_lot_id": line.seed_lot_id,
            "sown_site_count": line.sown_site_count,
            "seed_count": line.seed_count,
            "line_note": line.line_note,
        }
        for line in payload.lines
    ]
    try:
        event = sowing_service.sow_batch(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            batch_id=batch_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            note=payload.note,
            lines=lines,
        )
    except (FarmNotFoundError, CropBatchNotFoundError, CarrierNotFoundError, SeedLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        CropBatchClosedError,
        CarrierAlreadyAssignedError,
        SowingCommandReusedWithDifferentPayloadError,
        BatchAlreadySownError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        SowingValidationError,
        InvalidSowingEffectiveTimeError,
        TooManySowingLinesError,
        MixedSeedLotInSowingCommandError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return sowing_service.get_sowing_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, sowing_event_id=event.id
    )


@router.get("/farms/{farm_id}/crop-batches/{batch_id}/sowings", response_model=list[SowingEventRead])
def list_sowings(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_READ)),
) -> list[SowingEventRead]:
    try:
        return sowing_service.list_sowing_events(db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id)
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/sowings/{sowing_event_id}", response_model=SowingEventRead
)
def get_sowing(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    sowing_event_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_READ)),
) -> SowingEventRead:
    try:
        return sowing_service.get_sowing_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, sowing_event_id=sowing_event_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError, SowingEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/carriers", response_model=list[BatchCarrierAssignmentRead]
)
def list_batch_carriers(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_READ)),
) -> list[BatchCarrierAssignmentRead]:
    try:
        return sowing_service.list_batch_carriers(db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id)
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/carriers/{carrier_id}/batch-assignment",
    response_model=BatchCarrierAssignmentRead | None,
)
def get_carrier_batch_assignment(
    farm_id: uuid.UUID,
    carrier_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_READ)),
) -> BatchCarrierAssignmentRead | None:
    try:
        return sowing_service.get_carrier_batch_assignment(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, carrier_id=carrier_id
        )
    except (FarmNotFoundError, CarrierNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
