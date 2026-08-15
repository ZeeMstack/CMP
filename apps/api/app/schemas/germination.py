"""NURSERY-OPS-002A: Germination Placement -- physical placement only, no
biological outcome. Frozen authoritative model: a Germination Trolley Asset
occupies a Germination Chamber Location directly (no chamber_position); a
Seed Tray Carrier occupies a Trolley Slot AssetPosition."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from app.schemas.sowing_event import CarrierSummary, SeedLotSummary


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class GerminationChamberSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class TrolleySummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class SlotSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    shelf_code: str


# --- Commands ----------------------------------------------------------------------


class PlaceTrolleyCreate(BaseModel):
    client_command_id: uuid.UUID
    trolley_id: uuid.UUID
    chamber_id: uuid.UUID
    effective_time: datetime
    reason: str | None = None

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class PlaceTrayCreate(BaseModel):
    client_command_id: uuid.UUID
    tray_id: uuid.UUID
    trolley_id: uuid.UUID
    slot_id: uuid.UUID
    effective_time: datetime
    reason: str | None = None

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class TrolleyPlacementRead(BaseModel):
    movement_id: uuid.UUID
    client_command_id: uuid.UUID
    trolley: TrolleySummary
    chamber: GerminationChamberSummary
    effective_time: datetime


class TrayPlacementRead(BaseModel):
    movement_id: uuid.UUID
    client_command_id: uuid.UUID
    tray: CarrierSummary
    batch_code: str
    seeds_sown: int
    trolley: TrolleySummary
    slot: SlotSummary
    chamber: GerminationChamberSummary
    effective_time: datetime


# --- Reads ---------------------------------------------------------------------------


class GerminationChamberAvailabilityRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    trolley_capacity: int | None
    active_trolley_count: int
    remaining_capacity: int


class TrolleySlotAvailabilityRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    shelf_code: str
    occupied: bool


class AvailableTrolleyRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    chamber: GerminationChamberSummary
    total_slot_count: int
    occupied_slot_count: int
    available_slot_count: int


GerminationPlacementState = Literal["awaiting_placement", "elsewhere", "in_germination"]


class GerminationResolvedPlacement(BaseModel):
    trolley: TrolleySummary
    chamber: GerminationChamberSummary
    slot: SlotSummary


class GerminationTrayRead(BaseModel):
    batch_id: uuid.UUID
    batch_code: str
    seed_lot: SeedLotSummary
    tray: CarrierSummary
    batch_carrier_assignment_id: uuid.UUID
    seeds_sown: int
    state: GerminationPlacementState
    placement: GerminationResolvedPlacement | None
