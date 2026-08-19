import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.nursery import AvailableSeedTrayRead, SowNewBatchCreate
from app.schemas.sowing_event import SowingEventRead
from app.services import nursery_service, sowing_service
from app.services.errors import (
    AmbiguousSowingWorkflowError,
    BatchAlreadySownError,
    CarrierAlreadyAssignedError,
    DuplicateBatchCodeError,
    FarmNotFoundError,
    NoSowingWorkflowFoundError,
    SeedingMachineInvalidError,
    SeedingStationInvalidError,
    SeedLotNotFoundError,
    SowingCapacityExceededError,
    SowingCommandReusedWithDifferentPayloadError,
    SowingValidationError,
    TooManySowingLinesError,
)

router = APIRouter(tags=["nursery"])


@router.post(
    "/farms/{farm_id}/nursery/sowings",
    response_model=SowingEventRead,
    status_code=status.HTTP_201_CREATED,
)
def sow_new_batch(
    farm_id: uuid.UUID,
    payload: SowNewBatchCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_MANAGE)),
) -> SowingEventRead:
    """NURSERY-OPS-001: the atomic Sowing command -- one call creates
    exactly one Crop Batch and its one Sowing Event. Gated on
    `sowing.manage` alone: this is a production/operational write, not a
    structural configuration change (Farm Setup's `location.manage`/
    `asset.manage` do not apply -- the Seeding Station/Seeding Machine are
    being USED here, not created)."""
    trays = [
        {"carrier_id": t.carrier_id, "sown_site_count": t.sown_site_count, "seeds_sown": t.seeds_sown}
        for t in payload.trays
    ]
    try:
        event = nursery_service.sow_new_batch(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            seed_lot_id=payload.seed_lot_id,
            seeding_station_id=payload.seeding_station_id,
            seeding_machine_id=payload.seeding_machine_id,
            effective_time=payload.effective_time,
            note=payload.note,
            trays=trays,
        )
    except (FarmNotFoundError, SeedLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        CarrierAlreadyAssignedError,
        SowingCommandReusedWithDifferentPayloadError,
        BatchAlreadySownError,
        DuplicateBatchCodeError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        SowingValidationError,
        SowingCapacityExceededError,
        TooManySowingLinesError,
        SeedingStationInvalidError,
        SeedingMachineInvalidError,
        NoSowingWorkflowFoundError,
        AmbiguousSowingWorkflowError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return sowing_service.get_sowing_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=event.batch_id, sowing_event_id=event.id
    )


@router.get(
    "/farms/{farm_id}/nursery/seed-trays/available", response_model=list[AvailableSeedTrayRead]
)
def list_available_seed_trays(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CARRIER_READ)),
) -> list[AvailableSeedTrayRead]:
    """Section 16: an active `seed_tray` Carrier with no active Batch-
    Carrier-Assignment. Gated on `carrier.read` (the resource actually
    being read), not a Sowing-specific permission."""
    try:
        return nursery_service.list_available_seed_trays(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
