import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.movement import MovementCreate, MovementRead
from app.services import germination_service, movement_service
from app.services.errors import (
    AssetCannotOccupyOwnPositionError,
    AssetNotFoundError,
    AssetPositionNotFoundError,
    CarrierNotFoundError,
    FarmNotFoundError,
    GerminationPlacementMustUseGerminationOperationError,
    InactiveOccupantError,
    InactiveTargetError,
    IncompatibleOccupantTargetError,
    InvalidEffectiveTimeError,
    LocationNotFoundError,
    MovementCommandReusedWithDifferentPayloadError,
    NoOpMovementError,
    NothingToRemoveError,
    OccupantAlreadyActiveError,
    TargetNotOccupiableError,
    TargetOccupiedError,
)

router = APIRouter(tags=["movements"])


@router.post("/farms/{farm_id}/movements", response_model=MovementRead, status_code=status.HTTP_201_CREATED)
def create_movement(
    farm_id: uuid.UUID,
    payload: MovementCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.MOVEMENT_MANAGE)),
) -> MovementRead:
    try:
        # PILOT-UX-001B section 5: a Seed Tray Carrier may only reach a
        # Germination Trolley AssetPosition (Level or legacy Slot) through
        # the Germination domain operation, never this generic endpoint --
        # `movement_service.execute_movement` itself stays fully generic
        # and is not given any Germination-specific knowledge. Checked here
        # only; `germination_service.place_tray` calls `execute_movement`
        # directly and is therefore unaffected by this guard.
        germination_service.reject_generic_bypass_for_seed_tray_placement(
            db,
            occupant_kind=payload.occupant.kind,
            occupant_id=payload.occupant.id,
            destination_kind=payload.destination.kind if payload.destination else None,
            destination_id=payload.destination.id if payload.destination else None,
        )
        movement = movement_service.execute_movement(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            occupant_kind=payload.occupant.kind,
            occupant_id=payload.occupant.id,
            destination_kind=payload.destination.kind if payload.destination else None,
            destination_id=payload.destination.id if payload.destination else None,
            reason=payload.reason,
        )
    except (FarmNotFoundError, AssetNotFoundError, CarrierNotFoundError, LocationNotFoundError, AssetPositionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (InactiveOccupantError, InactiveTargetError, TargetOccupiedError, OccupantAlreadyActiveError,
            NoOpMovementError, NothingToRemoveError, MovementCommandReusedWithDifferentPayloadError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (TargetNotOccupiableError, IncompatibleOccupantTargetError, AssetCannotOccupyOwnPositionError,
            InvalidEffectiveTimeError, GerminationPlacementMustUseGerminationOperationError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return MovementRead.from_model(movement)
