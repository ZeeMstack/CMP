from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.models.inspection_finding import FINDING_CATEGORIES, FINDING_SEVERITIES

OverallAssessment = Literal["normal", "attention_needed", "critical"]
FindingCategory = Literal[FINDING_CATEGORIES]  # type: ignore[valid-type]
FindingSeverity = Literal[FINDING_SEVERITIES]  # type: ignore[valid-type]


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("must be timezone-aware")
    return v


# --- Commands ----------------------------------------------------------------------


class InspectionObservationValueIn(BaseModel):
    """Mirrors `app.schemas.observation_event.ObservationValueCreate`'s own
    shape -- passed straight through to `observation_service.
    record_observation` so no value/unit/range logic is duplicated here."""

    model_config = ConfigDict(extra="forbid")

    observation_definition_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID | None = None
    value_integer: int | None = None
    value_decimal: float | None = None
    value_boolean: bool | None = None
    value_text: str | None = None
    note: str | None = None


class InspectionFindingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: FindingCategory
    severity: FindingSeverity
    affected_count: int | None = None
    notes: str | None = None
    suspected_cause: str | None = None

    @field_validator("affected_count")
    @classmethod
    def validate_affected_count(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("affected_count must be >= 0")
        return v


class GrowerInspectionCreate(BaseModel):
    """Records one Grower Inspection, optionally with structured Findings
    and/or Observation values recorded in the same command -- one atomic
    transaction (PILOT-AGRO-001 section 16's "Context -> Findings ->
    Observations -> Crop Issue if needed -> Save" workspace flow)."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    batch_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID | None = None
    effective_time: datetime | None = None
    inspected_count: int | None = None
    overall_assessment: OverallAssessment
    notes: str | None = None
    findings: list[InspectionFindingIn] = []
    observation_values: list[InspectionObservationValueIn] = []

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime | None) -> datetime | None:
        return _require_tz_aware(v) if v is not None else None

    @field_validator("inspected_count")
    @classmethod
    def validate_inspected_count(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("inspected_count must be >= 0")
        return v

    @model_validator(mode="after")
    def validate_affected_within_inspected(self) -> "GrowerInspectionCreate":
        if self.inspected_count is not None:
            for finding in self.findings:
                if finding.affected_count is not None and finding.affected_count > self.inspected_count:
                    raise ValueError("a finding's affected_count cannot exceed the inspection's inspected_count")
        return self


# --- Reads -----------------------------------------------------------------------


class InspectionFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: FindingCategory
    severity: FindingSeverity
    affected_count: int | None
    notes: str | None
    suspected_cause: str | None
    recorded_at: datetime


class GrowerInspectionRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    batch_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID | None
    location_id: uuid.UUID | None
    growing_protocol_version_id: uuid.UUID | None
    inspected_by_user_id: uuid.UUID
    effective_time: datetime
    recorded_time: datetime
    inspected_count: int | None
    overall_assessment: OverallAssessment
    notes: str | None
    observation_event_id: uuid.UUID | None
    findings: list[InspectionFindingRead]
