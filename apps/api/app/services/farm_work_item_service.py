"""PILOT-OPS-001: Farm Work Item service -- the small operational
task/assignment domain backing "Today on the Farm". A `FarmWorkItem` is a
CURRENT-STATE row (ADR-005): every mutating command here follows the same
per-command idempotency shape `location_service.deactivate_location`/
`update_location` established (UX-IA-001) -- pre-lock replay check, row
lock, post-lock replay recheck, mutate, flush with IntegrityError fallback,
`append_audit_event`, commit. Full lifecycle history is read back from
`audit_events` (`list_history`), never duplicated onto this row.

Never a substitute for the real GrowCMP transaction it may reference: an
OPERATIONAL_RECORD item can only reach COMPLETED through
`link_operational_result`, called by the owning domain service (harvest,
observation, ...) strictly *after* its own authoritative command has
already committed -- never before, and never repeating that command on a
link failure (see `link_operational_result`'s own docstring)."""

import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.audit_event import AuditEvent
from app.models.carrier import Carrier
from app.models.crop_batch import CropBatch
from app.models.crop_issue import CropIssue
from app.models.equipment_incident import EquipmentIncident
from app.models.farm_work_item import (
    WORK_ITEM_TERMINAL_STATUSES,
    FarmWorkItem,
)
from app.models.location import Location
from app.models.unit_of_measure import UnitOfMeasure
from app.services import asset_service, carrier_service, farm_service, location_service, membership_service
from app.services.audit import append_audit_event
from app.services.errors import (
    AssetNotFoundError,
    CarrierNotFoundError,
    CropBatchNotFoundError,
    CropIssueNotFoundError,
    EquipmentIncidentNotFoundError,
    FarmNotFoundError,
    FarmWorkItemCommandReusedWithDifferentPayloadError,
    FarmWorkItemInvalidTransitionError,
    FarmWorkItemManualCompletionNotAllowedError,
    FarmWorkItemNotAssignableError,
    FarmWorkItemNotFoundError,
    FarmWorkItemResultConflictError,
    FarmWorkItemWrongCompletionModeError,
    LocationNotFoundError,
    UnitOfMeasureNotFoundError,
    UserNotFoundError,
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


def _get_crop_batch_row(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, crop_batch_id: uuid.UUID) -> CropBatch:
    batch = db.execute(
        select(CropBatch).where(
            CropBatch.id == crop_batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(crop_batch_id))
    return batch


def _get_crop_issue_row(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, crop_issue_id: uuid.UUID) -> CropIssue:
    issue = db.execute(
        select(CropIssue).where(
            CropIssue.id == crop_issue_id, CropIssue.tenant_id == tenant_id, CropIssue.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if issue is None:
        raise CropIssueNotFoundError(str(crop_issue_id))
    return issue


def _get_equipment_incident_row(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, equipment_incident_id: uuid.UUID
) -> EquipmentIncident:
    incident = db.execute(
        select(EquipmentIncident).where(
            EquipmentIncident.id == equipment_incident_id, EquipmentIncident.tenant_id == tenant_id,
            EquipmentIncident.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if incident is None:
        raise EquipmentIncidentNotFoundError(str(equipment_incident_id))
    return incident


def _require_active_member(db: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    membership = membership_service.get_active_membership(db, tenant_id=tenant_id, user_id=user_id)
    if membership is None:
        raise UserNotFoundError(str(user_id))


def _require_uom(db: Session, *, uom_id: uuid.UUID) -> None:
    exists = db.execute(select(UnitOfMeasure.id).where(UnitOfMeasure.id == uom_id)).first()
    if exists is None:
        raise UnitOfMeasureNotFoundError(str(uom_id))


def _generate_work_item_code(db: Session, *, tenant_id: uuid.UUID, local_date: date) -> str:
    """Sequential per tenant per local calendar date -- `FW-YYYYMMDD-NNN`,
    serialized by a `pg_advisory_xact_lock` for the remainder of this
    transaction, exactly mirroring `nursery_service._generate_batch_code`'s
    established convention. No new sequence table."""
    lock_key = f"{tenant_id}:farm_work_item_code:{local_date.isoformat()}"
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key})
    prefix = f"FW-{local_date.strftime('%Y%m%d')}-"
    seq = 1
    while True:
        code = f"{prefix}{seq:04d}"
        exists = db.execute(
            select(FarmWorkItem.id).where(FarmWorkItem.tenant_id == tenant_id, FarmWorkItem.code.ilike(code))
        ).first()
        if exists is None:
            return code
        seq += 1


def _lock_work_item(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, work_item_id: uuid.UUID) -> FarmWorkItem:
    item = db.execute(
        select(FarmWorkItem)
        .where(
            FarmWorkItem.id == work_item_id, FarmWorkItem.tenant_id == tenant_id, FarmWorkItem.farm_id == farm_id
        )
        .with_for_update()
    ).scalar_one_or_none()
    if item is None:
        raise FarmWorkItemNotFoundError(str(work_item_id))
    return item


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


# --- create ------------------------------------------------------------------------


def create_work_item(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    work_type: str,
    category: str,
    title: str,
    instructions: str | None,
    priority: str,
    due_at: datetime | None,
    assigned_to_user_id: uuid.UUID | None,
    crop_batch_id: uuid.UUID | None,
    location_id: uuid.UUID | None,
    carrier_id: uuid.UUID | None,
    asset_id: uuid.UUID | None,
    quantity: Decimal | None,
    quantity_uom_id: uuid.UUID | None,
    completion_mode: str,
    crop_issue_id: uuid.UUID | None = None,
    equipment_incident_id: uuid.UUID | None = None,
) -> FarmWorkItem:
    """`crop_issue_id` (PILOT-AGRO-001): the optional CropIssue this Work
    Item is corrective action FOR (section 12). `equipment_incident_id`
    (PILOT-ASSET-001): the optional EquipmentIncident this Work Item is
    corrective action FOR, mirroring `crop_issue_id` exactly -- linking
    never resolves the Incident (see equipment_incident_service). Both
    defaulted, not a required positional-equivalent, so every pre-existing
    caller of this function is completely unaffected."""
    farm = _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    def _find_by_command() -> FarmWorkItem | None:
        return db.execute(
            select(FarmWorkItem).where(
                FarmWorkItem.tenant_id == tenant_id, FarmWorkItem.client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    fingerprint = _fingerprint(
        tenant_id, farm_id, actor_user_id, work_type, category, title, instructions, priority, due_at,
        assigned_to_user_id, crop_batch_id, location_id, carrier_id, asset_id, quantity, quantity_uom_id,
        completion_mode, crop_issue_id, equipment_incident_id,
    )

    existing = _find_by_command()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    if assigned_to_user_id is not None:
        _require_active_member(db, tenant_id=tenant_id, user_id=assigned_to_user_id)
    if crop_batch_id is not None:
        _get_crop_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=crop_batch_id)
    if location_id is not None:
        location_service.get_location(db, tenant_id=tenant_id, farm_id=farm_id, location_id=location_id)
    if carrier_id is not None:
        carrier_service.get_carrier(db, tenant_id=tenant_id, farm_id=farm_id, carrier_id=carrier_id)
    if asset_id is not None:
        asset_service.get_asset(db, tenant_id=tenant_id, farm_id=farm_id, asset_id=asset_id)
    if crop_issue_id is not None:
        _get_crop_issue_row(db, tenant_id=tenant_id, farm_id=farm_id, crop_issue_id=crop_issue_id)
    if equipment_incident_id is not None:
        _get_equipment_incident_row(
            db, tenant_id=tenant_id, farm_id=farm_id, equipment_incident_id=equipment_incident_id
        )
    if quantity_uom_id is not None:
        _require_uom(db, uom_id=quantity_uom_id)

    local_date = datetime.now(timezone.utc).astimezone(ZoneInfo(farm.timezone)).date()
    code = _generate_work_item_code(db, tenant_id=tenant_id, local_date=local_date)

    item = FarmWorkItem(
        tenant_id=tenant_id,
        farm_id=farm_id,
        code=code,
        work_type=work_type,
        category=category,
        title=title,
        instructions=instructions,
        status="open",
        priority=priority,
        due_at=due_at,
        assigned_to_user_id=assigned_to_user_id,
        crop_batch_id=crop_batch_id,
        location_id=location_id,
        carrier_id=carrier_id,
        asset_id=asset_id,
        crop_issue_id=crop_issue_id,
        equipment_incident_id=equipment_incident_id,
        quantity=quantity,
        quantity_uom_id=quantity_uom_id,
        completion_mode=completion_mode,
        created_by_user_id=actor_user_id,
        client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_farm_work_items_tenant_client_command_id":
            replay = _find_by_command()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="farm_work_item.created",
        entity_type="farm_work_item", entity_id=item.id,
        event_data={
            "code": item.code, "work_type": work_type, "category": category, "title": title,
            "priority": priority, "assigned_to_user_id": str(assigned_to_user_id) if assigned_to_user_id else None,
            "completion_mode": completion_mode,
            "crop_issue_id": str(crop_issue_id) if crop_issue_id else None,
            "equipment_incident_id": str(equipment_incident_id) if equipment_incident_id else None,
        },
    )
    db.commit()
    db.refresh(item)
    return item


# --- supervisory update (reassign / priority / due window) -----------------------


def update_work_item(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    work_item_id: uuid.UUID,
    client_command_id: uuid.UUID,
    assigned_to_user_id: uuid.UUID | None,
    priority: str,
    due_at: datetime | None,
) -> FarmWorkItem:
    fingerprint = _fingerprint(tenant_id, work_item_id, assigned_to_user_id, priority, due_at)

    def _find_by_command() -> FarmWorkItem | None:
        return db.execute(
            select(FarmWorkItem).where(
                FarmWorkItem.tenant_id == tenant_id, FarmWorkItem.update_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    item = _lock_work_item(db, tenant_id=tenant_id, farm_id=farm_id, work_item_id=work_item_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    if item.status in WORK_ITEM_TERMINAL_STATUSES:
        raise FarmWorkItemInvalidTransitionError(f"work item {work_item_id} is already {item.status}")

    if assigned_to_user_id is not None:
        _require_active_member(db, tenant_id=tenant_id, user_id=assigned_to_user_id)

    before = {
        "assigned_to_user_id": str(item.assigned_to_user_id) if item.assigned_to_user_id else None,
        "priority": item.priority, "due_at": item.due_at.isoformat() if item.due_at else None,
    }
    item.assigned_to_user_id = assigned_to_user_id
    item.priority = priority
    item.due_at = due_at
    item.update_client_command_id = client_command_id
    item.update_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_farm_work_items_tenant_update_command":
            replay = _find_by_command()
            if replay is not None and replay.update_request_fingerprint == fingerprint:
                return replay
            raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="farm_work_item.updated",
        entity_type="farm_work_item", entity_id=item.id,
        event_data={
            "code": item.code, "before": before,
            "after": {
                "assigned_to_user_id": str(assigned_to_user_id) if assigned_to_user_id else None,
                "priority": priority, "due_at": due_at.isoformat() if due_at else None,
            },
        },
    )
    db.commit()
    db.refresh(item)
    return item


# --- lifecycle transitions ----------------------------------------------------------


def start_work_item(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    work_item_id: uuid.UUID, client_command_id: uuid.UUID,
) -> FarmWorkItem:
    fingerprint = _fingerprint(tenant_id, work_item_id, actor_user_id, "start")

    def _find_by_command() -> FarmWorkItem | None:
        return db.execute(
            select(FarmWorkItem).where(
                FarmWorkItem.tenant_id == tenant_id, FarmWorkItem.start_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.start_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    item = _lock_work_item(db, tenant_id=tenant_id, farm_id=farm_id, work_item_id=work_item_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.start_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    if item.status != "open":
        raise FarmWorkItemInvalidTransitionError(f"work item {work_item_id} is not open (status={item.status})")
    if item.assigned_to_user_id is not None and item.assigned_to_user_id != actor_user_id:
        raise FarmWorkItemNotAssignableError(str(work_item_id))

    item.status = "in_progress"
    item.start_client_command_id = client_command_id
    item.start_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_farm_work_items_tenant_start_command":
            replay = _find_by_command()
            if replay is not None and replay.start_request_fingerprint == fingerprint:
                return replay
            raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="farm_work_item.started",
        entity_type="farm_work_item", entity_id=item.id, event_data={"code": item.code},
    )
    db.commit()
    db.refresh(item)
    return item


def block_work_item(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    work_item_id: uuid.UUID, client_command_id: uuid.UUID, reason: str,
) -> FarmWorkItem:
    fingerprint = _fingerprint(tenant_id, work_item_id, actor_user_id, "block", reason)

    def _find_by_command() -> FarmWorkItem | None:
        return db.execute(
            select(FarmWorkItem).where(
                FarmWorkItem.tenant_id == tenant_id, FarmWorkItem.block_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.block_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    item = _lock_work_item(db, tenant_id=tenant_id, farm_id=farm_id, work_item_id=work_item_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.block_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    if item.status not in ("open", "in_progress"):
        raise FarmWorkItemInvalidTransitionError(f"work item {work_item_id} cannot be blocked (status={item.status})")

    item.status = "blocked"
    item.blocked_reason = reason
    item.blocked_at = datetime.now(timezone.utc)
    item.blocked_by_user_id = actor_user_id
    item.block_client_command_id = client_command_id
    item.block_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_farm_work_items_tenant_block_command":
            replay = _find_by_command()
            if replay is not None and replay.block_request_fingerprint == fingerprint:
                return replay
            raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="farm_work_item.blocked",
        entity_type="farm_work_item", entity_id=item.id, event_data={"code": item.code, "reason": reason},
    )
    db.commit()
    db.refresh(item)
    return item


def unblock_work_item(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    work_item_id: uuid.UUID, client_command_id: uuid.UUID,
) -> FarmWorkItem:
    fingerprint = _fingerprint(tenant_id, work_item_id, actor_user_id, "unblock")

    def _find_by_command() -> FarmWorkItem | None:
        return db.execute(
            select(FarmWorkItem).where(
                FarmWorkItem.tenant_id == tenant_id, FarmWorkItem.unblock_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.unblock_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    item = _lock_work_item(db, tenant_id=tenant_id, farm_id=farm_id, work_item_id=work_item_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.unblock_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    if item.status != "blocked":
        raise FarmWorkItemInvalidTransitionError(f"work item {work_item_id} is not blocked (status={item.status})")

    reason_before = item.blocked_reason
    item.status = "in_progress"
    item.blocked_reason = None
    item.blocked_at = None
    item.blocked_by_user_id = None
    item.unblock_client_command_id = client_command_id
    item.unblock_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_farm_work_items_tenant_unblock_command":
            replay = _find_by_command()
            if replay is not None and replay.unblock_request_fingerprint == fingerprint:
                return replay
            raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="farm_work_item.unblocked",
        entity_type="farm_work_item", entity_id=item.id,
        event_data={"code": item.code, "previous_blocked_reason": reason_before},
    )
    db.commit()
    db.refresh(item)
    return item


def complete_work_item(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    work_item_id: uuid.UUID, client_command_id: uuid.UUID, completion_note: str | None,
) -> FarmWorkItem:
    """MANUAL_RECORD completion only -- see `FarmWorkItem.completion_mode`.
    An OPERATIONAL_RECORD item can never be checked off here; it can only
    reach COMPLETED through `link_operational_result`."""
    fingerprint = _fingerprint(tenant_id, work_item_id, actor_user_id, "complete", completion_note)

    def _find_by_command() -> FarmWorkItem | None:
        return db.execute(
            select(FarmWorkItem).where(
                FarmWorkItem.tenant_id == tenant_id, FarmWorkItem.complete_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.complete_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    item = _lock_work_item(db, tenant_id=tenant_id, farm_id=farm_id, work_item_id=work_item_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.complete_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    if item.completion_mode != "manual_record":
        raise FarmWorkItemManualCompletionNotAllowedError(str(work_item_id))
    if item.status not in ("open", "in_progress"):
        raise FarmWorkItemInvalidTransitionError(f"work item {work_item_id} cannot be completed (status={item.status})")
    if item.assigned_to_user_id is not None and item.assigned_to_user_id != actor_user_id:
        raise FarmWorkItemNotAssignableError(str(work_item_id))

    item.status = "completed"
    item.completed_at = datetime.now(timezone.utc)
    item.completed_by_user_id = actor_user_id
    item.completion_note = completion_note
    item.complete_client_command_id = client_command_id
    item.complete_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_farm_work_items_tenant_complete_command":
            replay = _find_by_command()
            if replay is not None and replay.complete_request_fingerprint == fingerprint:
                return replay
            raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="farm_work_item.completed",
        entity_type="farm_work_item", entity_id=item.id,
        event_data={"code": item.code, "completion_mode": "manual_record"},
    )
    db.commit()
    db.refresh(item)
    return item


def cancel_work_item(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    work_item_id: uuid.UUID, client_command_id: uuid.UUID, reason: str | None,
) -> FarmWorkItem:
    fingerprint = _fingerprint(tenant_id, work_item_id, actor_user_id, "cancel", reason)

    def _find_by_command() -> FarmWorkItem | None:
        return db.execute(
            select(FarmWorkItem).where(
                FarmWorkItem.tenant_id == tenant_id, FarmWorkItem.cancel_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.cancel_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    item = _lock_work_item(db, tenant_id=tenant_id, farm_id=farm_id, work_item_id=work_item_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.cancel_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    if item.status in WORK_ITEM_TERMINAL_STATUSES:
        raise FarmWorkItemInvalidTransitionError(f"work item {work_item_id} is already {item.status}")

    item.status = "cancelled"
    item.blocked_reason = None
    item.blocked_at = None
    item.blocked_by_user_id = None
    item.cancelled_at = datetime.now(timezone.utc)
    item.cancelled_by_user_id = actor_user_id
    item.cancel_reason = reason
    item.cancel_client_command_id = client_command_id
    item.cancel_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_farm_work_items_tenant_cancel_command":
            replay = _find_by_command()
            if replay is not None and replay.cancel_request_fingerprint == fingerprint:
                return replay
            raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="farm_work_item.cancelled",
        entity_type="farm_work_item", entity_id=item.id, event_data={"code": item.code, "reason": reason},
    )
    db.commit()
    db.refresh(item)
    return item


# --- transaction-backed (operational-record) completion ----------------------------


def link_operational_result(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    work_item_id: uuid.UUID,
    client_command_id: uuid.UUID,
    result_entity_type: str,
    result_entity_id: uuid.UUID,
    effective_time: datetime,
) -> FarmWorkItem:
    """Completes an OPERATIONAL_RECORD Work Item by linking it to the
    already-committed authoritative record (`result_entity_type`/
    `result_entity_id`) -- called strictly AFTER that record's own command
    has committed (see `harvest_service.record_harvest`/
    `observation_service.record_observation`'s own call sites). Never
    raises for "this exact result is already linked" -- that is the
    documented retry/replay no-op case (CLAUDE.md "Transaction-backed
    completion": "retry/replay does not create duplicate Work Item
    completion"). A DIFFERENT result already linked to a COMPLETED item is
    a genuine conflict and is rejected."""
    fingerprint = _fingerprint(tenant_id, work_item_id, result_entity_type, result_entity_id)

    def _find_by_command() -> FarmWorkItem | None:
        return db.execute(
            select(FarmWorkItem).where(
                FarmWorkItem.tenant_id == tenant_id,
                FarmWorkItem.link_result_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.link_result_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    item = _lock_work_item(db, tenant_id=tenant_id, farm_id=farm_id, work_item_id=work_item_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.link_result_request_fingerprint == fingerprint:
            return existing
        raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id))

    if item.completion_mode != "operational_record":
        raise FarmWorkItemWrongCompletionModeError(str(work_item_id))

    if item.status == "completed":
        if item.result_entity_type == result_entity_type and item.result_entity_id == result_entity_id:
            # Idempotent no-op: a different client_command_id (e.g. a UI
            # reconciliation retry) pointing at the same already-linked
            # result. Nothing to change.
            return item
        raise FarmWorkItemResultConflictError(str(work_item_id))

    if item.status == "cancelled":
        raise FarmWorkItemInvalidTransitionError(f"work item {work_item_id} is cancelled")

    item.status = "completed"
    item.completed_at = datetime.now(timezone.utc)
    item.result_entity_type = result_entity_type
    item.result_entity_id = result_entity_id
    item.result_recorded_at = effective_time
    item.blocked_reason = None
    item.blocked_at = None
    item.blocked_by_user_id = None
    item.link_result_client_command_id = client_command_id
    item.link_result_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_farm_work_items_tenant_link_result_command":
            replay = _find_by_command()
            if replay is not None and replay.link_result_request_fingerprint == fingerprint:
                return replay
            raise FarmWorkItemCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="farm_work_item.completed",
        entity_type="farm_work_item", entity_id=item.id,
        event_data={
            "code": item.code, "completion_mode": "operational_record",
            "result_entity_type": result_entity_type, "result_entity_id": str(result_entity_id),
        },
    )
    db.commit()
    db.refresh(item)
    return item


def link_operational_result_best_effort(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    work_item_id: uuid.UUID,
    client_command_id: uuid.UUID,
    result_entity_type: str,
    result_entity_id: uuid.UUID,
    effective_time: datetime,
) -> str:
    """Wraps `link_operational_result` for call sites where the
    authoritative operation (Harvest, Observation, ...) has ALREADY
    committed successfully: linking failure must never be surfaced as if
    the operation itself failed, and the operation must never be repeated
    (CLAUDE.md "Transaction-backed completion"). Returns "linked" or
    "failed" for the caller's own response (never raises); the caller's
    session is left usable either way -- a failure here rolls back only
    this link attempt, not the already-committed operation."""
    try:
        link_operational_result(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, work_item_id=work_item_id,
            client_command_id=client_command_id, result_entity_type=result_entity_type,
            result_entity_id=result_entity_id, effective_time=effective_time,
        )
        return "linked"
    except Exception:
        db.rollback()
        return "failed"


# --- reads -----------------------------------------------------------------------


def get_work_item(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, work_item_id: uuid.UUID) -> FarmWorkItem:
    item = db.execute(
        select(FarmWorkItem).where(
            FarmWorkItem.id == work_item_id, FarmWorkItem.tenant_id == tenant_id, FarmWorkItem.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if item is None:
        raise FarmWorkItemNotFoundError(str(work_item_id))
    return item


def list_work_items(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    statuses: list[str] | None = None,
    assigned_to_user_id: uuid.UUID | None = None,
    include_completed: bool = False,
    limit: int = MAX_LIST_LIMIT,
) -> list[FarmWorkItem]:
    """One bounded, set-based board read -- the frontend derives every
    section (My Work / Blocked / In Progress / Carryover / Farm Work) from
    this single list via a pure function, mirroring
    `computeHomeKpis`/`groupBatchesByStage`'s existing precedent on the
    Farm Home page, rather than one backend endpoint per section."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    query = select(FarmWorkItem).where(FarmWorkItem.tenant_id == tenant_id, FarmWorkItem.farm_id == farm_id)
    if statuses:
        query = query.where(FarmWorkItem.status.in_(statuses))
    elif not include_completed:
        query = query.where(FarmWorkItem.status.notin_(WORK_ITEM_TERMINAL_STATUSES))
    if assigned_to_user_id is not None:
        query = query.where(FarmWorkItem.assigned_to_user_id == assigned_to_user_id)
    priority_rank = text(
        "CASE farm_work_items.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END"
    )
    query = query.order_by(priority_rank, FarmWorkItem.due_at.asc().nulls_last(), FarmWorkItem.created_at.asc())
    query = query.limit(min(limit, MAX_LIST_LIMIT))
    return list(db.execute(query).scalars().all())


def list_work_items_for_context(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    crop_batch_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    carrier_id: uuid.UUID | None = None,
    asset_id: uuid.UUID | None = None,
    limit: int = 20,
) -> list[FarmWorkItem]:
    """PILOT-SCAN-001: open/in-progress/blocked Work Items matching one of
    this Farm Work Item's own structured context references -- reused by
    the QR scan resolver so a scanned Table/Batch/Carrier surfaces its
    relevant work without inferring any relationship this ticket didn't
    already establish. Never returns a completed/cancelled item (matches
    `list_work_items`'s own default). Exactly one of the four context ids
    should normally be given; if more than one is, an item matching ANY of
    them is returned (a plain OR), consistent with each column being an
    independent structured reference on the same row."""
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    conditions = []
    if crop_batch_id is not None:
        conditions.append(FarmWorkItem.crop_batch_id == crop_batch_id)
    if location_id is not None:
        conditions.append(FarmWorkItem.location_id == location_id)
    if carrier_id is not None:
        conditions.append(FarmWorkItem.carrier_id == carrier_id)
    if asset_id is not None:
        conditions.append(FarmWorkItem.asset_id == asset_id)
    if not conditions:
        return []
    query = (
        select(FarmWorkItem)
        .where(
            FarmWorkItem.tenant_id == tenant_id,
            FarmWorkItem.farm_id == farm_id,
            FarmWorkItem.status.notin_(WORK_ITEM_TERMINAL_STATUSES),
            or_(*conditions),
        )
        .order_by(FarmWorkItem.created_at.desc())
        .limit(min(limit, MAX_LIST_LIMIT))
    )
    return list(db.execute(query).scalars().all())


def list_history(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, work_item_id: uuid.UUID
) -> list[AuditEvent]:
    get_work_item(db, tenant_id=tenant_id, farm_id=farm_id, work_item_id=work_item_id)
    return list(
        db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.entity_type == "farm_work_item",
                AuditEvent.entity_id == work_item_id,
            )
            .order_by(AuditEvent.recorded_time.asc())
        ).scalars().all()
    )


def resolve_read_context(
    db: Session, *, tenant_id: uuid.UUID, items: list[FarmWorkItem]
) -> dict[str, dict[uuid.UUID, object]]:
    """Bounded, batched lookups (one query per referenced entity kind) for
    the summaries `FarmWorkItemRead` nests -- never one query per row."""
    batch_ids = {i.crop_batch_id for i in items if i.crop_batch_id}
    location_ids = {i.location_id for i in items if i.location_id}
    carrier_ids = {i.carrier_id for i in items if i.carrier_id}
    asset_ids = {i.asset_id for i in items if i.asset_id}
    crop_issue_ids = {i.crop_issue_id for i in items if i.crop_issue_id}
    equipment_incident_ids = {i.equipment_incident_id for i in items if i.equipment_incident_id}
    uom_ids = {i.quantity_uom_id for i in items if i.quantity_uom_id}

    batches = {}
    if batch_ids:
        for row in db.execute(
            select(CropBatch.id, CropBatch.code).where(CropBatch.tenant_id == tenant_id, CropBatch.id.in_(batch_ids))
        ):
            batches[row.id] = {"id": row.id, "code": row.code}

    locations = {}
    if location_ids:
        for row in db.execute(
            select(Location.id, Location.code, Location.name).where(
                Location.tenant_id == tenant_id, Location.id.in_(location_ids)
            )
        ):
            locations[row.id] = {"id": row.id, "code": row.code, "name": row.name}

    carriers = {}
    if carrier_ids:
        for row in db.execute(
            select(Carrier.id, Carrier.code).where(Carrier.tenant_id == tenant_id, Carrier.id.in_(carrier_ids))
        ):
            carriers[row.id] = {"id": row.id, "code": row.code}

    assets = {}
    if asset_ids:
        for row in db.execute(
            select(Asset.id, Asset.code, Asset.name).where(Asset.tenant_id == tenant_id, Asset.id.in_(asset_ids))
        ):
            assets[row.id] = {"id": row.id, "code": row.code, "name": row.name}

    uoms = {}
    if uom_ids:
        for row in db.execute(select(UnitOfMeasure.id, UnitOfMeasure.code).where(UnitOfMeasure.id.in_(uom_ids))):
            uoms[row.id] = {"id": row.id, "code": row.code}

    crop_issues = {}
    if crop_issue_ids:
        for row in db.execute(
            select(CropIssue.id, CropIssue.code, CropIssue.status).where(
                CropIssue.tenant_id == tenant_id, CropIssue.id.in_(crop_issue_ids)
            )
        ):
            crop_issues[row.id] = {"id": row.id, "code": row.code, "status": row.status}

    equipment_incidents = {}
    if equipment_incident_ids:
        for row in db.execute(
            select(EquipmentIncident.id, EquipmentIncident.code, EquipmentIncident.status).where(
                EquipmentIncident.tenant_id == tenant_id, EquipmentIncident.id.in_(equipment_incident_ids)
            )
        ):
            equipment_incidents[row.id] = {"id": row.id, "code": row.code, "status": row.status}

    return {
        "crop_batches": batches, "locations": locations, "carriers": carriers, "assets": assets, "uoms": uoms,
        "crop_issues": crop_issues, "equipment_incidents": equipment_incidents,
    }
