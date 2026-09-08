import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.vines_production_transfer import (
    AvailableGrowBagPoolRead,
    VinesProductionPlacementGrowBagRead,
    VinesProductionPlacementRead,
    VinesProductionTransferCreate,
    VinesProductionTransferRead,
)
from app.services import vines_production_transfer_service
from app.services.errors import (
    AssetCannotOccupyOwnPositionError,
    CarrierNotFoundError,
    CarrierSpecificationNotFoundError,
    CarrierSpecificationTypeMismatchError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    DestinationCarrierAlreadyAssignedError,
    FarmNotFoundError,
    InactiveOccupantError,
    InactiveTargetError,
    IncompatibleOccupantTargetError,
    InsufficientAvailableGrowBagPositionsError,
    InsufficientAvailableGrowBagsError,
    InsufficientAvailableInterVinesPlantsError,
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
    VinesProductionTransferReplayStateConflictError,
)

router = APIRouter(tags=["vines-production-transfers"])


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/vines-production-transfers",
    response_model=VinesProductionTransferRead,
    status_code=status.HTTP_201_CREATED,
)
def record_vines_production_transfer(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: VinesProductionTransferCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_MANAGE)),
) -> VinesProductionTransferRead:
    """VINES-OPS-001B: one atomic operator command -- biological Transplant
    of the requested plant quantity from a named InterVines (Batch, Table)
    group onto a server-allocated pool of Grow Bag(s), then physical
    placement of every allocated Grow Bag onto a free Grow Bag Position
    under the selected Grow Gutter, one transaction. Gated by
    `TRANSPLANT_MANAGE` alone, mirroring `intervines_transplants.record_
    intervines_transplant`'s own identical rationale."""
    try:
        return vines_production_transfer_service.record_vines_production_transfer(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            batch_id=batch_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            note=payload.note,
            source_intervines_table_id=payload.source_intervines_table_id,
            plant_count=payload.plant_count,
            destination_grow_gutter_id=payload.destination_grow_gutter_id,
            grow_bag_specification_id=payload.grow_bag_specification_id,
        )
    except (
        FarmNotFoundError,
        CropBatchNotFoundError,
        SourceAssignmentNotFoundError,
        CarrierNotFoundError,
        CarrierSpecificationNotFoundError,
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
        VinesProductionTransferReplayStateConflictError,
        InsufficientAvailableInterVinesPlantsError,
        InsufficientAvailableGrowBagsError,
        InsufficientAvailableGrowBagPositionsError,
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
        CarrierSpecificationTypeMismatchError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/farms/{farm_id}/vines-production/available-grow-bags", response_model=list[AvailableGrowBagPoolRead]
)
def list_available_grow_bag_pools(
    farm_id: uuid.UUID,
    destination_grow_gutter_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_READ)),
) -> list[AvailableGrowBagPoolRead]:
    """VINES-OPS-001B: narrow, read-only support for the Vines Production
    Transfer operator UI's Grow Bag specification picker and available-
    capacity display."""
    try:
        return vines_production_transfer_service.list_available_grow_bag_pools(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, destination_grow_gutter_id=destination_grow_gutter_id,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc


@router.get("/farms/{farm_id}/vines-production/placements", response_model=list[VinesProductionPlacementRead])
def list_vines_production_placements(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_READ)),
) -> list[VinesProductionPlacementRead]:
    """VINES-OPS-001B: the compact Vines Production read view -- one
    aggregated row per (Batch, Grow Gutter)."""
    try:
        return vines_production_transfer_service.list_vines_production_placements(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc


@router.get(
    "/farms/{farm_id}/vines-production/placements/{batch_id}/{gutter_id}/grow-bags",
    response_model=list[VinesProductionPlacementGrowBagRead],
)
def list_vines_production_placement_grow_bags(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    gutter_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_READ)),
) -> list[VinesProductionPlacementGrowBagRead]:
    """VINES-OPS-001B: drill-down individual Grow Bag / Grow Cube / Seed
    Tray traceability for one aggregated Vines Production placement row --
    never the default view."""
    try:
        return vines_production_transfer_service.list_vines_production_placement_grow_bags(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, gutter_id=gutter_id,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
