from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.protocol_care_activity import CARE_ACTIVITY_TYPES
from app.models.protocol_observation_requirement import REQUIREMENT_LEVELS
from app.models.workflow_stage import STAGE_CATEGORIES

ProtocolStatus = Literal["active", "inactive"]
ProtocolVersionState = Literal["draft", "active", "retired"]
StageCategory = Literal[STAGE_CATEGORIES]  # type: ignore[valid-type]
RequirementLevel = Literal[REQUIREMENT_LEVELS]  # type: ignore[valid-type]
CareActivityType = Literal[CARE_ACTIVITY_TYPES]  # type: ignore[valid-type]


def _require_non_blank(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


# --- Commands ----------------------------------------------------------------------


class GrowingProtocolCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    crop_id: uuid.UUID
    variety_id: uuid.UUID | None = None
    production_system_id: uuid.UUID | None = None
    season_context: str | None = None

    @field_validator("code", "name")
    @classmethod
    def validate_required_text(cls, v: str) -> str:
        return _require_non_blank(v)


class GrowingProtocolVersionCreate(BaseModel):
    """Creates the next DRAFT version for a protocol -- version_number is
    server-assigned (max existing + 1), mirroring `workflow_service.
    create_draft_version`."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    reason: str
    effective_date: date | None = None

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        return _require_non_blank(v)


class ProtocolObservationRequirementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_category: StageCategory
    observation_definition_id: uuid.UUID
    requirement_level: RequirementLevel
    frequency_days: int | None = None
    due_window_start_days: int | None = None
    due_window_end_days: int | None = None
    # PILOT-AGRO-001A: optionally narrows this requirement to the Nth
    # (1-based) real occurrence of `stage_category` within whichever
    # WorkflowVersion a Batch actually runs -- see the model's own
    # docstring. None (default) applies to every occurrence.
    stage_sequence_index: int | None = None
    instructions: str | None = None
    escalation_guidance: str | None = None
    display_order: int = 0


class ProtocolCareActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_category: StageCategory
    activity_type: CareActivityType
    title: str
    instructions: str | None = None
    frequency_days: int | None = None
    stage_sequence_index: int | None = None
    display_order: int = 0

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        return _require_non_blank(v)


class GrowingProtocolVersionActivateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class GrowingProtocolVersionRetireIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class BatchProtocolAssignIn(BaseModel):
    """Assigns (or changes) the ACTIVE `GrowingProtocolVersion` a Batch is
    following. `effective_from` defaults to now when omitted."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    growing_protocol_version_id: uuid.UUID
    effective_from: datetime | None = None
    reason: str | None = None


# --- Reads -----------------------------------------------------------------------


class GrowingProtocolVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    growing_protocol_id: uuid.UUID
    version_number: int
    state: ProtocolVersionState
    author_user_id: uuid.UUID
    reason: str
    effective_date: date | None
    created_at: datetime
    activated_at: datetime | None
    retired_at: datetime | None


class GrowingProtocolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    crop_id: uuid.UUID
    variety_id: uuid.UUID | None
    production_system_id: uuid.UUID | None
    season_context: str | None
    status: ProtocolStatus
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ProtocolObservationRequirementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    growing_protocol_version_id: uuid.UUID
    stage_category: StageCategory
    observation_definition_id: uuid.UUID
    requirement_level: RequirementLevel
    frequency_days: int | None
    due_window_start_days: int | None
    due_window_end_days: int | None
    stage_sequence_index: int | None
    instructions: str | None
    escalation_guidance: str | None
    display_order: int


class ProtocolCareActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    growing_protocol_version_id: uuid.UUID
    stage_category: StageCategory
    activity_type: CareActivityType
    title: str
    instructions: str | None
    frequency_days: int | None
    stage_sequence_index: int | None
    display_order: int


class BatchProtocolAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    growing_protocol_version_id: uuid.UUID
    assigned_by_user_id: uuid.UUID
    assigned_at: datetime
    effective_from: datetime
    effective_to: datetime | None
    reason: str | None


class BatchProtocolStatusRead(BaseModel):
    """Compact "protocol context for a Batch" panel data (PILOT-AGRO-001
    section 15) -- current assignment plus a deterministic due/deviation
    read, never a persisted fact."""

    current_assignment: BatchProtocolAssignmentRead | None
    protocol: GrowingProtocolRead | None
    protocol_version: GrowingProtocolVersionRead | None
    current_stage_category: str | None
    # PILOT-AGRO-001A: 1-based rank of the Batch's current WorkflowStage
    # among its own same-`stage_category` siblings within its
    # WorkflowVersion -- what a requirement's own `stage_sequence_index`
    # is compared against. None when there is no active stage run.
    current_stage_occurrence_index: int | None
    days_in_stage: int | None
    due_observation_requirements: list["DueRequirementRead"]
    open_crop_issue_count: int


class FarmProtocolDueSummaryItem(BaseModel):
    """One row of PILOT-AGRO-001B's Today-on-the-Farm "Inspections Due" read
    model -- a currently-active Batch that has a Protocol assigned and
    currently has something due or an open Crop Issue. Never persisted;
    recomputed fresh on every read, same as `BatchProtocolStatusRead`."""

    batch_id: uuid.UUID
    batch_code: str
    protocol: GrowingProtocolRead | None
    protocol_version: GrowingProtocolVersionRead | None
    due_count: int
    overdue_count: int
    open_crop_issue_count: int


class DueRequirementRead(BaseModel):
    """One deterministic due/deviation read for a single Protocol
    Observation Requirement against one Batch -- section 18: age informs
    display only, never an automatic stage/farm event."""

    requirement: ProtocolObservationRequirementRead
    observation_definition_code: str
    observation_definition_name: str
    is_due: bool
    is_overdue: bool
    is_outside_expected_window: bool
    last_satisfied_at: datetime | None
