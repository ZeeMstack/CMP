"""NURSERY-OPS-003B: Seedling Biological Dispositions -- immutable,
insert-only quantity-reducing facts recorded AFTER `SeedlingEntry` (see
`docs/domain/OBSERVATION_QUALITY_MODEL.md`'s NURSERY-OPS-003B addendum).
Deliberately not built on `ObservationEvent`/`GerminationOutcomeSnapshot`
schemas -- a disposition is a different domain fact (quantity-reducing,
ledger-like) from a descriptive observation."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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


class SeedlingDispositionReasonRead(BaseModel):
    code: str
    name: str


# --- Commands --------------------------------------------------------------------


class RecordSeedlingDispositionCreate(BaseModel):
    """Section 17: the operator supplies only physical/biological command
    facts -- a positive `quantity`, never a signed delta, never a current
    or starting balance."""

    client_command_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    quantity: int = Field(gt=0)
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


class CorrectedDispositionIn(BaseModel):
    quantity: int = Field(gt=0)
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


class CorrectSeedlingDispositionCreate(BaseModel):
    """Section 18/0.B: `corrected=None` means VOID (reversal only, no
    replacement); a populated `corrected` means replace the original with a
    corrected biological fact. One atomic command either way (section 0.A)."""

    client_command_id: uuid.UUID
    corrected: CorrectedDispositionIn | None = None


# --- Reads -------------------------------------------------------------------------


class SeedlingDispositionEventRead(BaseModel):
    id: uuid.UUID
    command_id: uuid.UUID
    seedling_entry_id: uuid.UUID
    event_kind: DispositionEventKind
    reason_code: str
    quantity_delta: int
    effective_time: datetime
    note: str | None
    reverses_event_id: uuid.UUID | None
    corrects_event_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    recorded_at: datetime


class SeedlingDispositionRecordResult(BaseModel):
    command_id: uuid.UUID
    client_command_id: uuid.UUID
    seedling_entry_id: uuid.UUID
    event: SeedlingDispositionEventRead
    previous_living_seedling_count: int
    quantity_delta: int
    resulting_living_seedling_count: int


class SeedlingDispositionCorrectResult(BaseModel):
    command_id: uuid.UUID
    client_command_id: uuid.UUID
    seedling_entry_id: uuid.UUID
    target_event: SeedlingDispositionEventRead
    reversal_event: SeedlingDispositionEventRead
    replacement_event: SeedlingDispositionEventRead | None
    previous_living_seedling_count: int
    resulting_living_seedling_count: int


class SeedlingBiologicalTrayRead(BaseModel):
    """Section 54/57: the dedicated Seedling-page read -- per Tray that has
    a `SeedlingEntry`, the frozen start, the derived current balance, and
    enough context to drive both the record and correction UI without a
    second round-trip.

    NURSERY-OPS-004A section 27/28: `current_living_seedling_count` keeps
    its UNCHANGED 003B meaning -- all living plants ever accounted for by
    this Tray's disposition history, checkpoint-unaware. It does NOT mean
    "still available to transplant" once any checkpoint exists.
    `current_source_available_count` is the new, checkpoint/transplant-
    aware figure operators must use to decide how many plants remain
    transplantable right now."""

    batch_id: uuid.UUID
    batch_code: str
    tray_id: uuid.UUID
    tray_code: str
    crop_common_name: str
    variety_name: str
    seed_lot_code: str
    batch_carrier_assignment_id: uuid.UUID
    seedling_entry_id: uuid.UUID
    starting_living_seedling_count: int
    total_reduction_magnitude: int
    total_reversal_magnitude: int
    current_living_seedling_count: int
    current_source_available_count: int
    checkpoint_count: int
    latest_checkpoint_id: uuid.UUID | None
    latest_checkpoint_effective_time: datetime | None
    latest_checkpoint_remainder_after: int | None
    is_depleted: bool
    event_count: int
    seedling_table_id: uuid.UUID | None
    seedling_table_code: str | None
    assignment_active: bool
    assignment_released_effective_time: datetime | None


class SeedlingDispositionHistoryRead(BaseModel):
    """Full, un-collapsed event history for one Tray -- section 55: never
    hides original erroneous facts; corrections are visible as their own
    rows with explicit linkage."""

    seedling_entry_id: uuid.UUID
    starting_living_seedling_count: int
    current_living_seedling_count: int
    events: list[SeedlingDispositionEventRead]
