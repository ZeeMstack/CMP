from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


def _require_non_blank(v: str, *, field_name: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{field_name} must not be blank")
    return v


class InventoryItemPackagingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    inventory_item_id: uuid.UUID
    code: str
    display_name: str
    package_quantity: Decimal

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _require_non_blank(v, field_name="code").upper()

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str) -> str:
        return _require_non_blank(v, field_name="display_name")

    @field_validator("package_quantity")
    @classmethod
    def validate_package_quantity(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("package_quantity must be positive")
        return v


class InventoryItemPackagingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    display_name: str
    package_quantity: Decimal

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, v: str) -> str:
        return _require_non_blank(v, field_name="display_name")

    @field_validator("package_quantity")
    @classmethod
    def validate_package_quantity(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("package_quantity must be positive")
        return v


class InventoryItemPackagingDeactivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class InventoryItemPackagingReactivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class InventoryItemPackagingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    inventory_item_id: uuid.UUID
    code: str
    display_name: str
    package_quantity: Decimal
    status: str
    created_at: datetime


__all__ = [
    "InventoryItemPackagingCreate",
    "InventoryItemPackagingUpdate",
    "InventoryItemPackagingDeactivate",
    "InventoryItemPackagingReactivate",
    "InventoryItemPackagingRead",
]
