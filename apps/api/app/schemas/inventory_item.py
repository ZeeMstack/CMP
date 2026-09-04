from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


def _require_non_blank(v: str, *, field_name: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{field_name} must not be blank")
    return v


def _validate_tracking_policy(
    *, lot_tracking_required: bool, expiry_tracking_required: bool, qc_release_required: bool
) -> None:
    """docs/domain/STORE_INVENTORY_MODEL.md §5: expiry tracking and QC
    release are both InventoryLot-level concepts and meaningless on
    material that isn't lot-tracked at all."""
    if expiry_tracking_required and not lot_tracking_required:
        raise ValueError("expiry_tracking_required requires lot_tracking_required")
    if qc_release_required and not lot_tracking_required:
        raise ValueError("qc_release_required requires lot_tracking_required")


class InventoryItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    code: str
    name: str
    category_id: uuid.UUID
    base_uom_id: uuid.UUID
    lot_tracking_required: bool = False
    expiry_tracking_required: bool = False
    qc_release_required: bool = False

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _require_non_blank(v, field_name="name")

    @model_validator(mode="after")
    def validate_tracking_policy(self) -> "InventoryItemCreate":
        _validate_tracking_policy(
            lot_tracking_required=self.lot_tracking_required,
            expiry_tracking_required=self.expiry_tracking_required,
            qc_release_required=self.qc_release_required,
        )
        return self


class InventoryItemUpdate(BaseModel):
    """Full-body update of every mutable field -- `code` is never accepted
    here; there is no update path for it at all. `base_uom_id` IS
    updatable in STORE-INV-001B (see the model's own docstring)."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    name: str
    category_id: uuid.UUID
    base_uom_id: uuid.UUID
    lot_tracking_required: bool
    expiry_tracking_required: bool
    qc_release_required: bool

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _require_non_blank(v, field_name="name")

    @model_validator(mode="after")
    def validate_tracking_policy(self) -> "InventoryItemUpdate":
        _validate_tracking_policy(
            lot_tracking_required=self.lot_tracking_required,
            expiry_tracking_required=self.expiry_tracking_required,
            qc_release_required=self.qc_release_required,
        )
        return self


class InventoryItemDeactivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class InventoryItemReactivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID


class InventoryItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    inventory_category_id: uuid.UUID
    base_uom_id: uuid.UUID
    lot_tracking_required: bool
    expiry_tracking_required: bool
    qc_release_required: bool
    status: str
    created_at: datetime


__all__ = [
    "InventoryItemCreate",
    "InventoryItemUpdate",
    "InventoryItemDeactivate",
    "InventoryItemReactivate",
    "InventoryItemRead",
]
