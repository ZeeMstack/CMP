import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.models.production_disposition_event import ProductionDispositionEvent
from app.schemas.sowing_event import CarrierSummary, CarrierTypeSummary
from app.schemas.vines_production_disposition import (
    CorrectVinesGrowCubeDispositionCreate,
    RecordVinesGrowCubeDispositionCreate,
    VinesGrowCubeDispositionCorrectResult,
    VinesGrowCubeDispositionEventRead,
    VinesGrowCubeDispositionRecordResult,
    VinesProductionDispositionHistoryRead,
)
from app.services import production_disposition_service, vines_production_transfer_service
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
    ProductionDispositionGrowCubeAlreadyDisposedError,
    ProductionDispositionGrowCubeNotInAssignmentError,
    ProductionDispositionNotReductionError,
    ProductionDispositionValidationError,
    UnsupportedProductionDispositionCarrierTypeError,
)

router = APIRouter(tags=["vines-production-disposition"])

_NOT_FOUND = (FarmNotFoundError, BatchCarrierAssignmentNotFoundError, ProductionDispositionEventNotFoundError)
_INVALID = (
    ProductionDispositionValidationError,
    InvalidProductionDispositionReasonError,
    InvalidProductionDispositionEffectiveTimeError,
    UnsupportedProductionDispositionCarrierTypeError,
    NoPopulationRootError,
    ProductionDispositionNotReductionError,
    ProductionDispositionGrowCubeNotInAssignmentError,
)
_CONFLICT = (
    CropBatchClosedError,
    ProductionDispositionAssignmentReleasedError,
    ProductionDispositionBalanceError,
    ProductionDispositionCommandReusedWithDifferentPayloadError,
    ProductionDispositionAlreadyCorrectedError,
    ProductionDispositionCarrierReusedError,
    ProductionDispositionGrowCubeAlreadyDisposedError,
)


def _event_read(
    db: Session, event: ProductionDispositionEvent, *, is_reversed: bool, actor_user_id: uuid.UUID | None,
) -> VinesGrowCubeDispositionEventRead:
    grow_cubes = [
        CarrierSummary(
            id=r["id"], code=r["code"],
            carrier_type=CarrierTypeSummary(id=r["carrier_type_id"], code=r["carrier_type_code"], name=r["carrier_type_name"]),
        )
        for r in production_disposition_service.get_grow_cube_disposition_event_carriers(
            db, production_disposition_event_id=event.id
        )
    ]
    return VinesGrowCubeDispositionEventRead(
        id=event.id, command_id=event.command_id, batch_carrier_assignment_id=event.batch_carrier_assignment_id,
        population_root_batch_carrier_assignment_id=event.population_root_batch_carrier_assignment_id,
        event_kind=event.event_kind, reason_code=event.reason_code, quantity_delta=event.quantity_delta,
        plant_loss_quantity=max(0, -event.quantity_delta), effective_time=event.effective_time,
        recorded_at=event.recorded_at, note=event.note, reverses_event_id=event.reverses_event_id,
        is_reversed=is_reversed, actor_user_id=actor_user_id, grow_cubes=grow_cubes,
    )


@router.post(
    "/farms/{farm_id}/vines-production/dispositions",
    response_model=VinesGrowCubeDispositionRecordResult,
    status_code=status.HTTP_201_CREATED,
)
def record_vines_grow_cube_disposition(
    farm_id: uuid.UUID,
    payload: RecordVinesGrowCubeDispositionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.BIOLOGICAL_DISPOSITION_MANAGE)),
) -> VinesGrowCubeDispositionRecordResult:
    try:
        command = production_disposition_service.record_grow_cube_disposition(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            batch_carrier_assignment_id=payload.batch_carrier_assignment_id,
            grow_cube_carrier_ids=payload.grow_cube_carrier_ids, reason_code=payload.reason_code,
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
    return VinesGrowCubeDispositionRecordResult(
        command_id=command.id, client_command_id=command.client_command_id,
        batch_carrier_assignment_id=command.batch_carrier_assignment_id,
        population_root_batch_carrier_assignment_id=root_id,
        event=_event_read(db, event, is_reversed=False, actor_user_id=command.actor_user_id),
        previous_living_population=previous, resulting_living_population=resulting,
        assignment_released=resulting == 0,
    )


@router.post(
    "/farms/{farm_id}/vines-production/dispositions/{event_id}/correct",
    response_model=VinesGrowCubeDispositionCorrectResult,
    status_code=status.HTTP_201_CREATED,
)
def correct_vines_grow_cube_disposition(
    farm_id: uuid.UUID,
    event_id: uuid.UUID,
    payload: CorrectVinesGrowCubeDispositionCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.BIOLOGICAL_DISPOSITION_CORRECT)),
) -> VinesGrowCubeDispositionCorrectResult:
    try:
        command = production_disposition_service.correct_grow_cube_disposition(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, target_event_id=event_id, corrected=None,
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

    root_id = target.population_root_batch_carrier_assignment_id
    resulting = production_disposition_service.get_current_living_population(
        db, root_batch_carrier_assignment_id=root_id
    )
    previous = resulting - reversal.quantity_delta

    return VinesGrowCubeDispositionCorrectResult(
        command_id=command.id, client_command_id=command.client_command_id,
        population_root_batch_carrier_assignment_id=root_id,
        target_event=_event_read(db, target, is_reversed=True, actor_user_id=None),
        reversal_event=_event_read(db, reversal, is_reversed=False, actor_user_id=command.actor_user_id),
        previous_living_population=previous, resulting_living_population=resulting,
    )


@router.get(
    "/farms/{farm_id}/vines-production/dispositions",
    response_model=list[VinesProductionDispositionHistoryRead],
)
def list_vines_production_disposition_history(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.TRANSPLANT_READ)),
) -> list[VinesProductionDispositionHistoryRead]:
    try:
        return vines_production_transfer_service.get_vines_production_disposition_history(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
