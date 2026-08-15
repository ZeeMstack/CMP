"""FARM-SETUP-001: typed, classification-specific physical setup request/
response models.

Deliberately NOT a generic arbitrary-Location-graph payload -- every
generator config here mirrors the exact shape `LocationBulkChildrenCreate`/
`AssetPositionsGenerate` already validate and implement (code_prefix/start/
end/pad_width[/capacity]), just nested once per structural level. This
keeps payload size small even for a large commercial structure (thousands
of Grow Bag Positions collapse to a handful of generator configs) and lets
the setup service reuse the SAME validated generator primitives the
existing single-call bulk-children/positions-generate endpoints already
use -- no parallel validation logic, no arbitrary graph writes.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.asset_position import MAX_BULK_POSITIONS
from app.schemas.location import GREENHOUSE_CLASSIFICATIONS, MAX_BULK_CHILDREN, _normalize_code


def _validate_capacity(v: int | None) -> int | None:
    if v is not None and v < 1:
        raise ValueError("capacity must be a positive integer")
    return v


def _validate_generator_range(*, start: int, end: int, pad_width: int, label: str) -> None:
    if start < 1:
        raise ValueError(f"{label}: start must be a positive integer")
    if end < start:
        raise ValueError(f"{label}: end must be greater than or equal to start")
    if pad_width < 1:
        raise ValueError(f"{label}: pad_width must be a positive integer")


class TableGeneratorConfig(BaseModel):
    """Generates N sibling table-like locations under one parent, in one
    `_bulk_generate_children_core` call -- code_prefix/start/end/pad_width
    exactly mirror the existing `LocationBulkChildrenCreate` shape.
    Numbering restarts naturally per parent simply because each parent gets
    its own generator config with its own `start` (see LOCATION_MODEL.md
    setup section) -- no separate "restart vs continue" flag is needed."""

    code_prefix: str
    start: int
    end: int
    pad_width: int
    capacity: int | None = None

    @field_validator("code_prefix")
    @classmethod
    def validate_prefix(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("code_prefix must not be blank")
        return v

    @field_validator("capacity")
    @classmethod
    def validate_capacity(cls, v: int | None) -> int | None:
        return _validate_capacity(v)

    @model_validator(mode="after")
    def validate_range(self) -> "TableGeneratorConfig":
        _validate_generator_range(start=self.start, end=self.end, pad_width=self.pad_width, label="table generator")
        count = self.end - self.start + 1
        if count > MAX_BULK_CHILDREN:
            raise ValueError(f"cannot generate more than {MAX_BULK_CHILDREN} tables per generator")
        return self


class GutterGeneratorConfig(BaseModel):
    """Generates N sibling Grow Gutters under one Span, each with the same
    number of Grow Bag Positions. Grow Bag Position is a true exclusive
    physical position -- its capacity is never configurable here and is
    always left at the domain default (NULL -> effective capacity 1);
    this model has no `capacity` field at all, deliberately, so there is no
    biological/plant-capacity input to misuse."""

    code_prefix: str
    start: int
    end: int
    pad_width: int
    bag_positions_per_gutter: int = Field(gt=0)
    bag_position_code_prefix: str
    bag_position_pad_width: int

    @field_validator("code_prefix", "bag_position_code_prefix")
    @classmethod
    def validate_prefixes(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("code_prefix must not be blank")
        return v

    @model_validator(mode="after")
    def validate_range(self) -> "GutterGeneratorConfig":
        _validate_generator_range(start=self.start, end=self.end, pad_width=self.pad_width, label="gutter generator")
        count = self.end - self.start + 1
        if count > MAX_BULK_CHILDREN:
            raise ValueError(f"cannot generate more than {MAX_BULK_CHILDREN} gutters per generator")
        if self.bag_position_pad_width < 1:
            raise ValueError("bag_position_pad_width must be a positive integer")
        if self.bag_positions_per_gutter > MAX_BULK_CHILDREN:
            raise ValueError(f"cannot generate more than {MAX_BULK_CHILDREN} bag positions per gutter")
        return self


class SpanSetupConfig(BaseModel):
    code: str
    tables: TableGeneratorConfig | None = None
    gutters: GutterGeneratorConfig | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)


class ZoneSetupConfig(BaseModel):
    code: str
    spans: list[SpanSetupConfig] = Field(min_length=1)

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)


class LeafySetupConfig(BaseModel):
    zones: list[ZoneSetupConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def every_span_has_tables(self) -> "LeafySetupConfig":
        for zone in self.zones:
            for span in zone.spans:
                if span.tables is None:
                    raise ValueError(f"span {span.code!r}: tables configuration is required for a Leafy Greens greenhouse")
                if span.gutters is not None:
                    raise ValueError(f"span {span.code!r}: gutters are not valid for a Leafy Greens greenhouse")
        return self


class VinesSetupConfig(BaseModel):
    zones: list[ZoneSetupConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def every_span_has_gutters(self) -> "VinesSetupConfig":
        for zone in self.zones:
            for span in zone.spans:
                if span.gutters is None:
                    raise ValueError(f"span {span.code!r}: gutters configuration is required for a Vines greenhouse")
                if span.tables is not None:
                    raise ValueError(f"span {span.code!r}: tables are not valid for a Vines greenhouse")
        return self


class TrolleyLevelGeneratorConfig(BaseModel):
    """Mirrors `AssetPositionsGenerate` exactly. `slots_per_shelf` is the
    number of Seed Trays each Level physically holds -- represented as one
    exclusive numbered slot per tray (the existing, only, occupancy-
    compatibility-proven target for a seed_tray carrier), not as a single
    high-capacity shelf row; `slot_capacity` stays NULL/1 accordingly
    unless the caller has a genuine reason to widen it."""

    shelf_count: int
    slots_per_shelf: int
    shelf_prefix: str
    slot_prefix: str
    shelf_pad_width: int
    slot_pad_width: int
    slot_capacity: int | None = None

    @field_validator("shelf_prefix", "slot_prefix")
    @classmethod
    def validate_prefixes(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("prefix must not be blank")
        return v

    @field_validator("slot_capacity")
    @classmethod
    def validate_capacity(cls, v: int | None) -> int | None:
        return _validate_capacity(v)

    @model_validator(mode="after")
    def validate_counts(self) -> "TrolleyLevelGeneratorConfig":
        if self.shelf_count < 1:
            raise ValueError("shelf_count must be a positive integer")
        if self.slots_per_shelf < 1:
            raise ValueError("slots_per_shelf must be a positive integer")
        if self.shelf_pad_width < 1 or self.slot_pad_width < 1:
            raise ValueError("pad widths must be positive integers")
        total = self.shelf_count + (self.shelf_count * self.slots_per_shelf)
        if total > MAX_BULK_POSITIONS:
            raise ValueError(f"cannot generate more than {MAX_BULK_POSITIONS} positions per trolley")
        return self


class TrolleySetupConfig(BaseModel):
    code: str
    name: str | None = None
    levels: TrolleyLevelGeneratorConfig

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)


class SeedingMachineSetupConfig(BaseModel):
    code: str
    name: str | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)


MAX_NURSERY_ASSETS_PER_SETUP = 50


class NurserySectionConfig(BaseModel):
    """FARM-SETUP-001.1: Seeding Station / Germination Chamber -- a single
    physical section directly under the Nursery Greenhouse, user-supplied
    code (never a generated/hidden identity, unlike the table generators --
    there is exactly one of each per Nursery, not "N of them")."""

    code: str
    name: str | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)


class NurserySetupConfig(BaseModel):
    """Section 7 (Seedling/InterSalads/InterVines tables) plus sections 8-9
    (optional Germination Trolley/Seeding Machine assets) plus
    FARM-SETUP-001.1's Seeding Station / Germination Chamber -- the
    complete authoritative Nursery topology is now configurable entirely
    inside Farm Setup, no generic Location API workaround required."""

    seeding_station: NurserySectionConfig | None = None
    germination_chamber: NurserySectionConfig | None = None
    seedling_tables: TableGeneratorConfig | None = None
    intersalads_tables: TableGeneratorConfig | None = None
    intervines_tables: TableGeneratorConfig | None = None
    trolleys: list[TrolleySetupConfig] = Field(default_factory=list)
    seeding_machines: list[SeedingMachineSetupConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def at_least_one_group_and_bounded_assets(self) -> "NurserySetupConfig":
        if not any(
            [
                self.seeding_station, self.germination_chamber,
                self.seedling_tables, self.intersalads_tables, self.intervines_tables,
                self.trolleys, self.seeding_machines,
            ]
        ):
            raise ValueError(
                "Nursery setup requires at least one configured section (seeding station, germination "
                "chamber, tables, trolleys, or seeding machines)"
            )
        if len(self.trolleys) > MAX_NURSERY_ASSETS_PER_SETUP:
            raise ValueError(f"cannot register more than {MAX_NURSERY_ASSETS_PER_SETUP} trolleys per setup command")
        if len(self.seeding_machines) > MAX_NURSERY_ASSETS_PER_SETUP:
            raise ValueError(f"cannot register more than {MAX_NURSERY_ASSETS_PER_SETUP} seeding machines per setup command")
        trolley_codes = [t.code for t in self.trolleys]
        if len(trolley_codes) != len(set(trolley_codes)):
            raise ValueError("duplicate trolley codes within the same setup command")
        machine_codes = [m.code for m in self.seeding_machines]
        if len(machine_codes) != len(set(machine_codes)):
            raise ValueError("duplicate seeding machine codes within the same setup command")
        return self


class GreenhouseSetupCreate(BaseModel):
    code: str
    name: str
    classification: str
    client_command_id: uuid.UUID
    nursery: NurserySetupConfig | None = None
    leafy: LeafySetupConfig | None = None
    vines: VinesSetupConfig | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("classification")
    @classmethod
    def validate_classification(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in GREENHOUSE_CLASSIFICATIONS:
            allowed = ", ".join(sorted(GREENHOUSE_CLASSIFICATIONS))
            raise ValueError(f"classification must be one of: {allowed}")
        return v

    @model_validator(mode="after")
    def exactly_one_matching_structure(self) -> "GreenhouseSetupCreate":
        provided = {
            "nursery": self.nursery is not None,
            "leafy_greens": self.leafy is not None,
            "vines": self.vines is not None,
        }
        if provided.get(self.classification) is not True:
            raise ValueError(f"a {self.classification!r} greenhouse requires matching {self.classification!r} setup configuration")
        others = [k for k, present in provided.items() if present and k != self.classification]
        if others:
            raise ValueError(f"setup configuration for {others} must not be provided for a {self.classification!r} greenhouse")
        return self


class GreenhouseSetupCounts(BaseModel):
    zones: int = 0
    spans: int = 0
    tables: int = 0
    gutters: int = 0
    bag_positions: int = 0
    seeding_stations: int = 0
    germination_chambers: int = 0
    seedling_tables: int = 0
    intersalads_tables: int = 0
    intervines_tables: int = 0
    trolleys: int = 0
    trolley_levels: int = 0
    trolley_slots: int = 0
    seeding_machines: int = 0


class GreenhouseSetupResult(BaseModel):
    greenhouse_id: uuid.UUID
    code: str
    name: str
    classification: str
    counts: GreenhouseSetupCounts


class GreenhouseOverviewItem(BaseModel):
    """One row of the Farm Setup Greenhouses overview -- every count is
    derived from actual configured `locations` rows, never fabricated."""

    greenhouse_id: uuid.UUID
    code: str
    name: str
    classification: str
    status: str  # "empty" | "partial" | "configured" -- see farm_setup_service._derive_status
    counts: GreenhouseSetupCounts


class StructureTableNode(BaseModel):
    id: uuid.UUID
    code: str
    capacity: int | None


class StructureSpanNode(BaseModel):
    id: uuid.UUID
    code: str
    tables: list[StructureTableNode]


class StructureZoneNode(BaseModel):
    id: uuid.UUID
    code: str
    spans: list[StructureSpanNode]


class StructureGutterNode(BaseModel):
    id: uuid.UUID
    code: str
    bag_position_count: int


class StructureVinesSpanNode(BaseModel):
    id: uuid.UUID
    code: str
    gutters: list[StructureGutterNode]


class StructureVinesZoneNode(BaseModel):
    id: uuid.UUID
    code: str
    spans: list[StructureVinesSpanNode]


class StructureNurseryTableGroup(BaseModel):
    area_id: uuid.UUID | None
    tables: list[StructureTableNode]


class StructureSectionNode(BaseModel):
    """FARM-SETUP-001.1: Seeding Station / Germination Chamber -- a single
    section directly under the Nursery Greenhouse, not a generated group."""

    id: uuid.UUID
    code: str
    name: str


class GreenhouseStructureRead(BaseModel):
    """A readable, classification-shaped view of one Greenhouse's existing
    physical structure -- not a generic Location dump. Exactly one of the
    three classification-specific groups below is populated, matching
    `greenhouse.classification`."""

    greenhouse_id: uuid.UUID
    code: str
    name: str
    classification: str
    leafy_zones: list[StructureZoneNode] | None = None
    vines_zones: list[StructureVinesZoneNode] | None = None
    # NURSERY-OPS-001.1: a Nursery Greenhouse structurally CAN have more than
    # one Seeding Station location (the generic `POST /farms/{farm_id}/locations`
    # route has no cardinality guard here, even though today's Farm Setup
    # wizard only ever creates 0 or 1) -- the full list is returned, never
    # silently collapsed to "the first one", so callers (the Sowing form)
    # can require an explicit operator choice when more than one exists.
    nursery_seeding_stations: list[StructureSectionNode] = Field(default_factory=list)
    nursery_germination_chamber: StructureSectionNode | None = None
    nursery_seedling: StructureNurseryTableGroup | None = None
    nursery_intersalads: StructureNurseryTableGroup | None = None
    nursery_intervines: StructureNurseryTableGroup | None = None
