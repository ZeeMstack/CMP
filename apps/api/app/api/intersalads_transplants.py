import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.intersalads_transplant import (
    AvailableNurseryCultivationPlateRead,
    IntersaladsTransplantCreate,
    IntersaladsTransplantRead,
)
from app.services import intersalads_transplant_service
from app.services.errors import (
    AssetCannotOccupyOwnPositionError,
    CarrierNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    DestinationCarrierAlreadyAssignedError,
    FarmNotFoundError,
    InactiveOccupantError,
    InactiveTargetError,
    IncompatibleOccupantTargetError,
    IntersaladsTransplantReplayStateConflictError,
    InvalidEffectiveTimeError,
    InvalidTransplantEffectiveTimeError,
    LocationNotFoundError,
    MovementCommandReusedWithDifferentPayloadError,
    NoOpMovementError,
    OccupantAlreadyActiveError,
    SourceAssignmentAlreadyReleasedError,
    SourceAssignmentHasNoSeedlingEntryError,
    SourceAssignmentNotFoundError,
    TargetNotOccupiableError,
    TargetOccupiedError,
    TooManyTransplantLinesError,
    TransplantCapacityExceededError,
    TransplantCommandReusedWithDifferentPayloadError,
    TransplantValidationError,
)

router = APIRouter(tags=["intersalads-transplants"])


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/intersalads-transplants",
    response_model=IntersaladsTransplantRead,
    status_code=status.HTTP_201_CREATED,
)
def record_intersalads_transplant(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: IntersaladsTransplantCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_MANAGE)),
) -> IntersaladsTransplantRead:
    """NURSERY-OPS-004B.1: one atomic operator command -- biological
    Transplant onto Nursery Cultivation Plate destination(s), then physical
    placement of each onto its selected InterSalads Table, one transaction.
    Gated by `TRANSPLANT_MANAGE` alone (not `MOVEMENT_MANAGE` in addition):
    the physical placement is an inseparable side effect of the approved
    biological Transplant workflow, and the biological half -- the harder-
    to-reverse, dominant operation -- is what this permission represents.
    The internal cores perform no permission checks of their own, so this
    route declares its own authorization dependency explicitly rather than
    assuming one is inherited from `transplants.py`/`movements.py`."""
    source_lines = [
        {
            "source_assignment_id": line.source_assignment_id,
            "transplant_damage_count": line.transplant_damage_count,
            "qc_rejection_count": line.qc_rejection_count,
            "sample_count": line.sample_count,
            "other_loss_count": line.other_loss_count,
            "other_loss_note": line.other_loss_note,
            "note": line.note,
        }
        for line in payload.source_lines
    ]
    destination_lines = [
        {
            "destination_carrier_id": line.destination_carrier_id,
            "assigned_plant_count": line.assigned_plant_count,
            "destination_location_id": line.destination_location_id,
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
        return intersalads_transplant_service.record_intersalads_transplant(
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
        LocationNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        CropBatchClosedError,
        SourceAssignmentAlreadyReleasedError,
        DestinationCarrierAlreadyAssignedError,
        TransplantCommandReusedWithDifferentPayloadError,
        InactiveOccupantError,
        InactiveTargetError,
        TargetOccupiedError,
        OccupantAlreadyActiveError,
        NoOpMovementError,
        MovementCommandReusedWithDifferentPayloadError,
        IntersaladsTransplantReplayStateConflictError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        TransplantValidationError,
        TransplantCapacityExceededError,
        InvalidTransplantEffectiveTimeError,
        TooManyTransplantLinesError,
        SourceAssignmentHasNoSeedlingEntryError,
        TargetNotOccupiableError,
        IncompatibleOccupantTargetError,
        AssetCannotOccupyOwnPositionError,
        InvalidEffectiveTimeError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/farms/{farm_id}/nursery/intersalads/available-plates",
    response_model=list[AvailableNurseryCultivationPlateRead],
)
def list_available_intersalads_plates(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_READ)),
) -> list[AvailableNurseryCultivationPlateRead]:
    """NURSERY-OPS-004B.2 section 13: narrow, read-only support for the
    InterSalads Transplant operator UI's destination-Plate picker -- not a
    generic Carrier-availability framework."""
    try:
        return intersalads_transplant_service.list_available_intersalads_plates(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
