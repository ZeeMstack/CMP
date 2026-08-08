import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.dev_auth import DevTenantContext, require_dev_tenant_context
from app.schemas.dispatch import DispatchEventCreate, DispatchEventRead
from app.services import dispatch_service
from app.services.errors import (
    DispatchCommandReusedWithDifferentPayloadError,
    DispatchEventNotFoundError,
    DispatchFinishedGoodsLotNotFoundError,
    DispatchValidationError,
    DuplicateDispatchCodeError,
    FarmNotFoundError,
    InsufficientFinishedGoodsBalanceError,
    InsufficientUnplacedQuantityError,
    InvalidDispatchEffectiveTimeError,
    QualityHoldOpenError,
)

router = APIRouter(tags=["dispatch"])


@router.post(
    "/farms/{farm_id}/dispatches",
    response_model=DispatchEventRead,
    status_code=status.HTTP_201_CREATED,
)
def record_dispatch(
    farm_id: uuid.UUID,
    payload: DispatchEventCreate,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> DispatchEventRead:
    lines = [
        {
            "finished_goods_lot_id": line.finished_goods_lot_id,
            "dispatched_weight_kg": line.dispatched_weight_kg,
            "dispatched_package_count": line.dispatched_package_count,
        }
        for line in payload.lines
    ]
    try:
        event = dispatch_service.record_dispatch(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            code=payload.code,
            external_reference=payload.external_reference,
            note=payload.note,
            lines=lines,
        )
    except (FarmNotFoundError, DispatchFinishedGoodsLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        QualityHoldOpenError,
        DispatchCommandReusedWithDifferentPayloadError,
        DuplicateDispatchCodeError,
        InsufficientFinishedGoodsBalanceError,
        InsufficientUnplacedQuantityError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        DispatchValidationError,
        InvalidDispatchEffectiveTimeError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return dispatch_service.get_dispatch_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, dispatch_event_id=event.id
    )


@router.get("/farms/{farm_id}/dispatches", response_model=list[DispatchEventRead])
def list_dispatch_events(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> list[DispatchEventRead]:
    try:
        return dispatch_service.list_dispatch_events(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/dispatches/{dispatch_event_id}", response_model=DispatchEventRead)
def get_dispatch_event(
    farm_id: uuid.UUID,
    dispatch_event_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> DispatchEventRead:
    try:
        return dispatch_service.get_dispatch_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, dispatch_event_id=dispatch_event_id
        )
    except (FarmNotFoundError, DispatchEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
