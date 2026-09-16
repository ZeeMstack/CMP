import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import TenantContext
from app.core.db import get_db
from app.core.permissions import Permission, require_permission
from app.schemas.crop_issue import (
    CropIssueCloseIn,
    CropIssueConfirmDiagnosisIn,
    CropIssueFollowUpIn,
    CropIssueFollowUpRead,
    CropIssueOpenIn,
    CropIssueRead,
    CropIssueResolveIn,
    CropIssueUpdateIn,
)
from app.services import crop_issue_service
from app.services.errors import (
    CropIssueCommandReusedWithDifferentPayloadError,
    CropIssueFollowUpCommandReusedWithDifferentPayloadError,
    CropIssueInvalidTransitionError,
    CropIssueNotFoundError,
    FarmNotFoundError,
    GrowerInspectionNotFoundError,
)

router = APIRouter(tags=["crop-issues"])

_NOT_FOUND_ERRORS = (FarmNotFoundError, CropIssueNotFoundError, GrowerInspectionNotFoundError)
_CONFLICT_ERRORS = (
    CropIssueCommandReusedWithDifferentPayloadError, CropIssueInvalidTransitionError,
    CropIssueFollowUpCommandReusedWithDifferentPayloadError,
)


def _to_read(db: Session, *, tenant_id: uuid.UUID, issue) -> CropIssueRead:
    overlays = crop_issue_service.read_model_overlays(db, tenant_id=tenant_id, issues=[issue])[issue.id]
    return CropIssueRead(
        id=issue.id, tenant_id=issue.tenant_id, farm_id=issue.farm_id, code=issue.code, batch_id=issue.batch_id,
        batch_carrier_assignment_id=issue.batch_carrier_assignment_id, location_id=issue.location_id,
        originating_grower_inspection_id=issue.originating_grower_inspection_id,
        originating_finding_id=issue.originating_finding_id, category=issue.category, severity=issue.severity,
        description=issue.description, suspected_cause=issue.suspected_cause,
        confirmed_diagnosis=issue.confirmed_diagnosis,
        diagnosis_confirmed_by_user_id=issue.diagnosis_confirmed_by_user_id,
        diagnosis_confirmed_at=issue.diagnosis_confirmed_at, status=issue.status,
        opened_by_user_id=issue.opened_by_user_id, opened_at=issue.opened_at,
        assigned_owner_user_id=issue.assigned_owner_user_id, follow_up_due_at=issue.follow_up_due_at,
        resolved_by_user_id=issue.resolved_by_user_id, resolved_at=issue.resolved_at,
        resolution_note=issue.resolution_note, closed_by_user_id=issue.closed_by_user_id,
        closed_at=issue.closed_at, close_note=issue.close_note, updated_at=issue.updated_at,
        has_open_work_item=overlays["has_open_work_item"], is_follow_up_overdue=overlays["is_follow_up_overdue"],
    )


@router.post(
    "/farms/{farm_id}/crop-issues", response_model=CropIssueRead, status_code=status.HTTP_201_CREATED
)
def open_crop_issue(
    farm_id: uuid.UUID,
    payload: CropIssueOpenIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_ISSUE_MANAGE)),
) -> CropIssueRead:
    try:
        issue = crop_issue_service.open_crop_issue(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id,
            client_command_id=payload.client_command_id,
            originating_grower_inspection_id=payload.originating_grower_inspection_id,
            originating_finding_id=payload.originating_finding_id, category=payload.category,
            severity=payload.severity, description=payload.description, suspected_cause=payload.suspected_cause,
            assigned_owner_user_id=payload.assigned_owner_user_id, follow_up_due_at=payload.follow_up_due_at,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, issue=issue)


@router.get("/farms/{farm_id}/crop-issues", response_model=list[CropIssueRead])
def list_crop_issues(
    farm_id: uuid.UUID,
    batch_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_INSPECTION_READ)),
) -> list[CropIssueRead]:
    try:
        issues = crop_issue_service.list_crop_issues(db, tenant_id=ctx.tenant_id, farm_id=farm_id, batch_id=batch_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    overlays = crop_issue_service.read_model_overlays(db, tenant_id=ctx.tenant_id, issues=issues)
    return [
        CropIssueRead(
            id=i.id, tenant_id=i.tenant_id, farm_id=i.farm_id, code=i.code, batch_id=i.batch_id,
            batch_carrier_assignment_id=i.batch_carrier_assignment_id, location_id=i.location_id,
            originating_grower_inspection_id=i.originating_grower_inspection_id,
            originating_finding_id=i.originating_finding_id, category=i.category, severity=i.severity,
            description=i.description, suspected_cause=i.suspected_cause, confirmed_diagnosis=i.confirmed_diagnosis,
            diagnosis_confirmed_by_user_id=i.diagnosis_confirmed_by_user_id,
            diagnosis_confirmed_at=i.diagnosis_confirmed_at, status=i.status, opened_by_user_id=i.opened_by_user_id,
            opened_at=i.opened_at, assigned_owner_user_id=i.assigned_owner_user_id,
            follow_up_due_at=i.follow_up_due_at, resolved_by_user_id=i.resolved_by_user_id,
            resolved_at=i.resolved_at, resolution_note=i.resolution_note, closed_by_user_id=i.closed_by_user_id,
            closed_at=i.closed_at, close_note=i.close_note, updated_at=i.updated_at,
            has_open_work_item=overlays[i.id]["has_open_work_item"],
            is_follow_up_overdue=overlays[i.id]["is_follow_up_overdue"],
        )
        for i in issues
    ]


@router.get("/farms/{farm_id}/crop-issues/{crop_issue_id}", response_model=CropIssueRead)
def get_crop_issue(
    farm_id: uuid.UUID,
    crop_issue_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_INSPECTION_READ)),
) -> CropIssueRead:
    try:
        issue = crop_issue_service.get_crop_issue(db, tenant_id=ctx.tenant_id, farm_id=farm_id, crop_issue_id=crop_issue_id)
    except CropIssueNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    return _to_read(db, tenant_id=ctx.tenant_id, issue=issue)


@router.post("/farms/{farm_id}/crop-issues/{crop_issue_id}/update", response_model=CropIssueRead)
def update_crop_issue(
    farm_id: uuid.UUID,
    crop_issue_id: uuid.UUID,
    payload: CropIssueUpdateIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_ISSUE_MANAGE)),
) -> CropIssueRead:
    try:
        issue = crop_issue_service.update_crop_issue(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, crop_issue_id=crop_issue_id,
            client_command_id=payload.client_command_id, severity=payload.severity,
            assigned_owner_user_id=payload.assigned_owner_user_id, follow_up_due_at=payload.follow_up_due_at,
            suspected_cause=payload.suspected_cause,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, issue=issue)


@router.post("/farms/{farm_id}/crop-issues/{crop_issue_id}/confirm-diagnosis", response_model=CropIssueRead)
def confirm_diagnosis(
    farm_id: uuid.UUID,
    crop_issue_id: uuid.UUID,
    payload: CropIssueConfirmDiagnosisIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_ISSUE_MANAGE)),
) -> CropIssueRead:
    try:
        issue = crop_issue_service.confirm_diagnosis(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, crop_issue_id=crop_issue_id,
            client_command_id=payload.client_command_id, confirmed_diagnosis=payload.confirmed_diagnosis,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, issue=issue)


@router.post("/farms/{farm_id}/crop-issues/{crop_issue_id}/resolve", response_model=CropIssueRead)
def resolve_crop_issue(
    farm_id: uuid.UUID,
    crop_issue_id: uuid.UUID,
    payload: CropIssueResolveIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_ISSUE_MANAGE)),
) -> CropIssueRead:
    try:
        issue = crop_issue_service.resolve_crop_issue(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, crop_issue_id=crop_issue_id,
            client_command_id=payload.client_command_id, resolution_note=payload.resolution_note,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, issue=issue)


@router.post("/farms/{farm_id}/crop-issues/{crop_issue_id}/close", response_model=CropIssueRead)
def close_crop_issue(
    farm_id: uuid.UUID,
    crop_issue_id: uuid.UUID,
    payload: CropIssueCloseIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_ISSUE_MANAGE)),
) -> CropIssueRead:
    try:
        issue = crop_issue_service.close_crop_issue(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, crop_issue_id=crop_issue_id,
            client_command_id=payload.client_command_id, close_note=payload.close_note,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_read(db, tenant_id=ctx.tenant_id, issue=issue)


@router.post(
    "/farms/{farm_id}/crop-issues/{crop_issue_id}/follow-ups", response_model=CropIssueFollowUpRead,
    status_code=status.HTTP_201_CREATED,
)
def record_follow_up(
    farm_id: uuid.UUID,
    crop_issue_id: uuid.UUID,
    payload: CropIssueFollowUpIn,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_INSPECTION_MANAGE)),
) -> CropIssueFollowUpRead:
    try:
        follow_up = crop_issue_service.record_follow_up(
            db, tenant_id=ctx.tenant_id, farm_id=farm_id, actor_user_id=ctx.user_id, crop_issue_id=crop_issue_id,
            client_command_id=payload.client_command_id,
            follow_up_grower_inspection_id=payload.follow_up_grower_inspection_id,
            affected_count=payload.affected_count, notes=payload.notes, outcome=payload.outcome,
        )
    except _NOT_FOUND_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CropIssueFollowUpRead.model_validate(follow_up)


@router.get("/farms/{farm_id}/crop-issues/{crop_issue_id}/follow-ups", response_model=list[CropIssueFollowUpRead])
def list_follow_ups(
    farm_id: uuid.UUID,
    crop_issue_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: TenantContext = Depends(require_permission(Permission.CROP_INSPECTION_READ)),
) -> list[CropIssueFollowUpRead]:
    try:
        crop_issue_service.get_crop_issue(db, tenant_id=ctx.tenant_id, farm_id=farm_id, crop_issue_id=crop_issue_id)
    except CropIssueNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    follow_ups = crop_issue_service.list_follow_ups(db, tenant_id=ctx.tenant_id, crop_issue_id=crop_issue_id)
    return [CropIssueFollowUpRead.model_validate(f) for f in follow_ups]
