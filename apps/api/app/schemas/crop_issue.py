from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.crop_issue import CROP_ISSUE_STATUSES
from app.models.crop_issue_follow_up import FOLLOW_UP_OUTCOMES
from app.models.inspection_finding import FINDING_CATEGORIES, FINDING_SEVERITIES

CropIssueStatus = Literal[CROP_ISSUE_STATUSES]  # type: ignore[valid-type]
FollowUpOutcome = Literal[FOLLOW_UP_OUTCOMES]  # type: ignore[valid-type]
IssueCategory = Literal[FINDING_CATEGORIES]  # type: ignore[valid-type]
IssueSeverity = Literal[FINDING_SEVERITIES]  # type: ignore[valid-type]


def _require_non_blank(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("must be timezone-aware")
    return v


# --- Commands ----------------------------------------------------------------------


class CropIssueOpenIn(BaseModel):
    """Opens a CropIssue from a significant Inspection Finding. Grower/
    supervisory only (PILOT-AGRO-001 section 19)."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    originating_grower_inspection_id: uuid.UUID
    originating_finding_id: uuid.UUID | None = None
    category: IssueCategory
    severity: IssueSeverity
    description: str
    suspected_cause: str | None = None
    assigned_owner_user_id: uuid.UUID | None = None
    follow_up_due_at: datetime | None = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        return _require_non_blank(v)

    @field_validator("follow_up_due_at")
    @classmethod
    def validate_follow_up_due_at(cls, v: datetime | None) -> datetime | None:
        return _require_tz_aware(v) if v is not None else None


class CropIssueUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    severity: IssueSeverity
    assigned_owner_user_id: uuid.UUID | None = None
    follow_up_due_at: datetime | None = None
    suspected_cause: str | None = None

    @field_validator("follow_up_due_at")
    @classmethod
    def validate_follow_up_due_at(cls, v: datetime | None) -> datetime | None:
        return _require_tz_aware(v) if v is not None else None


class CropIssueConfirmDiagnosisIn(BaseModel):
    """Suspected cause is never automatically promoted -- a confirmed
    diagnosis is always this explicit, separate command (PILOT-AGRO-001
    section 11)."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    confirmed_diagnosis: str

    @field_validator("confirmed_diagnosis")
    @classmethod
    def validate_confirmed_diagnosis(cls, v: str) -> str:
        return _require_non_blank(v)


class CropIssueResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    resolution_note: str

    @field_validator("resolution_note")
    @classmethod
    def validate_resolution_note(cls, v: str) -> str:
        return _require_non_blank(v)


class CropIssueCloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    close_note: str | None = None


class CropIssueFollowUpIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    follow_up_grower_inspection_id: uuid.UUID | None = None
    affected_count: int | None = None
    notes: str | None = None
    outcome: FollowUpOutcome

    @field_validator("affected_count")
    @classmethod
    def validate_affected_count(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("affected_count must be >= 0")
        return v


# --- Reads -----------------------------------------------------------------------


class CropIssueRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    batch_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID | None
    location_id: uuid.UUID | None
    originating_grower_inspection_id: uuid.UUID
    originating_finding_id: uuid.UUID | None
    category: IssueCategory
    severity: IssueSeverity
    description: str
    suspected_cause: str | None
    confirmed_diagnosis: str | None
    diagnosis_confirmed_by_user_id: uuid.UUID | None
    diagnosis_confirmed_at: datetime | None
    status: CropIssueStatus
    opened_by_user_id: uuid.UUID
    opened_at: datetime
    assigned_owner_user_id: uuid.UUID | None
    follow_up_due_at: datetime | None
    resolved_by_user_id: uuid.UUID | None
    resolved_at: datetime | None
    resolution_note: str | None
    closed_by_user_id: uuid.UUID | None
    closed_at: datetime | None
    close_note: str | None
    updated_at: datetime
    # Read-model overlays (PILOT-AGRO-001 section 10 -- never persisted).
    has_open_work_item: bool
    is_follow_up_overdue: bool


class CropIssueFollowUpRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    crop_issue_id: uuid.UUID
    follow_up_grower_inspection_id: uuid.UUID | None
    affected_count: int | None
    notes: str | None
    outcome: FollowUpOutcome
    recorded_by_user_id: uuid.UUID
    recorded_at: datetime
