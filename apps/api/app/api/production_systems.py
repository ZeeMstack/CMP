import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext, require_tenant_context
from app.core.permissions import Permission, require_permission
from app.schemas.production_system import ProductionSystemCreate, ProductionSystemRead
from app.services import production_system_service
from app.services.errors import DuplicateProductionSystemCodeError, ProductionSystemNotFoundError

router = APIRouter(tags=["production-systems"])


@router.post("/production-systems", response_model=ProductionSystemRead, status_code=status.HTTP_201_CREATED)
def create_production_system(
    payload: ProductionSystemCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> ProductionSystemRead:
    try:
        production_system = production_system_service.register_production_system(
            db,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
        )
    except DuplicateProductionSystemCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Production system code already exists in this tenant"
        ) from exc
    return ProductionSystemRead.model_validate(production_system)


@router.get("/production-systems", response_model=list[ProductionSystemRead])
def list_production_systems(
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PRODUCTION_SYSTEM_READ)),
) -> list[ProductionSystemRead]:
    production_systems = production_system_service.list_production_systems(db, tenant_id=ctx.tenant_id)
    return [ProductionSystemRead.model_validate(ps) for ps in production_systems]


@router.get("/production-systems/{production_system_id}", response_model=ProductionSystemRead)
def get_production_system(
    production_system_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PRODUCTION_SYSTEM_READ)),
) -> ProductionSystemRead:
    try:
        production_system = production_system_service.get_production_system(
            db, tenant_id=ctx.tenant_id, production_system_id=production_system_id
        )
    except ProductionSystemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Production system not found") from exc
    return ProductionSystemRead.model_validate(production_system)
