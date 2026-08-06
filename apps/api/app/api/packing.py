import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.dev_auth import DevTenantContext, require_dev_tenant_context
from app.schemas.packing import FinishedGoodsLotRead, PackingEventCreate, PackingEventRead
from app.services import packing_service
from app.services.errors import (
    DuplicateFinishedGoodsLotCodeError,
    FarmNotFoundError,
    FinishedGoodsLotNotFoundError,
    InsufficientProduceLotBalanceError,
    InvalidPackingEffectiveTimeError,
    PackingCommandReusedWithDifferentPayloadError,
    PackingCropVarietyMismatchError,
    PackingEventNotFoundError,
    PackingInputProduceLotNotFoundError,
    PackingValidationError,
    QualityHoldOpenError,
    TooManyPackingInputLinesError,
)

router = APIRouter(tags=["packing"])


@router.post(
    "/farms/{farm_id}/packing-events",
    response_model=PackingEventRead,
    status_code=status.HTTP_201_CREATED,
)
def record_packing(
    farm_id: uuid.UUID,
    payload: PackingEventCreate,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> PackingEventRead:
    input_lines = [
        {
            "harvested_produce_lot_id": line.harvested_produce_lot_id,
            "consumed_weight_kg": line.consumed_weight_kg,
            "consumed_whole_unit_count": line.consumed_whole_unit_count,
            "note": line.note,
        }
        for line in payload.input_lines
    ]
    try:
        event = packing_service.record_packing(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            finished_goods_lot_code=payload.finished_goods_lot_code,
            package_count=payload.package_count,
            packed_output_weight_kg=payload.packed_output_weight_kg,
            process_loss_weight_kg=payload.process_loss_weight_kg,
            rejected_weight_kg=payload.rejected_weight_kg,
            note=payload.note,
            input_lines=input_lines,
        )
    except (FarmNotFoundError, PackingInputProduceLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        QualityHoldOpenError,
        PackingCommandReusedWithDifferentPayloadError,
        DuplicateFinishedGoodsLotCodeError,
        InsufficientProduceLotBalanceError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        PackingValidationError,
        InvalidPackingEffectiveTimeError,
        TooManyPackingInputLinesError,
        PackingCropVarietyMismatchError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return packing_service.get_packing_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, packing_event_id=event.id
    )


@router.get("/farms/{farm_id}/packing-events", response_model=list[PackingEventRead])
def list_packing_events(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> list[PackingEventRead]:
    try:
        return packing_service.list_packing_events(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/packing-events/{packing_event_id}", response_model=PackingEventRead)
def get_packing_event(
    farm_id: uuid.UUID,
    packing_event_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> PackingEventRead:
    try:
        return packing_service.get_packing_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, packing_event_id=packing_event_id
        )
    except (FarmNotFoundError, PackingEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/finished-goods-lots", response_model=list[FinishedGoodsLotRead])
def list_finished_goods_lots(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> list[FinishedGoodsLotRead]:
    try:
        return packing_service.list_finished_goods_lots(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/finished-goods-lots/{finished_goods_lot_id}", response_model=FinishedGoodsLotRead)
def get_finished_goods_lot(
    farm_id: uuid.UUID,
    finished_goods_lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
) -> FinishedGoodsLotRead:
    try:
        return packing_service.get_finished_goods_lot(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, finished_goods_lot_id=finished_goods_lot_id
        )
    except (FarmNotFoundError, FinishedGoodsLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
