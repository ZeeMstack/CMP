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
    """PILOT-UX-001B: the new-model Nursery Germination Level generator --
    creates ONLY `level_count` root `shelf`-kind AssetPositions ("Levels"),
    each with `capacity=trays_per_level`; deliberately no child `slot` rows
    are ever created here (a Level holds Seed Trays directly, via
    DOMAIN-FARM-002's generic N-occupant capacity mechanism).

    PILOT-UX-001B2: `level_prefix` is operator-configurable (defaults to
    "L", matching the original hardcoded behavior exactly), but
    `farm_setup_service` always PREPENDS the owning Trolley's own code to
    it server-side (`{trolley.code}-{level_prefix}{NN}`) -- the caller can
    never supply a level code that omits or contradicts its Trolley's real
    identity, only the short suffix segment. This schema no longer mirrors
    `AssetPositionsGenerate`, which keeps its own full shelf+slot shape
    unchanged for legacy/generic use."""

    level_count: int
    trays_per_level: int
    level_pad_width: int
    level_prefix: str = "L"

    @field_validator("trays_per_level")
    @classmethod
    def validate_trays_per_level(cls, v: int) -> int:
        if v < 1:
            raise ValueError("trays_per_level must be a positive integer")
        return v

    @field_validator("level_prefix")
    @classmethod
    def validate_level_prefix(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("level_prefix must not be blank")
        return v

    @model_validator(mode="after")
    def validate_counts(self) -> "TrolleyLevelGeneratorConfig":
        if self.level_count < 1:
            raise ValueError("level_count must be a positive integer")
        if self.level_pad_width < 1:
            raise ValueError("level_pad_width must be a positive integer")
        if self.level_count > MAX_BULK_POSITIONS:
            raise ValueError(f"cannot generate more than {MAX_BULK_POSITIONS} levels per trolley")
        return self


class TrolleySetupConfig(BaseModel):
    """Explicit, hand-entered single-Trolley registration -- the caller
    supplies the Trolley's own code directly. See `TrolleyGeneratorConfig`
    below for the bulk N-trolleys-at-once alternative; `NurserySetupConfig`
    accepts one or the other, never both, in the same command."""

    code: str
    name: str | None = None
    levels: TrolleyLevelGeneratorConfig

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)


class TrolleyGeneratorConfig(BaseModel):
    """PILOT-UX-001B2: bulk Germination Trolley generator -- creates
    `trolley_count` Trolley Assets, code = `{trolley_prefix}-{NN}`
    (`NN` zero-padded to `trolley_pad_width`, sequence 1..trolley_count),
    each with its own independent `levels` generator (Level numbering
    restarts inside every Trolley, since each Trolley's Levels are
    generated separately -- exactly like `TableGeneratorConfig`'s own
    per-parent restart). Trolley identity is always server-generated from
    the prefix; the operator configures the prefix only, never types an
    individual Trolley or Level code by hand."""

    trolley_count: int
    trolley_prefix: str
    trolley_pad_width: int = 2
    levels: TrolleyLevelGeneratorConfig

    @field_validator("trolley_prefix")
    @classmethod
    def validate_trolley_prefix(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("trolley_prefix must not be blank")
        return v

    @model_validator(mode="after")
    def validate_counts(self) -> "TrolleyGeneratorConfig":
        if self.trolley_count < 1:
            raise ValueError("trolley_count must be a positive integer")
        if self.trolley_pad_width < 1:
            raise ValueError("trolley_pad_width must be a positive integer")
        if self.trolley_count > MAX_NURSERY_ASSETS_PER_SETUP:
            raise ValueError(f"cannot generate more than {MAX_NURSERY_ASSETS_PER_SETUP} trolleys per generator")
        return self


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


class GerminationChamberSetupConfig(NurserySectionConfig):
    """NURSERY-OPS-002A: the Germination Chamber directly occupies Germination
    Trolley Assets (the frozen authoritative model -- no chamber_position
    child locations). `trolley_capacity` is the number of distinct Trolleys
    the Chamber may simultaneously hold -- NULL/1 (DOMAIN-FARM-002 default)
    means exclusive, matching the pre-existing capacity convention exactly."""

    trolley_capacity: int | None = None

    @field_validator("trolley_capacity")
    @classmethod
    def validate_trolley_capacity(cls, v: int | None) -> int | None:
        return _validate_capacity(v)


class NurserySetupConfig(BaseModel):
    """Section 7 (Seedling/InterSalads/InterVines tables) plus sections 8-9
    (optional Germination Trolley/Seeding Machine assets) plus
    FARM-SETUP-001.1's Seeding Station / Germination Chamber -- the
    complete authoritative Nursery topology is now configurable entirely
    inside Farm Setup, no generic Location API workaround required."""

    seeding_station: NurserySectionConfig | None = None
    germination_chamber: GerminationChamberSetupConfig | None = None
    seedling_tables: TableGeneratorConfig | None = None
    intersalads_tables: TableGeneratorConfig | None = None
    intervines_tables: TableGeneratorConfig | None = None
    trolleys: list[TrolleySetupConfig] = Field(default_factory=list)
    # PILOT-UX-001B2: the bulk N-trolleys-at-once alternative to `trolleys`
    # above -- mutually exclusive with it (see the validator below), so a
    # setup command always picks exactly one shape for its Trolleys.
    trolley_generator: TrolleyGeneratorConfig | None = None
    seeding_machines: list[SeedingMachineSetupConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def at_least_one_group_and_bounded_assets(self) -> "NurserySetupConfig":
        if not any(
            [
                self.seeding_station, self.germination_chamber,
                self.seedling_tables, self.intersalads_tables, self.intervines_tables,
                self.trolleys, self.trolley_generator, self.seeding_machines,
            ]
        ):
            raise ValueError(
                "Nursery setup requires at least one configured section (seeding station, germination "
                "chamber, tables, trolleys, or seeding machines)"
            )
        if self.trolleys and self.trolley_generator is not None:
            raise ValueError("provide either explicit trolleys or a trolley_generator, not both")
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


class StructureGerminationChamberNode(StructureSectionNode):
    """NURSERY-OPS-002A: `trolley_capacity` is the Chamber's configured
    number-of-Trolleys capacity (NULL means the DOMAIN-FARM-002 default of
    1, exclusive) -- never a tray/seed/plant quantity."""

    trolley_capacity: int | None = None


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
    nursery_germination_chamber: StructureGerminationChamberNode | None = None
    nursery_seedling: StructureNurseryTableGroup | None = None
    nursery_intersalads: StructureNurseryTableGroup | None = None
    nursery_intervines: StructureNurseryTableGroup | None = None
