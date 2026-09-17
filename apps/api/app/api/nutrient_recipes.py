import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.nutrient_recipe import (
    NutrientRecipeComponentCreate,
    NutrientRecipeComponentRead,
    NutrientRecipeCreate,
    NutrientRecipeRead,
    NutrientRecipeVersionCreate,
    NutrientRecipeVersionLifecycleCommand,
    NutrientRecipeVersionRead,
)
from app.services import nutrient_recipe_service
from app.services.errors import (
    CropNotFoundError,
    DuplicateNutrientRecipeCodeError,
    InventoryItemNotFoundError,
    NutrientRecipeNotFoundError,
    NutrientRecipeVersionCommandReusedWithDifferentPayloadError,
    NutrientRecipeVersionNotDraftError,
    NutrientRecipeVersionNotFoundError,
    ProductionSystemNotFoundError,
    UnitOfMeasureNotFoundError,
    VarietyCropMismatchError,
)

router = APIRouter(tags=["nutrient-recipes"])


@router.post("/nutrient-recipes", response_model=NutrientRecipeRead, status_code=status.HTTP_201_CREATED)
def register_recipe(
    payload: NutrientRecipeCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_RECIPE_MANAGE)),
) -> NutrientRecipeRead:
    try:
        return nutrient_recipe_service.register_recipe(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, code=payload.code, name=payload.name,
            crop_id=payload.crop_id, variety_id=payload.variety_id, production_system_id=payload.production_system_id,
        )
    except (CropNotFoundError, ProductionSystemNotFoundError, VarietyCropMismatchError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except DuplicateNutrientRecipeCodeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recipe code already exists") from exc


@router.get("/nutrient-recipes", response_model=list[NutrientRecipeRead])
def list_recipes(
    db: Session = Depends(get_db), ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_RECIPE_READ)),
) -> list[NutrientRecipeRead]:
    return nutrient_recipe_service.list_recipes(db, tenant_id=ctx.tenant_id)


@router.get("/nutrient-recipes/{nutrient_recipe_id}", response_model=NutrientRecipeRead)
def get_recipe(
    nutrient_recipe_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_RECIPE_READ)),
) -> NutrientRecipeRead:
    try:
        return nutrient_recipe_service.get_recipe(db, tenant_id=ctx.tenant_id, nutrient_recipe_id=nutrient_recipe_id)
    except NutrientRecipeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found") from exc


@router.post(
    "/nutrient-recipes/{nutrient_recipe_id}/versions", response_model=NutrientRecipeVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_draft_version(
    nutrient_recipe_id: uuid.UUID,
    payload: NutrientRecipeVersionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_RECIPE_MANAGE)),
) -> NutrientRecipeVersionRead:
    try:
        return nutrient_recipe_service.create_draft_version(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, nutrient_recipe_id=nutrient_recipe_id,
            client_command_id=payload.client_command_id, reason=payload.reason, target_ec=payload.target_ec,
            target_ph=payload.target_ph, instructions=payload.instructions, effective_date=payload.effective_date,
        )
    except NutrientRecipeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found") from exc
    except NutrientRecipeVersionCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/nutrient-recipes/{nutrient_recipe_id}/versions", response_model=list[NutrientRecipeVersionRead])
def list_versions(
    nutrient_recipe_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_RECIPE_READ)),
) -> list[NutrientRecipeVersionRead]:
    return nutrient_recipe_service.list_versions(db, tenant_id=ctx.tenant_id, nutrient_recipe_id=nutrient_recipe_id)


@router.get("/nutrient-recipe-versions/{version_id}", response_model=NutrientRecipeVersionRead)
def get_version(
    version_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_RECIPE_READ)),
) -> NutrientRecipeVersionRead:
    try:
        return nutrient_recipe_service.get_version(db, tenant_id=ctx.tenant_id, version_id=version_id)
    except NutrientRecipeVersionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe version not found") from exc


@router.post("/nutrient-recipe-versions/{version_id}/activate", response_model=NutrientRecipeVersionRead)
def activate_version(
    version_id: uuid.UUID,
    payload: NutrientRecipeVersionLifecycleCommand,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_RECIPE_MANAGE)),
) -> NutrientRecipeVersionRead:
    try:
        return nutrient_recipe_service.activate_version(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, version_id=version_id,
            client_command_id=payload.client_command_id,
        )
    except NutrientRecipeVersionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe version not found") from exc
    except NutrientRecipeVersionNotDraftError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Version is not in draft state") from exc
    except NutrientRecipeVersionCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/nutrient-recipe-versions/{version_id}/retire", response_model=NutrientRecipeVersionRead)
def retire_version(
    version_id: uuid.UUID,
    payload: NutrientRecipeVersionLifecycleCommand,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_RECIPE_MANAGE)),
) -> NutrientRecipeVersionRead:
    try:
        return nutrient_recipe_service.retire_version(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, version_id=version_id,
            client_command_id=payload.client_command_id,
        )
    except NutrientRecipeVersionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe version not found") from exc
    except NutrientRecipeVersionNotDraftError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Version is not active") from exc
    except NutrientRecipeVersionCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/nutrient-recipe-versions/{version_id}/components", response_model=NutrientRecipeComponentRead,
    status_code=status.HTTP_201_CREATED,
)
def add_component(
    version_id: uuid.UUID,
    payload: NutrientRecipeComponentCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_RECIPE_MANAGE)),
) -> NutrientRecipeComponentRead:
    try:
        return nutrient_recipe_service.add_component(
            db, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id, version_id=version_id,
            inventory_item_id=payload.inventory_item_id, component_label=payload.component_label,
            target_quantity=payload.target_quantity, target_quantity_uom_id=payload.target_quantity_uom_id,
            basis_volume=payload.basis_volume, basis_volume_uom_id=payload.basis_volume_uom_id,
            sequence_number=payload.sequence_number, instructions=payload.instructions,
        )
    except NutrientRecipeVersionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe version not found") from exc
    except NutrientRecipeVersionNotDraftError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Components may only be added to a DRAFT version") from exc
    except (UnitOfMeasureNotFoundError, InventoryItemNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/nutrient-recipe-versions/{version_id}/components", response_model=list[NutrientRecipeComponentRead])
def list_components(
    version_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_RECIPE_READ)),
) -> list[NutrientRecipeComponentRead]:
    return nutrient_recipe_service.list_components(db, tenant_id=ctx.tenant_id, version_id=version_id)
