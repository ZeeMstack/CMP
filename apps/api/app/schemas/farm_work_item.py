from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WorkItemCategory = Literal[
    "nursery", "production", "crop_care", "harvest", "post_harvest",
    "store", "quality", "dispatch", "cleaning", "maintenance",
]
WorkItemStatus = Literal["open", "in_progress", "blocked", "completed", "cancelled"]
WorkItemPriority = Literal["normal", "high", "critical"]
WorkItemCompletionMode = Literal["operational_record", "manual_record"]
WorkItemResultEntityType = Literal["harvest_event", "observation_event"]


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _require_non_blank(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


# --- Commands ----------------------------------------------------------------------


class FarmWorkItemCreate(BaseModel):
    """Creates a manual or operational-record Work Item. `completion_mode`
    is fixed at creation -- an OPERATIONAL_RECORD item can only ever be
    completed by linking the authoritative GrowCMP record
    (`link_operational_result`), never a checkbox; a MANUAL_RECORD item can
    only ever be completed via `complete`."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    work_type: str
    category: WorkItemCategory
    title: str
    instructions: str | None = None
    priority: WorkItemPriority = "normal"
    due_at: datetime | None = None
    assigned_to_user_id: uuid.UUID | None = None
    crop_batch_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    carrier_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    # PILOT-AGRO-001: the CropIssue this Work Item is corrective action
    # FOR, set only at creation (never retrofit onto an existing item).
    crop_issue_id: uuid.UUID | None = None
    quantity: Decimal | None = None
    quantity_uom_id: uuid.UUID | None = None
    completion_mode: WorkItemCompletionMode

    @field_validator("work_type", "title")
    @classmethod
    def validate_required_text(cls, v: str) -> str:
        return _require_non_blank(v)

    @field_validator("instructions")
    @classmethod
    def validate_instructions(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, v: datetime | None) -> datetime | None:
        return _require_tz_aware(v) if v is not None else None

    @model_validator(mode="after")
    def validate_quantity_pairing(self) -> "FarmWorkItemCreate":
        if (self.quantity is None) != (self.quantity_uom_id is None):
            raise ValueError("quantity and quantity_uom_id must be supplied together or not at all")
        return self


class FarmWorkItemUpdateIn(BaseModel):
    """The one supervisory command covering reassignment, priority change,
    and due-window change -- a real domain command with explicit, fully-
    specified target fields, never a generic PATCH (CLAUDE.md "API and
    Offline Rules"). Every field is the item's complete new value (not a
    partial patch) -- e.g. `assigned_to_user_id=None` explicitly unassigns."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    assigned_to_user_id: uuid.UUID | None = None
    priority: WorkItemPriority = "normal"
    due_at: datetime | None = None

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, v: datetime | None) -> datetime | None:
        return _require_tz_aware(v) if v is not None else None


class FarmWorkItemStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class FarmWorkItemBlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        return _require_non_blank(v)


class FarmWorkItemUnblockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class FarmWorkItemCompleteIn(BaseModel):
    """MANUAL_RECORD completion only -- rejected outright for an
    OPERATIONAL_RECORD item (see `FarmWorkItemCreate`'s docstring)."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    completion_note: str | None = None

    @field_validator("completion_note")
    @classmethod
    def validate_completion_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class FarmWorkItemCancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class FarmWorkItemLinkResultIn(BaseModel):
    """OPERATIONAL_RECORD completion only. Called after the authoritative
    GrowCMP command (Harvest, Observation, ...) has already committed --
    never before. `effective_time` is the authoritative operation's own
    effective time, recorded here as `result_recorded_at`."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    result_entity_type: WorkItemResultEntityType
    result_entity_id: uuid.UUID
    effective_time: datetime

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)


# --- Reads -----------------------------------------------------------------------


class WorkItemCropBatchSummary(BaseModel):
    id: uuid.UUID
    code: str


class WorkItemLocationSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class WorkItemCarrierSummary(BaseModel):
    id: uuid.UUID
    code: str


class WorkItemAssetSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class WorkItemUomSummary(BaseModel):
    id: uuid.UUID
    code: str


class WorkItemCropIssueSummary(BaseModel):
    id: uuid.UUID
    code: str
    status: str


class FarmWorkItemRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    work_type: str
    category: WorkItemCategory
    title: str
    instructions: str | None
    status: WorkItemStatus
    priority: WorkItemPriority
    due_at: datetime | None
    assigned_to_user_id: uuid.UUID | None

    crop_batch: WorkItemCropBatchSummary | None
    location: WorkItemLocationSummary | None
    carrier: WorkItemCarrierSummary | None
    asset: WorkItemAssetSummary | None
    crop_issue: WorkItemCropIssueSummary | None = None
    quantity: Decimal | None
    quantity_uom: WorkItemUomSummary | None

    completion_mode: WorkItemCompletionMode
    result_entity_type: WorkItemResultEntityType | None
    result_entity_id: uuid.UUID | None
    result_recorded_at: datetime | None
    completed_by_user_id: uuid.UUID | None
    completed_at: datetime | None
    completion_note: str | None

    blocked_reason: str | None
    blocked_at: datetime | None
    blocked_by_user_id: uuid.UUID | None

    cancelled_at: datetime | None
    cancelled_by_user_id: uuid.UUID | None
    cancel_reason: str | None

    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class FarmWorkItemHistoryEntryRead(BaseModel):
    """One operator-facing lifecycle-history row, read back from the
    existing `audit_events` table (`docs/domain/AUDIT_MODEL.md`) -- Farm
    Work Item history is deliberately not duplicated into a second event
    model."""

    id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None
    effective_time: datetime
    event_data: dict
