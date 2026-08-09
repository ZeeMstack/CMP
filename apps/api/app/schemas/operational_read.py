"""CMP-FE-002A: read-only operational models over existing facts (crop
batches, sowing/derivation lineage, carrier occupancy). No new persisted
state -- every field here is derived at read time from tables that already
exist."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.crop_batch import CropSummary, StageSummary, VarietySummary


class LocationPathSegment(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class SowingOrigin(BaseModel):
    """One provable seed/sowing origin reachable from a batch's own
    derivation ancestry. A batch may have more than one (a future merge of
    batches sown on different dates) -- never collapsed to a guess."""

    source_batch_id: uuid.UUID
    source_batch_code: str
    sowing_event_id: uuid.UUID
    effective_time: datetime
    seed_lot_id: uuid.UUID
    seed_lot_code: str


class BatchPlacement(BaseModel):
    carrier_id: uuid.UUID
    carrier_code: str
    location_id: uuid.UUID
    location_code: str
    location_name: str
    path: list[LocationPathSegment]


class PlacementFacts(BaseModel):
    """Structured current-placement truth for one batch. `active_*_count`
    always partitions exactly (`active = placed + unplaced`) -- proven by
    the database's own partial-unique constraint that a carrier has at
    most one active occupancy at a time (`ux_occupancies_active_occupant_carrier`)."""

    active_carrier_count: int
    placed_carrier_count: int
    unplaced_carrier_count: int
    placements: list[BatchPlacement]
    common_ancestor_path: list[LocationPathSegment] | None


class BatchOperationalContext(BaseModel):
    """One batch's full operational read model -- shared shape returned by
    both the farm-wide summary list and the single-batch context route.
    Never includes a UI string; every field is a fact, ID, code, name,
    count, or timestamp."""

    id: uuid.UUID
    code: str
    crop: CropSummary
    variety: VarietySummary | None
    state: str
    current_stage: StageSummary
    sowing_origins: list[SowingOrigin]
    sown_effective_time: datetime | None
    placement: PlacementFacts
    open_quality_hold_count: int


class OccupantBatchContext(BaseModel):
    batch_id: uuid.UUID
    batch_code: str
    crop: CropSummary
    current_stage: StageSummary


class LocationOccupant(BaseModel):
    kind: str
    id: uuid.UUID
    carrier_code: str | None
    batch: OccupantBatchContext | None


class OccupiedLocation(BaseModel):
    location_id: uuid.UUID
    occupant: LocationOccupant


class LocationAggregateCount(BaseModel):
    location_id: uuid.UUID
    occupiable_location_count: int
    occupied_location_count: int


class SubtreeOccupancyRead(BaseModel):
    root_location_id: uuid.UUID
    aggregate_counts: list[LocationAggregateCount]
    occupied_locations: list[OccupiedLocation]
