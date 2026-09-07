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


class InventoryAdjustmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    inventory_quantity_cohort_id: uuid.UUID
    quantity_delta: Decimal
    effective_time: datetime
    reason: str

    @field_validator("quantity_delta")
    @classmethod
    def validate_quantity_delta(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("quantity_delta must not be zero")
        return v

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        return _require_non_blank(v, field_name="reason")


class InventoryExistenceReversalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    target_entry_id: uuid.UUID
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        return _require_non_blank(v, field_name="reason")


class InventoryExistenceLedgerEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    inventory_quantity_cohort_id: uuid.UUID
    inventory_item_id: uuid.UUID
    inventory_lot_id: uuid.UUID | None
    receiving_farm_id: uuid.UUID
    entry_kind: str
    quantity_delta_base: Decimal
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    reason: str | None
    reversal_of_entry_id: uuid.UUID | None


class InventoryItemExistenceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_item_id: uuid.UUID
    existing_quantity: Decimal


class InventoryLotExistenceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_lot_id: uuid.UUID
    existing_quantity: Decimal


class InventoryItemCohortProvenanceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_quantity_cohort_id: uuid.UUID
    inventory_lot_id: uuid.UUID | None
    source_goods_receipt_line_id: uuid.UUID
    received_at_farm_id: uuid.UUID
    balance: Decimal


__all__ = [
    "InventoryAdjustmentCreate",
    "InventoryExistenceReversalCreate",
    "InventoryExistenceLedgerEntryRead",
    "InventoryItemExistenceRead",
    "InventoryLotExistenceRead",
    "InventoryItemCohortProvenanceRead",
]
