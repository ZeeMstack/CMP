"""NURSERY-OPS-004B.1: composite InterSalads Transplant + physical Plate
placement command. Deliberately its own schema module, not a mutation of
`app.schemas.transplant_event` -- the generic `/transplants` endpoint and
its `TransplantDestinationLineIn` (no location field) must remain
independently usable and backward compatible; this composite command has a
materially different destination-line shape (it additionally requires
`destination_location_id`) and is a genuinely different API contract, not a
superset applied in place.

NURSERY-OPS-004B.2: also carries `AvailableNurseryCultivationPlateRead`, the
narrow operator-facing read backing the InterSalads Transplant UI's
destination-Plate picker -- co-located here (not in `app.schemas.carrier`)
because its eligibility semantics are specific to this composite command,
not a generic Carrier concept."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.carrier_specification import CarrierSpecificationSummary
from app.schemas.crop_batch import StageSummary
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


class IntersaladsDestinationLineIn(BaseModel):
    """One destination Nursery Cultivation Plate: the biological quantity
    assigned to it (`assigned_plant_count`, reconciled by the existing
    Transplant core exactly as for the generic endpoint) plus the InterSalads
    Table it must be physically placed on in the same atomic command
    (`destination_location_id`) -- the one genuinely new fact the generic
    `TransplantDestinationLineIn` does not and must not carry."""

    model_config = ConfigDict(extra="forbid")

    destination_carrier_id: uuid.UUID
    assigned_plant_count: int = Field(gt=0)
    destination_location_id: uuid.UUID
    note: str | None = None

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class IntersaladsTransplantCreate(BaseModel):
    """Mirrors `TransplantEventCreate`'s own structure and validation
    intent exactly (including the established duplicate-destination-carrier
    prohibition -- section 4's revalidation confirmed this is already the
    generic Transplant domain's existing semantics, not a new
    interpretation), substituting `IntersaladsDestinationLineIn` for
    `TransplantDestinationLineIn`."""

    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    note: str | None = None
    source_lines: list[TransplantSourceLineIn] = Field(min_length=1, max_length=MAX_SOURCE_LINES)
    destination_lines: list[IntersaladsDestinationLineIn] = Field(
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
    def validate_payload(self) -> "IntersaladsTransplantCreate":
        source_ids = [line.source_assignment_id for line in self.source_lines]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate source_assignment_id within one transplant command")

        dest_ids = [line.destination_carrier_id for line in self.destination_lines]
        if len(dest_ids) != len(set(dest_ids)):
            raise ValueError("duplicate destination_carrier_id within one transplant command")

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


class IntersaladsDestinationLineRead(BaseModel):
    """Section 19 of the ticket: the composite response must be
    reconstructible identically on exact replay -- every field here is
    re-derivable from already-committed TransplantDestinationLine + Movement
    rows, never from in-memory-only state."""

    destination_batch_carrier_assignment_id: uuid.UUID
    carrier: CarrierSummary
    assigned_plant_count: int
    allocated_plant_count: int
    destination_location_id: uuid.UUID
    movement_id: uuid.UUID
    note: str | None


class IntersaladsTransplantRead(BaseModel):
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
    destination_lines: list[IntersaladsDestinationLineRead]
    allocations: list[TransplantAllocationRead]
    total_source_available_before: int
    total_destination_plant_count: int
    total_discarded_plant_count: int
    total_remainder_after: int


class AvailableNurseryCultivationPlateRead(BaseModel):
    """NURSERY-OPS-004B.2 section 13: one row per `nursery_cultivation_plate`
    Carrier currently eligible as a NEW InterSalads Transplant destination --
    active status, no currently-active `BatchCarrierAssignment` (the same
    eligibility `_record_transplant_core` itself enforces via
    `DestinationCarrierAlreadyAssignedError`, read-only here). Deliberately
    reuses `CarrierSpecificationSummary` (`carrier_specification.py`) rather
    than inventing a parallel shape."""

    id: uuid.UUID
    code: str
    status: str
    specification_id: uuid.UUID | None
    specification: CarrierSpecificationSummary | None


__all__ = [
    "IntersaladsDestinationLineIn",
    "IntersaladsTransplantCreate",
    "IntersaladsDestinationLineRead",
    "IntersaladsTransplantRead",
    "AvailableNurseryCultivationPlateRead",
]
