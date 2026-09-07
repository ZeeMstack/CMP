import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.inventory_item_seed_profile import (
    InventoryItemSeedProfileCreate,
    InventoryItemSeedProfileRead,
    InventoryItemSeedProfileRemove,
    InventoryItemSeedProfileUpdate,
)
from app.services import inventory_item_seed_profile_service
from app.services.errors import (
    CropNotFoundError,
    InventoryItemNotFoundError,
    InventoryItemSeedProfileAlreadyExistsError,
    InventoryItemSeedProfileCommandReusedWithDifferentPayloadError,
    InventoryItemSeedProfileCreationBlockedError,
    InventoryItemSeedProfileNotFoundError,
    InventoryItemSeedProfileStructurallyLockedError,
    InventoryItemSeedProfileUpdateReusedWithDifferentPayloadError,
    VarietyNotFoundError,
)

router = APIRouter(tags=["inventory-item-seed-profiles"])


@router.post(
    "/inventory-item-seed-profiles", response_model=InventoryItemSeedProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_seed_profile(
    payload: InventoryItemSeedProfileCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_MANAGE)),
) -> InventoryItemSeedProfileRead:
    try:
        profile = inventory_item_seed_profile_service.register_seed_profile(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            inventory_item_id=payload.inventory_item_id, crop_id=payload.crop_id, variety_id=payload.variety_id,
        )
    except (InventoryItemNotFoundError, CropNotFoundError, VarietyNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown reference") from exc
    except InventoryItemSeedProfileCreationBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this item already has posted receipt history and never had Seed Details",
        ) from exc
    except InventoryItemSeedProfileAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Seed Details already exist for this item") from exc
    except InventoryItemSeedProfileCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    return InventoryItemSeedProfileRead.model_validate(profile)


@router.get("/inventory-item-seed-profiles/{profile_id}", response_model=InventoryItemSeedProfileRead)
def get_seed_profile(
    profile_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_READ)),
) -> InventoryItemSeedProfileRead:
    try:
        profile = inventory_item_seed_profile_service.get_seed_profile(
            db, tenant_id=ctx.tenant_id, profile_id=profile_id
        )
    except InventoryItemSeedProfileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seed Details not found") from exc
    return InventoryItemSeedProfileRead.model_validate(profile)


@router.get(
    "/inventory-items/{item_id}/seed-profile", response_model=InventoryItemSeedProfileRead | None
)
def get_seed_profile_for_item(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_READ)),
) -> InventoryItemSeedProfileRead | None:
    profile = inventory_item_seed_profile_service.get_seed_profile_for_item(
        db, tenant_id=ctx.tenant_id, inventory_item_id=item_id
    )
    return InventoryItemSeedProfileRead.model_validate(profile) if profile is not None else None


@router.post("/inventory-item-seed-profiles/{profile_id}/update", response_model=InventoryItemSeedProfileRead)
def update_seed_profile(
    profile_id: uuid.UUID,
    payload: InventoryItemSeedProfileUpdate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_MANAGE)),
) -> InventoryItemSeedProfileRead:
    try:
        profile = inventory_item_seed_profile_service.update_seed_profile(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            profile_id=profile_id, crop_id=payload.crop_id, variety_id=payload.variety_id,
        )
    except InventoryItemSeedProfileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seed Details not found") from exc
    except InventoryItemSeedProfileUpdateReusedWithDifferentPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="client_command_id already used with a different payload",
        ) from exc
    except InventoryItemSeedProfileStructurallyLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Seed Details are structurally locked once the item has any posted Goods Receipt",
        ) from exc
    except (CropNotFoundError, VarietyNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown reference") from exc
    return InventoryItemSeedProfileRead.model_validate(profile)


@router.post("/inventory-item-seed-profiles/{profile_id}/remove", response_model=dict)
def remove_seed_profile(
    profile_id: uuid.UUID,
    payload: InventoryItemSeedProfileRemove,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.INVENTORY_ITEM_MANAGE)),
) -> dict:
    # Matches this codebase's own client-layer convention of every mutation
    # returning a JSON body (never a bare 204) -- see apps/web/lib/api/
    # client.ts's postJson, which always parses a response body.
    try:
        inventory_item_seed_profile_service.remove_seed_profile(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, client_command_id=payload.client_command_id,
            profile_id=profile_id,
        )
    except InventoryItemSeedProfileStructurallyLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Seed Details are structurally locked once the item has any posted Goods Receipt",
        ) from exc
    return {"removed": True}
