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


class ReservationLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_item_id: uuid.UUID
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        return _validate_positive_quantity(v)


class InventoryReservationCreate(BaseModel):
    """A fungible CLAIM against usable in-Store quantity, frozen at
    Farm + Item -- never touches Existence, Quality, or physical custody."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    purpose: str
    effective_time: datetime
    lines: list[ReservationLineCreate]

    @field_validator("lines")
    @classmethod
    def validate_lines(cls, v: list[ReservationLineCreate]) -> list[ReservationLineCreate]:
        if not v:
            raise ValueError("a reservation must have at least one line")
        return v


class InventoryReservationReleaseCreate(BaseModel):
    """Releases (part of) the unused CLAIM on one reservation line -- never
    moves stock, never alters Existence/Quality."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    quantity: Decimal
    effective_time: datetime
    reason: str | None = None

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        return _validate_positive_quantity(v)


# --- Reads -----------------------------------------------------------------------


class InventoryReservationLineRead(BaseModel):
    id: uuid.UUID
    inventory_item_id: uuid.UUID
    requested_quantity_base: Decimal
    remaining_quantity_base: Decimal
    blocked_by_quality: bool


class InventoryReservationRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    code: str
    purpose: str
    requested_by_user_id: uuid.UUID
    effective_time: datetime
    recorded_time: datetime
    lines: list[InventoryReservationLineRead]


class InventoryReservationLineEntryRead(BaseModel):
    id: uuid.UUID
    reservation_line_id: uuid.UUID
    entry_kind: str
    quantity_base: Decimal
    effective_time: datetime
    actor_user_id: uuid.UUID
    reason: str | None
    issue_id: uuid.UUID | None


__all__ = [
    "ReservationLineCreate",
    "InventoryReservationCreate",
    "InventoryReservationReleaseCreate",
    "InventoryReservationLineRead",
    "InventoryReservationRead",
    "InventoryReservationLineEntryRead",
]
