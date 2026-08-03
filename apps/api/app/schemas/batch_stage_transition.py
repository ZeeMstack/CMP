from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class BatchStageTransitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured_transition_id: uuid.UUID
    client_command_id: uuid.UUID
    effective_time: datetime
    reason: str | None = None

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("effective_time must be timezone-aware")
        return v

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class BatchStageTransitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    batch_id: uuid.UUID
    workflow_version_id: uuid.UUID
    command_kind: str
    source_stage_id: uuid.UUID | None
    destination_stage_id: uuid.UUID
    configured_transition_id: uuid.UUID | None
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID
    reason: str | None
