from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.schemas.crop_batch import CropSummary, VarietySummary
from app.schemas.harvest import MAX_WHOLE_UNIT_COUNT, _parse_strict_decimal, canonical_decimal_str

MAX_GRADING_OUTPUTS = 50


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


# --- Commands ----------------------------------------------------------------------


class GradingOutputIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grade_definition_version_id: uuid.UUID
    code: str
    output_weight_kg: Decimal
    output_whole_unit_count: int | None = Field(default=None, gt=0, le=MAX_WHOLE_UNIT_COUNT)

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("output_weight_kg", mode="before")
    @classmethod
    def validate_weight(cls, v: object) -> Decimal:
        return _parse_strict_decimal(v)


class GradingEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    source_harvested_produce_lot_id: uuid.UUID
    processing_hall_location_id: uuid.UUID
    effective_time: datetime
    note: str | None = None

    input_presented_weight_kg: Decimal
    input_presented_whole_unit_count: int | None = Field(default=None, gt=0, le=MAX_WHOLE_UNIT_COUNT)
    rejected_weight_kg: Decimal
    rejected_whole_unit_count: int | None = Field(default=None, ge=0, le=MAX_WHOLE_UNIT_COUNT)
    loss_weight_kg: Decimal
    loss_whole_unit_count: int | None = Field(default=None, ge=0, le=MAX_WHOLE_UNIT_COUNT)
    sample_weight_kg: Decimal
    sample_whole_unit_count: int | None = Field(default=None, ge=0, le=MAX_WHOLE_UNIT_COUNT)
    remainder_weight_kg: Decimal
    remainder_whole_unit_count: int | None = Field(default=None, ge=0, le=MAX_WHOLE_UNIT_COUNT)

    outputs: list[GradingOutputIn] = Field(default_factory=list, max_length=MAX_GRADING_OUTPUTS)

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @field_validator("input_presented_weight_kg", mode="before")
    @classmethod
    def validate_input_presented_weight(cls, v: object) -> Decimal:
        return _parse_strict_decimal(v)

    @field_validator(
        "rejected_weight_kg", "loss_weight_kg", "sample_weight_kg", "remainder_weight_kg", mode="before"
    )
    @classmethod
    def validate_nonnegative_weight(cls, v: object) -> Decimal:
        return _parse_strict_decimal(v, allow_zero=True)

    @model_validator(mode="after")
    def validate_shape(self) -> "GradingEventCreate":
        # Count-mode all-or-none across the top-level fields: either every
        # one is populated (count-bearing source) or every one is NULL
        # (weight-only source) -- never a partial mix, mirroring
        # GradingEvent's own DB-level ck_grading_events_count_mode_shape.
        count_fields = [
            self.input_presented_whole_unit_count, self.rejected_whole_unit_count, self.loss_whole_unit_count,
            self.sample_whole_unit_count, self.remainder_whole_unit_count,
        ]
        populated = [c is not None for c in count_fields]
        if any(populated) and not all(populated):
            raise ValueError(
                "input_presented/rejected/loss/sample/remainder whole_unit_count must be either all null "
                "(weight-only source) or all populated (count-bearing source)"
            )
        count_mode = all(populated)

        if self.remainder_weight_kg >= self.input_presented_weight_kg:
            raise ValueError("remainder_weight_kg must be less than input_presented_weight_kg")
        if count_mode and self.remainder_whole_unit_count >= self.input_presented_whole_unit_count:
            raise ValueError("remainder_whole_unit_count must be less than input_presented_whole_unit_count")

        seen_grade_versions: set[uuid.UUID] = set()
        seen_codes: set[str] = set()
        for output in self.outputs:
            if output.grade_definition_version_id in seen_grade_versions:
                raise ValueError("duplicate grade_definition_version_id within one grading command's outputs")
            seen_grade_versions.add(output.grade_definition_version_id)
            if output.code in seen_codes:
                raise ValueError("duplicate output code within one grading command's outputs")
            seen_codes.add(output.code)
            if count_mode and output.output_whole_unit_count is None:
                raise ValueError(
                    f"output {output.code} must carry output_whole_unit_count for a count-bearing source"
                )
            if not count_mode and output.output_whole_unit_count is not None:
                raise ValueError(
                    f"output {output.code} must not carry output_whole_unit_count for a weight-only source"
                )
        return self


# --- Reads -----------------------------------------------------------------------


class GradedProduceLotRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    grading_event_id: uuid.UUID
    code: str
    crop: CropSummary
    variety: VarietySummary | None
    grade_definition_version_id: uuid.UUID
    original_received_weight_kg: Decimal
    original_received_whole_unit_count: int | None
    effective_time: datetime
    recorded_at: datetime

    @field_serializer("original_received_weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class GradingEventRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    source_harvested_produce_lot_id: uuid.UUID
    source_produce_lot_code: str
    processing_hall_location_id: uuid.UUID
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID
    note: str | None

    input_presented_weight_kg: Decimal
    input_presented_whole_unit_count: int | None
    rejected_weight_kg: Decimal
    rejected_whole_unit_count: int | None
    loss_weight_kg: Decimal
    loss_whole_unit_count: int | None
    sample_weight_kg: Decimal
    sample_whole_unit_count: int | None
    remainder_weight_kg: Decimal
    remainder_whole_unit_count: int | None
    processed_weight_kg: Decimal
    processed_whole_unit_count: int | None

    outputs: list[GradedProduceLotRead]

    @field_serializer(
        "input_presented_weight_kg", "rejected_weight_kg", "loss_weight_kg", "sample_weight_kg",
        "remainder_weight_kg", "processed_weight_kg",
    )
    def serialize_weights(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


# --- POSTHARVEST-OPS-001H: reversal ------------------------------------------------


class GradingReversalEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    reason_code: str
    # PRE-COMMIT AUDIT: optional -- only reason_code is mandatory (mirrors
    # SeedlingDispositionEvent's own REVERSAL shape).
    note: str | None = None

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reason_code must not be blank")
        return v

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class GradingReversalOutputRead(BaseModel):
    id: uuid.UUID
    graded_produce_lot_id: uuid.UUID
    graded_produce_lot_code: str
    reversed_weight_kg: Decimal
    reversed_whole_unit_count: int | None

    @field_serializer("reversed_weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class GradingReversalEventRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    grading_event_id: uuid.UUID
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID
    reason_code: str
    note: str | None
    restored_produce_lot_weight_kg: Decimal
    restored_produce_lot_whole_unit_count: int | None
    outputs: list[GradingReversalOutputRead]

    @field_serializer("restored_produce_lot_weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


__all__ = [
    "GradingOutputIn",
    "GradingEventCreate",
    "GradedProduceLotRead",
    "GradingEventRead",
    "GradingReversalEventCreate",
    "GradingReversalOutputRead",
    "GradingReversalEventRead",
]
