import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.inventory_category import (
    InventoryCategoryCreate,
    InventoryCategoryDeactivate,
    InventoryCategoryReactivate,
    InventoryCategoryRead,
    InventoryCategoryUpdate,
)
from app.services import inventory_category_service
from app.services.errors import (
    DuplicateInventoryCategoryCodeError,
    InventoryCategoryCommandReusedWithDifferentPayloadError,
    InventoryCategoryDeactivationReusedWithDifferentPayloadError,
    InventoryCategoryNotActiveError,
    InventoryCategoryNotFoundError,
    InventoryCategoryNotInactiveError,
    InventoryCategoryReactivationReusedWithDifferentPayloadError,
)

router = APIRouter(tags=["inventory-categories"])


@router.post(
    "/inventory-categories", response_model=InventoryCategoryRead, status_code=status.HTTP_201_CREATED
)
def create_inventory_category(
    payload: InventoryCategoryCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_CATEGORY_MANAGE)),
) -> InventoryCategoryRead:
    try:
        category = inventory_category_service.register_inventory_category(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            code=payload.code, name=payload.name,
        )
    except DuplicateInventoryCategoryCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Inventory category code already exists in this tenant"
        ) from exc
    except InventoryCategoryCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    return InventoryCategoryRead.model_validate(category)


@router.get("/inventory-categories", response_model=list[InventoryCategoryRead])
def list_inventory_categories(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_CATEGORY_READ)),
) -> list[InventoryCategoryRead]:
    categories = inventory_category_service.list_inventory_categories(
        db, tenant_id=ctx.tenant_id, status=status_filter
    )
    return [InventoryCategoryRead.model_validate(c) for c in categories]


@router.get("/inventory-categories/{category_id}", response_model=InventoryCategoryRead)
def get_inventory_category(
    category_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_CATEGORY_READ)),
) -> InventoryCategoryRead:
    try:
        category = inventory_category_service.get_inventory_category(
            db, tenant_id=ctx.tenant_id, category_id=category_id
        )
    except InventoryCategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory category not found") from exc
    return InventoryCategoryRead.model_validate(category)


@router.post("/inventory-categories/{category_id}/update", response_model=InventoryCategoryRead)
def update_inventory_category(
    category_id: uuid.UUID,
    payload: InventoryCategoryUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_CATEGORY_MANAGE)),
) -> InventoryCategoryRead:
    try:
        category = inventory_category_service.update_inventory_category(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            category_id=category_id, name=payload.name,
        )
    except InventoryCategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory category not found") from exc
    except InventoryCategoryCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    return InventoryCategoryRead.model_validate(category)


@router.post("/inventory-categories/{category_id}/deactivate", response_model=InventoryCategoryRead)
def deactivate_inventory_category(
    category_id: uuid.UUID,
    payload: InventoryCategoryDeactivate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_CATEGORY_MANAGE)),
) -> InventoryCategoryRead:
    try:
        category = inventory_category_service.deactivate_inventory_category(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            category_id=category_id,
        )
    except InventoryCategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory category not found") from exc
    except (
        InventoryCategoryNotActiveError,
        InventoryCategoryDeactivationReusedWithDifferentPayloadError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryCategoryRead.model_validate(category)


@router.post("/inventory-categories/{category_id}/reactivate", response_model=InventoryCategoryRead)
def reactivate_inventory_category(
    category_id: uuid.UUID,
    payload: InventoryCategoryReactivate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_CATEGORY_MANAGE)),
) -> InventoryCategoryRead:
    try:
        category = inventory_category_service.reactivate_inventory_category(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            category_id=category_id,
        )
    except InventoryCategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory category not found") from exc
    except (
        InventoryCategoryNotInactiveError,
        InventoryCategoryReactivationReusedWithDifferentPayloadError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return InventoryCategoryRead.model_validate(category)
