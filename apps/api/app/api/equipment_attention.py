import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.equipment_attention import EquipmentAttentionItem
from app.services import equipment_attention_service
from app.services.errors import FarmNotFoundError

router = APIRouter(tags=["equipment-attention"])


@router.get("/farms/{farm_id}/equipment-attention", response_model=list[EquipmentAttentionItem])
def get_equipment_attention(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_READ)),
) -> list[EquipmentAttentionItem]:
    try:
        return equipment_attention_service.get_equipment_attention(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
