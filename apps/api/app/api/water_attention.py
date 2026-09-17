import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.water_attention import WaterAttentionItem
from app.services import water_attention_service

router = APIRouter(tags=["water-attention"])


@router.get("/farms/{farm_id}/water/attention", response_model=list[WaterAttentionItem])
def get_water_attention(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.WATER_TOPOLOGY_READ)),
) -> list[WaterAttentionItem]:
    return water_attention_service.get_water_attention(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
