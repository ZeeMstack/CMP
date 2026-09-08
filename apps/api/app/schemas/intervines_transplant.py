"""VINES-OPS-001A -- the InterVines Transplant composite operator command:

    Seedling source (Seed Tray, seed_tray/SeedlingEntry authority)
    -> biological Transplant                     (transplant_service._record_transplant_core)
    -> a server-allocated pool of Grow Cube(s)    (grow_cube Carriers, one plant each)
    -> physical placement of those Grow Cube(s)   (movement_service._execute_movement_core)
    -> one InterVines Table

Deliberately its own schema module, not a mutation of `app.schemas.
transplant_event` or `app.schemas.intersalads_transplant` -- the operator
request shape here is materially different from InterSalads' own composite:
InterVines is plant-count/pool-based (the operator names a quantity and one
destination Table; the server deterministically allocates that many
currently-available Grow Cubes under lock) rather than destination-Carrier-
picker-based (the operator explicitly names each destination Carrier id).
A single `source_assignment_id` (not a list) matches the ticket's frozen
compact UX ("Source Batch / Tray", singular) -- multiple source Trays feeding
one InterVines command is out of scope; the operator issues one command per
source Tray, exactly as many times as needed until it is exhausted (ticket:
"Multiple commands from the same Seed Tray/Batch are allowed"). No loss/
damage/rejection/sample fields are exposed here at all -- the ticket is
explicit that this workflow "does NOT record a biological loss"; the
underlying generic Transplant reconciliation is still exercised with all
four loss categories hardcoded to 0 by the service layer, never surfaced to
the operator."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.carrier_specification import CarrierSpecificationSummary
from app.schemas.crop_batch import StageSummary
from app.schemas.sowing_event import CarrierSummary
from app.schemas.transplant_event import MAX_DESTINATION_LINES


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class IntervinesTransplantCreate(BaseModel):
    """`plant_count` is bounded by `MAX_DESTINATION_LINES` (matching
    `_record_transplant_core`'s own hard limit -- one destination line per
    Grow Cube) so an over-large request is rejected by Pydantic before ever
    touching the Grow Cube pool or the database."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    note: str | None = None
    source_assignment_id: uuid.UUID
    plant_count: int = Field(gt=0, le=MAX_DESTINATION_LINES)
    destination_location_id: uuid.UUID
    grow_cube_specification_id: uuid.UUID | None = None

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class IntervinesGrowCubePlacementRead(BaseModel):
    """One allocated Grow Cube: its own permanent Carrier identity, the
    BatchCarrierAssignment created for it, and the Movement that physically
    placed it on the requested InterVines Table -- every fact the ticket's
    required traceability chain (Batch -> Seedling source -> InterVines
    transplant -> Grow Cube -> InterVines Table) needs, re-derivable
    identically on an exact replay."""

    destination_batch_carrier_assignment_id: uuid.UUID
    carrier: CarrierSummary
    destination_location_id: uuid.UUID
    movement_id: uuid.UUID


class IntervinesTransplantRead(BaseModel):
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
    source_assignment_id: uuid.UUID
    source_carrier: CarrierSummary
    total_source_available_before: int
    total_remainder_after: int
    plant_count: int
    destination_location_id: uuid.UUID
    grow_cubes: list[IntervinesGrowCubePlacementRead]


class AvailableGrowCubePoolRead(BaseModel):
    """VINES-OPS-001A: one row per distinct `CarrierSpecification` (or one
    row with `specification=None` for un-specified Grow Cubes) currently
    eligible as InterVines Transplant destinations in this Farm -- active
    status, no currently-active `BatchCarrierAssignment`. The frontend shows
    the specification picker only when more than one row is returned (ticket:
    "Grow Cube specification [ select, if more than one valid option ]").
    A single aggregated count per group, never a per-Grow-Cube row list --
    the ticket is explicit that the pool must not be rendered as hundreds of
    individual rows."""

    specification_id: uuid.UUID | None
    specification: CarrierSpecificationSummary | None
    available_count: int


class IntervinesPlacementRead(BaseModel):
    """VINES-OPS-001A: one aggregated row per (Batch, InterVines Table) --
    the compact InterVines read view (ticket: "Batch | Crop | Variety |
    Table | Plants | Days in InterVines | Action"). Never one row per Grow
    Cube; drill-down into individual Grow Cube traceability is a separate,
    narrower endpoint."""

    batch_id: uuid.UUID
    batch_code: str
    crop_id: uuid.UUID
    crop_code: str
    crop_common_name: str
    variety_id: uuid.UUID | None
    variety_code: str | None
    variety_name: str | None
    table_id: uuid.UUID
    table_code: str
    table_name: str
    plant_count: int
    earliest_assigned_effective_time: datetime
    days_in_intervines: int


class IntervinesPlacementGrowCubeRead(BaseModel):
    """Drill-down detail for one (Batch, InterVines Table) row: every
    individual Grow Cube currently carrying a live plant there."""

    carrier: CarrierSummary
    batch_carrier_assignment_id: uuid.UUID
    assigned_effective_time: datetime


__all__ = [
    "IntervinesTransplantCreate",
    "IntervinesGrowCubePlacementRead",
    "IntervinesTransplantRead",
    "AvailableGrowCubePoolRead",
    "IntervinesPlacementRead",
    "IntervinesPlacementGrowCubeRead",
]
