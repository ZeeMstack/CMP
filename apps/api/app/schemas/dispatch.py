from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.schemas.harvest import MAX_WHOLE_UNIT_COUNT, _parse_strict_decimal, canonical_decimal_str

# PILOT-READY-001: a data-sanity bound only (rejects garbage input like a
# mistyped extra digit) -- deliberately NOT a cold-chain acceptability
# threshold, so it is wide enough to admit any real dispatch, ambient or
# frozen. No decimal-place truncation is enforced (no documented CMP
# temperature-precision convention exists to justify inventing one).
_MIN_DISPATCH_TEMPERATURE_C = Decimal("-100")
_MAX_DISPATCH_TEMPERATURE_C = Decimal("100")


def _parse_strict_temperature(v: object) -> Decimal:
    """Exact-Decimal parser for `dispatch_temperature_c`, mirroring
    `_parse_strict_decimal`'s no-bool/no-binary-float/finite rules, but
    -- unlike every weight field -- explicitly allowing negative values
    (frozen dispatches) and applying no decimal-place truncation."""
    if isinstance(v, bool):
        raise ValueError("dispatch_temperature_c must be a string, integer, or Decimal, not a boolean")
    if isinstance(v, float):
        raise ValueError(
            "dispatch_temperature_c must not be a binary float — send it as a JSON string, e.g. \"-18.5\""
        )
    if isinstance(v, Decimal):
        d = v
    elif isinstance(v, (str, int)):
        try:
            d = Decimal(str(v))
        except InvalidOperation as exc:
            raise ValueError("dispatch_temperature_c is not a valid decimal value") from exc
    else:
        raise ValueError("dispatch_temperature_c must be a string, integer, or Decimal")
    if not d.is_finite():
        raise ValueError("dispatch_temperature_c must be a finite value")
    if d <= _MIN_DISPATCH_TEMPERATURE_C or d >= _MAX_DISPATCH_TEMPERATURE_C:
        raise ValueError("dispatch_temperature_c is outside the supported range")
    return d


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


class DispatchLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finished_goods_lot_id: uuid.UUID
    dispatched_weight_kg: Decimal
    dispatched_package_count: int = Field(gt=0, le=MAX_WHOLE_UNIT_COUNT)

    @field_validator("dispatched_weight_kg", mode="before")
    @classmethod
    def validate_weight(cls, v: object) -> Decimal:
        return _parse_strict_decimal(v)


class DispatchEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    code: str
    external_reference: str | None = None
    note: str | None = None
    # PILOT-READY-001: exactly one Celsius reading per dispatch/vehicle,
    # applying to the whole dispatch -- never per line/lot/product. Lives
    # here, at the event (header) level, only -- DispatchLineIn never gets
    # this field.
    dispatch_temperature_c: Decimal
    lines: list[DispatchLineIn] = Field(min_length=1)

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("dispatch_temperature_c", mode="before")
    @classmethod
    def validate_dispatch_temperature(cls, v: object) -> Decimal:
        return _parse_strict_temperature(v)

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("external_reference", "note")
    @classmethod
    def validate_optional_text(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_lines(self) -> "DispatchEventCreate":
        lot_ids = [line.finished_goods_lot_id for line in self.lines]
        if len(lot_ids) != len(set(lot_ids)):
            raise ValueError("duplicate finished_goods_lot_id within one dispatch command")
        return self


# --- Reads -----------------------------------------------------------------------


class DispatchLineRead(BaseModel):
    id: uuid.UUID
    finished_goods_lot_id: uuid.UUID
    finished_goods_lot_code: str
    dispatched_weight_kg: Decimal
    dispatched_package_count: int
    ledger_entry_id: uuid.UUID

    @field_serializer("dispatched_weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class DispatchEventRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    lines: list[DispatchLineRead]
    total_dispatched_weight_kg: Decimal
    total_dispatched_package_count: int
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID
    external_reference: str | None
    note: str | None
    # Nullable only to honestly represent a row inserted before this
    # column existed -- never backfilled with an invented reading.
    dispatch_temperature_c: Decimal | None

    @field_serializer("total_dispatched_weight_kg")
    def serialize_total_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)

    @field_serializer("dispatch_temperature_c")
    def serialize_dispatch_temperature(self, v: Decimal | None) -> str | None:
        return canonical_decimal_str(v) if v is not None else None


__all__ = [
    "DispatchLineIn",
    "DispatchEventCreate",
    "DispatchLineRead",
    "DispatchEventRead",
]
