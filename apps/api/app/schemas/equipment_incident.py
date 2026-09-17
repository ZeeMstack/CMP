from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.equipment_incident import INCIDENT_CATEGORIES, INCIDENT_SEVERITIES, INCIDENT_STATUSES

IncidentStatus = Literal[INCIDENT_STATUSES]  # type: ignore[valid-type]
IncidentSeverity = Literal[INCIDENT_SEVERITIES]  # type: ignore[valid-type]
IncidentCategory = Literal[INCIDENT_CATEGORIES]  # type: ignore[valid-type]


def _require_non_blank(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be blank")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("must be timezone-aware")
    return v


# --- Commands ----------------------------------------------------------------------


class EquipmentIncidentOpenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    asset_id: uuid.UUID
    location_id: uuid.UUID | None = None
    # PART 13: "Potentially impacted area" -- deliberately never the same
    # field as location_id. See docs/domain/EQUIPMENT_READINESS_MODEL.md.
    potentially_impacted_location_id: uuid.UUID | None = None
    severity: IncidentSeverity
    category: IncidentCategory
    description: str
    detected_at: datetime
    assigned_owner_user_id: uuid.UUID | None = None
    notes: str | None = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        return _require_non_blank(v)

    @field_validator("detected_at")
    @classmethod
    def validate_detected_at(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class EquipmentIncidentAcknowledgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class EquipmentIncidentActionInProgressIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class EquipmentIncidentAssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    assigned_owner_user_id: uuid.UUID | None = None


class EquipmentIncidentResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    resolution_note: str

    @field_validator("resolution_note")
    @classmethod
    def validate_resolution_note(cls, v: str) -> str:
        return _require_non_blank(v)


class EquipmentIncidentCloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    close_note: str | None = None

    @field_validator("close_note")
    @classmethod
    def validate_close_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


# --- Reads -----------------------------------------------------------------------


class EquipmentIncidentAssetSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    criticality: str


class EquipmentIncidentLocationSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class EquipmentIncidentRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    asset_id: uuid.UUID
    asset: EquipmentIncidentAssetSummary | None = None
    location_id: uuid.UUID | None
    location: EquipmentIncidentLocationSummary | None = None
    potentially_impacted_location_id: uuid.UUID | None
    potentially_impacted_location: EquipmentIncidentLocationSummary | None = None
    severity: IncidentSeverity
    category: IncidentCategory
    description: str
    detected_by_user_id: uuid.UUID
    detected_at: datetime
    notes: str | None
    status: IncidentStatus
    opened_by_user_id: uuid.UUID
    opened_at: datetime
    assigned_owner_user_id: uuid.UUID | None
    acknowledged_by_user_id: uuid.UUID | None
    acknowledged_at: datetime | None
    resolved_by_user_id: uuid.UUID | None
    resolved_at: datetime | None
    resolution_note: str | None
    closed_by_user_id: uuid.UUID | None
    closed_at: datetime | None
    close_note: str | None
    updated_at: datetime


class EquipmentIncidentHistoryEntryRead(BaseModel):
    id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None
    effective_time: datetime
    event_data: dict
