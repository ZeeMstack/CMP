"""Water exposure read contracts.

Every interval here is HALF-OPEN, `[start, end)`: start inclusive, end
exclusive; touching intervals do not overlap and no zero-duration interval
is ever returned (`interval_convention` = `HALF_OPEN_START_INCLUSIVE_END_
EXCLUSIVE`). `exposure_kind` is exactly `CONFIGURED_TOPOLOGY_EXPOSURE` or
`RECORDED_DELIVERY_EXPOSURE` -- potential exposure evidence, never a
disease/contamination claim. A source with no persisted end is clipped to
`window_end` and named in `open_ended_sources`; no end is ever invented.
See `app/services/water_exposure_service.py` and
docs/domain/WATER_NUTRIENT_SYSTEM_MODEL.md."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

# --- UX-OPS-001D0 exact interval timeline -------------------------------------------------


class WaterExposureIntervalRead(BaseModel):
    """One exact exposure interval on one Reservoir -> Circuit -> Delivery
    Point route for one Batch/Carrier/Location placement. For
    `RECORDED_DELIVERY_EXPOSURE`, `water_delivery_event_id` names the
    delivery; for `CONFIGURED_TOPOLOGY_EXPOSURE` it is null."""

    exposure_kind: str
    interval_start: datetime
    interval_end: datetime
    batch_id: uuid.UUID
    carrier_id: uuid.UUID
    location_id: uuid.UUID
    reservoir_id: uuid.UUID
    irrigation_circuit_id: uuid.UUID
    water_delivery_point_id: uuid.UUID
    delivery_point_location_id: uuid.UUID
    water_delivery_event_id: uuid.UUID | None
    batch_carrier_assignment_id: uuid.UUID
    occupancy_id: uuid.UUID
    reservoir_circuit_link_id: uuid.UUID
    circuit_delivery_point_link_id: uuid.UUID
    start_clipped_to_window: bool
    end_clipped_to_window: bool
    # Contributing sources with no persisted end (e.g. "WATER_DELIVERY_EVENT",
    # "OCCUPANCY") -- non-empty only when the interval was clipped at
    # window_end because of them.
    open_ended_sources: list[str]


class WaterExposureGapRead(BaseModel):
    """Time within a valid Batch assignment + Occupancy (inside the window)
    that no complete Reservoir -> Circuit -> Delivery Point route covers.
    Not an exposure kind."""

    reason: str  # "NO_COMPLETE_TOPOLOGY_ROUTE"
    gap_start: datetime
    gap_end: datetime
    batch_id: uuid.UUID
    carrier_id: uuid.UUID
    location_id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    occupancy_id: uuid.UUID
    start_clipped_to_window: bool
    end_clipped_to_window: bool
    open_ended_sources: list[str]


class BatchWaterExposureTimelineRead(BaseModel):
    batch_id: uuid.UUID
    farm_id: uuid.UUID
    window_start: datetime
    window_end: datetime
    interval_convention: str
    intervals: list[WaterExposureIntervalRead]
    gaps: list[WaterExposureGapRead]


class WaterExposureTimelineRead(BaseModel):
    anchor_type: str  # "IRRIGATION_CIRCUIT" | "RESERVOIR"
    anchor_id: uuid.UUID
    farm_id: uuid.UUID
    window_start: datetime
    window_end: datetime
    interval_convention: str
    intervals: list[WaterExposureIntervalRead]


# --- PILOT-WATER-001A/B list shapes (now one row per exact interval) ------------------------


class ExposedPlacementRead(BaseModel):
    batch_id: uuid.UUID
    carrier_id: uuid.UUID
    location_id: uuid.UUID
    irrigation_circuit_id: uuid.UUID
    exposure_kind: str
    overlap_start: datetime
    overlap_end: datetime
    # UX-OPS-001D0 additive fields.
    reservoir_id: uuid.UUID | None = None
    water_delivery_point_id: uuid.UUID | None = None
    water_delivery_event_id: uuid.UUID | None = None
    end_clipped_to_window: bool = False
    open_ended_sources: list[str] = []


class BatchWaterExposureRead(BaseModel):
    irrigation_circuit_id: uuid.UUID
    # Single-element since UX-OPS-001D0: one row per exact interval, never an
    # aggregate across non-overlapping reservoirs/Locations.
    reservoir_ids: list[uuid.UUID]
    location_ids: list[uuid.UUID]
    exposure_kind: str
    # UX-OPS-001D0 additive fields.
    carrier_id: uuid.UUID | None = None
    water_delivery_point_id: uuid.UUID | None = None
    water_delivery_event_id: uuid.UUID | None = None
    interval_start: datetime | None = None
    interval_end: datetime | None = None
    end_clipped_to_window: bool = False
    open_ended_sources: list[str] = []
