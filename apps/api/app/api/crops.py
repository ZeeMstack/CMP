import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.crop import CropCreate, CropRead, VarietyCreate, VarietyRead
from app.services import crop_service
from app.services.errors import (
    CropNotFoundError,
    DuplicateCropCodeError,
    DuplicateVarietyCodeError,
    VarietyNotFoundError,
)

router = APIRouter(tags=["crops"])


@router.post("/crops", response_model=CropRead, status_code=status.HTTP_201_CREATED)
def create_crop(
    payload: CropCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_MANAGE)),
) -> CropRead:
    try:
        crop = crop_service.register_crop(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            code=payload.code,
            common_name=payload.common_name,
            scientific_name=payload.scientific_name,
            crop_category=payload.crop_category,
        )
    except DuplicateCropCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Crop code already exists in this tenant"
        ) from exc
    return CropRead.model_validate(crop)


@router.get("/crops", response_model=list[CropRead])
def list_crops(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_READ)),
) -> list[CropRead]:
    crops = crop_service.list_crops(db, tenant_id=ctx.tenant_id)
    return [CropRead.model_validate(crop) for crop in crops]


@router.get("/crops/{crop_id}", response_model=CropRead)
def get_crop(
    crop_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_READ)),
) -> CropRead:
    try:
        crop = crop_service.get_crop(db, tenant_id=ctx.tenant_id, crop_id=crop_id)
    except CropNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop not found") from exc
    return CropRead.model_validate(crop)


@router.post(
    "/crops/{crop_id}/varieties", response_model=VarietyRead, status_code=status.HTTP_201_CREATED
)
def create_variety(
    crop_id: uuid.UUID,
    payload: VarietyCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_MANAGE)),
) -> VarietyRead:
    try:
        variety = crop_service.register_variety(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            crop_id=crop_id,
            code=payload.code,
            name=payload.name,
            supplier_reference=payload.supplier_reference,
        )
    except CropNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop not found") from exc
    except DuplicateVarietyCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Variety code already exists for this crop"
        ) from exc
    return VarietyRead.model_validate(variety)


@router.get("/crops/{crop_id}/varieties", response_model=list[VarietyRead])
def list_varieties(
    crop_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_READ)),
) -> list[VarietyRead]:
    try:
        varieties = crop_service.list_varieties(db, tenant_id=ctx.tenant_id, crop_id=crop_id)
    except CropNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop not found") from exc
    return [VarietyRead.model_validate(variety) for variety in varieties]


@router.get("/crops/{crop_id}/varieties/{variety_id}", response_model=VarietyRead)
def get_variety(
    crop_id: uuid.UUID,
    variety_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_READ)),
) -> VarietyRead:
    try:
        variety = crop_service.get_variety(db, tenant_id=ctx.tenant_id, crop_id=crop_id, variety_id=variety_id)
    except (CropNotFoundError, VarietyNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return VarietyRead.model_validate(variety)
