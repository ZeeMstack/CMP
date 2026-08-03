from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


class CropBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    workflow_id: uuid.UUID
    client_command_id: uuid.UUID
    effective_time: datetime

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)


class StageSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    is_terminal: bool


class WorkflowSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class CropSummary(BaseModel):
    id: uuid.UUID
    code: str
    common_name: str


class VarietySummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class ProductionSystemSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class CropBatchRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    workflow: WorkflowSummary
    workflow_version_id: uuid.UUID
    version_number: int
    crop: CropSummary
    variety: VarietySummary | None
    production_system: ProductionSystemSummary
    state: str
    current_stage: StageSummary
    created_effective_time: datetime
    created_at: datetime
    closed_effective_time: datetime | None


class CurrentStageRead(BaseModel):
    batch_id: uuid.UUID
    current_stage: StageSummary
    entered_effective_time: datetime


class BatchStageRunRead(BaseModel):
    id: uuid.UUID
    stage: StageSummary
    entered_effective_time: datetime
    exited_effective_time: datetime | None
