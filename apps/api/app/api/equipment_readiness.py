import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.models.equipment_readiness_state import EquipmentReadinessState
from app.schemas.equipment_readiness import (
    CleaningEventRead,
    EquipmentReadinessHistoryEntryRead,
    EquipmentReadinessReportDamageIn,
    EquipmentReadinessStateRead,
    EquipmentReadinessTransitionIn,
    RecordCleaningIn,
)
from app.services import equipment_readiness_service
from app.services.errors import (
    AssetNotFoundError,
    CarrierNotFoundError,
    CleaningEventCommandReusedWithDifferentPayloadError,
    EquipmentReadinessCarrierInUseError,
    EquipmentReadinessCleaningNotCompletedError,
    EquipmentReadinessCleaningNotRequiredError,
    EquipmentReadinessCommandReusedWithDifferentPayloadError,
    EquipmentReadinessInvalidTransitionError,
    EquipmentReadinessNotTrackedError,
    EquipmentReadinessStateNotFoundError,
    FarmNotFoundError,
)

router = APIRouter(tags=["equipment-readiness"])

_NOT_FOUND_ERRORS = (
    FarmNotFoundError, AssetNotFoundError, CarrierNotFoundError, EquipmentReadinessStateNotFoundError,
    EquipmentReadinessNotTrackedError,
)
_CONFLICT_ERRORS = (
    EquipmentReadinessCommandReusedWithDifferentPayloadError, EquipmentReadinessInvalidTransitionError,
    EquipmentReadinessCarrierInUseError, EquipmentReadinessCleaningNotRequiredError,
    EquipmentReadinessCleaningNotCompletedError, CleaningEventCommandReusedWithDifferentPayloadError,
)


def _to_read(state: EquipmentReadinessState) -> EquipmentReadinessStateRead:
    return EquipmentReadinessStateRead(
        id=state.id, tenant_id=state.tenant_id, farm_id=state.farm_id, entity_type=state.entity_type,
        asset_id=state.asset_id, carrier_id=state.carrier_id, current_state=state.current_state,
        state_changed_at=state.state_changed_at, state_changed_by_user_id=state.state_changed_by_user_id,
        state_note=state.state_note, last_cleaning_event_id=state.last_cleaning_event_id,
        created_at=state.created_at, updated_at=state.updated_at,
    )


@router.get("/farms/{farm_id}/assets/{asset_id}/readiness", response_model=EquipmentReadinessStateRead)
def get_asset_readiness(
    farm_id: uuid.UUID, asset_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_READ)),
) -> EquipmentReadinessStateRead:
    try:
        state = equipment_readiness_service.get_readiness_for_asset(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, asset_id=asset_id
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return _to_read(state)


@router.get("/farms/{farm_id}/carriers/{carrier_id}/readiness", response_model=EquipmentReadinessStateRead)
def get_carrier_readiness(
    farm_id: uuid.UUID, carrier_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_READ)),
) -> EquipmentReadinessStateRead:
    try:
        state = equipment_readiness_service.get_readiness_for_carrier(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, carrier_id=carrier_id
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return _to_read(state)


@router.get("/farms/{farm_id}/equipment-readiness", response_model=list[EquipmentReadinessStateRead])
def list_equipment_readiness(
    farm_id: uuid.UUID,
    state_filter: list[str] | None = Query(default=None, alias="state"),
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_READ)),
) -> list[EquipmentReadinessStateRead]:
    try:
        states = equipment_readiness_service.list_farm_readiness_states(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, states=state_filter
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [_to_read(s) for s in states]


@router.get("/farms/{farm_id}/equipment-readiness/awaiting-cleaning", response_model=list[EquipmentReadinessStateRead])
def list_awaiting_cleaning(
    farm_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_READ)),
) -> list[EquipmentReadinessStateRead]:
    """PART 19: the Cleaning Queue."""
    try:
        states = equipment_readiness_service.list_awaiting_cleaning(db, tenant_id=ctx.tenant_id, farm_id=farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [_to_read(s) for s in states]


@router.get("/farms/{farm_id}/equipment-readiness/{state_id}/history", response_model=list[EquipmentReadinessHistoryEntryRead])
def get_readiness_history(
    farm_id: uuid.UUID, state_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_READ)),
) -> list[EquipmentReadinessHistoryEntryRead]:
    events = equipment_readiness_service.list_readiness_history(db, tenant_id=ctx.tenant_id, state_id=state_id)
    return [
        EquipmentReadinessHistoryEntryRead(
            id=e.id, action=e.action, actor_user_id=e.actor_user_id, effective_time=e.effective_time,
            event_data=e.event_data,
        )
        for e in events
    ]


@router.get("/farms/{farm_id}/cleaning-events", response_model=list[CleaningEventRead])
def list_cleaning_events(
    farm_id: uuid.UUID,
    asset_id: uuid.UUID | None = None,
    carrier_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_READ)),
) -> list[CleaningEventRead]:
    events = equipment_readiness_service.list_cleaning_history(
        db, tenant_id=ctx.tenant_id, farm_id=farm_id, asset_id=asset_id, carrier_id=carrier_id
    )
    return [CleaningEventRead.model_validate(e) for e in events]


@router.post(
    "/farms/{farm_id}/equipment-readiness/{state_id}/mark-awaiting-cleaning",
    response_model=EquipmentReadinessStateRead,
)
def mark_awaiting_cleaning(
    farm_id: uuid.UUID, state_id: uuid.UUID, payload: EquipmentReadinessTransitionIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_EXECUTE)),
) -> EquipmentReadinessStateRead:
    try:
        state = equipment_readiness_service.mark_awaiting_cleaning(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, state_id=state_id,
            client_command_id=payload.client_command_id, note=payload.note,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(state)


@router.post(
    "/farms/{farm_id}/equipment-readiness/{state_id}/record-cleaning", response_model=EquipmentReadinessStateRead
)
def record_cleaning(
    farm_id: uuid.UUID, state_id: uuid.UUID, payload: RecordCleaningIn, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_EXECUTE)),
) -> EquipmentReadinessStateRead:
    try:
        state, _event = equipment_readiness_service.record_cleaning_completed(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, state_id=state_id,
            client_command_id=payload.client_command_id, effective_at=payload.effective_at,
            method=payload.method, result=payload.result, notes=payload.notes,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(state)


@router.post("/farms/{farm_id}/equipment-readiness/{state_id}/mark-ready", response_model=EquipmentReadinessStateRead)
def mark_ready(
    farm_id: uuid.UUID, state_id: uuid.UUID, payload: EquipmentReadinessTransitionIn, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_MANAGE)),
) -> EquipmentReadinessStateRead:
    try:
        state = equipment_readiness_service.mark_ready(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, state_id=state_id,
            client_command_id=payload.client_command_id, note=payload.note,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(state)


@router.post(
    "/farms/{farm_id}/equipment-readiness/{state_id}/report-damage", response_model=EquipmentReadinessStateRead
)
def report_damage(
    farm_id: uuid.UUID, state_id: uuid.UUID, payload: EquipmentReadinessReportDamageIn, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_EXECUTE)),
) -> EquipmentReadinessStateRead:
    try:
        state = equipment_readiness_service.report_damage(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, state_id=state_id,
            client_command_id=payload.client_command_id, note=payload.note,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(state)


@router.post(
    "/farms/{farm_id}/equipment-readiness/{state_id}/send-to-maintenance",
    response_model=EquipmentReadinessStateRead,
)
def send_to_maintenance(
    farm_id: uuid.UUID, state_id: uuid.UUID, payload: EquipmentReadinessTransitionIn, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_MANAGE)),
) -> EquipmentReadinessStateRead:
    try:
        state = equipment_readiness_service.send_to_maintenance(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, state_id=state_id,
            client_command_id=payload.client_command_id, note=payload.note,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(state)


@router.post(
    "/farms/{farm_id}/equipment-readiness/{state_id}/return-from-maintenance",
    response_model=EquipmentReadinessStateRead,
)
def return_from_maintenance(
    farm_id: uuid.UUID, state_id: uuid.UUID, payload: EquipmentReadinessTransitionIn, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_MANAGE)),
) -> EquipmentReadinessStateRead:
    try:
        state = equipment_readiness_service.return_from_maintenance(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, state_id=state_id,
            client_command_id=payload.client_command_id, note=payload.note,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(state)


@router.post("/farms/{farm_id}/equipment-readiness/{state_id}/retire", response_model=EquipmentReadinessStateRead)
def retire(
    farm_id: uuid.UUID, state_id: uuid.UUID, payload: EquipmentReadinessTransitionIn, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_READINESS_MANAGE)),
) -> EquipmentReadinessStateRead:
    try:
        state = equipment_readiness_service.retire(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, state_id=state_id,
            client_command_id=payload.client_command_id, note=payload.note,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(state)
