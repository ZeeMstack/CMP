import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.inventory_item_packaging import (
    InventoryItemPackagingCreate,
    InventoryItemPackagingDeactivate,
    InventoryItemPackagingReactivate,
    InventoryItemPackagingRead,
    InventoryItemPackagingUpdate,
)
from app.services import inventory_item_packaging_service
from app.services.errors import (
    DuplicateInventoryItemPackagingCodeError,
    InventoryItemNotFoundError,
    InventoryItemPackagingCommandReusedWithDifferentPayloadError,
    InventoryItemPackagingDeactivationReusedWithDifferentPayloadError,
    InventoryItemPackagingNotActiveError,
    InventoryItemPackagingNotFoundError,
    InventoryItemPackagingNotInactiveError,
    InventoryItemPackagingReactivationReusedWithDifferentPayloadError,
    InventoryItemPackagingStructurallyLockedError,
    InventoryItemPackagingUpdateReusedWithDifferentPayloadError,
)

router = APIRouter(tags=["inventory-item-packaging"])


@router.post(
    "/inventory-item-packaging", response_model=InventoryItemPackagingRead, status_code=status.HTTP_201_CREATED
)
def create_inventory_item_packaging(
    payload: InventoryItemPackagingCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_MANAGE)),
) -> InventoryItemPackagingRead:
    try:
        packaging = inventory_item_packaging_service.register_inventory_item_packaging(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            inventory_item_id=payload.inventory_item_id, code=payload.code, display_name=payload.display_name,
            package_quantity=payload.package_quantity,
        )
    except InventoryItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown inventory item") from exc
    except DuplicateInventoryItemPackagingCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Packaging code already exists for this item"
        ) from exc
    except InventoryItemPackagingCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    return InventoryItemPackagingRead.model_validate(packaging)


@router.get("/inventory-item-packaging", response_model=list[InventoryItemPackagingRead])
def list_inventory_item_packaging(
    inventory_item_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_READ)),
) -> list[InventoryItemPackagingRead]:
    rows = inventory_item_packaging_service.list_inventory_item_packaging(
        db, tenant_id=ctx.tenant_id, inventory_item_id=inventory_item_id, status=status_filter
    )
    return [InventoryItemPackagingRead.model_validate(r) for r in rows]


@router.get("/inventory-item-packaging/{packaging_id}", response_model=InventoryItemPackagingRead)
def get_inventory_item_packaging(
    packaging_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_READ)),
) -> InventoryItemPackagingRead:
    try:
        packaging = inventory_item_packaging_service.get_inventory_item_packaging(
            db, tenant_id=ctx.tenant_id, packaging_id=packaging_id
        )
    except InventoryItemPackagingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packaging not found") from exc
    return InventoryItemPackagingRead.model_validate(packaging)


@router.post("/inventory-item-packaging/{packaging_id}/update", response_model=InventoryItemPackagingRead)
def update_inventory_item_packaging(
    packaging_id: uuid.UUID,
    payload: InventoryItemPackagingUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_MANAGE)),
) -> InventoryItemPackagingRead:
    try:
        packaging = inventory_item_packaging_service.update_inventory_item_packaging(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            packaging_id=packaging_id, display_name=payload.display_name,
            package_quantity=payload.package_quantity,
        )
    except InventoryItemPackagingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packaging not found") from exc
    except InventoryItemPackagingUpdateReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except InventoryItemPackagingStructurallyLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="package_quantity is structurally locked once referenced by a posted Goods Receipt line",
        ) from exc
    return InventoryItemPackagingRead.model_validate(packaging)


@router.post("/inventory-item-packaging/{packaging_id}/deactivate", response_model=InventoryItemPackagingRead)
def deactivate_inventory_item_packaging(
    packaging_id: uuid.UUID,
    payload: InventoryItemPackagingDeactivate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_MANAGE)),
) -> InventoryItemPackagingRead:
    try:
        packaging = inventory_item_packaging_service.deactivate_inventory_item_packaging(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            packaging_id=packaging_id,
        )
    except InventoryItemPackagingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packaging not found") from exc
    except (InventoryItemPackagingNotActiveError, InventoryItemPackagingDeactivationReusedWithDifferentPayloadError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryItemPackagingRead.model_validate(packaging)


@router.post("/inventory-item-packaging/{packaging_id}/reactivate", response_model=InventoryItemPackagingRead)
def reactivate_inventory_item_packaging(
    packaging_id: uuid.UUID,
    payload: InventoryItemPackagingReactivate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_MANAGE)),
) -> InventoryItemPackagingRead:
    try:
        packaging = inventory_item_packaging_service.reactivate_inventory_item_packaging(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            packaging_id=packaging_id,
        )
    except InventoryItemPackagingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Packaging not found") from exc
    except (
        InventoryItemPackagingNotInactiveError, InventoryItemPackagingReactivationReusedWithDifferentPayloadError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryItemPackagingRead.model_validate(packaging)
