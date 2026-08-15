import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.germination import (
    AvailableTrolleyRead,
    GerminationChamberAvailabilityRead,
    GerminationTrayRead,
    PlaceTrayCreate,
    PlaceTrolleyCreate,
    TrayPlacementRead,
    TrolleyPlacementRead,
    TrolleySlotAvailabilityRead,
)
from app.services import germination_service
from app.services.errors import (
    AssetNotFoundError,
    AssetPositionNotFoundError,
    CarrierNotFoundError,
    FarmNotFoundError,
    GerminationChamberInvalidError,
    GerminationTraySlotInvalidError,
    GerminationTrolleyInvalidError,
    InactiveOccupantError,
    InactiveTargetError,
    IncompatibleOccupantTargetError,
    InvalidEffectiveTimeError,
    LocationNotFoundError,
    MovementCommandReusedWithDifferentPayloadError,
    NoOpMovementError,
    OccupantAlreadyActiveError,
    TargetNotOccupiableError,
    TargetOccupiedError,
    TrayNotSownError,
    TrolleyNotInGerminationError,
)

router = APIRouter(tags=["germination"])

_NOT_FOUND = (
    FarmNotFoundError,
    CarrierNotFoundError,
    AssetNotFoundError,
    AssetPositionNotFoundError,
    LocationNotFoundError,
)
_INVALID = (
    GerminationChamberInvalidError,
    GerminationTrolleyInvalidError,
    GerminationTraySlotInvalidError,
    TrayNotSownError,
    TrolleyNotInGerminationError,
    TargetNotOccupiableError,
    IncompatibleOccupantTargetError,
    InvalidEffectiveTimeError,
)
_CONFLICT = (
    InactiveOccupantError,
    InactiveTargetError,
    TargetOccupiedError,
    OccupantAlreadyActiveError,
    NoOpMovementError,
    MovementCommandReusedWithDifferentPayloadError,
)


@router.post(
    "/farms/{farm_id}/germination/trolley-placements",
    response_model=TrolleyPlacementRead,
    status_code=status.HTTP_201_CREATED,
)
def place_trolley(
    farm_id: uuid.UUID,
    payload: PlaceTrolleyCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.MOVEMENT_MANAGE)),
) -> TrolleyPlacementRead:
    try:
        movement = germination_service.place_trolley_in_chamber(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            trolley_id=payload.trolley_id,
            chamber_id=payload.chamber_id,
            effective_time=payload.effective_time,
            reason=payload.reason,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except _INVALID as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return germination_service.describe_trolley_placement(db, movement=movement)


@router.post(
    "/farms/{farm_id}/germination/tray-placements",
    response_model=TrayPlacementRead,
    status_code=status.HTTP_201_CREATED,
)
def place_tray(
    farm_id: uuid.UUID,
    payload: PlaceTrayCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.MOVEMENT_MANAGE)),
) -> TrayPlacementRead:
    try:
        movement = germination_service.place_tray_in_slot(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            tray_id=payload.tray_id,
            trolley_id=payload.trolley_id,
            slot_id=payload.slot_id,
            effective_time=payload.effective_time,
            reason=payload.reason,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except _INVALID as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return germination_service.describe_tray_placement(db, tenant_id=ctx.tenant_id, farm_id=farm_id, movement=movement)


@router.get(
    "/farms/{farm_id}/germination/chambers/available", response_model=list[GerminationChamberAvailabilityRead]
)
def list_available_chambers(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_READ)),
) -> list[GerminationChamberAvailabilityRead]:
    try:
        return germination_service.list_available_chambers(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/germination/trolleys/available", response_model=list[AvailableTrolleyRead])
def list_available_trolleys(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.ASSET_READ)),
) -> list[AvailableTrolleyRead]:
    try:
        return germination_service.list_available_trolleys(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/germination/trolleys/{trolley_id}/slots",
    response_model=list[TrolleySlotAvailabilityRead],
)
def list_trolley_slots(
    farm_id: uuid.UUID,
    trolley_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.ASSET_READ)),
) -> list[TrolleySlotAvailabilityRead]:
    try:
        return germination_service.list_trolley_slots(db, tenant_id=ctx.tenant_id, farm_id=farm_id, trolley_id=trolley_id)
    except (FarmNotFoundError, AssetNotFoundError, GerminationTrolleyInvalidError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/germination/trays", response_model=list[GerminationTrayRead])
def list_germination_trays(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_READ)),
) -> list[GerminationTrayRead]:
    try:
        return germination_service.list_germination_trays(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
