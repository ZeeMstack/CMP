import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.grading import GradedProduceLotRead, GradingEventCreate, GradingEventRead
from app.schemas.graded_produce_lot_ledger import GradedProduceLotBalanceRead, GradedProduceLotLedgerEntryRead
from app.services import grading_service, graded_produce_lot_ledger_service
from app.services.errors import (
    DuplicateGradedProduceLotCodeError,
    FarmNotFoundError,
    GradeDefinitionVersionNotFoundError,
    GradedProduceLotNotFoundError,
    GradingCommandReusedWithDifferentPayloadError,
    GradingEventNotFoundError,
    GradingSourceProduceLotNotFoundError,
    GradingValidationError,
    InsufficientHarvestedProduceLotBalanceError,
    InvalidGradingEffectiveTimeError,
    ProcessingHallLocationInvalidError,
    QualityHoldOpenError,
    RecallContainmentOpenError,
    TooManyGradingOutputsError,
)

router = APIRouter(tags=["grading"])


@router.post(
    "/farms/{farm_id}/grading-events", response_model=GradingEventRead, status_code=status.HTTP_201_CREATED
)
def record_grading(
    farm_id: uuid.UUID,
    payload: GradingEventCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_MANAGE)),
) -> GradingEventRead:
    outputs = [
        {
            "grade_definition_version_id": o.grade_definition_version_id, "code": o.code,
            "output_weight_kg": o.output_weight_kg, "output_whole_unit_count": o.output_whole_unit_count,
        }
        for o in payload.outputs
    ]
    try:
        event = grading_service.record_grading(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            source_harvested_produce_lot_id=payload.source_harvested_produce_lot_id,
            processing_hall_location_id=payload.processing_hall_location_id,
            effective_time=payload.effective_time,
            note=payload.note,
            input_presented_weight_kg=payload.input_presented_weight_kg,
            input_presented_whole_unit_count=payload.input_presented_whole_unit_count,
            rejected_weight_kg=payload.rejected_weight_kg,
            rejected_whole_unit_count=payload.rejected_whole_unit_count,
            loss_weight_kg=payload.loss_weight_kg,
            loss_whole_unit_count=payload.loss_whole_unit_count,
            sample_weight_kg=payload.sample_weight_kg,
            sample_whole_unit_count=payload.sample_whole_unit_count,
            remainder_weight_kg=payload.remainder_weight_kg,
            remainder_whole_unit_count=payload.remainder_whole_unit_count,
            outputs=outputs,
        )
    except (
        FarmNotFoundError, GradingSourceProduceLotNotFoundError, GradeDefinitionVersionNotFoundError,
        ProcessingHallLocationInvalidError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (
        QualityHoldOpenError,
        RecallContainmentOpenError,
        GradingCommandReusedWithDifferentPayloadError,
        DuplicateGradedProduceLotCodeError,
        InsufficientHarvestedProduceLotBalanceError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        GradingValidationError,
        InvalidGradingEffectiveTimeError,
        TooManyGradingOutputsError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return grading_service.get_grading_event(db, tenant_id=ctx.tenant_id, farm_id=farm_id, grading_event_id=event.id)


@router.get("/farms/{farm_id}/grading-events", response_model=list[GradingEventRead])
def list_grading_events(
    farm_id: uuid.UUID,
    source_harvested_produce_lot_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> list[GradingEventRead]:
    try:
        return grading_service.list_grading_events(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id,
            source_harvested_produce_lot_id=source_harvested_produce_lot_id,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/grading-events/{grading_event_id}", response_model=GradingEventRead)
def get_grading_event(
    farm_id: uuid.UUID,
    grading_event_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> GradingEventRead:
    try:
        return grading_service.get_grading_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, grading_event_id=grading_event_id
        )
    except (FarmNotFoundError, GradingEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get("/farms/{farm_id}/graded-produce-lots", response_model=list[GradedProduceLotRead])
def list_graded_produce_lots(
    farm_id: uuid.UUID,
    crop_id: uuid.UUID | None = Query(default=None),
    variety_id: uuid.UUID | None = Query(default=None),
    grade_definition_version_id: uuid.UUID | None = Query(default=None),
    grading_event_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> list[GradedProduceLotRead]:
    try:
        return grading_service.list_graded_produce_lots(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, crop_id=crop_id, variety_id=variety_id,
            grade_definition_version_id=grade_definition_version_id, grading_event_id=grading_event_id,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/graded-produce-lots/{graded_produce_lot_id}", response_model=GradedProduceLotRead
)
def get_graded_produce_lot(
    farm_id: uuid.UUID,
    graded_produce_lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> GradedProduceLotRead:
    try:
        return grading_service.get_graded_produce_lot(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, graded_produce_lot_id=graded_produce_lot_id
        )
    except (FarmNotFoundError, GradedProduceLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/graded-produce-lots/{graded_produce_lot_id}/ledger",
    response_model=list[GradedProduceLotLedgerEntryRead],
)
def get_graded_produce_lot_ledger(
    farm_id: uuid.UUID,
    graded_produce_lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> list[GradedProduceLotLedgerEntryRead]:
    try:
        return graded_produce_lot_ledger_service.get_ledger(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, graded_produce_lot_id=graded_produce_lot_id
        )
    except (FarmNotFoundError, GradedProduceLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/graded-produce-lots/{graded_produce_lot_id}/balance",
    response_model=GradedProduceLotBalanceRead,
)
def get_graded_produce_lot_balance(
    farm_id: uuid.UUID,
    graded_produce_lot_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.PACKING_READ)),
) -> GradedProduceLotBalanceRead:
    try:
        return graded_produce_lot_ledger_service.get_balance(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, graded_produce_lot_id=graded_produce_lot_id
        )
    except (FarmNotFoundError, GradedProduceLotNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
