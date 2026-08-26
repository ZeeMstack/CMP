from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


def _require_non_blank(v: str, *, field_name: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{field_name} must not be blank")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


# --- Commands ----------------------------------------------------------------------


class GradeDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    code: str
    name: str
    crop_id: uuid.UUID
    variety_id: uuid.UUID | None = None
    description: str | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _require_non_blank(v, field_name="name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class GradeDefinitionVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    spec_notes: str | None = None

    @field_validator("spec_notes")
    @classmethod
    def validate_spec_notes(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class GradeDefinitionVersionActivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)


class GradeDefinitionVersionRetire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)


# --- Reads -----------------------------------------------------------------------


class GradeDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    crop_id: uuid.UUID
    variety_id: uuid.UUID | None
    code: str
    name: str
    description: str | None
    created_at: datetime


class GradeDefinitionVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    grade_definition_id: uuid.UUID
    version_number: int
    status: str
    effective_from: datetime | None
    effective_until: datetime | None
    spec_notes: str | None
    created_by: uuid.UUID | None
    created_at: datetime


__all__ = [
    "GradeDefinitionCreate",
    "GradeDefinitionVersionCreate",
    "GradeDefinitionVersionActivate",
    "GradeDefinitionVersionRetire",
    "GradeDefinitionRead",
    "GradeDefinitionVersionRead",
]
