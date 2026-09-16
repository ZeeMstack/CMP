"""PILOT-AGRO-001: Crop Issue lifecycle (OPEN -> RESOLVED -> CLOSED, never
reopened) plus Issue Follow-ups. `suspected_cause` and `confirmed_
diagnosis` are two permanently distinct fields -- no command here ever
copies one into the other (section 11). Work Item linkage reuses
`FarmWorkItem.crop_issue_id` (set only at Work Item creation, see
`farm_work_item_service.create_work_item`) -- completing that Work Item
never resolves this Issue (section WORK ITEM COMPLETE != ISSUE RESOLVED);
resolution and closure are always the two deliberate, separate commands
below."""

import hashlib
import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crop_issue import CropIssue
from app.models.crop_issue_follow_up import CropIssueFollowUp
from app.models.farm_work_item import WORK_ITEM_TERMINAL_STATUSES, FarmWorkItem
from app.models.grower_inspection import GrowerInspection
from app.models.inspection_finding import InspectionFinding
from app.services.audit import append_audit_event
from app.services.errors import (
    CropIssueCommandReusedWithDifferentPayloadError,
    CropIssueFollowUpCommandReusedWithDifferentPayloadError,
    CropIssueInvalidTransitionError,
    CropIssueNotFoundError,
    FarmNotFoundError,
    GrowerInspectionNotFoundError,
)
from app.services import farm_service


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


def _generate_issue_code(db: Session, *, tenant_id: uuid.UUID, local_date: date) -> str:
    """Sequential per tenant per local calendar date -- `CI-YYYYMMDD-NNNN`,
    mirrors `farm_work_item_service._generate_work_item_code` exactly."""
    lock_key = f"{tenant_id}:crop_issue_code:{local_date.isoformat()}"
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key})
    prefix = f"CI-{local_date.strftime('%Y%m%d')}-"
    seq = 1
    while True:
        code = f"{prefix}{seq:04d}"
        exists = db.execute(
            select(CropIssue.id).where(CropIssue.tenant_id == tenant_id, CropIssue.code.ilike(code))
        ).first()
        if exists is None:
            return code
        seq += 1


def _lock_issue(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, crop_issue_id: uuid.UUID) -> CropIssue:
    issue = db.execute(
        select(CropIssue)
        .where(CropIssue.id == crop_issue_id, CropIssue.tenant_id == tenant_id, CropIssue.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if issue is None:
        raise CropIssueNotFoundError(str(crop_issue_id))
    return issue


# --- open ----------------------------------------------------------------------------


def open_crop_issue(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    originating_grower_inspection_id: uuid.UUID,
    originating_finding_id: uuid.UUID | None,
    category: str,
    severity: str,
    description: str,
    suspected_cause: str | None,
    assigned_owner_user_id: uuid.UUID | None,
    follow_up_due_at: datetime | None,
) -> CropIssue:
    fingerprint = _fingerprint(
        tenant_id, farm_id, originating_grower_inspection_id, originating_finding_id, category, severity,
        description, suspected_cause, assigned_owner_user_id, follow_up_due_at,
    )

    def _find_by_command() -> CropIssue | None:
        return db.execute(
            select(CropIssue).where(CropIssue.tenant_id == tenant_id, CropIssue.client_command_id == client_command_id)
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id))

    farm = _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    inspection = db.execute(
        select(GrowerInspection).where(
            GrowerInspection.id == originating_grower_inspection_id, GrowerInspection.tenant_id == tenant_id,
            GrowerInspection.farm_id == farm_id,
        )
    ).scalar_one_or_none()
    if inspection is None:
        raise GrowerInspectionNotFoundError(str(originating_grower_inspection_id))

    if originating_finding_id is not None:
        finding = db.execute(
            select(InspectionFinding).where(
                InspectionFinding.id == originating_finding_id, InspectionFinding.tenant_id == tenant_id,
                InspectionFinding.grower_inspection_id == originating_grower_inspection_id,
            )
        ).scalar_one_or_none()
        if finding is None:
            raise CropIssueInvalidTransitionError(f"finding {originating_finding_id} does not belong to inspection {originating_grower_inspection_id}")

    existing = _find_by_command()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id))

    local_date = datetime.now(timezone.utc).astimezone(ZoneInfo(farm.timezone)).date()
    code = _generate_issue_code(db, tenant_id=tenant_id, local_date=local_date)

    issue = CropIssue(
        tenant_id=tenant_id, farm_id=farm_id, code=code, batch_id=inspection.batch_id,
        batch_carrier_assignment_id=inspection.batch_carrier_assignment_id, location_id=inspection.location_id,
        originating_grower_inspection_id=originating_grower_inspection_id, originating_finding_id=originating_finding_id,
        category=category, severity=severity, description=description, suspected_cause=suspected_cause,
        status="open", opened_by_user_id=actor_user_id, assigned_owner_user_id=assigned_owner_user_id,
        follow_up_due_at=follow_up_due_at, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(issue)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_crop_issues_tenant_client_command_id":
            replay = _find_by_command()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_issue.opened", entity_type="crop_issue",
        entity_id=issue.id,
        event_data={
            "code": issue.code, "batch_id": str(issue.batch_id), "category": category, "severity": severity,
            "originating_grower_inspection_id": str(originating_grower_inspection_id),
        },
    )
    db.commit()
    db.refresh(issue)
    return issue


# --- update / diagnosis / resolve / close ---------------------------------------------


def update_crop_issue(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, crop_issue_id: uuid.UUID,
    client_command_id: uuid.UUID, severity: str, assigned_owner_user_id: uuid.UUID | None,
    follow_up_due_at: datetime | None, suspected_cause: str | None,
) -> CropIssue:
    fingerprint = _fingerprint(tenant_id, crop_issue_id, severity, assigned_owner_user_id, follow_up_due_at, suspected_cause)

    def _find_by_command() -> CropIssue | None:
        return db.execute(
            select(CropIssue).where(
                CropIssue.tenant_id == tenant_id, CropIssue.update_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id))

    issue = _lock_issue(db, tenant_id=tenant_id, farm_id=farm_id, crop_issue_id=crop_issue_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.update_request_fingerprint == fingerprint:
            return existing
        raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id))

    if issue.status == "closed":
        raise CropIssueInvalidTransitionError(f"crop issue {crop_issue_id} is closed")

    before = {
        "severity": issue.severity, "assigned_owner_user_id": str(issue.assigned_owner_user_id) if issue.assigned_owner_user_id else None,
        "follow_up_due_at": issue.follow_up_due_at.isoformat() if issue.follow_up_due_at else None,
    }
    issue.severity = severity
    issue.assigned_owner_user_id = assigned_owner_user_id
    issue.follow_up_due_at = follow_up_due_at
    issue.suspected_cause = suspected_cause
    issue.update_client_command_id = client_command_id
    issue.update_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_crop_issues_tenant_update_command":
            replay = _find_by_command()
            if replay is not None and replay.update_request_fingerprint == fingerprint:
                return replay
            raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_issue.updated", entity_type="crop_issue",
        entity_id=issue.id, event_data={"code": issue.code, "before": before},
    )
    db.commit()
    db.refresh(issue)
    return issue


def confirm_diagnosis(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, crop_issue_id: uuid.UUID,
    client_command_id: uuid.UUID, confirmed_diagnosis: str,
) -> CropIssue:
    fingerprint = _fingerprint(tenant_id, crop_issue_id, confirmed_diagnosis)

    def _find_by_command() -> CropIssue | None:
        return db.execute(
            select(CropIssue).where(
                CropIssue.tenant_id == tenant_id, CropIssue.diagnosis_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.diagnosis_request_fingerprint == fingerprint:
            return existing
        raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id))

    issue = _lock_issue(db, tenant_id=tenant_id, farm_id=farm_id, crop_issue_id=crop_issue_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.diagnosis_request_fingerprint == fingerprint:
            return existing
        raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id))

    if issue.status == "closed":
        raise CropIssueInvalidTransitionError(f"crop issue {crop_issue_id} is closed")

    issue.confirmed_diagnosis = confirmed_diagnosis
    issue.diagnosis_confirmed_by_user_id = actor_user_id
    issue.diagnosis_confirmed_at = datetime.now(timezone.utc)
    issue.diagnosis_client_command_id = client_command_id
    issue.diagnosis_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_crop_issues_tenant_diagnosis_command":
            replay = _find_by_command()
            if replay is not None and replay.diagnosis_request_fingerprint == fingerprint:
                return replay
            raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_issue.diagnosis_confirmed",
        entity_type="crop_issue", entity_id=issue.id,
        event_data={"code": issue.code, "confirmed_diagnosis": confirmed_diagnosis, "suspected_cause": issue.suspected_cause},
    )
    db.commit()
    db.refresh(issue)
    return issue


def resolve_crop_issue(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, crop_issue_id: uuid.UUID,
    client_command_id: uuid.UUID, resolution_note: str,
) -> CropIssue:
    fingerprint = _fingerprint(tenant_id, crop_issue_id, resolution_note)

    def _find_by_command() -> CropIssue | None:
        return db.execute(
            select(CropIssue).where(
                CropIssue.tenant_id == tenant_id, CropIssue.resolve_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.resolve_request_fingerprint == fingerprint:
            return existing
        raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id))

    issue = _lock_issue(db, tenant_id=tenant_id, farm_id=farm_id, crop_issue_id=crop_issue_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.resolve_request_fingerprint == fingerprint:
            return existing
        raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id))

    if issue.status != "open":
        raise CropIssueInvalidTransitionError(f"crop issue {crop_issue_id} is not open (status={issue.status})")

    issue.status = "resolved"
    issue.resolved_by_user_id = actor_user_id
    issue.resolved_at = datetime.now(timezone.utc)
    issue.resolution_note = resolution_note
    issue.resolve_client_command_id = client_command_id
    issue.resolve_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_crop_issues_tenant_resolve_command":
            replay = _find_by_command()
            if replay is not None and replay.resolve_request_fingerprint == fingerprint:
                return replay
            raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_issue.resolved", entity_type="crop_issue",
        entity_id=issue.id, event_data={"code": issue.code, "resolution_note": resolution_note},
    )
    db.commit()
    db.refresh(issue)
    return issue


def close_crop_issue(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, crop_issue_id: uuid.UUID,
    client_command_id: uuid.UUID, close_note: str | None,
) -> CropIssue:
    fingerprint = _fingerprint(tenant_id, crop_issue_id, close_note)

    def _find_by_command() -> CropIssue | None:
        return db.execute(
            select(CropIssue).where(
                CropIssue.tenant_id == tenant_id, CropIssue.close_client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.close_request_fingerprint == fingerprint:
            return existing
        raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id))

    issue = _lock_issue(db, tenant_id=tenant_id, farm_id=farm_id, crop_issue_id=crop_issue_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.close_request_fingerprint == fingerprint:
            return existing
        raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id))

    if issue.status != "resolved":
        raise CropIssueInvalidTransitionError(f"crop issue {crop_issue_id} is not resolved (status={issue.status})")

    issue.status = "closed"
    issue.closed_by_user_id = actor_user_id
    issue.closed_at = datetime.now(timezone.utc)
    issue.close_note = close_note
    issue.close_client_command_id = client_command_id
    issue.close_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_crop_issues_tenant_close_command":
            replay = _find_by_command()
            if replay is not None and replay.close_request_fingerprint == fingerprint:
                return replay
            raise CropIssueCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_issue.closed", entity_type="crop_issue",
        entity_id=issue.id, event_data={"code": issue.code, "close_note": close_note},
    )
    db.commit()
    db.refresh(issue)
    return issue


# --- follow-up -------------------------------------------------------------------------


def record_follow_up(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, crop_issue_id: uuid.UUID,
    client_command_id: uuid.UUID, follow_up_grower_inspection_id: uuid.UUID | None, affected_count: int | None,
    notes: str | None, outcome: str,
) -> CropIssueFollowUp:
    """Recording an outcome, including RESOLVED, never transitions the
    parent Issue's status by itself -- see `close_crop_issue`/`resolve_
    crop_issue` for the deliberate, separate commands that do."""
    fingerprint = _fingerprint(tenant_id, crop_issue_id, follow_up_grower_inspection_id, affected_count, notes, outcome)

    def _find_by_command() -> CropIssueFollowUp | None:
        return db.execute(
            select(CropIssueFollowUp).where(
                CropIssueFollowUp.tenant_id == tenant_id, CropIssueFollowUp.client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise CropIssueFollowUpCommandReusedWithDifferentPayloadError(str(client_command_id))

    issue = _lock_issue(db, tenant_id=tenant_id, farm_id=farm_id, crop_issue_id=crop_issue_id)

    existing = _find_by_command()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise CropIssueFollowUpCommandReusedWithDifferentPayloadError(str(client_command_id))

    if issue.status == "closed":
        raise CropIssueInvalidTransitionError(f"crop issue {crop_issue_id} is closed")

    if follow_up_grower_inspection_id is not None:
        inspection = db.execute(
            select(GrowerInspection).where(
                GrowerInspection.id == follow_up_grower_inspection_id, GrowerInspection.tenant_id == tenant_id,
                GrowerInspection.farm_id == farm_id,
            )
        ).scalar_one_or_none()
        if inspection is None:
            raise GrowerInspectionNotFoundError(str(follow_up_grower_inspection_id))

    follow_up = CropIssueFollowUp(
        tenant_id=tenant_id, farm_id=farm_id, crop_issue_id=crop_issue_id,
        follow_up_grower_inspection_id=follow_up_grower_inspection_id, affected_count=affected_count, notes=notes,
        outcome=outcome, recorded_by_user_id=actor_user_id, client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(follow_up)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_crop_issue_follow_ups_tenant_client_command_id":
            replay = _find_by_command()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise CropIssueFollowUpCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_issue.follow_up_recorded",
        entity_type="crop_issue", entity_id=issue.id,
        event_data={"code": issue.code, "outcome": outcome, "follow_up_id": str(follow_up.id)},
    )
    db.commit()
    db.refresh(follow_up)
    return follow_up


def list_follow_ups(db: Session, *, tenant_id: uuid.UUID, crop_issue_id: uuid.UUID) -> list[CropIssueFollowUp]:
    return list(
        db.execute(
            select(CropIssueFollowUp)
            .where(CropIssueFollowUp.tenant_id == tenant_id, CropIssueFollowUp.crop_issue_id == crop_issue_id)
            .order_by(CropIssueFollowUp.recorded_at)
        ).scalars()
    )


# --- reads -----------------------------------------------------------------------------


def get_crop_issue(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, crop_issue_id: uuid.UUID) -> CropIssue:
    issue = db.execute(
        select(CropIssue).where(
            CropIssue.id == crop_issue_id, CropIssue.tenant_id == tenant_id, CropIssue.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if issue is None:
        raise CropIssueNotFoundError(str(crop_issue_id))
    return issue


def list_crop_issues(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID | None = None,
    statuses: list[str] | None = None,
) -> list[CropIssue]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    query = select(CropIssue).where(CropIssue.tenant_id == tenant_id, CropIssue.farm_id == farm_id)
    if batch_id is not None:
        query = query.where(CropIssue.batch_id == batch_id)
    if statuses:
        query = query.where(CropIssue.status.in_(statuses))
    return list(db.execute(query.order_by(CropIssue.opened_at.desc())).scalars())


def read_model_overlays(db: Session, *, tenant_id: uuid.UUID, issues: list[CropIssue]) -> dict[uuid.UUID, dict]:
    """PILOT-AGRO-001 section 10: `ACTION_IN_PROGRESS`/`FOLLOW_UP_DUE` are
    read-model overlays, never persisted CropIssue statuses -- computed
    here from one bounded, set-based query each, never one query per
    row."""
    if not issues:
        return {}
    issue_ids = [i.id for i in issues]
    open_work_item_issue_ids = set(
        db.execute(
            select(FarmWorkItem.crop_issue_id).where(
                FarmWorkItem.tenant_id == tenant_id, FarmWorkItem.crop_issue_id.in_(issue_ids),
                FarmWorkItem.status.notin_(WORK_ITEM_TERMINAL_STATUSES),
            )
        ).scalars()
    )
    now = datetime.now(timezone.utc)
    return {
        i.id: {
            "has_open_work_item": i.id in open_work_item_issue_ids,
            "is_follow_up_overdue": (
                i.status != "closed" and i.follow_up_due_at is not None and i.follow_up_due_at <= now
            ),
        }
        for i in issues
    }
