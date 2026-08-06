from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.schemas.crop_batch import CropSummary, VarietySummary
from app.schemas.harvest import MAX_WHOLE_UNIT_COUNT, _parse_strict_decimal, canonical_decimal_str

MAX_PACKING_INPUT_LINES = 50


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


class PackingInputLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    harvested_produce_lot_id: uuid.UUID
    consumed_weight_kg: Decimal
    consumed_whole_unit_count: int | None = Field(default=None, gt=0, le=MAX_WHOLE_UNIT_COUNT)
    note: str | None = None

    @field_validator("consumed_weight_kg", mode="before")
    @classmethod
    def validate_weight(cls, v: object) -> Decimal:
        return _parse_strict_decimal(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class PackingEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    finished_goods_lot_code: str
    package_count: int = Field(gt=0, le=MAX_WHOLE_UNIT_COUNT)
    packed_output_weight_kg: Decimal
    process_loss_weight_kg: Decimal
    rejected_weight_kg: Decimal
    note: str | None = None
    input_lines: list[PackingInputLineIn] = Field(min_length=1, max_length=MAX_PACKING_INPUT_LINES)

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("finished_goods_lot_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("packed_output_weight_kg", mode="before")
    @classmethod
    def validate_packed_output_weight(cls, v: object) -> Decimal:
        return _parse_strict_decimal(v)

    @field_validator("process_loss_weight_kg", "rejected_weight_kg", mode="before")
    @classmethod
    def validate_nonnegative_weight(cls, v: object) -> Decimal:
        return _parse_strict_decimal(v, allow_zero=True)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_lines(self) -> "PackingEventCreate":
        lot_ids = [line.harvested_produce_lot_id for line in self.input_lines]
        if len(lot_ids) != len(set(lot_ids)):
            raise ValueError("duplicate harvested_produce_lot_id within one packing command")
        return self


# --- Reads -----------------------------------------------------------------------


class PackingInputLineRead(BaseModel):
    id: uuid.UUID
    harvested_produce_lot_id: uuid.UUID
    produce_lot_code: str
    harvest_event_id: uuid.UUID
    consumed_weight_kg: Decimal
    consumed_whole_unit_count: int | None
    ledger_entry_id: uuid.UUID
    note: str | None
    recorded_time: datetime

    @field_serializer("consumed_weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class FinishedGoodsLotSummary(BaseModel):
    id: uuid.UUID
    code: str
    net_packed_weight_kg: Decimal
    package_count: int

    @field_serializer("net_packed_weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class PackingEventRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    crop: CropSummary
    variety: VarietySummary | None
    finished_goods_lot: FinishedGoodsLotSummary
    input_lines: list[PackingInputLineRead]
    total_input_weight_kg: Decimal
    packed_output_weight_kg: Decimal
    process_loss_weight_kg: Decimal
    rejected_weight_kg: Decimal
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID
    note: str | None

    @field_serializer(
        "total_input_weight_kg", "packed_output_weight_kg", "process_loss_weight_kg", "rejected_weight_kg"
    )
    def serialize_weights(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class FinishedGoodsLotRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    packing_event_id: uuid.UUID
    crop: CropSummary
    variety: VarietySummary | None
    net_packed_weight_kg: Decimal
    package_count: int
    source_produce_lot_ids: list[uuid.UUID]
    effective_time: datetime
    recorded_time: datetime

    @field_serializer("net_packed_weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


__all__ = [
    "PackingInputLineIn",
    "PackingEventCreate",
    "PackingInputLineRead",
    "FinishedGoodsLotSummary",
    "PackingEventRead",
    "FinishedGoodsLotRead",
]
