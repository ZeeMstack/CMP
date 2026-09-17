from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


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
    effective_at: datetime
    target_volume: Decimal | None = None
    target_volume_uom_id: uuid.UUID | None = None
    actual_volume: Decimal | None = None
    actual_volume_uom_id: uuid.UUID | None = None
    notes: str | None = None
    client_command_id: uuid.UUID
    inputs: list[NutrientMixInputCreate]


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
