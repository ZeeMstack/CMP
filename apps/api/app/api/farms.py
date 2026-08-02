import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.dev_auth import DevTenantContext, require_dev_tenant_context
from app.schemas.farm import FarmCreate, FarmRead
from app.services import farm_service
from app.services.errors import DuplicateFarmCodeError, FarmNotFoundError

router = APIRouter(tags=["farms"])


@router.post("/farms", response_model=FarmRead, status_code=status.HTTP_201_CREATED)
def create_farm(
    payload: FarmCreate,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> FarmRead:
    try:
        farm = farm_service.create_farm(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            code=payload.code,
            name=payload.name,
            country_code=payload.country_code,
            city_region=payload.city_region,
            timezone=payload.timezone,
        )
    except DuplicateFarmCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Farm code already exists in this tenant"
        ) from exc
    return FarmRead.model_validate(farm)


@router.get("/farms/{farm_id}", response_model=FarmRead)
def get_farm(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> FarmRead:
    try:
        farm = farm_service.get_farm(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
    return FarmRead.model_validate(farm)


@router.get("/farms", response_model=list[FarmRead])
def list_farms(
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> list[FarmRead]:
    farms = farm_service.list_farms(db, tenant_id=ctx.tenant_id)
    return [FarmRead.model_validate(farm) for farm in farms]
