from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

from app.schemas.crop_batch import StageSummary
from app.schemas.sowing_event import CarrierSummary

MAX_OBSERVATION_ENTRIES = 500


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class ObservationValueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_definition_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID | None = None
    value_integer: StrictInt | None = None
    value_decimal: Decimal | None = None
    value_boolean: StrictBool | None = None
    value_text: str | None = None
    note: str | None = None

    @field_validator("value_text", "note")
    @classmethod
    def validate_optional_text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_exactly_one_typed_value(self) -> "ObservationValueIn":
        populated = [
            v is not None for v in (self.value_integer, self.value_decimal, self.value_boolean, self.value_text)
        ]
        if sum(populated) != 1:
            raise ValueError(
                "exactly one of value_integer, value_decimal, value_boolean, value_text must be set"
            )
        return self


class GerminationCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_carrier_assignment_id: uuid.UUID
    inspected_site_count: int = Field(gt=0)
    normal_germinated_site_count: int = Field(ge=0)
    abnormal_germinated_site_count: int = Field(ge=0)
    failed_site_count: int = Field(ge=0)
    note: str | None = None

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_categories_within_inspected(self) -> "GerminationCheckIn":
        total = self.normal_germinated_site_count + self.abnormal_germinated_site_count + self.failed_site_count
        if total > self.inspected_site_count:
            raise ValueError("normal + abnormal + failed site counts cannot exceed inspected_site_count")
        return self


class ObservationEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    note: str | None = None
    values: list[ObservationValueIn] = Field(default_factory=list)
    germination_checks: list[GerminationCheckIn] = Field(default_factory=list)

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_entries(self) -> "ObservationEventCreate":
        total = len(self.values) + len(self.germination_checks)
        if total < 1:
            raise ValueError("at least one value or germination check is required")
        if total > MAX_OBSERVATION_ENTRIES:
            raise ValueError(f"a command may include at most {MAX_OBSERVATION_ENTRIES} combined entries")
        seen_targets = set()
        for value in self.values:
            key = (value.observation_definition_id, value.batch_carrier_assignment_id)
            if key in seen_targets:
                raise ValueError("duplicate definition/target combination within one event")
            seen_targets.add(key)
        seen_assignments = set()
        for check in self.germination_checks:
            if check.batch_carrier_assignment_id in seen_assignments:
                raise ValueError("duplicate germination check assignment within one event")
            seen_assignments.add(check.batch_carrier_assignment_id)
        return self


class ObservationDefinitionSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    value_type: str
    unit: str | None


class ObservationValueRead(BaseModel):
    id: uuid.UUID
    definition: ObservationDefinitionSummary
    carrier: CarrierSummary | None
    batch_carrier_assignment_id: uuid.UUID | None
    value_integer: int | None
    value_decimal: Decimal | None
    value_boolean: bool | None
    value_text: str | None
    note: str | None


class GerminationCheckRead(BaseModel):
    id: uuid.UUID
    carrier: CarrierSummary
    batch_carrier_assignment_id: uuid.UUID
    inspected_site_count: int
    normal_germinated_site_count: int
    abnormal_germinated_site_count: int
    failed_site_count: int
    unresolved_site_count: int
    total_germinated_site_count: int
    germination_percentage: Decimal
    note: str | None


class ObservationEventRead(BaseModel):
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
    values: list[ObservationValueRead]
    germination_checks: list[GerminationCheckRead]
