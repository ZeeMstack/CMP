from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.schemas.crop_batch import CropSummary, StageSummary, VarietySummary, WorkflowSummary
from app.schemas.sowing_event import CarrierSummary

MAX_WEIGHT_KG = Decimal("100000000000")
MAX_WHOLE_UNIT_COUNT = 9223372036854775807  # BIGINT max — whole_unit_count columns are BIGINT


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


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


def canonical_decimal_str(d: Decimal) -> str:
    """Non-exponent canonical string for a Decimal — `1.2`/`1.20`/`1.200`
    all normalize identically, and negative zero normalizes to `0`. Used
    both for API serialization and (imported by the service) idempotency
    fingerprint computation, so both share one definition of "same value"."""
    normalized = d.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _parse_strict_decimal(v: object) -> Decimal:
    if isinstance(v, bool):
        raise ValueError("weight must be a string, integer, or Decimal, not a boolean")
    if isinstance(v, float):
        raise ValueError(
            "weight must not be a binary float — send it as a JSON string, e.g. \"12.375\""
        )
    if isinstance(v, Decimal):
        d = v
    elif isinstance(v, (str, int)):
        try:
            d = Decimal(str(v))
        except InvalidOperation as exc:
            raise ValueError("weight is not a valid decimal value") from exc
    else:
        raise ValueError("weight must be a string, integer, or Decimal")
    if not d.is_finite():
        raise ValueError("weight must be a finite value")
    if d <= 0:
        raise ValueError("weight must be positive")
    if d >= MAX_WEIGHT_KG:
        raise ValueError("weight exceeds the supported range")
    # Check scale on the *normalized* value, not the literal input: a
    # literal like "1.2000" (raw exponent -4) or scientific notation like
    # "1.000E-3" carries excess trailing precision in its string form but
    # is exactly representable in <=3 decimal places once trailing zeros
    # are stripped — normalize() is the same canonicalization
    # `canonical_decimal_str` already applies for fingerprinting/output, so
    # "does this value fit the envelope" and "what does it fingerprint as"
    # agree. A truly excess-precision value (e.g. "1.2345") still has a
    # non-zero digit past the third decimal place after normalization and
    # is correctly rejected.
    normalized_exponent = d.normalize().as_tuple().exponent
    if not isinstance(normalized_exponent, int) or normalized_exponent < -3:
        raise ValueError("weight supports at most 3 decimal places")
    return d


# --- Commands ----------------------------------------------------------------------


class HarvestSourceLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_carrier_assignment_id: uuid.UUID
    harvested_weight_kg: Decimal
    whole_unit_count: int | None = Field(default=None, gt=0, le=MAX_WHOLE_UNIT_COUNT)
    note: str | None = None

    @field_validator("harvested_weight_kg", mode="before")
    @classmethod
    def validate_weight(cls, v: object) -> Decimal:
        return _parse_strict_decimal(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class HarvestEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    produce_lot_code: str
    note: str | None = None
    source_lines: list[HarvestSourceLineIn] = Field(min_length=1, max_length=500)

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("produce_lot_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_lines(self) -> "HarvestEventCreate":
        assignment_ids = [line.batch_carrier_assignment_id for line in self.source_lines]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("duplicate batch_carrier_assignment_id within one harvest command")
        counts = [line.whole_unit_count for line in self.source_lines]
        has_some = any(c is not None for c in counts)
        has_all = all(c is not None for c in counts)
        if has_some and not has_all:
            raise ValueError("whole_unit_count must be supplied on every source line or on none of them")
        return self


# --- Reads -----------------------------------------------------------------------


class HarvestSourceLineRead(BaseModel):
    id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    carrier: CarrierSummary
    opening_kind: str
    opening_id: uuid.UUID
    harvested_weight_kg: Decimal
    whole_unit_count: int | None
    note: str | None

    @field_serializer("harvested_weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class HarvestEventRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    batch_id: uuid.UUID
    batch_code: str
    workflow: WorkflowSummary
    workflow_version_id: uuid.UUID
    crop: CropSummary
    variety: VarietySummary | None
    stage: StageSummary
    produce_lot_id: uuid.UUID
    produce_lot_code: str
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID
    note: str | None
    source_lines: list[HarvestSourceLineRead]
    total_harvested_weight_kg: Decimal
    total_whole_unit_count: int | None

    @field_serializer("total_harvested_weight_kg")
    def serialize_total_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class HarvestedProduceLotRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    harvest_event_id: uuid.UUID
    batch_id: uuid.UUID
    batch_code: str
    workflow: WorkflowSummary
    workflow_version_id: uuid.UUID
    crop: CropSummary
    variety: VarietySummary | None
    total_harvested_weight_kg: Decimal
    total_whole_unit_count: int | None
    effective_time: datetime
    recorded_at: datetime
    source_lines: list[HarvestSourceLineRead]

    @field_serializer("total_harvested_weight_kg")
    def serialize_total_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)
