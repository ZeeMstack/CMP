import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.leafy_production_transfer import (
    AvailableLeafyProductionSourceRead,
    AvailableProductionCultivationPlateRead,
    LeafyProductionTransferCreate,
    LeafyProductionTransferRead,
)
from app.services import leafy_production_transfer_service
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
    InvalidEffectiveTimeError,
    InvalidTransplantEffectiveTimeError,
    LeafyProductionTransferReplayStateConflictError,
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
    UnsupportedTransplantSourceCarrierTypeError,
)

router = APIRouter(tags=["leafy-production-transfers"])


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/leafy-production-transfers",
    response_model=LeafyProductionTransferRead,
    status_code=status.HTTP_201_CREATED,
)
def record_leafy_production_transfer(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: LeafyProductionTransferCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_MANAGE)),
) -> LeafyProductionTransferRead:
    """NURSERY-OPS-005B: one atomic operator command -- biological
    Transplant off Nursery Cultivation Plate source(s) (NURSERY-OPS-005A's
    unified source authority, unchanged) onto Production Cultivation Plate
    destination(s), then physical placement of each onto its selected Leafy
    Production Table, one transaction. Gated by `TRANSPLANT_MANAGE` alone,
    mirroring the InterSalads composite's identical rationale: the physical
    placement is an inseparable side effect of the approved biological
    Transplant, the harder-to-reverse, dominant operation. Never transitions
    the Batch's stage -- NURSERY-OPS-005A's own guards remain the Batch's
    only stage gates."""
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
        return leafy_production_transfer_service.record_leafy_production_transfer(
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
        LeafyProductionTransferReplayStateConflictError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        TransplantValidationError,
        TransplantCapacityExceededError,
        InvalidTransplantEffectiveTimeError,
        TooManyTransplantLinesError,
        SourceAssignmentHasNoSeedlingEntryError,
        UnsupportedTransplantSourceCarrierTypeError,
        TargetNotOccupiableError,
        IncompatibleOccupantTargetError,
        AssetCannotOccupyOwnPositionError,
        InvalidEffectiveTimeError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/farms/{farm_id}/leafy-production/available-sources",
    response_model=list[AvailableLeafyProductionSourceRead],
)
def list_available_leafy_production_sources(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_READ)),
) -> list[AvailableLeafyProductionSourceRead]:
    """NURSERY-OPS-005B: narrow, read-only support for the Leafy Production
    Transfer operator UI's source-Plate picker -- not a generic "all BCAs
    with population" framework. Optional `batch_id` narrows to sources
    already established as belonging to the same Batch as a prior
    selection; omitted before that first selection is made."""
    try:
        return leafy_production_transfer_service.list_available_leafy_production_sources(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc


@router.get(
    "/farms/{farm_id}/leafy-production/available-plates",
    response_model=list[AvailableProductionCultivationPlateRead],
)
def list_available_production_plates(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_READ)),
) -> list[AvailableProductionCultivationPlateRead]:
    """NURSERY-OPS-005B: narrow, read-only support for the Leafy Production
    Transfer operator UI's destination-Plate picker."""
    try:
        return leafy_production_transfer_service.list_available_production_plates(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
