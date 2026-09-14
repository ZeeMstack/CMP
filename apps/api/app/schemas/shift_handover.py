from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


class ShiftHandoverCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    note: str
    work_item_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("note must not be blank")
        return v


class ShiftHandoverRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    author_user_id: uuid.UUID
    effective_time: datetime
    recorded_at: datetime
    note: str
    work_item_ids: list[uuid.UUID]
