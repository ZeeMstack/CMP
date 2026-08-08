from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.schemas.harvest import MAX_WHOLE_UNIT_COUNT, _parse_strict_decimal, canonical_decimal_str

MOVEMENT_KINDS = ("place", "transfer", "release")


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


# --- Commands ------------------------------------------------------------------------


class FinishedGoodsStorageMovementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    finished_goods_lot_id: uuid.UUID
    movement_kind: str
    source_location_id: uuid.UUID | None = None
    destination_location_id: uuid.UUID | None = None
    moved_weight_kg: Decimal
    moved_package_count: int = Field(gt=0, le=MAX_WHOLE_UNIT_COUNT)
    note: str | None = None

    @field_validator("moved_weight_kg", mode="before")
    @classmethod
    def validate_weight(cls, v: object) -> Decimal:
        return _parse_strict_decimal(v)

    @field_validator("movement_kind")
    @classmethod
    def validate_kind(cls, v: str) -> str:
        if v not in MOVEMENT_KINDS:
            raise ValueError(f"movement_kind must be one of {MOVEMENT_KINDS}")
        return v

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_shape(self) -> "FinishedGoodsStorageMovementCreate":
        if self.movement_kind == "place":
            if self.source_location_id is not None:
                raise ValueError("place must not set source_location_id")
            if self.destination_location_id is None:
                raise ValueError("place requires destination_location_id")
        elif self.movement_kind == "transfer":
            if self.source_location_id is None or self.destination_location_id is None:
                raise ValueError("transfer requires both source_location_id and destination_location_id")
            if self.source_location_id == self.destination_location_id:
                raise ValueError("transfer source and destination locations must differ")
        elif self.movement_kind == "release":
            if self.source_location_id is None:
                raise ValueError("release requires source_location_id")
            if self.destination_location_id is not None:
                raise ValueError("release must not set destination_location_id")
        return self


# --- Reads -----------------------------------------------------------------------


class FinishedGoodsStorageMovementRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    finished_goods_lot_id: uuid.UUID
    movement_kind: str
    source_location_id: uuid.UUID | None
    destination_location_id: uuid.UUID | None
    moved_weight_kg: Decimal
    moved_package_count: int
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID
    note: str | None

    @field_serializer("moved_weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class LocationBalanceRead(BaseModel):
    location_id: uuid.UUID
    weight_kg: Decimal
    package_count: int

    @field_serializer("weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class FinishedGoodsPlacementRead(BaseModel):
    finished_goods_lot_id: uuid.UUID
    finished_goods_lot_code: str
    available_weight_kg: Decimal
    available_package_count: int
    total_placed_weight_kg: Decimal
    total_placed_package_count: int
    unplaced_weight_kg: Decimal
    unplaced_package_count: int
    locations: list[LocationBalanceRead]

    @field_serializer("available_weight_kg", "total_placed_weight_kg", "unplaced_weight_kg")
    def serialize_weights(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class LotBalanceRead(BaseModel):
    finished_goods_lot_id: uuid.UUID
    finished_goods_lot_code: str
    weight_kg: Decimal
    package_count: int

    @field_serializer("weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class LocationInventoryRead(BaseModel):
    location_id: uuid.UUID
    lots: list[LotBalanceRead]


__all__ = [
    "FinishedGoodsStorageMovementCreate",
    "FinishedGoodsStorageMovementRead",
    "LocationBalanceRead",
    "FinishedGoodsPlacementRead",
    "LotBalanceRead",
    "LocationInventoryRead",
]
