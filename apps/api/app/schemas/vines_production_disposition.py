"""VINES-OPS-002: Vines Production plant-loss (Biological Disposition)
schemas -- deliberately a separate module from `app.schemas.production_
disposition` (LEAFY-OPS-001's own, which stays byte-for-byte untouched),
mirroring its shape but adding the one genuinely new field every Vines
command/read needs: specific Grow Cube identity (`grow_cube_carrier_ids`/
`grow_cubes`), since "one Grow Cube = one plant" makes a bare count
insufficient here. Correction stays void-only for now (see `production_
disposition_service.correct_grow_cube_disposition`'s own docstring)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.sowing_event import CarrierSummary

VinesDispositionEventKind = Literal["REDUCTION", "REVERSAL"]


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class RecordVinesGrowCubeDispositionCreate(BaseModel):
    """The operator supplies the specific Grow Cube(s) actually lost --
    never a bare count. The service translates this into `quantity_delta =
    -len(grow_cube_carrier_ids)`."""

    client_command_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    grow_cube_carrier_ids: list[uuid.UUID] = Field(min_length=1)
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


class CorrectVinesGrowCubeDispositionCreate(BaseModel):
    """Void (pure reversal) only -- see `correct_grow_cube_disposition`'s own
    docstring for why replacement is intentionally not exposed yet."""

    client_command_id: uuid.UUID


class VinesGrowCubeDispositionEventRead(BaseModel):
    id: uuid.UUID
    command_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    population_root_batch_carrier_assignment_id: uuid.UUID
    event_kind: VinesDispositionEventKind
    reason_code: str
    quantity_delta: int
    plant_loss_quantity: int
    effective_time: datetime
    recorded_at: datetime
    note: str | None
    reverses_event_id: uuid.UUID | None
    is_reversed: bool
    actor_user_id: uuid.UUID | None
    grow_cubes: list[CarrierSummary]


class VinesGrowCubeDispositionRecordResult(BaseModel):
    command_id: uuid.UUID
    client_command_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    population_root_batch_carrier_assignment_id: uuid.UUID
    event: VinesGrowCubeDispositionEventRead
    previous_living_population: int
    resulting_living_population: int
    assignment_released: bool


class VinesGrowCubeDispositionCorrectResult(BaseModel):
    command_id: uuid.UUID
    client_command_id: uuid.UUID
    population_root_batch_carrier_assignment_id: uuid.UUID
    target_event: VinesGrowCubeDispositionEventRead
    reversal_event: VinesGrowCubeDispositionEventRead
    previous_living_population: int
    resulting_living_population: int


class VinesProductionDispositionHistoryRead(BaseModel):
    """Full, un-collapsed event history for one Grow Bag population lineage
    -- never hides original erroneous facts. Remains accessible after the
    lineage's active BCA is released (mirrors `ProductionDispositionHistoryRead`'s
    own established rule)."""

    population_root_batch_carrier_assignment_id: uuid.UUID
    grow_bag_code: str
    batch_id: uuid.UUID
    batch_code: str
    gutter_code: str | None
    opening_population: int
    current_living_population: int
    is_active: bool
    events: list[VinesGrowCubeDispositionEventRead]


__all__ = [
    "RecordVinesGrowCubeDispositionCreate",
    "CorrectVinesGrowCubeDispositionCreate",
    "VinesGrowCubeDispositionEventRead",
    "VinesGrowCubeDispositionRecordResult",
    "VinesGrowCubeDispositionCorrectResult",
    "VinesProductionDispositionHistoryRead",
]
