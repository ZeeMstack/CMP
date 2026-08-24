"""LEAFY-OPS-001: Production Biological Disposition -- immutable,
insert-only living-population-reducing facts recorded against a Production
Cultivation Plate's BatchCarrierAssignment, after a Nursery -> Leafy
Production transplant (NURSERY-OPS-005B) and before Harvest (out of scope).
Mirrors `app/schemas/seedling_disposition.py`'s shape, with two identity
fields per event instead of one -- see `ProductionDispositionEvent`'s own
model docstring for why."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

DispositionEventKind = Literal["REDUCTION", "REVERSAL"]


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class ProductionDispositionReasonRead(BaseModel):
    code: str
    name: str


# --- Commands ----------------------------------------------------------------------


class RecordProductionDispositionCreate(BaseModel):
    """The operator supplies only physical/biological command facts -- a
    positive `plant_loss_count`, never a signed delta. The service
    translates this into `quantity_delta = -plant_loss_count`."""

    client_command_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    plant_loss_count: int = Field(gt=0)
    reason_code: str
    effective_time: datetime
    note: str | None = None

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class CorrectedProductionDispositionIn(BaseModel):
    plant_loss_count: int = Field(gt=0)
    reason_code: str
    effective_time: datetime
    note: str | None = None

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class CorrectProductionDispositionCreate(BaseModel):
    """`corrected=None` means VOID (reversal only, no replacement); a
    populated `corrected` means replace the original with a corrected
    biological fact. One atomic command either way."""

    client_command_id: uuid.UUID
    corrected: CorrectedProductionDispositionIn | None = None


# --- Reads -------------------------------------------------------------------------


class ProductionDispositionEventRead(BaseModel):
    id: uuid.UUID
    command_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    population_root_batch_carrier_assignment_id: uuid.UUID
    event_kind: DispositionEventKind
    reason_code: str
    quantity_delta: int
    plant_loss_quantity: int
    effective_time: datetime
    recorded_at: datetime
    note: str | None
    reverses_event_id: uuid.UUID | None
    corrects_event_id: uuid.UUID | None
    is_reversed: bool
    actor_user_id: uuid.UUID | None


class ProductionDispositionRecordResult(BaseModel):
    command_id: uuid.UUID
    client_command_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    population_root_batch_carrier_assignment_id: uuid.UUID
    event: ProductionDispositionEventRead
    previous_living_population: int
    resulting_living_population: int
    assignment_released: bool


class ProductionDispositionCorrectResult(BaseModel):
    command_id: uuid.UUID
    client_command_id: uuid.UUID
    population_root_batch_carrier_assignment_id: uuid.UUID
    target_event: ProductionDispositionEventRead
    reversal_event: ProductionDispositionEventRead
    replacement_event: ProductionDispositionEventRead | None
    restored_batch_carrier_assignment_id: uuid.UUID | None
    previous_living_population: int
    resulting_living_population: int


# --- Leafy Production workspace reads -----------------------------------------------


class LeafyProductionLocationRead(BaseModel):
    """Operator context only, never biological authority -- mirrors
    NURSERY-OPS-005B's own `LeafyProductionCurrentLocationSummary`."""

    id: uuid.UUID
    code: str
    name: str
    location_type_code: str
    ancestry_label: str


class ActiveProductionPlateRead(BaseModel):
    """The narrow, Leafy-Production-specific active-placements read -- one
    row per currently-active (unreleased) Production Cultivation Plate
    BatchCarrierAssignment."""

    carrier_id: uuid.UUID
    plate_code: str
    batch_carrier_assignment_id: uuid.UUID
    population_root_batch_carrier_assignment_id: uuid.UUID
    batch_id: uuid.UUID
    batch_code: str
    crop_common_name: str
    variety_name: str | None
    opening_population: int
    current_living_population: int
    total_recorded_loss: int
    current_location: LeafyProductionLocationRead | None
    has_location_warning: bool


class ProductionDispositionHistoryRead(BaseModel):
    """Full, un-collapsed event history for one population lineage -- never
    hides original erroneous facts; corrections are visible as their own
    rows with explicit linkage. Remains accessible after the lineage's
    active BCA is released (section 30 of the ticket: a zero-exhausted
    Plate must stay discoverable here even though it disappears from
    Active Production Plates)."""

    population_root_batch_carrier_assignment_id: uuid.UUID
    plate_code: str
    batch_id: uuid.UUID
    batch_code: str
    opening_population: int
    current_living_population: int
    is_active: bool
    events: list[ProductionDispositionEventRead]
