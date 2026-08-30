import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.farm_setup_readiness import FarmSetupReadinessRead
from app.services import farm_setup_readiness_service
from app.services.errors import FarmNotFoundError

router = APIRouter(tags=["farm-setup-readiness"])


@router.get("/farms/{farm_id}/setup-readiness", response_model=FarmSetupReadinessRead)
def get_farm_setup_readiness(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_READ)),
) -> FarmSetupReadinessRead:
    try:
        return farm_setup_readiness_service.evaluate_farm_setup_readiness(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found") from exc
