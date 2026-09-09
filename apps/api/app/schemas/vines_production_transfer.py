"""VINES-OPS-001B -- the Nursery(InterVines) -> Vines Production Transfer
composite operator command:

    InterVines biological placement (Grow Cube, one living plant each)
    -> biological Transplant                       (transplant_service._record_transplant_core)
    -> a server-allocated pool of Grow Bag(s)       (grow_bag Carriers, configurable plant capacity)
    -> physical placement of those Grow Bag(s)      (movement_service._execute_movement_core)
    -> free Grow Bag Position(s) under one Grow Gutter

Deliberately its own schema module, mirroring `app.schemas.intervines_
transplant`'s own pool-based (not destination-picker-based) shape, extended
on BOTH sides: the SOURCE is now also server-allocated (N currently-living
InterVines Grow Cubes drawn from one named (Batch, InterVines Table) group,
never operator-picked one at a time), and the DESTINATION Grow Bag's own
plant capacity is READ from its CarrierSpecification (never assumed to be
1) -- `plant_count` Grow Cubes are deterministically packed into the fewest
Grow Bags their capacity allows, each Grow Bag then physically placed at one
free Grow Bag Position under the selected Grow Gutter.

No loss/damage/rejection/sample fields are exposed here at all, exactly like
`IntervinesTransplantCreate` -- the ticket is explicit that "No biological
loss is implied" by this transfer."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.carrier_specification import CarrierSpecificationSummary
from app.schemas.crop_batch import StageSummary
from app.schemas.sowing_event import CarrierSummary
from app.schemas.transplant_event import MAX_SOURCE_LINES


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class VinesProductionTransferCreate(BaseModel):
    """`plant_count` is bounded by `MAX_SOURCE_LINES` (matching `_record_
    transplant_core`'s own hard limit -- one source line per Grow Cube)
    so an over-large request is rejected by Pydantic before ever touching
    either pool or the database. `grow_bag_specification_id` is REQUIRED
    (unlike `IntervinesTransplantCreate`'s optional Grow Cube specification)
    -- a Grow Bag's plant capacity must always be an explicit, configured
    fact for this command; there is no "no filter, use any capacity"
    equivalent here."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    note: str | None = None
    source_intervines_table_id: uuid.UUID
    plant_count: int = Field(gt=0, le=MAX_SOURCE_LINES)
    destination_grow_gutter_id: uuid.UUID
    grow_bag_specification_id: uuid.UUID

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class VinesProductionGrowBagPlacementRead(BaseModel):
    destination_batch_carrier_assignment_id: uuid.UUID
    grow_bag: CarrierSummary
    assigned_plant_count: int
    grow_bag_position_id: uuid.UUID
    movement_id: uuid.UUID


class VinesProductionTransferRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    batch_id: uuid.UUID
    batch_code: str
    workflow_version_id: uuid.UUID
    stage: StageSummary
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    client_command_id: uuid.UUID
    note: str | None
    source_intervines_table_id: uuid.UUID
    plant_count: int
    destination_grow_gutter_id: uuid.UUID
    grow_bag_specification_id: uuid.UUID
    source_grow_cubes: list[CarrierSummary]
    grow_bags: list[VinesProductionGrowBagPlacementRead]


class AvailableGrowBagPoolRead(BaseModel):
    """VINES-OPS-001B: one row per Grow Bag CarrierSpecification currently
    eligible as a Vines Production Transfer destination in this Farm --
    active status, no currently-active `BatchCarrierAssignment`. When
    `destination_grow_gutter_id` is supplied to the listing call,
    `available_position_count`/`available_plant_capacity` are additionally
    bounded by that Gutter's own currently-free Grow Bag Positions (the true
    ceiling on how many Bags can actually be PLACED there); otherwise
    `available_position_count` is `None` and `available_plant_capacity`
    reflects the Bag pool alone."""

    specification_id: uuid.UUID
    specification: CarrierSpecificationSummary
    available_bag_count: int
    available_position_count: int | None
    available_plant_capacity: int


class VinesProductionPlacementRead(BaseModel):
    """VINES-OPS-001B: the compact Vines Production read view -- one
    aggregated row per (Batch, Grow Gutter), never one row per plant/Grow
    Bag (ticket: "Batch | Crop | Variety | Greenhouse | Gutter | Living
    Plants | Lost | Days in Production"). VINES-OPS-002: `plant_count`
    keeps its original opening/assigned meaning (backward compatible for the
    001B Transfer page); `living_plant_count`/`lost_plant_count` are the new
    authoritative-population fields (via `production_disposition_service.
    get_current_living_population`, carrier-agnostic, unchanged formula) the
    Vines Production workspace itself renders."""

    batch_id: uuid.UUID
    batch_code: str
    crop_id: uuid.UUID
    crop_code: str
    crop_common_name: str
    variety_id: uuid.UUID | None
    variety_code: str | None
    variety_name: str | None
    greenhouse_id: uuid.UUID
    greenhouse_code: str
    greenhouse_name: str
    gutter_id: uuid.UUID
    gutter_code: str
    plant_count: int
    living_plant_count: int
    lost_plant_count: int
    earliest_assigned_effective_time: datetime
    days_in_production: int


class VinesGrowCubeDispositionSummary(BaseModel):
    """VINES-OPS-002: the disposing fact for one removed Grow Cube -- present
    only when `status == "removed"`."""

    reason_code: str
    effective_time: datetime
    note: str | None


class VinesProductionPlacementGrowCubeRead(BaseModel):
    """One plant placement inside a drilled-down Grow Bag: its own Grow Cube
    identity plus, when resolvable, the originating Seed Tray -- the
    ticket's required backward lineage (Grow Bag -> Grow Cube -> Seed Tray)
    in one compact row. VINES-OPS-002: `status`/`disposition` distinguish a
    currently-living plant from one already removed -- a disposed Grow Cube
    is never dropped from this list (immutable history), only marked."""

    grow_cube: CarrierSummary
    source_seed_tray: CarrierSummary | None
    status: str = "living"
    disposition: VinesGrowCubeDispositionSummary | None = None


class VinesProductionPlacementGrowBagRead(BaseModel):
    """Drill-down detail for one aggregated Vines Production placement row:
    every individual Grow Bag currently carrying living plants there, and
    every Grow Cube (with its own Seed Tray lineage and living/removed
    status) inside each Bag. VINES-OPS-002: `living_plant_count`/`capacity`/
    `free_capacity` expose the "Grow Bag capacity after loss" facts the
    ticket requires -- `assigned_plant_count`/capacity themselves never
    change; only living/free do."""

    grow_bag: CarrierSummary
    grow_bag_position_code: str
    batch_carrier_assignment_id: uuid.UUID
    assigned_plant_count: int
    living_plant_count: int
    capacity: int | None
    free_capacity: int | None
    assigned_effective_time: datetime
    grow_cubes: list[VinesProductionPlacementGrowCubeRead]


__all__ = [
    "VinesProductionTransferCreate",
    "VinesProductionGrowBagPlacementRead",
    "VinesProductionTransferRead",
    "AvailableGrowBagPoolRead",
    "VinesProductionPlacementRead",
    "VinesGrowCubeDispositionSummary",
    "VinesProductionPlacementGrowCubeRead",
    "VinesProductionPlacementGrowBagRead",
]
