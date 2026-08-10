import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext, require_tenant_context
from app.schemas.movement import MovementCreate, MovementRead
from app.services import movement_service
from app.services.errors import (
    AssetCannotOccupyOwnPositionError,
    AssetNotFoundError,
    AssetPositionNotFoundError,
    CarrierNotFoundError,
    FarmNotFoundError,
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
    ctx: TenantContext = Depends(require_tenant_context),
) -> MovementRead:
    try:
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
            InvalidEffectiveTimeError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return MovementRead.from_model(movement)
