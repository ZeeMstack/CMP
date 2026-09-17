import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.nutrient_mix import NutrientMixCreate, NutrientMixInputRead, NutrientMixRead
from app.services import nutrient_mix_service
from app.services.errors import (
    InventoryItemNotFoundError,
    NutrientMixNotFoundError,
    NutrientMixValidationError,
    ReservoirNotFoundError,
    UnitOfMeasureKindMismatchError,
    UnitOfMeasureNotFoundError,
)

router = APIRouter(tags=["nutrient-mixes"])


@router.post(
    "/farms/{farm_id}/reservoirs/{reservoir_id}/nutrient-mixes", response_model=NutrientMixRead,
    status_code=status.HTTP_201_CREATED,
)
def record_mix(
    farm_id: uuid.UUID,
    reservoir_id: uuid.UUID,
    payload: NutrientMixCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_OPERATIONS_MANAGE)),
) -> NutrientMixRead:
    try:
        return nutrient_mix_service.record_mix(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, reservoir_id=reservoir_id,
            nutrient_recipe_version_id=payload.nutrient_recipe_version_id, effective_at=payload.effective_at,
            target_volume=payload.target_volume, target_volume_uom_id=payload.target_volume_uom_id,
            actual_volume=payload.actual_volume, actual_volume_uom_id=payload.actual_volume_uom_id,
            notes=payload.notes, client_command_id=payload.client_command_id,
            inputs=[i.model_dump() for i in payload.inputs],
        )
    except ReservoirNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservoir not found") from exc
    except InventoryItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inventory item not found") from exc
    except (UnitOfMeasureNotFoundError, UnitOfMeasureKindMismatchError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except NutrientMixValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/reservoirs/{reservoir_id}/nutrient-mixes", response_model=list[NutrientMixRead])
def list_mixes(
    reservoir_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_OPERATIONS_READ)),
) -> list[NutrientMixRead]:
    return nutrient_mix_service.list_mixes_for_reservoir(db, tenant_id=ctx.tenant_id, reservoir_id=reservoir_id)


@router.get("/farms/{farm_id}/nutrient-mixes", response_model=list[NutrientMixRead])
def list_mixes_for_farm(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_OPERATIONS_READ)),
) -> list[NutrientMixRead]:
    return nutrient_mix_service.list_mixes_for_farm(db, tenant_id=ctx.tenant_id, farm_id=farm_id)


@router.get("/nutrient-mixes/{nutrient_mix_id}", response_model=NutrientMixRead)
def get_mix(
    nutrient_mix_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_OPERATIONS_READ)),
) -> NutrientMixRead:
    try:
        return nutrient_mix_service.get_mix(db, tenant_id=ctx.tenant_id, nutrient_mix_id=nutrient_mix_id)
    except NutrientMixNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nutrient mix not found") from exc


@router.get("/nutrient-mixes/{nutrient_mix_id}/inputs", response_model=list[NutrientMixInputRead])
def list_mix_inputs(
    nutrient_mix_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.NUTRIENT_OPERATIONS_READ)),
) -> list[NutrientMixInputRead]:
    try:
        return nutrient_mix_service.list_mix_inputs(db, tenant_id=ctx.tenant_id, nutrient_mix_id=nutrient_mix_id)
    except NutrientMixNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nutrient mix not found") from exc
