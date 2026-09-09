"""VINES-OPS-003: the operator-facing Vines Harvest API surface -- reuses
the generic CMP-013/HARVEST-OPS-001 Harvest domain (`app.services.
harvest_service`, `harvest_events`/`harvest_source_lines`/`harvested_
produce_lots`) completely unmodified in shape; the only new column
(`HarvestSourceLine.source_location_id`) is a second, mutually-exclusive
anchor on the SAME table (see the `5a26ba0dae6c` migration's own docstring).
Mirrors `app.schemas.leafy_harvest`'s own shape closely, substituting a Grow
Gutter Location for a single biological source Carrier: a Vines Harvest
source line records ONE operator-entered weight per Gutter (never a
fabricated per-Bag/per-plant split), with the underlying currently-living
Grow Bag lineage exposed separately, identity-only. No `whole_unit_count`
anywhere -- Vines Harvest is weight-only for the current pilot crops (Cherry
Tomato, Color Capsicum). No correction-driven population consequence exists
at all (repeat harvest never reduces living population), so `VinesHarvest
SourceLineRead` carries no population/BCA field of any kind."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.schemas.crop_batch import CropSummary, VarietySummary
from app.schemas.harvest import _parse_strict_decimal, canonical_decimal_str
from app.schemas.sowing_event import CarrierSummary

MAX_VINES_HARVEST_SOURCE_LINES = 200


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


class VinesLocationSlotRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class VinesHarvestLocationRead(BaseModel):
    """One Location breakdown, broken out by the fixed Vines chain
    (`zone -> span -> grow_gutter`, always under one `greenhouse`) --
    resolved by walking `parent_location_id`, never a hardcoded depth."""

    greenhouse: VinesLocationSlotRead | None
    zone: VinesLocationSlotRead | None
    span: VinesLocationSlotRead | None
    gutter: VinesLocationSlotRead | None


# --- Commands --------------------------------------------------------------------


class RecordVinesHarvestSourceLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gutter_id: uuid.UUID
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


class RecordVinesHarvestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    batch_id: uuid.UUID
    effective_time: datetime
    produce_lot_code: str
    note: str | None = None
    source_lines: list[RecordVinesHarvestSourceLineIn] = Field(
        min_length=1, max_length=MAX_VINES_HARVEST_SOURCE_LINES
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
    def validate_lines(self) -> "RecordVinesHarvestCreate":
        gutter_ids = [line.gutter_id for line in self.source_lines]
        if len(gutter_ids) != len(set(gutter_ids)):
            raise ValueError("duplicate gutter_id within one Vines Harvest command")
        return self


class CorrectVinesHarvestSourceLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_command_id: uuid.UUID
    supersedes_correction_id: uuid.UUID | None = None
    is_void: bool
    corrected_harvested_weight_kg: Decimal | None = None
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
    def validate_shape(self) -> "CorrectVinesHarvestSourceLineCreate":
        if self.is_void:
            if self.corrected_harvested_weight_kg is not None:
                raise ValueError("a void correction must not carry a corrected value")
        else:
            if self.corrected_harvested_weight_kg is None:
                raise ValueError("corrected_harvested_weight_kg is required for a non-void correction")
        return self


# --- Reads: Harvestable sources -----------------------------------------------------


class VinesHarvestableSourceRead(BaseModel):
    """One row per currently-eligible (Batch, Grow Gutter) Vines Harvest
    source -- at least one currently-living Grow Bag/Grow Cube under this
    Gutter for this Batch (VINES-OPS-002's own living-population authority,
    never recomputed). A Gutter with zero living plants for this Batch never
    appears here. A quality-held Batch DOES still appear here (visibly
    flagged, never hidden) -- the write endpoint remains the sole authority
    that actually blocks a new Harvest while the hold is open."""

    batch_id: uuid.UUID
    batch_code: str
    crop_common_name: str
    variety_name: str | None
    greenhouse_id: uuid.UUID
    greenhouse_code: str
    gutter_id: uuid.UUID
    gutter_code: str
    living_plant_count: int
    last_harvest_effective_time: datetime | None
    quality_hold_open: bool


# --- Reads: Harvest history / detail -----------------------------------------------


class VinesHarvestSourceLineCorrectionRead(BaseModel):
    id: uuid.UUID
    supersedes_correction_id: uuid.UUID | None
    is_void: bool
    corrected_harvested_weight_kg: Decimal | None
    reason_code: str
    note: str
    actor_user_id: uuid.UUID | None
    recorded_time: datetime

    @field_serializer("corrected_harvested_weight_kg")
    def serialize_weight(self, v: Decimal | None) -> str | None:
        return canonical_decimal_str(v) if v is not None else None


class VinesHarvestSourceLineRead(BaseModel):
    """Both the immutable ORIGINAL fact and the structurally-resolved
    CURRENT effective truth for one Gutter's own contribution -- mirrors
    `LeafyHarvestSourceLineRead`'s shape, minus every population/BCA field
    (Vines Harvest never has one) and minus `whole_unit_count` (weight-only).
    `grow_bags` is the point-in-time lineage snapshot -- identity only,
    never a weight split."""

    id: uuid.UUID
    gutter: VinesLocationSlotRead
    harvest_location: VinesHarvestLocationRead | None
    grow_bags: list[CarrierSummary]
    original_harvested_weight_kg: Decimal
    current_harvested_weight_kg: Decimal
    state: str
    correction_tip_id: uuid.UUID | None
    correction_history: list[VinesHarvestSourceLineCorrectionRead]

    @field_serializer("original_harvested_weight_kg", "current_harvested_weight_kg")
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


class VinesHarvestEventRead(BaseModel):
    """One HarvestEvent/HarvestedProduceLot pair, Vines-aware -- mirrors
    `LeafyHarvestEventRead`'s shape exactly, minus `*_whole_unit_count`
    (weight-only)."""

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
    current_total_harvested_weight_kg: Decimal
    available_balance_weight_kg: Decimal
    source_lines: list[VinesHarvestSourceLineRead]

    @field_serializer(
        "original_total_harvested_weight_kg", "current_total_harvested_weight_kg", "available_balance_weight_kg"
    )
    def serialize_weight(self, v: Decimal) -> str:
        return canonical_decimal_str(v)


__all__ = [
    "VinesLocationSlotRead",
    "VinesHarvestLocationRead",
    "RecordVinesHarvestSourceLineIn",
    "RecordVinesHarvestCreate",
    "CorrectVinesHarvestSourceLineCreate",
    "VinesHarvestableSourceRead",
    "VinesHarvestSourceLineCorrectionRead",
    "VinesHarvestSourceLineRead",
    "VinesHarvestEventRead",
]
