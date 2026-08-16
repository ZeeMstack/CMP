from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.crop_batch import StageSummary
from app.schemas.sowing_event import CarrierSummary, SeedLotSummary

MAX_SOURCE_LINES = 200
MAX_DESTINATION_LINES = 500
MAX_ALLOCATIONS = 2000


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class TransplantSourceLineIn(BaseModel):
    """NURSERY-OPS-004A: the operator supplies only the transplant-boundary
    reconciliation facts for a source Tray -- never `source_plant_count`
    (the authoritative `source_available_before`) and never
    `discarded_plant_count` (the server-computed aggregate of the four
    categorized counts below). Both are always server-derived (section 5/12)."""

    model_config = ConfigDict(extra="forbid")

    source_assignment_id: uuid.UUID
    transplant_damage_count: int = Field(ge=0, default=0)
    qc_rejection_count: int = Field(ge=0, default=0)
    sample_count: int = Field(ge=0, default=0)
    other_loss_count: int = Field(ge=0, default=0)
    other_loss_note: str | None = None
    note: str | None = None

    @field_validator("other_loss_note", "note")
    @classmethod
    def validate_notes(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_other_loss_note(self) -> "TransplantSourceLineIn":
        if self.other_loss_count > 0 and not self.other_loss_note:
            raise ValueError("other_loss_note is required when other_loss_count > 0")
        return self


class TransplantDestinationLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_carrier_id: uuid.UUID
    assigned_plant_count: int = Field(gt=0)
    note: str | None = None

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class TransplantAllocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_assignment_id: uuid.UUID
    destination_carrier_id: uuid.UUID
    allocated_plant_count: int = Field(gt=0)


class TransplantEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    effective_time: datetime
    note: str | None = None
    source_lines: list[TransplantSourceLineIn] = Field(min_length=1, max_length=MAX_SOURCE_LINES)
    destination_lines: list[TransplantDestinationLineIn] = Field(
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
    def validate_payload(self) -> "TransplantEventCreate":
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

        # NURSERY-OPS-004A: unlike the pre-checkpoint model, a destination
        # line lacking any allocation is no longer structurally impossible
        # to reconcile (a source's leftover could -- degenerately -- become
        # 100% remainder), but a destination line the operator explicitly
        # declared and that received nothing is still almost certainly a
        # mistake, so this check is kept.
        allocated_dest_ids = {a.destination_carrier_id for a in self.allocations}
        unused_destinations = dest_id_set - allocated_dest_ids
        if unused_destinations:
            raise ValueError("every destination line must receive at least one allocation")
        return self


class TransplantSourceLineRead(BaseModel):
    id: uuid.UUID
    source_batch_carrier_assignment_id: uuid.UUID
    carrier: CarrierSummary
    seed_lot: SeedLotSummary
    sowing_event_id: uuid.UUID
    source_available_before: int
    successful_transferred_count: int
    transplant_damage_count: int
    qc_rejection_count: int
    sample_count: int
    other_loss_count: int
    other_loss_note: str | None
    discarded_plant_count: int
    remainder_after: int
    checkpoint_id: uuid.UUID
    note: str | None


class TransplantDestinationLineRead(BaseModel):
    id: uuid.UUID
    destination_batch_carrier_assignment_id: uuid.UUID
    carrier: CarrierSummary
    assigned_plant_count: int
    allocated_plant_count: int
    note: str | None


class TransplantAllocationRead(BaseModel):
    id: uuid.UUID
    source_carrier: CarrierSummary
    destination_carrier: CarrierSummary
    allocated_plant_count: int


class TransplantEventRead(BaseModel):
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
    destination_lines: list[TransplantDestinationLineRead]
    allocations: list[TransplantAllocationRead]
    total_source_available_before: int
    total_destination_plant_count: int
    total_discarded_plant_count: int
    total_remainder_after: int
