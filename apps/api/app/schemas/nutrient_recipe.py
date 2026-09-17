from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


class NutrientRecipeCreate(BaseModel):
    code: str
    name: str
    crop_id: uuid.UUID | None = None
    variety_id: uuid.UUID | None = None
    production_system_id: uuid.UUID | None = None

    @field_validator("code", "name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class NutrientRecipeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    crop_id: uuid.UUID | None
    variety_id: uuid.UUID | None
    production_system_id: uuid.UUID | None
    status: str


class NutrientRecipeVersionCreate(BaseModel):
    client_command_id: uuid.UUID
    reason: str
    target_ec: Decimal | None = None
    target_ph: Decimal | None = None
    instructions: str | None = None
    effective_date: date | None = None

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reason must not be blank")
        return v


class NutrientRecipeVersionLifecycleCommand(BaseModel):
    client_command_id: uuid.UUID


class NutrientRecipeVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    nutrient_recipe_id: uuid.UUID
    version_number: int
    state: str
    reason: str
    target_ec: Decimal | None
    target_ph: Decimal | None
    instructions: str | None
    effective_date: date | None


class NutrientRecipeComponentCreate(BaseModel):
    inventory_item_id: uuid.UUID | None = None
    component_label: str
    target_quantity: Decimal
    target_quantity_uom_id: uuid.UUID
    basis_volume: Decimal | None = None
    basis_volume_uom_id: uuid.UUID | None = None
    sequence_number: int | None = None
    instructions: str | None = None

    @field_validator("component_label")
    @classmethod
    def _label_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("component_label must not be blank")
        return v


class NutrientRecipeComponentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    nutrient_recipe_version_id: uuid.UUID
    inventory_item_id: uuid.UUID | None
    component_label: str
    target_quantity: Decimal
    target_quantity_uom_id: uuid.UUID
    basis_volume: Decimal | None
    basis_volume_uom_id: uuid.UUID | None
    sequence_number: int | None
    instructions: str | None
