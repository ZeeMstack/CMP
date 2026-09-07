from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

VALID_DISPOSITIONS = ("RELEASED", "HELD", "REJECTED", "HOLD_RELEASED")


def _require_non_blank(v: str, *, field_name: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{field_name} must not be blank")
    return v


def _validate_disposition(v: str) -> str:
    if v not in VALID_DISPOSITIONS:
        raise ValueError(f"disposition must be one of {VALID_DISPOSITIONS}")
    return v


class QualityDispositionCreate(BaseModel):
    """Release / Hold / Reject / Hold-Release -- one ordinary whole-cohort
    human quality decision."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    inventory_quantity_cohort_id: uuid.UUID
    disposition: str
    effective_time: datetime
    reason: str | None = None

    @field_validator("disposition")
    @classmethod
    def validate_disposition(cls, v: str) -> str:
        return _validate_disposition(v)


class QualityDispositionCorrectionCreate(BaseModel):
    """Corrects the cohort's current human decision only -- never the
    automatic opening RECEIVED_QUARANTINED fact. `target_event_id` is the
    event the OPERATOR OBSERVED (read from the Quality work-queue), never
    resolved to "whatever is current" server-side -- if the cohort's
    current decision has since changed, the command is rejected as a
    stale-target conflict."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    inventory_quantity_cohort_id: uuid.UUID
    target_event_id: uuid.UUID
    reason: str
    replacement_disposition: str | None = None
    effective_time: datetime

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        return _require_non_blank(v, field_name="reason")

    @field_validator("replacement_disposition")
    @classmethod
    def validate_replacement_disposition(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_disposition(v)


class QualityPartialDispositionCreate(BaseModel):
    """"Apply disposition to part of quantity" -- never named "Split
    Cohort" anywhere in this surface."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    inventory_quantity_cohort_id: uuid.UUID
    quantity: Decimal
    disposition: str
    effective_time: datetime
    reason: str | None = None
    custody_location_id: uuid.UUID | None = None

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("quantity must be positive")
        return v

    @field_validator("disposition")
    @classmethod
    def validate_disposition(cls, v: str) -> str:
        return _validate_disposition(v)


class QualityPartialCorrectionCreate(BaseModel):
    """"Correct decision for part of quantity" -- compensating quantity
    partitioning for a mistaken classification (e.g. 20 kg of a 100 kg
    REJECTED cohort wrongly rejected). NEVER an ordinary forward
    transition and never named "Split Cohort" anywhere in this surface.
    `target_event_id` must be the source cohort's CURRENT human decision,
    as observed by the operator via the Quality work-queue."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    inventory_quantity_cohort_id: uuid.UUID
    target_event_id: uuid.UUID
    quantity: Decimal
    corrected_disposition: str
    reason: str
    effective_time: datetime
    custody_location_id: uuid.UUID | None = None

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("quantity must be positive")
        return v

    @field_validator("corrected_disposition")
    @classmethod
    def validate_corrected_disposition(cls, v: str) -> str:
        return _validate_disposition(v)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        return _require_non_blank(v, field_name="reason")


class QualityPartialCorrectionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_cohort_id: uuid.UUID
    source_cohort_id: uuid.UUID
    target_event_id: uuid.UUID
    quantity: Decimal
    corrected_disposition: str
    custody_location_id: uuid.UUID | None = None


class QualityDispositionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    inventory_quantity_cohort_id: uuid.UUID
    event_kind: str
    reverses_event_id: uuid.UUID | None
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    reason: str | None


class QualityDispositionCorrectionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reversal: QualityDispositionEventRead
    replacement: QualityDispositionEventRead | None


class QualityPartialDispositionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_cohort_id: uuid.UUID
    source_cohort_id: uuid.UUID
    quantity: Decimal
    disposition: str
    custody_location_id: uuid.UUID | None = None


class QualityWorkQueueRowRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_quantity_cohort_id: uuid.UUID
    inventory_item_id: uuid.UUID
    item_name: str
    base_uom_id: uuid.UUID
    inventory_lot_id: uuid.UUID | None
    manufacturer_lot_reference: str | None
    expiry_date: date | None
    received_at_farm_id: uuid.UUID
    source_goods_receipt_line_id: uuid.UUID
    receipt_code: str
    receipt_received_at: datetime
    balance: Decimal
    current_state: str
    current_event_id: uuid.UUID | None
    last_actor_user_id: uuid.UUID | None
    last_effective_time: datetime | None


class InventoryItemUsableExistenceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_item_id: uuid.UUID
    usable_quantity: Decimal


class InventoryLotUsableExistenceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_lot_id: uuid.UUID
    usable_quantity: Decimal


__all__ = [
    "QualityDispositionCreate",
    "QualityDispositionCorrectionCreate",
    "QualityPartialDispositionCreate",
    "QualityPartialCorrectionCreate",
    "QualityDispositionEventRead",
    "QualityDispositionCorrectionRead",
    "QualityPartialDispositionRead",
    "QualityPartialCorrectionRead",
    "QualityWorkQueueRowRead",
    "InventoryItemUsableExistenceRead",
    "InventoryLotUsableExistenceRead",
]
