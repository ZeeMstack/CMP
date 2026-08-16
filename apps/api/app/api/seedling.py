import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.seedling_entry import (
    AvailableSeedlingTableRead,
    SeedlingCandidateTrayRead,
    SeedlingEntryCreate,
    SeedlingEntryRead,
)
from app.services import seedling_entry_service
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    FarmNotFoundError,
    InvalidSeedlingEntryEffectiveTimeError,
    LocationNotFoundError,
    NoCompletedGerminationHandoffError,
    SeedlingEntryAlreadyExistsError,
    SeedlingEntryCommandReusedWithDifferentPayloadError,
    SeedlingEntryPhysicalChronologyError,
    SeedlingEntryValidationError,
    SeedlingTableInvalidError,
)
from app.services.errors import (
    AssetPositionNotFoundError,
    CarrierNotFoundError,
    InactiveOccupantError,
    InactiveTargetError,
    IncompatibleOccupantTargetError,
    MovementCommandReusedWithDifferentPayloadError,
    NoOpMovementError,
    OccupantAlreadyActiveError,
    TargetNotOccupiableError,
    TargetOccupiedError,
)

router = APIRouter(tags=["seedling"])

_NOT_FOUND = (
    FarmNotFoundError,
    BatchCarrierAssignmentNotFoundError,
    LocationNotFoundError,
    CarrierNotFoundError,
    AssetPositionNotFoundError,
)
_INVALID = (
    SeedlingTableInvalidError,
    SeedlingEntryValidationError,
    NoCompletedGerminationHandoffError,
    InvalidSeedlingEntryEffectiveTimeError,
    SeedlingEntryPhysicalChronologyError,
    TargetNotOccupiableError,
    IncompatibleOccupantTargetError,
)
_CONFLICT = (
    SeedlingEntryAlreadyExistsError,
    SeedlingEntryCommandReusedWithDifferentPayloadError,
    InactiveOccupantError,
    InactiveTargetError,
    TargetOccupiedError,
    OccupantAlreadyActiveError,
    NoOpMovementError,
    MovementCommandReusedWithDifferentPayloadError,
)


@router.post(
    "/farms/{farm_id}/nursery/seedling/entries",
    response_model=SeedlingEntryRead,
    status_code=status.HTTP_201_CREATED,
)
def record_seedling_entry(
    farm_id: uuid.UUID,
    payload: SeedlingEntryCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.MOVEMENT_MANAGE)),
) -> SeedlingEntryRead:
    try:
        entry = seedling_entry_service.record_seedling_entry(
            db,
            tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            batch_carrier_assignment_id=payload.batch_carrier_assignment_id,
            destination_seedling_table_id=payload.destination_seedling_table_id,
            effective_time=payload.effective_time, reason=payload.reason,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except _INVALID as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return seedling_entry_service.describe_seedling_entry(db, entry=entry)


@router.get(
    "/farms/{farm_id}/nursery/seedling/tables/available", response_model=list[AvailableSeedlingTableRead]
)
def list_available_seedling_tables(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.LOCATION_READ)),
) -> list[AvailableSeedlingTableRead]:
    try:
        return seedling_entry_service.list_available_seedling_tables(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/nursery/seedling/trays", response_model=list[SeedlingCandidateTrayRead])
def list_seedling_candidate_trays(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_READ)),
) -> list[SeedlingCandidateTrayRead]:
    try:
        return seedling_entry_service.list_seedling_candidate_trays(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
