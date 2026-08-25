"""HARVEST-OPS-001 SLICE 2: the operator-facing Leafy Harvest API surface --
harvestable Production Cultivation Plates, Leafy Harvest recording, and
source-line correction reads/writes. Layers on top of the Slice-1 domain
(`app.services.harvest_service`, `app.models.harvest_population_event`,
`app.models.harvest_source_line_correction`) without redesigning it: the
generic CMP-013 schemas in `app.schemas.harvest` show only the immutable
ORIGINAL fact per source line (correct for CMP-013, which has no
correction concept); these schemas additionally expose the Slice-1
correction chain's structurally-resolved CURRENT effective truth and full
correction history, since the Leafy workspace must show both without
confusing "current corrected received quantity" with "current available
after Packing" (two different numbers, both surfaced explicitly)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.schemas.crop_batch import CropSummary, VarietySummary
from app.schemas.harvest import MAX_WEIGHT_KG, MAX_WHOLE_UNIT_COUNT, _parse_strict_decimal, canonical_decimal_str
from app.schemas.sowing_event import CarrierSummary

MAX_LEAFY_HARVEST_SOURCE_LINES = 500


def _require_tz_aware(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("effective_time must be timezone-aware")
    return v


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


def _require_non_blank(v: str, *, field_name: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError(f"{field_name} is required")
    return v


# --- Shared read fragments -----------------------------------------------------------


class LeafyLocationSlotRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class LeafyHarvestLocationRead(BaseModel):
    """One Location breakdown, broken out by the fixed Leafy chain (`zone ->
    span -> grow_table`, always under one `greenhouse`) -- resolved by
    walking `parent_location_id` and slotting each ancestor by its own
    `location_type_code`, never by a hardcoded depth (CLAUDE.md: generic,
    UUID-based parent-child locations). Operator context only, never
    biological authority. Reused for two DELIBERATELY DIFFERENT-MEANING
    fields (never conflate them): `HarvestablePlateRead.location` is the
    Plate's CURRENT physical Occupancy target (operational, live);
    `LeafyHarvestSourceLineRead.harvest_location` is the Plate's HISTORICAL
    Occupancy target as of the HarvestEvent's own `effective_time` (a
    traceability fact, frozen at Harvest time, unaffected by any later
    Movement)."""

    greenhouse: LeafyLocationSlotRead | None
    zone: LeafyLocationSlotRead | None
    span: LeafyLocationSlotRead | None
    grow_table: LeafyLocationSlotRead | None


# --- Commands --------------------------------------------------------------------


class RecordLeafyHarvestSourceLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_carrier_assignment_id: uuid.UUID
    whole_unit_count: int = Field(gt=0, le=MAX_WHOLE_UNIT_COUNT)
    harvested_weight_kg: Decimal
    note: str | None = None

    @field_validator("harvested_weight_kg", mode="before")
    @classmethod
    def validate_weight(cls, v: object) -> Decimal:
        return _parse_strict_decimal(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class RecordLeafyHarvestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    batch_id: uuid.UUID
    effective_time: datetime
    produce_lot_code: str
    note: str | None = None
    source_lines: list[RecordLeafyHarvestSourceLineIn] = Field(
        min_length=1, max_length=MAX_LEAFY_HARVEST_SOURCE_LINES
    )

    @field_validator("effective_time")
    @classmethod
    def validate_effective_time(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)

    @field_validator("produce_lot_code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @model_validator(mode="after")
    def validate_lines(self) -> "RecordLeafyHarvestCreate":
        assignment_ids = [line.batch_carrier_assignment_id for line in self.source_lines]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("duplicate batch_carrier_assignment_id within one Leafy Harvest command")
        return self


class CorrectLeafyHarvestSourceLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    supersedes_correction_id: uuid.UUID | None = None
    is_void: bool
    corrected_harvested_weight_kg: Decimal | None = None
    corrected_whole_unit_count: int | None = Field(default=None, gt=0, le=MAX_WHOLE_UNIT_COUNT)
    reason_code: str
    note: str

    @field_validator("corrected_harvested_weight_kg", mode="before")
    @classmethod
    def validate_weight(cls, v: object) -> Decimal | None:
        if v is None:
            return None
        return _parse_strict_decimal(v)

    @field_validator("reason_code")
    @classmethod
    def validate_reason_code(cls, v: str) -> str:
        return _require_non_blank(v, field_name="reason_code")

    @field_validator("note")
    @classmethod
    def validate_note(cls, v: str) -> str:
        return _require_non_blank(v, field_name="note")

    @model_validator(mode="after")
    def validate_shape(self) -> "CorrectLeafyHarvestSourceLineCreate":
        if self.is_void:
            if self.corrected_harvested_weight_kg is not None or self.corrected_whole_unit_count is not None:
                raise ValueError("a void correction must not carry corrected values")
        else:
            if self.corrected_harvested_weight_kg is None or self.corrected_whole_unit_count is None:
                raise ValueError(
                    "corrected_harvested_weight_kg and corrected_whole_unit_count are both required for a "
                    "non-void correction"
                )
        return self


# --- Reads: Harvestable Plates -----------------------------------------------------


class HarvestablePlateRead(BaseModel):
    """One row per currently-eligible Leafy Harvest source: an active
    (unreleased) `production_cultivation_plate` BatchCarrierAssignment with
    positive current living population (Slice-1 shared authority). A
    zero-living Plate never appears here (it disappears from the
    harvestable list once fully harvested) but remains discoverable via
    Harvest history. A quality-held Plate DOES still appear here (visibly
    flagged, never hidden) -- the write endpoint remains the sole
    authority that actually blocks a new Harvest while the hold is open.
    Deliberately omits the internal population-root BatchCarrierAssignment
    id -- never genuinely useful to the operator-facing client."""

    production_plate_id: uuid.UUID
    production_plate_code: str
    batch_id: uuid.UUID
    batch_code: str
    crop_common_name: str
    variety_name: str | None
    current_living_heads: int
    current_batch_carrier_assignment_id: uuid.UUID
    location: LeafyHarvestLocationRead | None
    has_location_warning: bool
    quality_hold_open: bool


# --- Reads: Harvest history / detail -----------------------------------------------


class LeafyHarvestSourceLineCorrectionRead(BaseModel):
    id: uuid.UUID
    supersedes_correction_id: uuid.UUID | None
    is_void: bool
    corrected_harvested_weight_kg: Decimal | None
    corrected_whole_unit_count: int | None
    reason_code: str
    note: str
    actor_user_id: uuid.UUID | None
    recorded_time: datetime

    @field_serializer("corrected_harvested_weight_kg")
    def serialize_weight(self, v: Decimal | None) -> str | None:
        return canonical_decimal_str(v) if v is not None else None


class LeafyHarvestSourceLineRead(BaseModel):
    """Both the immutable ORIGINAL fact and the structurally-resolved
    CURRENT effective truth for one source contribution -- never collapses
    one into the other. `state` is `"VOID"` only when the correction chain
    tip is a void correction; otherwise `"ACTIVE"` (including when never
    corrected at all). `correction_tip_id` is the id the client MUST echo
    back as `supersedes_correction_id` on its next correction attempt (a
    stale value there is rejected with 409, never silently retargeted)."""

    id: uuid.UUID
    batch_carrier_assignment_id: uuid.UUID
    carrier: CarrierSummary
    harvest_location: LeafyHarvestLocationRead | None
    original_harvested_weight_kg: Decimal
    original_whole_unit_count: int | None
    current_harvested_weight_kg: Decimal
    current_whole_unit_count: int
    state: Literal["ACTIVE", "VOID"]
    correction_tip_id: uuid.UUID | None
    correction_history: list[LeafyHarvestSourceLineCorrectionRead]

    @field_serializer("original_harvested_weight_kg", "current_harvested_weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class LeafyHarvestEventRead(BaseModel):
    """One HarvestEvent/HarvestedProduceLot pair, Leafy-aware. `original_*`
    mirrors `HarvestedProduceLot.total_*` (immutable, never presented as
    current truth on its own). `current_*` is the aggregation of every
    source line's own current effective tuple (Slice-1's correction chain
    authority) -- may equal `original_*` in total even when individual
    lines changed in offsetting directions; per-line values in
    `source_lines` remain the only place that distinction is visible.
    `available_balance_*` is the produce lot's CURRENT ledger balance
    (after any downstream Packing consumption) -- deliberately a different
    number from `current_*`, never conflated with it."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    batch_id: uuid.UUID
    batch_code: str
    crop: CropSummary
    variety: VarietySummary | None
    effective_time: datetime
    recorded_time: datetime
    actor_user_id: uuid.UUID
    produce_lot_id: uuid.UUID
    produce_lot_code: str
    note: str | None
    original_total_harvested_weight_kg: Decimal
    original_total_whole_unit_count: int | None
    current_total_harvested_weight_kg: Decimal
    current_total_whole_unit_count: int
    available_balance_weight_kg: Decimal
    available_balance_whole_unit_count: int | None
    source_lines: list[LeafyHarvestSourceLineRead]

    @field_serializer(
        "original_total_harvested_weight_kg", "current_total_harvested_weight_kg", "available_balance_weight_kg"
    )
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)
