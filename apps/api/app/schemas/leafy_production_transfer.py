"""NURSERY-OPS-005B: composite Leafy Production Transfer command --

    Nursery Cultivation Plate source(s)
    -> biological Transplant                     (transplant_service._record_transplant_core)
    -> Production Cultivation Plate destination(s)
    -> physical placement of those Plate(s)       (movement_service._execute_movement_core)
    -> Leafy Production Table(s)

Deliberately its own schema module, mirroring `app.schemas.intersalads_
transplant`'s exact precedent -- the generic `/transplants` endpoint's
`TransplantDestinationLineIn` (no location field) remains independently
usable; this composite's destination-line shape additionally requires
`destination_location_id`, a materially different contract, not a superset
applied in place.

Also carries the two narrow operator-facing reads backing this workflow's
UI: `AvailableLeafyProductionSourceRead` (eligible Nursery Cultivation Plate
sources, authoritative population from `transplant_source_authority` only)
and `AvailableProductionCultivationPlateRead` (eligible Production
Cultivation Plate destinations) -- co-located here, not in `app.schemas.
carrier`, because their eligibility semantics are specific to this
composite command, exactly the same convention `intersalads_transplant.py`
already established for its own `AvailableNurseryCultivationPlateRead`."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.carrier_specification import CarrierSpecificationSummary
from app.schemas.crop_batch import CropSummary, StageSummary, VarietySummary
from app.schemas.sowing_event import CarrierSummary
from app.schemas.transplant_event import (
    MAX_ALLOCATIONS,
    MAX_DESTINATION_LINES,
    MAX_SOURCE_LINES,
    TransplantAllocationIn,
    TransplantAllocationRead,
    TransplantSourceLineIn,
    TransplantSourceLineRead,
)


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class LeafyProductionDestinationLineIn(BaseModel):
    """One destination Production Cultivation Plate: the biological
    quantity assigned to it (`assigned_plant_count`, reconciled by the
    existing Transplant core exactly as for the generic endpoint) plus the
    Leafy Production Table it must be physically placed on in the same
    atomic command (`destination_location_id` -- the Table itself, the only
    write-authoritative location identifier; Greenhouse/Zone/Span ids are
    frontend-only UX state for narrowing the picker, never sent here since
    backend semantics need only the final Table)."""

    model_config = ConfigDict(extra="forbid")

    destination_carrier_id: uuid.UUID
    assigned_plant_count: int = Field(gt=0)
    destination_location_id: uuid.UUID
    note: str | None = None

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class LeafyProductionTransferCreate(BaseModel):
    """Mirrors `IntersaladsTransplantCreate`'s own structure and validation
    intent exactly, substituting `LeafyProductionDestinationLineIn` for
    `IntersaladsDestinationLineIn` -- same duplicate-id/undeclared-reference/
    every-destination-allocated invariants, proven correct by that
    precedent, not reinvented here."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    note: str | None = None
    source_lines: list[TransplantSourceLineIn] = Field(min_length=1, max_length=MAX_SOURCE_LINES)
    destination_lines: list[LeafyProductionDestinationLineIn] = Field(
        min_length=1, max_length=MAX_DESTINATION_LINES
    )
    allocations: list[TransplantAllocationIn] = Field(min_length=1, max_length=MAX_ALLOCATIONS)

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_payload(self) -> "LeafyProductionTransferCreate":
        source_ids = [line.source_assignment_id for line in self.source_lines]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate source_assignment_id within one transfer command")

        dest_ids = [line.destination_carrier_id for line in self.destination_lines]
        if len(dest_ids) != len(set(dest_ids)):
            raise ValueError("duplicate destination_carrier_id within one transfer command")

        source_id_set = set(source_ids)
        dest_id_set = set(dest_ids)

        alloc_pairs = [(a.source_assignment_id, a.destination_carrier_id) for a in self.allocations]
        if len(alloc_pairs) != len(set(alloc_pairs)):
            raise ValueError("duplicate source_assignment_id/destination_carrier_id allocation pair")

        for allocation in self.allocations:
            if allocation.source_assignment_id not in source_id_set:
                raise ValueError("allocation references an undeclared source_assignment_id")
            if allocation.destination_carrier_id not in dest_id_set:
                raise ValueError("allocation references an undeclared destination_carrier_id")

        allocated_dest_ids = {a.destination_carrier_id for a in self.allocations}
        unused_destinations = dest_id_set - allocated_dest_ids
        if unused_destinations:
            raise ValueError("every destination line must receive at least one allocation")
        return self


class LeafyProductionDestinationLineRead(BaseModel):
    """Every field here is re-derivable from already-committed
    TransplantDestinationLine + Movement rows, never in-memory-only state --
    the composite's response stays identical on exact replay, mirroring
    `IntersaladsDestinationLineRead`'s own proven shape."""

    destination_batch_carrier_assignment_id: uuid.UUID
    carrier: CarrierSummary
    assigned_plant_count: int
    allocated_plant_count: int
    destination_location_id: uuid.UUID
    movement_id: uuid.UUID
    note: str | None


class LeafyProductionTransferRead(BaseModel):
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
    source_lines: list[TransplantSourceLineRead]
    destination_lines: list[LeafyProductionDestinationLineRead]
    allocations: list[TransplantAllocationRead]
    total_source_available_before: int
    total_destination_plant_count: int
    total_discarded_plant_count: int
    total_remainder_after: int


class LeafyProductionCurrentLocationSummary(BaseModel):
    """The source Plate's current physical Occupancy target, if any --
    operator context only, never a biological-eligibility fact (NURSERY-
    OPS-005B section 3: physical InterSalads location is informational,
    the authoritative source_assignment_id/authoritative_available_count
    above are what make a Plate a valid source)."""

    id: uuid.UUID
    code: str
    name: str
    location_type_code: str


class AvailableLeafyProductionSourceRead(BaseModel):
    """NURSERY-OPS-005B: one row per `nursery_cultivation_plate`-typed
    BatchCarrierAssignment currently eligible as a Leafy Production
    Transfer source -- active (unreleased) assignment, positive
    authoritative available population resolved through `transplant_
    source_authority.get_source_available` only (never a client-side or
    hand-summed reconstruction of historical events). Restoration lineage
    is handled for free: an assignment query scoped to `released_effective_
    time IS NULL` structurally can never return a historical, superseded
    generation -- only whichever generation (original or restored) is
    currently active is ever a candidate row."""

    source_assignment_id: uuid.UUID
    carrier: CarrierSummary
    batch_id: uuid.UUID
    batch_code: str
    crop: CropSummary
    variety: VarietySummary | None
    authoritative_available_count: int
    current_location: LeafyProductionCurrentLocationSummary | None


class AvailableProductionCultivationPlateRead(BaseModel):
    """NURSERY-OPS-005B: one row per `production_cultivation_plate` Carrier
    currently eligible as a NEW Leafy Production Transfer destination --
    active status, no currently-active `BatchCarrierAssignment` -- the same
    eligibility `_record_transplant_core` itself enforces via
    `DestinationCarrierAlreadyAssignedError`, read-only here. Deliberately
    does NOT require "no active Occupancy": Movement legitimately relocates
    a Carrier and closes its prior Occupancy as part of the same atomic
    move, so a Production Plate already sitting somewhere physically
    remains eligible. Mirrors `AvailableNurseryCultivationPlateRead`'s
    exact shape, reusing `CarrierSpecificationSummary`."""

    id: uuid.UUID
    code: str
    status: str
    specification_id: uuid.UUID | None
    specification: CarrierSpecificationSummary | None


__all__ = [
    "LeafyProductionDestinationLineIn",
    "LeafyProductionTransferCreate",
    "LeafyProductionDestinationLineRead",
    "LeafyProductionTransferRead",
    "LeafyProductionCurrentLocationSummary",
    "AvailableLeafyProductionSourceRead",
    "AvailableProductionCultivationPlateRead",
]
