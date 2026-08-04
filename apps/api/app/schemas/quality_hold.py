from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.crop_batch import StageSummary


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _normalize_reason_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("reason_code must not be blank")
    return v


def _require_non_blank(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


class QualityHoldCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    source_observation_event_id: uuid.UUID | None = None
    reason_code: str
    reason_text: str

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, v: str) -> str:
        return _normalize_reason_code(v)

    @field_validator("reason_text")
    @classmethod
    def validate_reason_text(cls, v: str) -> str:
        return _require_non_blank(v)


class QualityHoldReleaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    release_reason: str

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("release_reason")
    @classmethod
    def validate_release_reason(cls, v: str) -> str:
        return _require_non_blank(v)


class QualityHoldReleaseRead(BaseModel):
    id: uuid.UUID
    quality_hold_id: uuid.UUID
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID
    release_reason: str


class QualityHoldRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    batch_id: uuid.UUID
    stage: StageSummary
    source_observation_event_id: uuid.UUID | None
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID
    reason_code: str
    reason_text: str
    is_open: bool
    release: QualityHoldReleaseRead | None
