from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.models.workflow_stage import STAGE_CATEGORIES


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


class WorkflowStageCreate(BaseModel):
    code: str
    name: str
    display_order: int
    stage_category: str
    expected_duration_minutes: int | None = None
    permitted_location_type_code: str | None = None
    required_carrier_type_code: str | None = None
    is_start: bool = False
    is_terminal: bool = False

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("stage_category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in STAGE_CATEGORIES:
            allowed = ", ".join(STAGE_CATEGORIES)
            raise ValueError(f"stage_category must be one of: {allowed}")
        return v

    @model_validator(mode="after")
    def validate_values(self) -> "WorkflowStageCreate":
        if self.display_order < 0:
            raise ValueError("display_order must be zero or greater")
        if self.expected_duration_minutes is not None and self.expected_duration_minutes <= 0:
            raise ValueError("expected_duration_minutes must be greater than zero")
        return self


class WorkflowStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    workflow_version_id: uuid.UUID
    code: str
    name: str
    display_order: int
    stage_category: str
    expected_duration_minutes: int | None
    permitted_location_type_id: uuid.UUID | None
    required_carrier_type_id: uuid.UUID | None
    is_start: bool
    is_terminal: bool
