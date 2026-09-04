from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.unit_of_measure import UnitOfMeasureRead
from app.services import unit_of_measure_service

router = APIRouter(tags=["uoms"])


@router.get("/uoms", response_model=list[UnitOfMeasureRead])
def list_uoms(
    db: Session = Depends(get_db),
    _ctx: TenantContext = Depends(require_permission(Permission.UNIT_OF_MEASURE_READ)),
) -> list[UnitOfMeasureRead]:
    """STORE-INV-001B: global, system-seeded, read-only catalog -- no
    create/update/delete route exists for UnitOfMeasure at all."""
    uoms = unit_of_measure_service.list_uoms(db)
    return [UnitOfMeasureRead.model_validate(u) for u in uoms]
