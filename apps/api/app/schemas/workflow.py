from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.workflow_stage import WorkflowStageRead
from app.schemas.workflow_transition import WorkflowTransitionRead


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


class WorkflowCreate(BaseModel):
    crop_id: uuid.UUID
    variety_id: uuid.UUID | None = None
    production_system_id: uuid.UUID
    code: str
    name: str

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


class WorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    crop_id: uuid.UUID
    variety_id: uuid.UUID | None
    production_system_id: uuid.UUID
    code: str
    name: str
    status: str


class WorkflowVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    workflow_id: uuid.UUID
    version_number: int
    state: str
    created_at: datetime
    published_at: datetime | None
    retired_at: datetime | None


class WorkflowVersionDetailRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    workflow_id: uuid.UUID
    version_number: int
    state: str
    created_at: datetime
    published_at: datetime | None
    retired_at: datetime | None
    stages: list[WorkflowStageRead]
    transitions: list[WorkflowTransitionRead]
