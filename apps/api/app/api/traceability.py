import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Engine

from app.core.db import get_engine
from app.core.dev_auth import DevTenantContext, require_dev_tenant_context
from app.schemas.traceability import (
    CropBatchImpactRead,
    FinishedGoodsLotTraceRead,
    HarvestedProduceLotImpactRead,
)
from app.services import traceability_service
from app.services.errors import (
    CropBatchNotFoundError,
    FarmNotFoundError,
    FinishedGoodsLotNotFoundError,
    HarvestedProduceLotNotFoundError,
    TraceabilityIntegrityError,
)

router = APIRouter(tags=["traceability"])


@router.get(
    "/farms/{farm_id}/traceability/finished-goods-lots/{finished_goods_lot_id}",
    response_model=FinishedGoodsLotTraceRead,
)
def get_finished_goods_lot_trace(
    farm_id: uuid.UUID,
    finished_goods_lot_id: uuid.UUID,
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
    db_engine: Engine = Depends(get_engine),
) -> FinishedGoodsLotTraceRead:
    try:
        result = traceability_service.get_finished_goods_lot_trace(
            tenant_id=ctx.tenant_id, farm_id=farm_id, finished_goods_lot_id=finished_goods_lot_id, engine=db_engine
        )
    except (FarmNotFoundError, FinishedGoodsLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except TraceabilityIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return FinishedGoodsLotTraceRead.model_validate(result)


@router.get(
    "/farms/{farm_id}/traceability/crop-batches/{crop_batch_id}/impact",
    response_model=CropBatchImpactRead,
)
def get_crop_batch_impact(
    farm_id: uuid.UUID,
    crop_batch_id: uuid.UUID,
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
    db_engine: Engine = Depends(get_engine),
) -> CropBatchImpactRead:
    try:
        result = traceability_service.get_crop_batch_impact(
            tenant_id=ctx.tenant_id, farm_id=farm_id, crop_batch_id=crop_batch_id, engine=db_engine
        )
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except TraceabilityIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return CropBatchImpactRead.model_validate(result)


@router.get(
    "/farms/{farm_id}/traceability/harvested-produce-lots/{produce_lot_id}/impact",
    response_model=HarvestedProduceLotImpactRead,
)
def get_harvested_produce_lot_impact(
    farm_id: uuid.UUID,
    produce_lot_id: uuid.UUID,
    ctx: DevTenantContext = Depends(require_dev_tenant_context),
    db_engine: Engine = Depends(get_engine),
) -> HarvestedProduceLotImpactRead:
    try:
        result = traceability_service.get_harvested_produce_lot_impact(
            tenant_id=ctx.tenant_id, farm_id=farm_id, harvested_produce_lot_id=produce_lot_id, engine=db_engine
        )
    except (FarmNotFoundError, HarvestedProduceLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except TraceabilityIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return HarvestedProduceLotImpactRead.model_validate(result)
