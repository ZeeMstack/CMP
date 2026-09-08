from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


def _validate_positive_quantity(v: Decimal) -> Decimal:
    if v <= 0:
        raise ValueError("quantity must be positive")
    return v


# --- Commands ------------------------------------------------------------------------


class IssueLineCreate(BaseModel):
    """The operator's actual physical source: Item, usable Cohort, and
    Store Bin -- `reservation_line_id` set only when this line fulfills
    part of a Reservation line."""

    model_config = ConfigDict(extra="forbid")

    inventory_item_id: uuid.UUID
    inventory_quantity_cohort_id: uuid.UUID
    source_location_id: uuid.UUID
    quantity: Decimal
    reservation_line_id: uuid.UUID | None = None

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        return _validate_positive_quantity(v)


class InventoryIssueCreate(BaseModel):
    """A CUSTODY TRANSFER: Store Bin custody -> "Issued to operations"
    custody. Never touches Existence or Quality. Serves both Direct Issue
    (no `reservation_id`/line `reservation_line_id`) and Issue against
    Reservation (one or more lines pin a `reservation_line_id`)."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    purpose: str
    effective_time: datetime
    reservation_id: uuid.UUID | None = None
    lines: list[IssueLineCreate]

    @field_validator("lines")
    @classmethod
    def validate_lines(cls, v: list[IssueLineCreate]) -> list[IssueLineCreate]:
        if not v:
            raise ValueError("an issue must have at least one line")
        return v


# --- Reads -----------------------------------------------------------------------


class InventoryIssueLineRead(BaseModel):
    id: uuid.UUID
    inventory_item_id: uuid.UUID | None = None
    inventory_quantity_cohort_id: uuid.UUID
    source_location_id: uuid.UUID | None
    moved_quantity_base: Decimal
    reservation_line_id: uuid.UUID | None


class InventoryIssueRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    purpose: str
    issued_by_user_id: uuid.UUID
    effective_time: datetime
    recorded_time: datetime
    reservation_id: uuid.UUID | None
    lines: list[InventoryIssueLineRead]


class ItemFarmAvailabilityRead(BaseModel):
    inventory_item_id: uuid.UUID
    farm_id: uuid.UUID
    in_store_quantity: Decimal
    reserved_quantity: Decimal
    issued_to_operations_quantity: Decimal
    available_to_issue_quantity: Decimal


class IssuableSourceRead(BaseModel):
    """One (Cohort, Bin) pair an operator may pick as an Issue line's
    physical source -- usable, not expired, positive Bin balance."""

    inventory_quantity_cohort_id: uuid.UUID
    inventory_lot_id: uuid.UUID | None
    lot_label: str | None
    source_location_id: uuid.UUID
    bin_label: str
    balance: Decimal


__all__ = [
    "IssueLineCreate",
    "InventoryIssueCreate",
    "InventoryIssueLineRead",
    "InventoryIssueRead",
    "ItemFarmAvailabilityRead",
    "IssuableSourceRead",
]
