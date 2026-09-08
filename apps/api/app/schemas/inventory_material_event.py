from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


def _validate_positive_quantity(v: Decimal) -> Decimal:
    if v <= 0:
        raise ValueError("quantity must be positive")
    return v


# --- Commands ------------------------------------------------------------------------


class InventoryConsumptionCreate(BaseModel):
    """Material actually used by farm operations -- acts only on an Issue
    line's own outstanding balance, reduces Existence, never touches
    physical custody."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    issue_line_id: uuid.UUID
    quantity: Decimal
    effective_time: datetime

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        return _validate_positive_quantity(v)


class InventoryReturnCreate(BaseModel):
    """Unused issued material physically comes back to a Store Bin in the
    SAME Farm -- reduces the Issue line's own outstanding balance,
    increases Bin custody, Existence and Quality unchanged."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    issue_line_id: uuid.UUID
    destination_location_id: uuid.UUID
    quantity: Decimal
    effective_time: datetime

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        return _validate_positive_quantity(v)


class InventoryScrapCreate(BaseModel):
    """Material physically ceases to exist -- from exactly one of three
    truthful source buckets. `issue_line_id` only for `source_kind =
    'issued'`; `inventory_quantity_cohort_id` (+ `source_location_id`) for
    `'store_bin'`/`'not_put_away'`. A mandatory human-readable `reason` is
    always required."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    source_kind: Literal["issued", "store_bin", "not_put_away"]
    issue_line_id: uuid.UUID | None = None
    inventory_quantity_cohort_id: uuid.UUID | None = None
    source_location_id: uuid.UUID | None = None
    quantity: Decimal
    reason: str
    effective_time: datetime

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        return _validate_positive_quantity(v)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("scrap requires a human-readable reason")
        return v


# --- Reads -----------------------------------------------------------------------


class InventoryMaterialEventRead(BaseModel):
    id: uuid.UUID
    event_kind: str
    source_kind: str
    issue_line_id: uuid.UUID | None
    inventory_quantity_cohort_id: uuid.UUID
    source_location_id: uuid.UUID | None
    destination_location_id: uuid.UUID | None
    quantity_base: Decimal
    reason: str | None
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID


class IssueLineReconciliationRead(BaseModel):
    issue_line_id: uuid.UUID
    issued_quantity: Decimal
    consumed_quantity: Decimal
    returned_quantity: Decimal
    scrapped_quantity: Decimal
    outstanding_quantity: Decimal


class OutstandingIssuedMaterialRowRead(BaseModel):
    issue_line_id: uuid.UUID
    issue_id: uuid.UUID
    issue_code: str
    purpose: str
    inventory_item_id: uuid.UUID
    item_name: str
    base_uom_id: uuid.UUID
    inventory_lot_id: uuid.UUID | None
    manufacturer_lot_reference: str | None
    source_location_id: uuid.UUID | None
    issued_quantity: Decimal
    outstanding_quantity: Decimal


__all__ = [
    "InventoryConsumptionCreate",
    "InventoryReturnCreate",
    "InventoryScrapCreate",
    "InventoryMaterialEventRead",
    "IssueLineReconciliationRead",
    "OutstandingIssuedMaterialRowRead",
]
