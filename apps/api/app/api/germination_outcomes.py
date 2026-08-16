import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.germination_outcome import (
    GerminationOutcomeBatchAggregateRead,
    GerminationOutcomeCommandCreate,
    GerminationOutcomeCommandRead,
    GerminationOutcomeSnapshotRead,
)
from app.services import germination_outcome_service
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    FarmNotFoundError,
    InvalidObservationEffectiveTimeError,
    ObservationCommandReusedWithDifferentPayloadError,
    ObservationValidationError,
    TooManyObservationEntriesError,
)

router = APIRouter(tags=["germination-outcomes"])

_NOT_FOUND = (FarmNotFoundError, CropBatchNotFoundError, BatchCarrierAssignmentNotFoundError)
_CONFLICT = (CropBatchClosedError, ObservationCommandReusedWithDifferentPayloadError)
_INVALID = (ObservationValidationError, InvalidObservationEffectiveTimeError, TooManyObservationEntriesError)


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/germination-outcomes",
    response_model=GerminationOutcomeCommandRead,
    status_code=status.HTTP_201_CREATED,
)
def record_germination_outcomes(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: GerminationOutcomeCommandCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.OBSERVATION_ENTRY_MANAGE)),
) -> GerminationOutcomeCommandRead:
    outcomes = [
        {
            "batch_carrier_assignment_id": o.batch_carrier_assignment_id,
            "normal_seedling_count": o.normal_seedling_count,
            "abnormal_seedling_count": o.abnormal_seedling_count,
            "assessment_complete": o.assessment_complete,
            "note": o.note,
        }
        for o in payload.outcomes
    ]
    try:
        event = germination_outcome_service.record_germination_outcomes(
            db,
            tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, batch_id=batch_id,
            client_command_id=payload.client_command_id, effective_time=payload.effective_time,
            note=payload.note, outcomes=outcomes,
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except _INVALID as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return germination_outcome_service.describe_germination_outcome_command(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, event=event
    )


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/germination-outcomes",
    response_model=list[GerminationOutcomeSnapshotRead],
)
def list_germination_outcomes(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.OBSERVATION_READ)),
) -> list[GerminationOutcomeSnapshotRead]:
    try:
        return germination_outcome_service.list_germination_outcome_history(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/germination-outcomes/current",
    response_model=GerminationOutcomeBatchAggregateRead,
)
def get_current_germination_outcomes(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.OBSERVATION_READ)),
) -> GerminationOutcomeBatchAggregateRead:
    try:
        return germination_outcome_service.get_current_germination_outcomes(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except _NOT_FOUND as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
