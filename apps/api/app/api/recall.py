import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.db import get_db, get_engine
from app.core.auth import TenantContext, require_tenant_context
from app.schemas.recall import (
    RecallCaseClose,
    RecallCaseCreate,
    RecallCaseDetailRead,
    RecallCaseSummaryRead,
)
from app.services import recall_service
from app.services.errors import (
    CropBatchNotFoundError,
    DuplicateRecallCaseCodeError,
    FarmNotFoundError,
    FinishedGoodsLotNotFoundError,
    HarvestedProduceLotNotFoundError,
    InvalidRecallCaseEffectiveTimeError,
    RecallCaseAlreadyClosedError,
    RecallCaseCommandReusedWithDifferentPayloadError,
    RecallCaseNotFoundError,
    RecallCaseValidationError,
    RecallScopeStabilizationError,
)

router = APIRouter(tags=["recall"])


@router.post(
    "/farms/{farm_id}/recall-cases",
    response_model=RecallCaseDetailRead,
    status_code=status.HTTP_201_CREATED,
)
def open_recall_case(
    farm_id: uuid.UUID,
    payload: RecallCaseCreate,
    db: Session = Depends(get_db),
    db_engine: Engine = Depends(get_engine),
    ctx: TenantContext = Depends(require_tenant_context),
) -> RecallCaseDetailRead:
    try:
        case = recall_service.open_recall_case(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            code=payload.code,
            crop_batch_id=payload.crop_batch_id,
            harvested_produce_lot_id=payload.harvested_produce_lot_id,
            finished_goods_lot_id=payload.finished_goods_lot_id,
            reason_code=payload.reason_code,
            reason_text=payload.reason_text,
        )
    except (FarmNotFoundError, CropBatchNotFoundError, HarvestedProduceLotNotFoundError, FinishedGoodsLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        RecallCaseCommandReusedWithDifferentPayloadError,
        DuplicateRecallCaseCodeError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (RecallCaseValidationError, InvalidRecallCaseEffectiveTimeError, RecallScopeStabilizationError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    result = recall_service.get_recall_case(
        tenant_id=ctx.tenant_id, farm_id=farm_id, recall_case_id=case.id, engine=db_engine
    )
    return RecallCaseDetailRead.model_validate(result)


@router.get("/farms/{farm_id}/recall-cases", response_model=list[RecallCaseSummaryRead])
def list_recall_cases(
    farm_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_tenant_context),
) -> list[RecallCaseSummaryRead]:
    try:
        rows = recall_service.list_recall_cases(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [RecallCaseSummaryRead.model_validate(r) for r in rows]


@router.get("/farms/{farm_id}/recall-cases/{recall_case_id}", response_model=RecallCaseDetailRead)
def get_recall_case(
    farm_id: uuid.UUID,
    recall_case_id: uuid.UUID,
    ctx: TenantContext = Depends(require_tenant_context),
    db_engine: Engine = Depends(get_engine),
) -> RecallCaseDetailRead:
    try:
        result = recall_service.get_recall_case(
            tenant_id=ctx.tenant_id, farm_id=farm_id, recall_case_id=recall_case_id, engine=db_engine
        )
    except (FarmNotFoundError, RecallCaseNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return RecallCaseDetailRead.model_validate(result)


@router.post("/farms/{farm_id}/recall-cases/{recall_case_id}/close", response_model=RecallCaseDetailRead)
def close_recall_case(
    farm_id: uuid.UUID,
    recall_case_id: uuid.UUID,
    payload: RecallCaseClose,
    db: Session = Depends(get_db),
    db_engine: Engine = Depends(get_engine),
    ctx: TenantContext = Depends(require_tenant_context),
) -> RecallCaseDetailRead:
    try:
        recall_service.close_recall_case(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            recall_case_id=recall_case_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            close_reason=payload.close_reason,
        )
    except (FarmNotFoundError, RecallCaseNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (RecallCaseCommandReusedWithDifferentPayloadError, RecallCaseAlreadyClosedError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidRecallCaseEffectiveTimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    result = recall_service.get_recall_case(
        tenant_id=ctx.tenant_id, farm_id=farm_id, recall_case_id=recall_case_id, engine=db_engine
    )
    return RecallCaseDetailRead.model_validate(result)
