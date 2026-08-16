"""NURSERY-OPS-003A: Seedling Entry & Placement -- physical Movement +
immutable biological handoff freeze, committed atomically. Distinct from
NURSERY-OPS-002B's `GerminationOutcomeSnapshot` schemas (never redefines
them) and from NURSERY-OPS-002A's Germination placement schemas (reused here
for the `in_germination` placement case only)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

from app.schemas.germination import GerminationResolvedPlacement
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


class SeedlingTableSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class SeedlingAreaSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class SeedlingGreenhouseSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str


# --- Command -------------------------------------------------------------------------


class SeedlingEntryCreate(BaseModel):
    """Section 26: the operator supplies only physical/handoff-command
    facts -- `starting_living_seedling_count` and
    `source_germination_outcome_snapshot_id` are never accepted from the
    caller; the server always resolves and freezes them authoritatively
    (section 10/11)."""

    client_command_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    destination_seedling_table_id: uuid.UUID
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


class SeedlingEntryRead(BaseModel):
    id: uuid.UUID
    client_command_id: uuid.UUID
    batch_id: uuid.UUID
    batch_code: str
    batch_carrier_assignment_id: uuid.UUID
    tray: CarrierSummary
    seedling_table: SeedlingTableSummary
    movement_id: uuid.UUID
    source_germination_outcome_snapshot_id: uuid.UUID
    source_normal_seedling_count: int
    source_abnormal_seedling_count: int
    source_effective_time: datetime
    starting_living_seedling_count: int
    effective_time: datetime
    recorded_at: datetime


# --- Reads ---------------------------------------------------------------------------


class AvailableSeedlingTableRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    capacity: int | None
    active_tray_count: int
    remaining_capacity: int
    seedling_area: SeedlingAreaSummary
    greenhouse: SeedlingGreenhouseSummary


PhysicalPlacementKind = Literal["unplaced", "in_germination", "on_seedling_table", "elsewhere"]


class ResolvedPhysicalPlacement(BaseModel):
    kind: PhysicalPlacementKind
    germination: GerminationResolvedPlacement | None
    seedling_table: SeedlingTableSummary | None


class GerminationHandoffSummary(BaseModel):
    normal_seedling_count: int
    abnormal_seedling_count: int
    living_seedling_count: int
    effective_time: datetime


class SeedlingEntrySummary(BaseModel):
    id: uuid.UUID
    movement_id: uuid.UUID
    source_germination_outcome_snapshot_id: uuid.UUID
    starting_living_seedling_count: int
    effective_time: datetime


SeedlingPlacementState = Literal[
    "no_completed_handoff", "ready_for_seedling", "in_seedling", "in_seedling_unanchored", "elsewhere"
]


class SeedlingCandidateTrayRead(BaseModel):
    batch_id: uuid.UUID
    batch_code: str
    seed_lot: SeedLotSummary
    tray: CarrierSummary
    batch_carrier_assignment_id: uuid.UUID
    seeds_sown: int
    germination_handoff: GerminationHandoffSummary | None
    seedling_entry: SeedlingEntrySummary | None
    current_placement: ResolvedPhysicalPlacement
    state: SeedlingPlacementState
