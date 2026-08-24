import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.production_disposition_event import ProductionDispositionEvent
from app.schemas.production_disposition import (
    ActiveProductionPlateRead,
    CorrectProductionDispositionCreate,
    ProductionDispositionCorrectResult,
    ProductionDispositionEventRead,
    ProductionDispositionHistoryRead,
    ProductionDispositionRecordResult,
    RecordProductionDispositionCreate,
)
from app.services import production_disposition_service
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    CropBatchClosedError,
    FarmNotFoundError,
    InvalidProductionDispositionEffectiveTimeError,
    InvalidProductionDispositionReasonError,
    NoPopulationRootError,
    ProductionDispositionAlreadyCorrectedError,
    ProductionDispositionAssignmentReleasedError,
    ProductionDispositionBalanceError,
    ProductionDispositionCarrierReusedError,
    ProductionDispositionCommandReusedWithDifferentPayloadError,
    ProductionDispositionEventNotFoundError,
    ProductionDispositionNotReductionError,
    ProductionDispositionValidationError,
    UnsupportedProductionDispositionCarrierTypeError,
)

router = APIRouter(tags=["leafy-production-disposition"])

_NOT_FOUND = (FarmNotFoundError, BatchCarrierAssignmentNotFoundError, ProductionDispositionEventNotFoundError)
_INVALID = (
    ProductionDispositionValidationError,
    InvalidProductionDispositionReasonError,
    InvalidProductionDispositionEffectiveTimeError,
    UnsupportedProductionDispositionCarrierTypeError,
    NoPopulationRootError,
    ProductionDispositionNotReductionError,
)
_CONFLICT = (
    CropBatchClosedError,
    ProductionDispositionAssignmentReleasedError,
    ProductionDispositionBalanceError,
    ProductionDispositionCommandReusedWithDifferentPayloadError,
    ProductionDispositionAlreadyCorrectedError,
    ProductionDispositionCarrierReusedError,
)


def _event_read(event: ProductionDispositionEvent, *, is_reversed: bool, actor_user_id) -> ProductionDispositionEventRead:
    return ProductionDispositionEventRead(
        id=event.id, command_id=event.command_id, batch_carrier_assignment_id=event.batch_carrier_assignment_id,
        population_root_batch_carrier_assignment_id=event.population_root_batch_carrier_assignment_id,
        event_kind=event.event_kind, reason_code=event.reason_code, quantity_delta=event.quantity_delta,
        plant_loss_quantity=max(0, -event.quantity_delta), effective_time=event.effective_time,
        recorded_at=event.recorded_at, note=event.note, reverses_event_id=event.reverses_event_id,
        corrects_event_id=event.corrects_event_id, is_reversed=is_reversed, actor_user_id=actor_user_id,
    )


@router.post(
    "/farms/{farm_id}/leafy-production/dispositions",
    response_model=ProductionDispositionRecordResult,
    status_code=status.HTTP_201_CREATED,
)
def record_production_disposition(
    farm_id: uuid.UUID,
    payload: RecordProductionDispositionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.BIOLOGICAL_DISPOSITION_MANAGE)),
) -> ProductionDispositionRecordResult:
    try:
        command = production_disposition_service.record_disposition(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            batch_carrier_assignment_id=payload.batch_carrier_assignment_id,
            plant_loss_count=payload.plant_loss_count, reason_code=payload.reason_code,
            effective_time=payload.effective_time, note=payload.note,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except _INVALID as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    event = db.execute(
        select(ProductionDispositionEvent).where(ProductionDispositionEvent.command_id == command.id)
    ).scalar_one()
    root_id = event.population_root_batch_carrier_assignment_id
    resulting = production_disposition_service.get_current_living_population(
        db, root_batch_carrier_assignment_id=root_id
    )
    previous = resulting - event.quantity_delta
    return ProductionDispositionRecordResult(
        command_id=command.id, client_command_id=command.client_command_id,
        batch_carrier_assignment_id=command.batch_carrier_assignment_id,
        population_root_batch_carrier_assignment_id=root_id,
        event=_event_read(event, is_reversed=False, actor_user_id=command.actor_user_id),
        previous_living_population=previous, resulting_living_population=resulting,
        assignment_released=resulting == 0,
    )


@router.post(
    "/farms/{farm_id}/leafy-production/dispositions/{event_id}/correct",
    response_model=ProductionDispositionCorrectResult,
    status_code=status.HTTP_201_CREATED,
)
def correct_production_disposition(
    farm_id: uuid.UUID,
    event_id: uuid.UUID,
    payload: CorrectProductionDispositionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.BIOLOGICAL_DISPOSITION_CORRECT)),
) -> ProductionDispositionCorrectResult:
    corrected = (
        {
            "plant_loss_count": payload.corrected.plant_loss_count, "reason_code": payload.corrected.reason_code,
            "effective_time": payload.corrected.effective_time, "note": payload.corrected.note,
        }
        if payload.corrected is not None
        else None
    )
    try:
        command = production_disposition_service.correct_disposition(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, target_event_id=event_id, corrected=corrected,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except _INVALID as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    target = db.execute(
        select(ProductionDispositionEvent).where(ProductionDispositionEvent.id == command.target_event_id)
    ).scalar_one()
    reversal = db.execute(
        select(ProductionDispositionEvent).where(
            ProductionDispositionEvent.reverses_event_id == target.id,
            ProductionDispositionEvent.command_id == command.id,
        )
    ).scalar_one()
    replacement = db.execute(
        select(ProductionDispositionEvent).where(
            ProductionDispositionEvent.corrects_event_id == target.id,
            ProductionDispositionEvent.command_id == command.id,
        )
    ).scalar_one_or_none()

    root_id = target.population_root_batch_carrier_assignment_id
    resulting = production_disposition_service.get_current_living_population(
        db, root_batch_carrier_assignment_id=root_id
    )
    previous = resulting - reversal.quantity_delta - (replacement.quantity_delta if replacement else 0)

    restored_id = db.execute(
        select(BatchCarrierAssignment.id).where(
            BatchCarrierAssignment.opening_production_disposition_reversal_event_id == reversal.id
        )
    ).scalar_one_or_none()

    return ProductionDispositionCorrectResult(
        command_id=command.id, client_command_id=command.client_command_id,
        population_root_batch_carrier_assignment_id=root_id,
        target_event=_event_read(target, is_reversed=True, actor_user_id=None),
        reversal_event=_event_read(reversal, is_reversed=False, actor_user_id=command.actor_user_id),
        replacement_event=(
            _event_read(replacement, is_reversed=False, actor_user_id=command.actor_user_id)
            if replacement is not None
            else None
        ),
        restored_batch_carrier_assignment_id=restored_id,
        previous_living_population=previous, resulting_living_population=resulting,
    )


@router.get(
    "/farms/{farm_id}/leafy-production/active-plates",
    response_model=list[ActiveProductionPlateRead],
)
def list_active_production_plates(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_READ)),
) -> list[ActiveProductionPlateRead]:
    try:
        rows = production_disposition_service.list_active_production_plates(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [ActiveProductionPlateRead(**row) for row in rows]


@router.get(
    "/farms/{farm_id}/leafy-production/dispositions",
    response_model=list[ProductionDispositionHistoryRead],
)
def list_production_disposition_history(
    farm_id: uuid.UUID,
    batch_carrier_assignment_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.SOWING_READ)),
) -> list[ProductionDispositionHistoryRead]:
    try:
        rows = production_disposition_service.get_production_disposition_history(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id,
            batch_carrier_assignment_id=batch_carrier_assignment_id, batch_id=batch_id,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [ProductionDispositionHistoryRead(**row) for row in rows]
