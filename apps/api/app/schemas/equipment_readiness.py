from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.cleaning_event import CLEANING_RESULTS
from app.models.equipment_readiness_state import READINESS_ENTITY_TYPES, READINESS_STATES

ReadinessEntityType = Literal[READINESS_ENTITY_TYPES]  # type: ignore[valid-type]
ReadinessState = Literal[READINESS_STATES]  # type: ignore[valid-type]
CleaningResult = Literal[CLEANING_RESULTS]  # type: ignore[valid-type]


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


# --- Commands ----------------------------------------------------------------------


class EquipmentReadinessTransitionIn(BaseModel):
    """Shared shape for `mark_awaiting_cleaning`/`mark_ready`/
    `send_to_maintenance`/`return_from_maintenance`/`retire`. `report_damage`
    has its own `note` requirement below."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    note: str | None = None

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class EquipmentReadinessReportDamageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    note: str

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class RecordCleaningIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_at: datetime
    method: str | None = None
    result: CleaningResult
    notes: str | None = None

    @field_validator("effective_at")
    @classmethod
    def validate_effective_at(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("method", "notes")
    @classmethod
    def validate_optional_text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


# --- Reads -----------------------------------------------------------------------


class EquipmentReadinessStateRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    entity_type: ReadinessEntityType
    asset_id: uuid.UUID | None
    carrier_id: uuid.UUID | None
    current_state: ReadinessState
    state_changed_at: datetime
    state_changed_by_user_id: uuid.UUID | None
    state_note: str | None
    last_cleaning_event_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CleaningEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    entity_type: ReadinessEntityType
    asset_id: uuid.UUID | None
    carrier_id: uuid.UUID | None
    effective_at: datetime
    recorded_at: datetime
    performed_by_user_id: uuid.UUID
    method: str | None
    result: CleaningResult
    notes: str | None


class EquipmentReadinessHistoryEntryRead(BaseModel):
    id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None
    effective_time: datetime
    event_data: dict
