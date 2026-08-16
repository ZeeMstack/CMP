"""NURSERY-OPS-002B: modern, INDIVIDUAL-SEEDLING-based Germination outcome.

Distinct from the legacy site/cell-based `GerminationCheck`
(`app/schemas/observation_event.py`) -- this module never reuses its field
names or denominator. Both `normal_seedling_count` and
`abnormal_seedling_count` are LIVING counts; their sum need not equal the
assignment's `seed_count` -- the gap is deliberately left uncategorized (no
NON_GERMINATION or other loss-category inference belongs here)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.sowing_event import CarrierSummary

PlacementState = Literal["awaiting_placement", "elsewhere", "in_germination", "unknown"]


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class GerminationOutcomeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_carrier_assignment_id: uuid.UUID
    normal_seedling_count: int = Field(ge=0)
    abnormal_seedling_count: int = Field(ge=0)
    assessment_complete: bool
    note: str | None = None

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class GerminationOutcomeCommandCreate(BaseModel):
    """Dedicated, narrow modern command payload -- never exposes the
    generic ObservationEvent `values`/legacy `germination_checks` shape."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    note: str | None = None
    outcomes: list[GerminationOutcomeIn] = Field(min_length=1)

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("effective_time must be timezone-aware")
        return v

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_no_duplicate_assignment(self) -> "GerminationOutcomeCommandCreate":
        seen = set()
        for o in self.outcomes:
            if o.batch_carrier_assignment_id in seen:
                raise ValueError("duplicate germination outcome assignment within one command")
            seen.add(o.batch_carrier_assignment_id)
        return self


class GerminationOutcomeSnapshotRead(BaseModel):
    id: uuid.UUID
    observation_event_id: uuid.UUID
    tray: CarrierSummary
    batch_carrier_assignment_id: uuid.UUID
    normal_seedling_count: int
    abnormal_seedling_count: int
    living_seedling_count: int
    assessment_complete: bool
    note: str | None
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID


class GerminationOutcomeCommandRead(BaseModel):
    observation_event_id: uuid.UUID
    client_command_id: uuid.UUID
    batch_id: uuid.UUID
    effective_time: datetime
    note: str | None
    snapshots: list[GerminationOutcomeSnapshotRead]


class GerminationOutcomeCurrentRead(BaseModel):
    batch_carrier_assignment_id: uuid.UUID
    tray: CarrierSummary
    batch_id: uuid.UUID
    batch_code: str
    seeds_sown: int
    sown_site_count: int | None
    current_placement: PlacementState
    latest_snapshot: GerminationOutcomeSnapshotRead | None
    latest_completed_snapshot: GerminationOutcomeSnapshotRead | None
    current_normal_seedling_count: int | None
    current_abnormal_seedling_count: int | None
    current_living_seedling_count: int | None
    current_seed_to_living_gap_count: int | None
    # Section 31: NEVER "germination_percentage" / "germination rate" -- that
    # legacy name means germinated-sites/inspected-sites (a different unit).
    # This is living seedlings / seeds sown, explicitly named to avoid
    # confusion with the site-based legacy metric; optional/minimal for MVP.
    living_seedling_yield_percent: Decimal | None
    assessment_complete: bool
    authoritative_living_seedling_count: int | None
    latest_effective_time: datetime | None
    historical_snapshot_count: int


class GerminationOutcomeBatchAggregateRead(BaseModel):
    batch_id: uuid.UUID
    batch_code: str
    trays: list[GerminationOutcomeCurrentRead]
    authoritative_living_seedling_total: int
    completed_tray_count: int
    unresolved_tray_count: int
    all_resolved: bool
