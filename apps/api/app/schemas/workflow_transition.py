from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, field_validator


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


class WorkflowTransitionCreate(BaseModel):
    from_stage_id: uuid.UUID
    to_stage_id: uuid.UUID
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


class WorkflowTransitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    workflow_version_id: uuid.UUID
    from_stage_id: uuid.UUID
    to_stage_id: uuid.UUID
    code: str
    name: str
