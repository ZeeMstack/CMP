import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import TenantContext
from app.core.permissions import Permission, require_permission
from app.schemas.observation_event import ObservationEventCreate, ObservationEventRead, ObservationTargetRead
from app.services import farm_work_item_service, observation_service
from app.services.errors import (
    BatchCarrierAssignmentNotFoundError,
    CropBatchClosedError,
    CropBatchNotFoundError,
    FarmNotFoundError,
    InvalidObservationEffectiveTimeError,
    ObservationCommandReusedWithDifferentPayloadError,
    ObservationDefinitionNotFoundError,
    ObservationEventNotFoundError,
    ObservationValidationError,
    TooManyObservationEntriesError,
)

router = APIRouter(tags=["observations"])


@router.post(
    "/farms/{farm_id}/crop-batches/{batch_id}/observations",
    response_model=ObservationEventRead,
    status_code=status.HTTP_201_CREATED,
)
def record_observation(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: ObservationEventCreate,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.OBSERVATION_ENTRY_MANAGE)),
) -> ObservationEventRead:
    values = [
        {
            "observation_definition_id": v.observation_definition_id,
            "batch_carrier_assignment_id": v.batch_carrier_assignment_id,
            "value_integer": v.value_integer,
            "value_decimal": v.value_decimal,
            "value_boolean": v.value_boolean,
            "value_text": v.value_text,
            "note": v.note,
        }
        for v in payload.values
    ]
    germination_checks = [
        {
            "batch_carrier_assignment_id": c.batch_carrier_assignment_id,
            "inspected_site_count": c.inspected_site_count,
            "normal_germinated_site_count": c.normal_germinated_site_count,
            "abnormal_germinated_site_count": c.abnormal_germinated_site_count,
            "failed_site_count": c.failed_site_count,
            "note": c.note,
        }
        for c in payload.germination_checks
    ]
    try:
        event = observation_service.record_observation(
            db,
            tenant_id=ctx.tenant_id,
            farm_id=farm_id,
            actor_user_id=ctx.user_id,
            batch_id=batch_id,
            client_command_id=payload.client_command_id,
            effective_time=payload.effective_time,
            note=payload.note,
            values=values,
            germination_checks=germination_checks,
        )
    except (
        FarmNotFoundError,
        CropBatchNotFoundError,
        ObservationDefinitionNotFoundError,
        BatchCarrierAssignmentNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except (CropBatchClosedError, ObservationCommandReusedWithDifferentPayloadError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        ObservationValidationError,
        InvalidObservationEffectiveTimeError,
        TooManyObservationEntriesError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    result = observation_service.get_observation_event(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id, observation_event_id=event.id
    )
    # PILOT-OPS-001: the Observation is already authoritative and committed
    # above -- linking the optional Work Item is best-effort and never
    # repeats or invalidates this result on failure (CLAUDE.md
    # "Transaction-backed completion").
    if payload.work_item_id is not None:
        result.work_item_link_status = farm_work_item_service.link_operational_result_best_effort(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            work_item_id=payload.work_item_id, client_command_id=payload.client_command_id,
            result_entity_type="observation_event", result_entity_id=event.id,
            # HOTFIX-TIME-002: the resolved, authoritative value from the
            # committed result -- never `payload.effective_time`, which is
            # now optional/None for a "record now" command.
            effective_time=result.effective_time,
        )
    return result


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/observations", response_model=list[ObservationEventRead]
)
def list_observations(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.OBSERVATION_READ)),
) -> list[ObservationEventRead]:
    try:
        return observation_service.list_observation_events(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/observations/{observation_event_id}",
    response_model=ObservationEventRead,
)
def get_observation(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    observation_event_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.OBSERVATION_READ)),
) -> ObservationEventRead:
    try:
        return observation_service.get_observation_event(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id,
            observation_event_id=observation_event_id,
        )
    except (FarmNotFoundError, CropBatchNotFoundError, ObservationEventNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc


@router.get(
    "/farms/{farm_id}/crop-batches/{batch_id}/observation-targets",
    response_model=list[ObservationTargetRead],
)
def list_observation_targets(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.OBSERVATION_READ)),
) -> list[ObservationTargetRead]:
    try:
        return observation_service.list_batch_observation_targets(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id
        )
    except (FarmNotFoundError, CropBatchNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
