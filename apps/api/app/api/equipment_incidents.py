import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.models.equipment_incident import EquipmentIncident
from app.schemas.equipment_incident import (
    EquipmentIncidentAcknowledgeIn,
    EquipmentIncidentActionInProgressIn,
    EquipmentIncidentAssignIn,
    EquipmentIncidentAssetSummary,
    EquipmentIncidentCloseIn,
    EquipmentIncidentHistoryEntryRead,
    EquipmentIncidentLocationSummary,
    EquipmentIncidentOpenIn,
    EquipmentIncidentRead,
    EquipmentIncidentResolveIn,
)
from app.services import equipment_incident_service
from app.services.errors import (
    AssetNotFoundError,
    EquipmentIncidentCommandReusedWithDifferentPayloadError,
    EquipmentIncidentInvalidTransitionError,
    EquipmentIncidentNotFoundError,
    FarmNotFoundError,
    LocationNotFoundError,
)

router = APIRouter(tags=["equipment-incidents"])

_NOT_FOUND_ERRORS = (FarmNotFoundError, AssetNotFoundError, LocationNotFoundError, EquipmentIncidentNotFoundError)
_CONFLICT_ERRORS = (EquipmentIncidentCommandReusedWithDifferentPayloadError, EquipmentIncidentInvalidTransitionError)


def _to_read(db: Session, *, tenant_id: uuid.UUID, incident: EquipmentIncident) -> EquipmentIncidentRead:
    context = equipment_incident_service.resolve_read_context(db, tenant_id=tenant_id, incidents=[incident])
    return _build_read(incident, context)


def _build_read(incident: EquipmentIncident, context: dict) -> EquipmentIncidentRead:
    asset = context["assets"].get(incident.asset_id)
    return EquipmentIncidentRead(
        id=incident.id, tenant_id=incident.tenant_id, farm_id=incident.farm_id, code=incident.code,
        asset_id=incident.asset_id, asset=EquipmentIncidentAssetSummary(**asset) if asset else None,
        location_id=incident.location_id,
        location=(
            EquipmentIncidentLocationSummary(**context["locations"][incident.location_id])
            if incident.location_id and incident.location_id in context["locations"] else None
        ),
        potentially_impacted_location_id=incident.potentially_impacted_location_id,
        potentially_impacted_location=(
            EquipmentIncidentLocationSummary(**context["locations"][incident.potentially_impacted_location_id])
            if incident.potentially_impacted_location_id
            and incident.potentially_impacted_location_id in context["locations"] else None
        ),
        severity=incident.severity, category=incident.category, description=incident.description,
        detected_by_user_id=incident.detected_by_user_id, detected_at=incident.detected_at, notes=incident.notes,
        status=incident.status, opened_by_user_id=incident.opened_by_user_id, opened_at=incident.opened_at,
        assigned_owner_user_id=incident.assigned_owner_user_id,
        acknowledged_by_user_id=incident.acknowledged_by_user_id, acknowledged_at=incident.acknowledged_at,
        resolved_by_user_id=incident.resolved_by_user_id, resolved_at=incident.resolved_at,
        resolution_note=incident.resolution_note, closed_by_user_id=incident.closed_by_user_id,
        closed_at=incident.closed_at, close_note=incident.close_note, updated_at=incident.updated_at,
    )


@router.post("/farms/{farm_id}/equipment-incidents", response_model=EquipmentIncidentRead, status_code=status.HTTP_201_CREATED)
def open_incident(
    farm_id: uuid.UUID, payload: EquipmentIncidentOpenIn, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_INCIDENT_EXECUTE)),
) -> EquipmentIncidentRead:
    try:
        incident = equipment_incident_service.open_incident(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id, asset_id=payload.asset_id,
            location_id=payload.location_id,
            potentially_impacted_location_id=payload.potentially_impacted_location_id,
            severity=payload.severity, category=payload.category, description=payload.description,
            detected_at=payload.detected_at, assigned_owner_user_id=payload.assigned_owner_user_id,
            notes=payload.notes,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, incident=incident)


@router.get("/farms/{farm_id}/equipment-incidents", response_model=list[EquipmentIncidentRead])
def list_incidents(
    farm_id: uuid.UUID,
    status_filter: list[str] | None = Query(default=None, alias="status"),
    asset_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_INCIDENT_READ)),
) -> list[EquipmentIncidentRead]:
    try:
        incidents = equipment_incident_service.list_incidents(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, statuses=status_filter, asset_id=asset_id
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    context = equipment_incident_service.resolve_read_context(db, tenant_id=ctx.tenant_id, incidents=incidents)
    return [_build_read(i, context) for i in incidents]


@router.get("/farms/{farm_id}/equipment-incidents/{incident_id}", response_model=EquipmentIncidentRead)
def get_incident(
    farm_id: uuid.UUID, incident_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_INCIDENT_READ)),
) -> EquipmentIncidentRead:
    try:
        incident = equipment_incident_service.get_incident(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, incident_id=incident_id
        )
    except EquipmentIncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return _to_read(db, tenant_id=ctx.tenant_id, incident=incident)


@router.get("/farms/{farm_id}/equipment-incidents/{incident_id}/history", response_model=list[EquipmentIncidentHistoryEntryRead])
def get_incident_history(
    farm_id: uuid.UUID, incident_id: uuid.UUID, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_INCIDENT_READ)),
) -> list[EquipmentIncidentHistoryEntryRead]:
    try:
        events = equipment_incident_service.list_history(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, incident_id=incident_id
        )
    except EquipmentIncidentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return [
        EquipmentIncidentHistoryEntryRead(
            id=e.id, action=e.action, actor_user_id=e.actor_user_id, effective_time=e.effective_time,
            event_data=e.event_data,
        )
        for e in events
    ]


@router.post("/farms/{farm_id}/equipment-incidents/{incident_id}/acknowledge", response_model=EquipmentIncidentRead)
def acknowledge_incident(
    farm_id: uuid.UUID, incident_id: uuid.UUID, payload: EquipmentIncidentAcknowledgeIn, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_INCIDENT_EXECUTE)),
) -> EquipmentIncidentRead:
    try:
        incident = equipment_incident_service.acknowledge_incident(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, incident_id=incident_id,
            client_command_id=payload.client_command_id,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, incident=incident)


@router.post(
    "/farms/{farm_id}/equipment-incidents/{incident_id}/action-in-progress", response_model=EquipmentIncidentRead
)
def mark_action_in_progress(
    farm_id: uuid.UUID, incident_id: uuid.UUID, payload: EquipmentIncidentActionInProgressIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_INCIDENT_MANAGE)),
) -> EquipmentIncidentRead:
    try:
        incident = equipment_incident_service.mark_action_in_progress(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, incident_id=incident_id,
            client_command_id=payload.client_command_id,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, incident=incident)


@router.post("/farms/{farm_id}/equipment-incidents/{incident_id}/assign", response_model=EquipmentIncidentRead)
def assign_incident(
    farm_id: uuid.UUID, incident_id: uuid.UUID, payload: EquipmentIncidentAssignIn, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_INCIDENT_MANAGE)),
) -> EquipmentIncidentRead:
    try:
        incident = equipment_incident_service.assign_incident(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, incident_id=incident_id,
            client_command_id=payload.client_command_id, assigned_owner_user_id=payload.assigned_owner_user_id,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, incident=incident)


@router.post("/farms/{farm_id}/equipment-incidents/{incident_id}/resolve", response_model=EquipmentIncidentRead)
def resolve_incident(
    farm_id: uuid.UUID, incident_id: uuid.UUID, payload: EquipmentIncidentResolveIn, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_INCIDENT_MANAGE)),
) -> EquipmentIncidentRead:
    try:
        incident = equipment_incident_service.resolve_incident(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, incident_id=incident_id,
            client_command_id=payload.client_command_id, resolution_note=payload.resolution_note,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, incident=incident)


@router.post("/farms/{farm_id}/equipment-incidents/{incident_id}/close", response_model=EquipmentIncidentRead)
def close_incident(
    farm_id: uuid.UUID, incident_id: uuid.UUID, payload: EquipmentIncidentCloseIn, db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.EQUIPMENT_INCIDENT_MANAGE)),
) -> EquipmentIncidentRead:
    try:
        incident = equipment_incident_service.close_incident(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, incident_id=incident_id,
            client_command_id=payload.client_command_id, close_note=payload.close_note,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, incident=incident)
