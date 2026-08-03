from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.crop_batch import CropSummary, StageSummary, VarietySummary


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class SowingEventLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    carrier_id: uuid.UUID
    seed_lot_id: uuid.UUID
    sown_site_count: int = Field(gt=0)
    seed_count: int = Field(gt=0)
    line_note: str | None = None

    @field_validator("line_note")
    @classmethod
    def validate_line_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_counts(self) -> "SowingEventLineIn":
        if self.seed_count < self.sown_site_count:
            raise ValueError("seed_count must be greater than or equal to sown_site_count")
        return self


class SowingEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    note: str | None = None
    lines: list[SowingEventLineIn] = Field(min_length=1, max_length=500)

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_lines(self) -> "SowingEventCreate":
        carrier_ids = [line.carrier_id for line in self.lines]
        if len(carrier_ids) != len(set(carrier_ids)):
            raise ValueError("duplicate carrier_id within one sowing command")
        return self


class CarrierTypeSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class CarrierSummary(BaseModel):
    id: uuid.UUID
    code: str
    carrier_type: CarrierTypeSummary


class SeedLotSummary(BaseModel):
    id: uuid.UUID
    code: str
    supplier_lot_reference: str | None
    crop: CropSummary
    variety: VarietySummary


class SowingEventLineRead(BaseModel):
    id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    carrier: CarrierSummary
    seed_lot: SeedLotSummary
    sown_site_count: int
    seed_count: int
    line_note: str | None


class SowingEventRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    batch_id: uuid.UUID
    batch_code: str
    workflow_version_id: uuid.UUID
    stage: StageSummary
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID
    note: str | None
    lines: list[SowingEventLineRead]


class BatchCarrierAssignmentRead(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    carrier: CarrierSummary
    assigned_effective_time: datetime
    released_effective_time: datetime | None
    opening_sowing_event_id: uuid.UUID
