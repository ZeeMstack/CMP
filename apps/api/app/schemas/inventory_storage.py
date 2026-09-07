from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

STORAGE_MOVEMENT_KINDS = ("putaway", "transfer", "split_out", "split_in")


def _validate_positive_quantity(v: Decimal) -> Decimal:
    if v <= 0:
        raise ValueError("quantity must be positive")
    return v


# --- Commands ------------------------------------------------------------------------


class InventoryPutawayCreate(BaseModel):
    """"Not put away" quantity -> a Store Bin. Existence-neutral,
    Quality-neutral."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    inventory_quantity_cohort_id: uuid.UUID
    destination_location_id: uuid.UUID
    quantity: Decimal
    effective_time: datetime
    note: str | None = None

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        return _validate_positive_quantity(v)


class InventoryStorageTransferCreate(BaseModel):
    """Store Bin A -> Store Bin B, within the same Farm. Existence-neutral,
    Quality-neutral."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    inventory_quantity_cohort_id: uuid.UUID
    source_location_id: uuid.UUID
    destination_location_id: uuid.UUID
    quantity: Decimal
    effective_time: datetime
    note: str | None = None

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        return _validate_positive_quantity(v)


# --- Reads -----------------------------------------------------------------------


class InventoryStorageMovementRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    inventory_quantity_cohort_id: uuid.UUID
    movement_kind: str
    source_location_id: uuid.UUID | None
    destination_location_id: uuid.UUID | None
    moved_quantity_base: Decimal
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID | None
    note: str | None


class StorageBucketRead(BaseModel):
    """One eligible physical bucket for a Quality partial action --
    "Not put away" (`location_id` is None) or one specific Bin."""

    location_id: uuid.UUID | None
    label: str
    balance: Decimal


class CohortStorageBreakdownRead(BaseModel):
    inventory_quantity_cohort_id: uuid.UUID
    not_put_away_quantity: Decimal
    buckets: list[StorageBucketRead]


class NotPutAwayQueueEntryRead(BaseModel):
    inventory_quantity_cohort_id: uuid.UUID
    inventory_item_id: uuid.UUID
    item_name: str
    base_uom_id: uuid.UUID
    inventory_lot_id: uuid.UUID | None
    manufacturer_lot_reference: str | None
    received_at_farm_id: uuid.UUID
    receipt_code: str
    receipt_received_at: datetime
    not_put_away_quantity: Decimal


class ItemStorageBinBalanceRead(BaseModel):
    location_id: uuid.UUID
    label: str
    balance: Decimal


class ItemStorageBreakdownRead(BaseModel):
    inventory_item_id: uuid.UUID
    not_put_away_quantity: Decimal
    bins: list[ItemStorageBinBalanceRead]


__all__ = [
    "InventoryPutawayCreate",
    "InventoryStorageTransferCreate",
    "InventoryStorageMovementRead",
    "StorageBucketRead",
    "CohortStorageBreakdownRead",
    "NotPutAwayQueueEntryRead",
    "ItemStorageBinBalanceRead",
    "ItemStorageBreakdownRead",
]
