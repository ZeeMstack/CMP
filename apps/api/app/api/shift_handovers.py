import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.models.shift_handover import ShiftHandover
from app.schemas.shift_handover import ShiftHandoverCreate, ShiftHandoverRead
from app.services import shift_handover_service
from app.services.errors import (
    FarmNotFoundError,
    FarmWorkItemNotFoundError,
    ShiftHandoverCommandReusedWithDifferentPayloadError,
)

router = APIRouter(tags=["shift-handovers"])


def _to_read(db: Session, handover: ShiftHandover) -> ShiftHandoverRead:
    work_item_ids = shift_handover_service.get_handover_work_item_ids(db, handover_id=handover.id)
    return ShiftHandoverRead(
        id=handover.id, tenant_id=handover.tenant_id, farm_id=handover.farm_id,
        author_user_id=handover.author_user_id, effective_time=handover.effective_time,
        recorded_at=handover.recorded_at, note=handover.note, work_item_ids=work_item_ids,
    )


@router.post(
    "/farms/{farm_id}/shift-handovers", response_model=ShiftHandoverRead, status_code=status.HTTP_201_CREATED
)
def create_shift_handover(
    farm_id: uuid.UUID,
    payload: ShiftHandoverCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_EXECUTE)),
) -> ShiftHandoverRead:
    try:
        handover = shift_handover_service.create_handover(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, effective_time=payload.effective_time,
            note=payload.note, work_item_ids=payload.work_item_ids,
        )
    except (FarmNotFoundError, FarmWorkItemNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except ShiftHandoverCommandReusedWithDifferentPayloadError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, handover)


@router.get("/farms/{farm_id}/shift-handovers/latest", response_model=ShiftHandoverRead | None)
def get_latest_shift_handover(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_READ)),
) -> ShiftHandoverRead | None:
    handover = shift_handover_service.get_latest_handover(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    if handover is None:
        return None
    return _to_read(db, handover)


@router.get("/farms/{farm_id}/shift-handovers", response_model=list[ShiftHandoverRead])
def list_shift_handovers(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.FARM_WORK_ITEM_READ)),
) -> list[ShiftHandoverRead]:
    try:
        handovers = shift_handover_service.list_handovers(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [_to_read(db, h) for h in handovers]
