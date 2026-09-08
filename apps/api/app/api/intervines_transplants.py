import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.intervines_transplant import (
    AvailableGrowCubePoolRead,
    IntervinesPlacementGrowCubeRead,
    IntervinesPlacementRead,
    IntervinesTransplantCreate,
    IntervinesTransplantRead,
)
from app.services import intervines_transplant_service
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
    InsufficientAvailableGrowCubesError,
    IntervinesTransplantReplayStateConflictError,
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

router = APIRouter(tags=["intervines-transplants"])


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/intervines-transplants",
    response_model=IntervinesTransplantRead,
    status_code=status.HTTP_201_CREATED,
)
def record_intervines_transplant(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: IntervinesTransplantCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_MANAGE)),
) -> IntervinesTransplantRead:
    """VINES-OPS-001A: one atomic operator command -- biological Transplant
    of the requested plant quantity from one Seedling source Tray onto a
    server-allocated pool of Grow Cube(s), then physical placement of every
    allocated Grow Cube onto the selected InterVines Table, one transaction.
    Gated by `TRANSPLANT_MANAGE` alone, mirroring `intersalads_transplants.
    record_intersalads_transplant`'s own identical rationale: the physical
    placement is an inseparable side effect of the approved biological
    Transplant workflow."""
    try:
        return intervines_transplant_service.record_intervines_transplant(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            batch_id=batch_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            note=payload.note,
            source_assignment_id=payload.source_assignment_id,
            plant_count=payload.plant_count,
            destination_location_id=payload.destination_location_id,
            grow_cube_specification_id=payload.grow_cube_specification_id,
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
        IntervinesTransplantReplayStateConflictError,
        InsufficientAvailableGrowCubesError,
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
    "/farms/{farm_id}/nursery/intervines/available-grow-cubes", response_model=list[AvailableGrowCubePoolRead]
)
def list_available_grow_cube_pools(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_READ)),
) -> list[AvailableGrowCubePoolRead]:
    """VINES-OPS-001A: narrow, read-only support for the InterVines
    Transplant operator UI's Grow Cube specification picker and available-
    count display."""
    try:
        return intervines_transplant_service.list_available_grow_cube_pools(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc


@router.get("/farms/{farm_id}/nursery/intervines/placements", response_model=list[IntervinesPlacementRead])
def list_intervines_placements(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_READ)),
) -> list[IntervinesPlacementRead]:
    """VINES-OPS-001A: the compact InterVines read view -- one aggregated
    row per (Batch, InterVines Table)."""
    try:
        return intervines_transplant_service.list_intervines_placements(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc


@router.get(
    "/farms/{farm_id}/nursery/intervines/placements/{batch_id}/{table_id}/grow-cubes",
    response_model=list[IntervinesPlacementGrowCubeRead],
)
def list_intervines_placement_grow_cubes(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    table_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_READ)),
) -> list[IntervinesPlacementGrowCubeRead]:
    """VINES-OPS-001A: drill-down individual Grow Cube traceability for one
    aggregated InterVines placement row -- never the default view."""
    try:
        return intervines_transplant_service.list_intervines_placement_grow_cubes(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, table_id=table_id
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
