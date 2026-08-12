import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext, require_tenant_context
from app.core.permissions import Permission, require_permission
from app.schemas.transplant_event import TransplantEventCreate, TransplantEventRead
from app.services import transplant_service
from app.services.errors import (
    CarrierNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    DestinationCarrierAlreadyAssignedError,
    FarmNotFoundError,
    InvalidTransplantEffectiveTimeError,
    SourceAssignmentAlreadyReleasedError,
    SourceAssignmentNotFoundError,
    TooManyTransplantLinesError,
    TransplantCommandReusedWithDifferentPayloadError,
    TransplantEventNotFoundError,
    TransplantValidationError,
)

router = APIRouter(tags=["transplants"])


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/transplants",
    response_model=TransplantEventRead,
    status_code=status.HTTP_201_CREATED,
)
def record_transplant(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: TransplantEventCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> TransplantEventRead:
    source_lines = [
        {
            "source_assignment_id": line.source_assignment_id,
            "source_plant_count": line.source_plant_count,
            "discarded_plant_count": line.discarded_plant_count,
            "note": line.note,
        }
        for line in payload.source_lines
    ]
    destination_lines = [
        {
            "destination_carrier_id": line.destination_carrier_id,
            "assigned_plant_count": line.assigned_plant_count,
            "note": line.note,
        }
        for line in payload.destination_lines
    ]
    allocations = [
        {
            "source_assignment_id": a.source_assignment_id,
            "destination_carrier_id": a.destination_carrier_id,
            "allocated_plant_count": a.allocated_plant_count,
        }
        for a in payload.allocations
    ]
    try:
        event = transplant_service.record_transplant(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            batch_id=batch_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            note=payload.note,
            source_lines=source_lines,
            destination_lines=destination_lines,
            allocations=allocations,
        )
    except (
        FarmNotFoundError,
        CropBatchNotFoundError,
        SourceAssignmentNotFoundError,
        CarrierNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        CropBatchClosedError,
        SourceAssignmentAlreadyReleasedError,
        DestinationCarrierAlreadyAssignedError,
        TransplantCommandReusedWithDifferentPayloadError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        TransplantValidationError,
        InvalidTransplantEffectiveTimeError,
        TooManyTransplantLinesError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return transplant_service.get_transplant_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, transplant_event_id=event.id
    )


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/transplants", response_model=list[TransplantEventRead]
)
def list_transplants(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_READ)),
) -> list[TransplantEventRead]:
    try:
        return transplant_service.list_transplant_events(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/transplants/{transplant_event_id}",
    response_model=TransplantEventRead,
)
def get_transplant(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    transplant_event_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_READ)),
) -> TransplantEventRead:
    try:
        return transplant_service.get_transplant_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id,
            transplant_event_id=transplant_event_id,
        )
    except (FarmNotFoundError, CropBatchNotFoundError, TransplantEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
