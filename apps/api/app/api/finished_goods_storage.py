import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.finished_goods_storage import (
    FinishedGoodsPlacementRead,
    FinishedGoodsStorageMovementCreate,
    FinishedGoodsStorageMovementRead,
    LocationInventoryRead,
)
from app.services import finished_goods_storage_service
from app.services.errors import (
    FarmNotFoundError,
    FinishedGoodsLotNotFoundError,
    InactiveDestinationLocationError,
    IneligibleStorageLocationError,
    InsufficientStorageLocationBalanceError,
    InsufficientUnplacedQuantityError,
    InvalidStorageMovementEffectiveTimeError,
    StorageCommandReusedWithDifferentPayloadError,
    StorageLocationNotFoundError,
    StorageMovementValidationError,
)

router = APIRouter(tags=["finished-goods-storage"])


@router.post(
    "/farms/{farm_id}/finished-goods-storage-movements",
    response_model=FinishedGoodsStorageMovementRead,
    status_code=status.HTTP_201_CREATED,
)
def record_movement(
    farm_id: uuid.UUID,
    payload: FinishedGoodsStorageMovementCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FINISHED_GOODS_STORAGE_MANAGE)),
) -> FinishedGoodsStorageMovementRead:
    try:
        movement = finished_goods_storage_service.record_movement(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            finished_goods_lot_id=payload.finished_goods_lot_id,
            movement_kind=payload.movement_kind,
            source_location_id=payload.source_location_id,
            destination_location_id=payload.destination_location_id,
            moved_weight_kg=payload.moved_weight_kg,
            moved_package_count=payload.moved_package_count,
            note=payload.note,
        )
    except (FarmNotFoundError, FinishedGoodsLotNotFoundError, StorageLocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        StorageCommandReusedWithDifferentPayloadError,
        InsufficientUnplacedQuantityError,
        InsufficientStorageLocationBalanceError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        StorageMovementValidationError,
        InvalidStorageMovementEffectiveTimeError,
        IneligibleStorageLocationError,
        InactiveDestinationLocationError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return FinishedGoodsStorageMovementRead.model_validate(movement, from_attributes=True)


@router.get(
    "/farms/{farm_id}/finished-goods-lots/{finished_goods_lot_id}/storage-movements",
    response_model=list[FinishedGoodsStorageMovementRead],
)
def get_storage_movements(
    farm_id: uuid.UUID,
    finished_goods_lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FINISHED_GOODS_STORAGE_READ)),
) -> list[FinishedGoodsStorageMovementRead]:
    try:
        return finished_goods_storage_service.get_movement_history(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, finished_goods_lot_id=finished_goods_lot_id
        )
    except (FarmNotFoundError, FinishedGoodsLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/finished-goods-lots/{finished_goods_lot_id}/placements",
    response_model=FinishedGoodsPlacementRead,
)
def get_placement(
    farm_id: uuid.UUID,
    finished_goods_lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FINISHED_GOODS_STORAGE_READ)),
) -> FinishedGoodsPlacementRead:
    try:
        return finished_goods_storage_service.get_placement(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, finished_goods_lot_id=finished_goods_lot_id
        )
    except (FarmNotFoundError, FinishedGoodsLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/locations/{location_id}/finished-goods-inventory",
    response_model=LocationInventoryRead,
)
def get_location_inventory(
    farm_id: uuid.UUID,
    location_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FINISHED_GOODS_STORAGE_READ)),
) -> LocationInventoryRead:
    try:
        return finished_goods_storage_service.get_location_inventory(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, location_id=location_id
        )
    except (FarmNotFoundError, StorageLocationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except IneligibleStorageLocationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
