import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.finished_goods_ledger import FinishedGoodsBalanceRead, FinishedGoodsLedgerEntryRead
from app.schemas.packing import (
    FinishedGoodsLotRead,
    PackingEventCreate,
    PackingEventRead,
    PackingReversalEventCreate,
    PackingReversalEventRead,
)
from app.services import finished_goods_ledger_service, packing_service
from app.services.errors import (
    DuplicateFinishedGoodsLotCodeError,
    FarmNotFoundError,
    FinishedGoodsLotNotFoundError,
    InsufficientGradedProduceLotBalanceError,
    InvalidPackingEffectiveTimeError,
    InvalidPackingReversalEffectiveTimeError,
    PackingCommandReusedWithDifferentPayloadError,
    PackingCropVarietyMismatchError,
    PackingEventAlreadyReversedError,
    PackingEventNotFoundError,
    PackingGradeVersionMismatchError,
    PackingInputGradedProduceLotNotFoundError,
    PackingReversalBlockedByDownstreamActivityError,
    PackingReversalCommandReusedWithDifferentPayloadError,
    PackingReversalEventNotFoundError,
    PackingReversalValidationError,
    PackingValidationError,
    PackSpecificationVersionNotFoundError,
    PackSpecificationVersionNotUsableError,
    QualityHoldOpenError,
    RecallContainmentOpenError,
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
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> PackingEventRead:
    input_lines = [
        {
            "graded_produce_lot_id": line.graded_produce_lot_id,
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
            pack_specification_version_id=payload.pack_specification_version_id,
            effective_time=payload.effective_time,
            finished_goods_lot_code=payload.finished_goods_lot_code,
            package_count=payload.package_count,
            packed_output_weight_kg=payload.packed_output_weight_kg,
            process_loss_weight_kg=payload.process_loss_weight_kg,
            rejected_weight_kg=payload.rejected_weight_kg,
            note=payload.note,
            input_lines=input_lines,
        )
    except (
        FarmNotFoundError, PackingInputGradedProduceLotNotFoundError, PackSpecificationVersionNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        QualityHoldOpenError,
        RecallContainmentOpenError,
        PackingCommandReusedWithDifferentPayloadError,
        DuplicateFinishedGoodsLotCodeError,
        InsufficientGradedProduceLotBalanceError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        PackingValidationError,
        InvalidPackingEffectiveTimeError,
        TooManyPackingInputLinesError,
        PackingCropVarietyMismatchError,
        PackingGradeVersionMismatchError,
        PackSpecificationVersionNotUsableError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return packing_service.get_packing_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, packing_event_id=event.id
    )


@router.get("/farms/{farm_id}/packing-events", response_model=list[PackingEventRead])
def list_packing_events(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
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
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> PackingEventRead:
    try:
        return packing_service.get_packing_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, packing_event_id=packing_event_id
        )
    except (FarmNotFoundError, PackingEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.post(
    "/farms/{farm_id}/packing-events/{packing_event_id}/reversal",
    response_model=PackingReversalEventRead,
    status_code=status.HTTP_201_CREATED,
)
def reverse_packing_event(
    farm_id: uuid.UUID,
    packing_event_id: uuid.UUID,
    payload: PackingReversalEventCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> PackingReversalEventRead:
    try:
        packing_service.reverse_packing_event(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            packing_event_id=packing_event_id,
            effective_time=payload.effective_time,
            reason_code=payload.reason_code,
            note=payload.note,
        )
    except (FarmNotFoundError, PackingEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        PackingReversalCommandReusedWithDifferentPayloadError,
        PackingEventAlreadyReversedError,
        PackingReversalBlockedByDownstreamActivityError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (PackingReversalValidationError, InvalidPackingReversalEffectiveTimeError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return packing_service.get_packing_reversal_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, packing_event_id=packing_event_id
    )


@router.get(
    "/farms/{farm_id}/packing-events/{packing_event_id}/reversal", response_model=PackingReversalEventRead
)
def get_packing_reversal_event(
    farm_id: uuid.UUID,
    packing_event_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> PackingReversalEventRead:
    try:
        return packing_service.get_packing_reversal_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, packing_event_id=packing_event_id
        )
    except (FarmNotFoundError, PackingReversalEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/finished-goods-lots", response_model=list[FinishedGoodsLotRead])
def list_finished_goods_lots(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
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
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> FinishedGoodsLotRead:
    try:
        return packing_service.get_finished_goods_lot(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, finished_goods_lot_id=finished_goods_lot_id
        )
    except (FarmNotFoundError, FinishedGoodsLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/finished-goods-lots/{finished_goods_lot_id}/ledger",
    response_model=list[FinishedGoodsLedgerEntryRead],
)
def get_finished_goods_ledger(
    farm_id: uuid.UUID,
    finished_goods_lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> list[FinishedGoodsLedgerEntryRead]:
    try:
        return finished_goods_ledger_service.get_ledger(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, finished_goods_lot_id=finished_goods_lot_id
        )
    except (FarmNotFoundError, FinishedGoodsLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/finished-goods-lots/{finished_goods_lot_id}/balance",
    response_model=FinishedGoodsBalanceRead,
)
def get_finished_goods_balance(
    farm_id: uuid.UUID,
    finished_goods_lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> FinishedGoodsBalanceRead:
    try:
        return finished_goods_ledger_service.get_balance(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, finished_goods_lot_id=finished_goods_lot_id
        )
    except (FarmNotFoundError, FinishedGoodsLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
