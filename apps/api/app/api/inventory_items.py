import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.inventory_item import (
    InventoryItemCreate,
    InventoryItemDeactivate,
    InventoryItemReactivate,
    InventoryItemRead,
    InventoryItemUpdate,
)
from app.services import inventory_item_service
from app.services.errors import (
    DuplicateInventoryItemCodeError,
    InventoryCategoryInactiveForAssignmentError,
    InventoryCategoryNotInTenantError,
    InventoryItemCommandReusedWithDifferentPayloadError,
    InventoryItemDeactivationReusedWithDifferentPayloadError,
    InventoryItemNotActiveError,
    InventoryItemNotFoundError,
    InventoryItemNotInactiveError,
    InventoryItemReactivationReusedWithDifferentPayloadError,
    InventoryItemUpdateReusedWithDifferentPayloadError,
    UnitOfMeasureNotFoundError,
)

router = APIRouter(tags=["inventory-items"])


@router.post("/inventory-items", response_model=InventoryItemRead, status_code=status.HTTP_201_CREATED)
def create_inventory_item(
    payload: InventoryItemCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_MANAGE)),
) -> InventoryItemRead:
    try:
        item = inventory_item_service.register_inventory_item(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            code=payload.code, name=payload.name, category_id=payload.category_id,
            base_uom_id=payload.base_uom_id, lot_tracking_required=payload.lot_tracking_required,
            expiry_tracking_required=payload.expiry_tracking_required,
            qc_release_required=payload.qc_release_required,
        )
    except DuplicateInventoryItemCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Inventory item code already exists in this tenant"
        ) from exc
    except InventoryItemCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except InventoryCategoryNotInTenantError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown inventory category") from exc
    except InventoryCategoryInactiveForAssignmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Inventory category is not active"
        ) from exc
    except UnitOfMeasureNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown unit of measure") from exc
    return InventoryItemRead.model_validate(item)


@router.get("/inventory-items", response_model=list[InventoryItemRead])
def list_inventory_items(
    status_filter: str | None = Query(default=None, alias="status"),
    category_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_READ)),
) -> list[InventoryItemRead]:
    items = inventory_item_service.list_inventory_items(
        db, tenant_id=ctx.tenant_id, status=status_filter, category_id=category_id
    )
    return [InventoryItemRead.model_validate(i) for i in items]


@router.get("/inventory-items/{item_id}", response_model=InventoryItemRead)
def get_inventory_item(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_READ)),
) -> InventoryItemRead:
    try:
        item = inventory_item_service.get_inventory_item(db, tenant_id=ctx.tenant_id, item_id=item_id)
    except InventoryItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found") from exc
    return InventoryItemRead.model_validate(item)


@router.post("/inventory-items/{item_id}/update", response_model=InventoryItemRead)
def update_inventory_item(
    item_id: uuid.UUID,
    payload: InventoryItemUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_MANAGE)),
) -> InventoryItemRead:
    try:
        item = inventory_item_service.update_inventory_item(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            item_id=item_id, name=payload.name, category_id=payload.category_id,
            base_uom_id=payload.base_uom_id, lot_tracking_required=payload.lot_tracking_required,
            expiry_tracking_required=payload.expiry_tracking_required,
            qc_release_required=payload.qc_release_required,
        )
    except InventoryItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found") from exc
    except InventoryItemUpdateReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except InventoryCategoryNotInTenantError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown inventory category") from exc
    except InventoryCategoryInactiveForAssignmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Inventory category is not active"
        ) from exc
    except UnitOfMeasureNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown unit of measure") from exc
    return InventoryItemRead.model_validate(item)


@router.post("/inventory-items/{item_id}/deactivate", response_model=InventoryItemRead)
def deactivate_inventory_item(
    item_id: uuid.UUID,
    payload: InventoryItemDeactivate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_MANAGE)),
) -> InventoryItemRead:
    try:
        item = inventory_item_service.deactivate_inventory_item(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            item_id=item_id,
        )
    except InventoryItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found") from exc
    except (InventoryItemNotActiveError, InventoryItemDeactivationReusedWithDifferentPayloadError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryItemRead.model_validate(item)


@router.post("/inventory-items/{item_id}/reactivate", response_model=InventoryItemRead)
def reactivate_inventory_item(
    item_id: uuid.UUID,
    payload: InventoryItemReactivate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_MANAGE)),
) -> InventoryItemRead:
    try:
        item = inventory_item_service.reactivate_inventory_item(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            item_id=item_id,
        )
    except InventoryItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found") from exc
    except (InventoryItemNotInactiveError, InventoryItemReactivationReusedWithDifferentPayloadError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryItemRead.model_validate(item)
