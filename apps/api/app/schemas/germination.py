"""NURSERY-OPS-002A / PILOT-UX-001B: Germination Placement -- physical
placement only, no biological outcome. Frozen authoritative model: a
Germination Trolley Asset occupies a Germination Chamber Location directly
(no chamber_position); a Seed Tray Carrier occupies a Trolley Level
AssetPosition directly (new-model `direct_level`) or one of that Level's
child Slot AssetPositions (legacy-compatible `legacy_level`) -- see
`germination_service._classify_level`. A `shelf`-kind Level with zero child
Slots AND `capacity IS NULL` is an `invalid_level`: a Farm Setup
configuration gap, never a valid one-tray target."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from app.schemas.sowing_event import CarrierSummary, SeedLotSummary

GerminationLevelMode = Literal["legacy", "direct", "invalid"]


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


class GerminationPositionSummary(BaseModel):
    """The exact AssetPosition a Seed Tray occupies -- either the Level
    itself (`mode="direct"`, `code == level_code`) or a legacy child Slot
    (`mode="legacy"`, `code` is the Slot's own code, `level_code` is its
    parent Level's code)."""

    id: uuid.UUID
    code: str
    name: str
    level_code: str
    mode: GerminationLevelMode


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
    asset_position_id: uuid.UUID
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
    position: GerminationPositionSummary
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


class LegacySlotAvailabilityRead(BaseModel):
    """One child Slot of a `legacy_level` -- unchanged shape/meaning from
    before PILOT-UX-001B, just nested under its Level now instead of
    returned as a flat list."""

    id: uuid.UUID
    code: str
    name: str
    occupied: bool


class TrolleyLevelAvailabilityRead(BaseModel):
    """PILOT-UX-001B: one Level of a Trolley, backend-classified -- the
    frontend must consume `mode`, never re-derive it from raw position
    structure. `capacity`/`available_capacity` are populated for
    `mode="direct"` only; `slots` is populated for `mode="legacy"` only;
    `mode="invalid"` carries neither (a Farm Setup configuration gap, never
    advertised as an available destination)."""

    id: uuid.UUID
    code: str
    name: str
    mode: GerminationLevelMode
    capacity: int | None
    occupied_count: int
    available_capacity: int | None
    slots: list[LegacySlotAvailabilityRead] = []


class AvailableTrolleyRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    chamber: GerminationChamberSummary
    total_capacity: int
    occupied_count: int
    available_capacity: int


GerminationPlacementState = Literal["awaiting_placement", "elsewhere", "in_germination"]


class GerminationResolvedPlacement(BaseModel):
    trolley: TrolleySummary
    chamber: GerminationChamberSummary
    position: GerminationPositionSummary


class GerminationTrayRead(BaseModel):
    batch_id: uuid.UUID
    batch_code: str
    seed_lot: SeedLotSummary
    tray: CarrierSummary
    batch_carrier_assignment_id: uuid.UUID
    seeds_sown: int
    state: GerminationPlacementState
    placement: GerminationResolvedPlacement | None
