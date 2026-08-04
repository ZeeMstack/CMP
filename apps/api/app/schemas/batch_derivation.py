from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.crop_batch import StageSummary, WorkflowSummary, _normalize_code


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


# --- Commands ------------------------------------------------------------------


class SplitOutputIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_batch_code: str
    source_assignment_ids: list[uuid.UUID] = Field(min_length=1, max_length=2000)

    @field_validator("output_batch_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("source_assignment_ids")
    @classmethod
    def validate_no_duplicates(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(v) != len(set(v)):
            raise ValueError("duplicate source_assignment_id within one output")
        return v


class BatchSplitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    note: str | None = None
    outputs: list[SplitOutputIn] = Field(min_length=2, max_length=50)

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_outputs(self) -> "BatchSplitCreate":
        codes = [o.output_batch_code for o in self.outputs]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate output_batch_code within one split command")
        all_assignment_ids = [aid for o in self.outputs for aid in o.source_assignment_ids]
        if len(all_assignment_ids) != len(set(all_assignment_ids)):
            raise ValueError("duplicate source_assignment_id across outputs within one split command")
        if sum(len(o.source_assignment_ids) for o in self.outputs) > 2000:
            raise ValueError("a split command may include at most 2000 total carrier transfers")
        return self


class BatchMergeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    note: str | None = None
    source_batch_ids: list[uuid.UUID] = Field(min_length=2, max_length=50)
    output_batch_code: str

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @field_validator("output_batch_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("source_batch_ids")
    @classmethod
    def validate_no_duplicates(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(v) != len(set(v)):
            raise ValueError("duplicate source_batch_id within one merge command")
        return v


# --- Reads -----------------------------------------------------------------------


class BatchSummary(BaseModel):
    id: uuid.UUID
    code: str


class CarrierRefSummary(BaseModel):
    id: uuid.UUID
    code: str


class BatchDerivationSourceRead(BaseModel):
    id: uuid.UUID
    source_batch: BatchSummary
    source_batch_stage_run_id: uuid.UUID
    recorded_plant_quantity_total: int
    recorded_carrier_assignment_count: int


class BatchDerivationOutputRead(BaseModel):
    id: uuid.UUID
    output_batch: BatchSummary
    recorded_plant_quantity_total: int
    recorded_carrier_assignment_count: int


class BatchAssignmentTransferRead(BaseModel):
    id: uuid.UUID
    carrier: CarrierRefSummary
    source_batch: BatchSummary
    output_batch: BatchSummary
    released_source_assignment_id: uuid.UUID
    opened_destination_assignment_id: uuid.UUID
    transferred_plant_count: int


class BatchDerivationEventRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    derivation_kind: str
    workflow: WorkflowSummary
    workflow_version_id: uuid.UUID
    inherited_stage: StageSummary
    effective_time: datetime
    recorded_at: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID
    note: str | None
    sources: list[BatchDerivationSourceRead]
    outputs: list[BatchDerivationOutputRead]
    transfers: list[BatchAssignmentTransferRead]
    total_source_plant_count: int
    total_output_plant_count: int
    total_carrier_transfer_count: int


class BatchLineageEventRead(BaseModel):
    derivation_event_id: uuid.UUID
    derivation_kind: str
    effective_time: datetime
    batch: BatchSummary
    recorded_plant_quantity_total: int
    recorded_carrier_assignment_count: int


class BatchLineageRead(BaseModel):
    batch_id: uuid.UUID
    parents: list[BatchLineageEventRead]
    children: list[BatchLineageEventRead]
