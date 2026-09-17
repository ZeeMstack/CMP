from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("must be timezone-aware")
    return v


class NutrientMixInputCreate(BaseModel):
    inventory_item_id: uuid.UUID | None = None
    component_label: str
    actual_quantity: Decimal
    actual_quantity_uom_id: uuid.UUID
    sequence_number: int | None = None
    note: str | None = None

    @field_validator("component_label")
    @classmethod
    def _label_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("component_label must not be blank")
        return v


class NutrientMixCreate(BaseModel):
    nutrient_recipe_version_id: uuid.UUID | None = None
    # PILOT-WATER-001B (HOTFIX-TIME-002 pattern): omitting effective_at
    # means "record now" -- see WaterMeasurementCreate's identical note.
    effective_at: datetime | None = None
    target_volume: Decimal | None = None
    target_volume_uom_id: uuid.UUID | None = None
    actual_volume: Decimal | None = None
    actual_volume_uom_id: uuid.UUID | None = None
    notes: str | None = None
    client_command_id: uuid.UUID
    inputs: list[NutrientMixInputCreate]

    @field_validator("effective_at")
    @classmethod
    def validate_effective_at(cls, v: datetime | None) -> datetime | None:
        return v if v is None else _require_tz_aware(v)


class NutrientMixRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    reservoir_id: uuid.UUID
    nutrient_recipe_version_id: uuid.UUID | None
    effective_at: datetime
    recorded_at: datetime
    target_volume: Decimal | None
    actual_volume: Decimal | None
    notes: str | None


class NutrientMixInputRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    nutrient_mix_id: uuid.UUID
    inventory_item_id: uuid.UUID | None
    component_label: str
    actual_quantity: Decimal
    actual_quantity_uom_id: uuid.UUID
    sequence_number: int | None
    note: str | None
