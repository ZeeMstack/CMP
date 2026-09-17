"""PILOT-ASSET-001: Critical Equipment Incident lifecycle
(OPEN -> ACKNOWLEDGED -> ACTION_IN_PROGRESS -> RESOLVED -> CLOSED). A
lightweight CURRENT-STATE row modeled directly on `CropIssue`'s own shape
and idempotency pattern -- never a full CMMS. Incident != Work Item:
linking a `FarmWorkItem` (via `FarmWorkItem.equipment_incident_id`, set
only at Work Item creation) never resolves or closes this row; `resolve_
incident`/`close_incident` are always separate, deliberate commands.
Incident != Crop Issue: no command here ever creates, references, or
infers a `CropIssue`. See docs/domain/EQUIPMENT_READINESS_MODEL.md."""

import hashlib
import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.audit_event import AuditEvent
from app.models.equipment_incident import INCIDENT_TERMINAL_STATUSES, EquipmentIncident
from app.models.location import Location
from app.services import asset_service, farm_service, location_service
from app.services.audit import append_audit_event
from app.services.errors import (
    EquipmentIncidentCommandReusedWithDifferentPayloadError,
    EquipmentIncidentInvalidTransitionError,
    EquipmentIncidentNotFoundError,
    FarmNotFoundError,
)

MAX_LIST_LIMIT = 500


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def _generate_incident_code(db: Session, *, tenant_id: uuid.UUID, local_date: date) -> str:
    """Sequential per tenant per local calendar date -- `EI-YYYYMMDD-NNNN`,
    mirrors `crop_issue_service._generate_issue_code`/`farm_work_item_
    service._generate_work_item_code` exactly."""
    lock_key = f"{tenant_id}:equipment_incident_code:{local_date.isoformat()}"
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key})
    prefix = f"EI-{local_date.strftime('%Y%m%d')}-"
    seq = 1
    while True:
        code = f"{prefix}{seq:04d}"
        exists = db.execute(
            select(EquipmentIncident.id).where(
                EquipmentIncident.tenant_id == tenant_id, EquipmentIncident.code.ilike(code)
            )
        ).first()
        if exists is None:
            return code
        seq += 1


def _lock_incident(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, incident_id: uuid.UUID
) -> EquipmentIncident:
    incident = db.execute(
        select(EquipmentIncident)
        .where(
            EquipmentIncident.id == incident_id, EquipmentIncident.tenant_id == tenant_id,
            EquipmentIncident.farm_id == farm_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if incident is None:
        raise EquipmentIncidentNotFoundError(str(incident_id))
    return incident


# --- open ----------------------------------------------------------------------------


def open_incident(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    asset_id: uuid.UUID,
    location_id: uuid.UUID | None,
    potentially_impacted_location_id: uuid.UUID | None,
    severity: str,
    category: str,
    description: str,
    detected_at: datetime,
    assigned_owner_user_id: uuid.UUID | None,
    notes: str | None,
) -> EquipmentIncident:
    fingerprint = _fingerprint(
        tenant_id, farm_id, asset_id, location_id, potentially_impacted_location_id, severity, category,
        description, detected_at, assigned_owner_user_id, notes,
    )

    def _find_by_command() -> EquipmentIncident | None:
        return db.execute(
            select(EquipmentIncident).where(
                EquipmentIncident.tenant_id == tenant_id, EquipmentIncident.client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id))

    farm = _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    asset_service.get_asset(db, tenant_id=tenant_id, farm_id=farm_id, asset_id=asset_id)
    if location_id is not None:
        location_service.get_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)
    if potentially_impacted_location_id is not None:
        location_service.get_location(
            db, tenant_id=tenant_id, farm_id=farm_id, location_id=potentially_impacted_location_id
        )

    local_date = datetime.now(timezone.utc).astimezone(ZoneInfo(farm.timezone)).date()
    code = _generate_incident_code(db, tenant_id=tenant_id, local_date=local_date)

    incident = EquipmentIncident(
        tenant_id=tenant_id, farm_id=farm_id, code=code, asset_id=asset_id, location_id=location_id,
        potentially_impacted_location_id=potentially_impacted_location_id, severity=severity, category=category,
        description=description, detected_by_user_id=actor_user_id, detected_at=detected_at, notes=notes,
        status="open", opened_by_user_id=actor_user_id, assigned_owner_user_id=assigned_owner_user_id,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(incident)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_equipment_incidents_tenant_client_command_id":
            replay = _find_by_command()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="equipment_incident.opened",
        entity_type="equipment_incident", entity_id=incident.id,
        event_data={
            "code": incident.code, "asset_id": str(asset_id), "severity": severity, "category": category,
        },
    )
    db.commit()
    db.refresh(incident)
    return incident


# --- lifecycle transitions ----------------------------------------------------------


def acknowledge_incident(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, incident_id: uuid.UUID,
    client_command_id: uuid.UUID,
) -> EquipmentIncident:
    fingerprint = _fingerprint(tenant_id, incident_id, actor_user_id, "acknowledge")

    def _find_by_command() -> EquipmentIncident | None:
        return db.execute(
            select(EquipmentIncident).where(
                EquipmentIncident.tenant_id == tenant_id,
                EquipmentIncident.acknowledge_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.acknowledge_request_fingerprint == fingerprint:
            return existing
        raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id))

    incident = _lock_incident(db, tenant_id=tenant_id, farm_id=farm_id, incident_id=incident_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.acknowledge_request_fingerprint == fingerprint:
            return existing
        raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id))

    if incident.status != "open":
        raise EquipmentIncidentInvalidTransitionError(f"incident {incident_id} is not open (status={incident.status})")

    incident.status = "acknowledged"
    incident.acknowledged_at = datetime.now(timezone.utc)
    incident.acknowledged_by_user_id = actor_user_id
    incident.acknowledge_client_command_id = client_command_id
    incident.acknowledge_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_equipment_incidents_tenant_acknowledge_command":
            replay = _find_by_command()
            if replay is not None and replay.acknowledge_request_fingerprint == fingerprint:
                return replay
            raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="equipment_incident.acknowledged",
        entity_type="equipment_incident", entity_id=incident.id, event_data={"code": incident.code},
    )
    db.commit()
    db.refresh(incident)
    return incident


def mark_action_in_progress(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, incident_id: uuid.UUID,
    client_command_id: uuid.UUID,
) -> EquipmentIncident:
    fingerprint = _fingerprint(tenant_id, incident_id, actor_user_id, "action_in_progress")

    def _find_by_command() -> EquipmentIncident | None:
        return db.execute(
            select(EquipmentIncident).where(
                EquipmentIncident.tenant_id == tenant_id,
                EquipmentIncident.action_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.action_request_fingerprint == fingerprint:
            return existing
        raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id))

    incident = _lock_incident(db, tenant_id=tenant_id, farm_id=farm_id, incident_id=incident_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.action_request_fingerprint == fingerprint:
            return existing
        raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id))

    if incident.status not in ("open", "acknowledged"):
        raise EquipmentIncidentInvalidTransitionError(
            f"incident {incident_id} cannot start action (status={incident.status})"
        )

    # Acknowledging is implied by starting action if it hasn't happened yet
    # -- never skips the acknowledged fields' own required shape.
    if incident.status == "open":
        incident.acknowledged_at = datetime.now(timezone.utc)
        incident.acknowledged_by_user_id = actor_user_id
    incident.status = "action_in_progress"
    incident.action_client_command_id = client_command_id
    incident.action_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_equipment_incidents_tenant_action_command":
            replay = _find_by_command()
            if replay is not None and replay.action_request_fingerprint == fingerprint:
                return replay
            raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="equipment_incident.action_in_progress",
        entity_type="equipment_incident", entity_id=incident.id, event_data={"code": incident.code},
    )
    db.commit()
    db.refresh(incident)
    return incident


def assign_incident(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, incident_id: uuid.UUID,
    client_command_id: uuid.UUID, assigned_owner_user_id: uuid.UUID | None,
) -> EquipmentIncident:
    fingerprint = _fingerprint(tenant_id, incident_id, assigned_owner_user_id)

    def _find_by_command() -> EquipmentIncident | None:
        return db.execute(
            select(EquipmentIncident).where(
                EquipmentIncident.tenant_id == tenant_id,
                EquipmentIncident.assign_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.assign_request_fingerprint == fingerprint:
            return existing
        raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id))

    incident = _lock_incident(db, tenant_id=tenant_id, farm_id=farm_id, incident_id=incident_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.assign_request_fingerprint == fingerprint:
            return existing
        raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id))

    if incident.status in INCIDENT_TERMINAL_STATUSES:
        raise EquipmentIncidentInvalidTransitionError(f"incident {incident_id} is already {incident.status}")

    incident.assigned_owner_user_id = assigned_owner_user_id
    incident.assign_client_command_id = client_command_id
    incident.assign_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_equipment_incidents_tenant_assign_command":
            replay = _find_by_command()
            if replay is not None and replay.assign_request_fingerprint == fingerprint:
                return replay
            raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="equipment_incident.assigned",
        entity_type="equipment_incident", entity_id=incident.id,
        event_data={
            "code": incident.code,
            "assigned_owner_user_id": str(assigned_owner_user_id) if assigned_owner_user_id else None,
        },
    )
    db.commit()
    db.refresh(incident)
    return incident


def resolve_incident(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, incident_id: uuid.UUID,
    client_command_id: uuid.UUID, resolution_note: str,
) -> EquipmentIncident:
    fingerprint = _fingerprint(tenant_id, incident_id, actor_user_id, "resolve", resolution_note)

    def _find_by_command() -> EquipmentIncident | None:
        return db.execute(
            select(EquipmentIncident).where(
                EquipmentIncident.tenant_id == tenant_id,
                EquipmentIncident.resolve_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.resolve_request_fingerprint == fingerprint:
            return existing
        raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id))

    incident = _lock_incident(db, tenant_id=tenant_id, farm_id=farm_id, incident_id=incident_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.resolve_request_fingerprint == fingerprint:
            return existing
        raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id))

    if incident.status not in ("open", "acknowledged", "action_in_progress"):
        raise EquipmentIncidentInvalidTransitionError(
            f"incident {incident_id} cannot be resolved (status={incident.status})"
        )

    incident.status = "resolved"
    incident.resolved_at = datetime.now(timezone.utc)
    incident.resolved_by_user_id = actor_user_id
    incident.resolution_note = resolution_note
    incident.resolve_client_command_id = client_command_id
    incident.resolve_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_equipment_incidents_tenant_resolve_command":
            replay = _find_by_command()
            if replay is not None and replay.resolve_request_fingerprint == fingerprint:
                return replay
            raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="equipment_incident.resolved",
        entity_type="equipment_incident", entity_id=incident.id,
        event_data={"code": incident.code, "resolution_note": resolution_note},
    )
    db.commit()
    db.refresh(incident)
    return incident


def close_incident(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, incident_id: uuid.UUID,
    client_command_id: uuid.UUID, close_note: str | None,
) -> EquipmentIncident:
    fingerprint = _fingerprint(tenant_id, incident_id, actor_user_id, "close", close_note)

    def _find_by_command() -> EquipmentIncident | None:
        return db.execute(
            select(EquipmentIncident).where(
                EquipmentIncident.tenant_id == tenant_id,
                EquipmentIncident.close_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.close_request_fingerprint == fingerprint:
            return existing
        raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id))

    incident = _lock_incident(db, tenant_id=tenant_id, farm_id=farm_id, incident_id=incident_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.close_request_fingerprint == fingerprint:
            return existing
        raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id))

    if incident.status != "resolved":
        raise EquipmentIncidentInvalidTransitionError(
            f"incident {incident_id} must be resolved before closing (status={incident.status})"
        )

    incident.status = "closed"
    incident.closed_at = datetime.now(timezone.utc)
    incident.closed_by_user_id = actor_user_id
    incident.close_note = close_note
    incident.close_client_command_id = client_command_id
    incident.close_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_equipment_incidents_tenant_close_command":
            replay = _find_by_command()
            if replay is not None and replay.close_request_fingerprint == fingerprint:
                return replay
            raise EquipmentIncidentCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="equipment_incident.closed",
        entity_type="equipment_incident", entity_id=incident.id,
        event_data={"code": incident.code, "close_note": close_note},
    )
    db.commit()
    db.refresh(incident)
    return incident


# --- reads -----------------------------------------------------------------------


def get_incident(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, incident_id: uuid.UUID
) -> EquipmentIncident:
    incident = db.execute(
        select(EquipmentIncident).where(
            EquipmentIncident.id == incident_id, EquipmentIncident.tenant_id == tenant_id,
            EquipmentIncident.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if incident is None:
        raise EquipmentIncidentNotFoundError(str(incident_id))
    return incident


def list_incidents(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, statuses: list[str] | None = None,
    asset_id: uuid.UUID | None = None, limit: int = MAX_LIST_LIMIT,
) -> list[EquipmentIncident]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    query = select(EquipmentIncident).where(
        EquipmentIncident.tenant_id == tenant_id, EquipmentIncident.farm_id == farm_id
    )
    if statuses:
        query = query.where(EquipmentIncident.status.in_(statuses))
    if asset_id is not None:
        query = query.where(EquipmentIncident.asset_id == asset_id)
    severity_rank = text(
        "CASE equipment_incidents.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
        "WHEN 'medium' THEN 2 ELSE 3 END"
    )
    query = query.order_by(severity_rank, EquipmentIncident.opened_at.desc()).limit(min(limit, MAX_LIST_LIMIT))
    return list(db.execute(query).scalars().all())


def list_open_critical_incidents(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, limit: int = MAX_LIST_LIMIT
) -> list[EquipmentIncident]:
    """PART 15: Today-on-the-Farm Equipment Attention feed -- every
    non-terminal Incident, ordered severity-first."""
    return list_incidents(
        db, tenant_id=tenant_id, farm_id=farm_id,
        statuses=["open", "acknowledged", "action_in_progress"], limit=limit,
    )


def resolve_read_context(
    db: Session, *, tenant_id: uuid.UUID, incidents: list[EquipmentIncident]
) -> dict[str, dict[uuid.UUID, object]]:
    """Bounded, batched lookups for the summaries `EquipmentIncidentRead`
    nests -- never one query per row (mirrors `farm_work_item_service.
    resolve_read_context`'s own established pattern)."""
    asset_ids = {i.asset_id for i in incidents}
    location_ids = {i.location_id for i in incidents if i.location_id} | {
        i.potentially_impacted_location_id for i in incidents if i.potentially_impacted_location_id
    }

    assets = {}
    if asset_ids:
        for row in db.execute(
            select(Asset.id, Asset.code, Asset.name, Asset.criticality).where(
                Asset.tenant_id == tenant_id, Asset.id.in_(asset_ids)
            )
        ):
            assets[row.id] = {"id": row.id, "code": row.code, "name": row.name, "criticality": row.criticality}

    locations = {}
    if location_ids:
        for row in db.execute(
            select(Location.id, Location.code, Location.name).where(
                Location.tenant_id == tenant_id, Location.id.in_(location_ids)
            )
        ):
            locations[row.id] = {"id": row.id, "code": row.code, "name": row.name}

    return {"assets": assets, "locations": locations}


def list_history(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, incident_id: uuid.UUID
) -> list[AuditEvent]:
    get_incident(db, tenant_id=tenant_id, farm_id=farm_id, incident_id=incident_id)
    return list(
        db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id, AuditEvent.entity_type == "equipment_incident",
                AuditEvent.entity_id == incident_id,
            )
            .order_by(AuditEvent.recorded_time.asc())
        ).scalars().all()
    )
