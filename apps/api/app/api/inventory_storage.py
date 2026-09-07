import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.inventory_storage import (
    CohortStorageBreakdownRead,
    InventoryPutawayCreate,
    InventoryStorageMovementRead,
    InventoryStorageTransferCreate,
    ItemStorageBreakdownRead,
    NotPutAwayQueueEntryRead,
    StorageBucketRead,
)
from app.services import inventory_storage_service
from app.services.errors import (
    IneligibleStorageBinError,
    InactiveStorageBinError,
    InsufficientNotPutAwayQuantityError,
    InsufficientStorageBinBalanceError,
    InventoryStorageCommandReusedWithDifferentPayloadError,
    StorageBinNotFoundError,
    StorageBinsMustDifferError,
)
from app.services.errors import InventoryQuantityCohortNotFoundError

router = APIRouter(tags=["inventory-storage"])


@router.post(
    "/farms/{farm_id}/inventory-putaways", response_model=InventoryStorageMovementRead,
    status_code=status.HTTP_201_CREATED,
)
def record_putaway(
    farm_id: uuid.UUID,
    payload: InventoryPutawayCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_CUSTODY_MANAGE)),
) -> InventoryStorageMovementRead:
    try:
        movement = inventory_storage_service.record_putaway(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, cohort_id=payload.inventory_quantity_cohort_id,
            destination_location_id=payload.destination_location_id, quantity=payload.quantity,
            effective_time=payload.effective_time, note=payload.note,
        )
    except InventoryQuantityCohortNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cohort not found") from exc
    except StorageBinNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store bin not found") from exc
    except InventoryStorageCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="client_command_id already used with a different payload"
        ) from exc
    except IneligibleStorageBinError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InactiveStorageBinError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InsufficientNotPutAwayQuantityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryStorageMovementRead.model_validate(movement, from_attributes=True)


@router.post(
    "/farms/{farm_id}/inventory-storage-transfers", response_model=InventoryStorageMovementRead,
    status_code=status.HTTP_201_CREATED,
)
def record_transfer(
    farm_id: uuid.UUID,
    payload: InventoryStorageTransferCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_CUSTODY_MANAGE)),
) -> InventoryStorageMovementRead:
    try:
        movement = inventory_storage_service.record_transfer(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, cohort_id=payload.inventory_quantity_cohort_id,
            source_location_id=payload.source_location_id, destination_location_id=payload.destination_location_id,
            quantity=payload.quantity, effective_time=payload.effective_time, note=payload.note,
        )
    except InventoryQuantityCohortNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cohort not found") from exc
    except StorageBinNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store bin not found") from exc
    except InventoryStorageCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="client_command_id already used with a different payload"
        ) from exc
    except StorageBinsMustDifferError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except IneligibleStorageBinError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except InactiveStorageBinError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InsufficientStorageBinBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryStorageMovementRead.model_validate(movement, from_attributes=True)


@router.get("/inventory-not-put-away-queue", response_model=list[NotPutAwayQueueEntryRead])
def get_not_put_away_queue(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> list[NotPutAwayQueueEntryRead]:
    rows = inventory_storage_service.list_not_put_away_queue(db, tenant_id=ctx.tenant_id)
    return [NotPutAwayQueueEntryRead(**row) for row in rows]


@router.get(
    "/inventory-quantity-cohorts/{cohort_id}/storage-breakdown", response_model=CohortStorageBreakdownRead
)
def get_cohort_storage_breakdown(
    cohort_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> CohortStorageBreakdownRead:
    buckets = inventory_storage_service.get_cohort_bucket_breakdown(db, tenant_id=ctx.tenant_id, cohort_id=cohort_id)
    not_put_away = next((b["balance"] for b in buckets if b["location_id"] is None), 0)
    return CohortStorageBreakdownRead(
        inventory_quantity_cohort_id=cohort_id, not_put_away_quantity=not_put_away,
        buckets=[StorageBucketRead(**b) for b in buckets],
    )


@router.get("/inventory-items/{item_id}/storage-breakdown", response_model=ItemStorageBreakdownRead)
def get_item_storage_breakdown(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_READ)),
) -> ItemStorageBreakdownRead:
    breakdown = inventory_storage_service.get_item_storage_breakdown(
        db, tenant_id=ctx.tenant_id, inventory_item_id=item_id
    )
    return ItemStorageBreakdownRead(
        inventory_item_id=item_id, not_put_away_quantity=breakdown["not_put_away_quantity"], bins=breakdown["bins"]
    )
