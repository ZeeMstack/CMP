"""PILOT-SETUP-001A: config-driven, idempotent MASTER/CONFIGURATION-data
bootstrap for a real Iceberg pilot farm.

Scope, frozen by the PILOT-SETUP-001 discovery audit and the
PILOT-SETUP-001A build ticket:

* Creates ONLY master/configuration records: Farm, Greenhouse/Location
  structure, Cold Store/Packing Hall locations, CarrierSpecification,
  Carrier (physical registration only), Crop, Variety, ProductionSystem,
  Workflow/Stage/Transition (published), GradeDefinition/Version,
  PackagingUnit, PackSpecification/Version, and -- only if the farm has
  elected to supply one -- a real starting Seed Lot.

* NEVER creates an operational lifecycle transaction: no Sowing, no Crop
  Batch (beyond what a published Workflow Version's own existence
  implies -- none is created here), no Germination Outcome, no Seedling
  Entry, no biological disposition, no InterSalads/Production Transfer,
  no Harvest, no Grading, no Packing, no Finished-Goods storage movement,
  no Dispatch, no Recall. The config schema itself has no field capable of
  expressing any of these -- there is nothing to accidentally seed.

* Tenant/User/Membership provisioning is explicitly OUT of scope
  (DEPLOY-001). This module never creates a Tenant, User, or Membership --
  it only RESOLVES an already-existing Tenant (by code) and an
  already-existing administrative User + active Membership (by OIDC
  identity), and fails loudly if either cannot be resolved.

Every mutating call below reuses the real application service layer
(`app.services.*`) so tenant/farm/hierarchy/capacity/version/effective-date
validation is never reimplemented here -- this module only adds
get-or-create-by-human-code idempotency and conflict detection on top of
it. Two families of underlying service exist and are handled differently:

  1. Plain `register_*`/`create_*` calls (Farm, Crop, Variety,
     ProductionSystem, CarrierSpecification, Carrier, generic Location,
     SeedLot, Workflow/Stage/Transition) have no built-in idempotency --
     this module looks the row up by its natural human code FIRST, compares
     its identity-defining fields against the requested config if found,
     and only calls the register/create function when nothing exists yet.
     A field mismatch is reported as a CONFLICT, never silently applied.

  2. Command-idempotent calls (`farm_setup_service.create_greenhouse_setup`,
     `grade_definition_service.*`, `packaging_unit_service.*`,
     `pack_specification_service.*`) already implement
     client_command_id + fingerprint replay natively. This module derives a
     deterministic client_command_id from (tenant, entity kind, code) and
     always calls straight through -- a byte-identical rerun replays for
     free; a changed payload under the same code surfaces the service's own
     *ReusedWithDifferentPayloadError, reported here as a CONFLICT.

Transaction strategy: this module never calls `db.commit()` or
`db.rollback()` itself -- every underlying service call commits internally,
but the CALLER (see `scripts/bootstrap_pilot_master_data.py`) is expected to
bind `db` to a Session created with `join_transaction_mode="create_savepoint"`
over an explicit outer `Connection` transaction it controls (exactly
`tests/conftest.py`'s own `db_session` fixture pattern). Under that mode
every internal `db.commit()` this module triggers only releases a SAVEPOINT
-- the real outer transaction stays open until the caller explicitly
commits (APPLY) or rolls back (DRY RUN or an aborted APPLY), giving
"all master data lands, or none does" for free with zero changes to any
existing service.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.carrier import Carrier
from app.models.carrier_specification import CarrierSpecification
from app.models.crop import Crop
from app.models.farm import Farm
from app.models.grade_definition import GradeDefinition
from app.models.grade_definition_version import GradeDefinitionVersion
from app.models.location import Location
from app.models.packaging_unit import PackagingUnit
from app.models.pack_specification import PackSpecification
from app.models.pack_specification_version import PackSpecificationVersion
from app.models.production_system import ProductionSystem
from app.models.seed_lot import SeedLot
from app.models.tenant import Tenant
from app.models.variety import Variety
from app.models.workflow import Workflow
from app.models.workflow_stage import WorkflowStage
from app.models.workflow_transition import WorkflowTransition
from app.models.workflow_version import WorkflowVersion
from app.schemas.farm_setup import (
    GreenhouseSetupCreate,
    LeafySetupConfig,
    NurserySetupConfig,
)
from app.services import (
    carrier_service,
    carrier_specification_service,
    crop_service,
    farm_service,
    farm_setup_service,
    grade_definition_service,
    location_service,
    membership_service,
    packaging_unit_service,
    pack_specification_service,
    production_system_service,
    sowing_service,
    user_service,
    workflow_service,
)
from app.services.errors import DomainError

# A fixed, deterministic namespace (uuid5 of a fixed string -- never a
# hand-picked "random-looking" literal, and never reused from
# dev_seed_frontend_pilot.py's own PILOT_NAMESPACE, which belongs to an
# unrelated fixture scenario) used to derive every client_command_id this
# module needs, so a byte-identical rerun always produces the same command
# id and therefore hits each service's own idempotent-replay path.
PILOT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "cmp:pilot-setup-001a:bootstrap")

PLACEHOLDER_PREFIX = "REQUIRED_"
PLACEHOLDER_UNKNOWN = "UNKNOWN"

# Operational tables this bootstrap must NEVER write to. Row counts scoped
# to the resolved tenant are captured before and after an APPLY run purely
# as a self-check -- see `operational_integrity_ok` on `BootstrapResult`.
_OPERATIONAL_TABLES = (
    "crop_batches",
    "sowing_events",
    "germination_outcome_snapshots",
    "seedling_entries",
    "transplant_events",
    "harvest_events",
    "grading_events",
    "packing_events",
    "finished_goods_storage_movements",
    "dispatch_events",
    "recall_cases",
)


def _cmd_id(tenant_id: uuid.UUID, *parts: str) -> uuid.UUID:
    return uuid.uuid5(PILOT_NAMESPACE, ":".join([str(tenant_id), *parts]))


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


# =====================================================================
# Configuration schema -- maps directly onto the real domain services
# discovered in the PILOT-SETUP-001 audit. No field exists here for any
# operational transaction (Sowing, Batch, Germination, Transplant,
# Harvest, Grading, Packing, Storage movement, Dispatch, Recall) -- the
# schema itself excludes them, it does not merely decline to use them.
# =====================================================================


class TargetActorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    oidc_issuer: str
    oidc_subject: str


class TargetConfig(BaseModel):
    """The Tenant and administrative actor this bootstrap runs as. Both
    MUST already exist -- Tenant/User/Membership provisioning is
    DEPLOY-001's responsibility, never this module's."""

    model_config = ConfigDict(extra="forbid")
    tenant_code: str
    actor: TargetActorConfig

    @field_validator("tenant_code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class FarmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    country_code: str
    city_region: str | None = None
    timezone: str

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class GreenhousePilotConfig(BaseModel):
    """One Greenhouse plus its full structure. Deliberately has no `vines`
    field at all -- Vines is out of scope for this pilot, and the schema
    excludes it rather than merely declining to populate it. `nursery`/
    `leafy` reuse the exact Pydantic shapes `farm_setup_service` already
    validates hierarchy/capacity against (`NurserySetupConfig`/
    `LeafySetupConfig`) -- no parallel validation logic exists here."""

    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    classification: str
    nursery: NurserySetupConfig | None = None
    leafy: LeafySetupConfig | None = None

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("classification")
    @classmethod
    def _v_classification(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("nursery", "leafy_greens"):
            raise ValueError(
                "classification must be one of: nursery, leafy_greens "
                "(vines is out of scope for this pilot and is not an accepted value here)"
            )
        return v

    @model_validator(mode="after")
    def _v_matching_structure(self) -> "GreenhousePilotConfig":
        # Re-validates via the real GreenhouseSetupCreate shape so every
        # rule that schema already enforces (exactly-one-matching-structure,
        # every span has tables, etc.) applies identically here.
        GreenhouseSetupCreate(
            code=self.code, name=self.name, classification=self.classification,
            client_command_id=uuid.uuid4(), nursery=self.nursery, leafy=self.leafy, vines=None,
        )
        return self


class ColdStorePositionsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code_prefix: str
    start: int = Field(ge=1)
    end: int
    pad_width: int = Field(ge=1)
    capacity: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _v_range(self) -> "ColdStorePositionsConfig":
        if self.end < self.start:
            raise ValueError("cold_store.positions.end must be >= start")
        return self


class ColdStoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    positions: ColdStorePositionsConfig

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class PackingHallConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class LocationsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    packing_hall: PackingHallConfig | None = None
    cold_store: ColdStoreConfig | None = None


_PILOT_CARRIER_TYPE_CODES = ("seed_tray", "nursery_cultivation_plate", "production_cultivation_plate")


class CarrierSpecificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str  # local reference key, used by `carriers[].specification_key` below
    carrier_type_code: str
    code: str
    name: str
    length_mm: int = Field(gt=0)
    width_mm: int = Field(gt=0)
    height_mm: int | None = Field(default=None, gt=0)
    biological_position_count: int = Field(gt=0)

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("carrier_type_code")
    @classmethod
    def _v_type(cls, v: str) -> str:
        if v not in _PILOT_CARRIER_TYPE_CODES:
            raise ValueError(
                f"carrier_type_code must be one of {_PILOT_CARRIER_TYPE_CODES} "
                "(the legacy generic 'cultivation_plate' type is not accepted here)"
            )
        return v


class CarrierBatchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    specification_key: str
    code_prefix: str
    start: int = Field(ge=1)
    end: int
    pad_width: int = Field(ge=1)

    @model_validator(mode="after")
    def _v_range(self) -> "CarrierBatchConfig":
        if self.end < self.start:
            raise ValueError("carriers[].end must be >= start")
        return self


class CropConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    common_name: str
    scientific_name: str | None = None
    # "leafy_green" is a frozen, obvious classification for Iceberg lettuce
    # -- not a farm judgement call -- so it defaults rather than demanding
    # a placeholder, but remains overridable.
    crop_category: str = "leafy_green"

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class VarietyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    supplier_reference: str | None = None

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class ProductionSystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    description: str | None = None

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class WorkflowStageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    display_order: int
    stage_category: str
    expected_duration_minutes: int | None = Field(default=None, gt=0)
    permitted_location_type_code: str | None = None
    required_carrier_type_code: str | None = None
    is_start: bool = False
    is_terminal: bool = False

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class WorkflowTransitionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    from_stage_code: str
    to_stage_code: str

    @field_validator("code", "from_stage_code", "to_stage_code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class WorkflowConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    stages: list[WorkflowStageConfig] = Field(min_length=1)
    transitions: list[WorkflowTransitionConfig] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)

    @model_validator(mode="after")
    def _v_unique_stage_codes(self) -> "WorkflowConfig":
        codes = [s.code for s in self.stages]
        if len(codes) != len(set(codes)):
            raise ValueError("workflow.stages contains duplicate stage codes")
        known = set(codes)
        for t in self.transitions:
            if t.from_stage_code not in known or t.to_stage_code not in known:
                raise ValueError(
                    f"workflow transition {t.code!r} references a stage code not present in workflow.stages"
                )
        return self


class GradeDefinitionVersionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec_notes: str | None = None
    activate: bool = True
    # A real commercial effective date -- never defaulted to "today", since
    # that would fabricate a business fact this module has no authority to
    # invent. Required whenever `activate` is true.
    effective_date: date | None = None

    @model_validator(mode="after")
    def _v_effective_date_if_activating(self) -> "GradeDefinitionVersionConfig":
        if self.activate and self.effective_date is None:
            raise ValueError("grade_definitions[].version.effective_date is required when activate is true")
        return self


class GradeDefinitionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    description: str | None = None
    version: GradeDefinitionVersionConfig | None = None

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class PackagingUnitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class PackSpecificationVersionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    packaging_unit_code: str
    grade_definition_code: str | None = None
    nominal_net_weight_kg: Decimal | None = Field(default=None, gt=0)
    whole_units_per_pack: int | None = Field(default=None, gt=0)
    spec_notes: str | None = None
    activate: bool = True
    effective_date: date | None = None

    @model_validator(mode="after")
    def _v_shape(self) -> "PackSpecificationVersionConfig":
        if self.nominal_net_weight_kg is None and self.whole_units_per_pack is None:
            raise ValueError(
                "pack_specifications[].version requires at least one of "
                "nominal_net_weight_kg or whole_units_per_pack"
            )
        if self.activate and self.effective_date is None:
            raise ValueError("pack_specifications[].version.effective_date is required when activate is true")
        return self


class PackSpecificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    name: str
    customer_reference: str | None = None
    version: PackSpecificationVersionConfig | None = None

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class SeedLotConfig(BaseModel):
    """Deliberately optional at the top of `PilotConfig` (the field may be
    entirely absent). Registering a Seed Lot is the ONE genuine operational-
    looking record this bootstrap may create -- it is master starting-
    inventory data, not a transaction (see PILOT_SETUP.md). No default/fake
    values exist anywhere in this model; every identifying field must be a
    real, farm-supplied fact when this section is present at all."""

    model_config = ConfigDict(extra="forbid")
    code: str
    supplier_name: str | None = None
    supplier_lot_reference: str | None = None
    received_date: date | None = None
    expiry_date: date | None = None

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        return _normalize_code(v)


class PilotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: TargetConfig
    farm: FarmConfig
    greenhouses: list[GreenhousePilotConfig] = Field(default_factory=list)
    locations: LocationsConfig | None = None
    carrier_specifications: list[CarrierSpecificationConfig] = Field(default_factory=list)
    carriers: list[CarrierBatchConfig] = Field(default_factory=list)
    crop: CropConfig
    variety: VarietyConfig
    production_system: ProductionSystemConfig
    workflow: WorkflowConfig
    grade_definitions: list[GradeDefinitionConfig] = Field(default_factory=list)
    packaging_units: list[PackagingUnitConfig] = Field(default_factory=list)
    pack_specifications: list[PackSpecificationConfig] = Field(default_factory=list)
    seed_lot: SeedLotConfig | None = None

    @model_validator(mode="after")
    def _v_no_duplicate_codes_within_lists(self) -> "PilotConfig":
        def _dupes(label: str, codes: list[str]) -> None:
            seen: set[str] = set()
            for c in codes:
                if c in seen:
                    raise ValueError(f"duplicate code {c!r} within {label}")
                seen.add(c)

        _dupes("greenhouses", [g.code for g in self.greenhouses])
        _dupes("carrier_specifications", [c.code for c in self.carrier_specifications])
        _dupes("carrier_specifications keys", [c.key for c in self.carrier_specifications])
        _dupes("grade_definitions", [g.code for g in self.grade_definitions])
        _dupes("packaging_units", [p.code for p in self.packaging_units])
        _dupes("pack_specifications", [p.code for p in self.pack_specifications])

        spec_keys = {c.key for c in self.carrier_specifications}
        for batch in self.carriers:
            if batch.specification_key not in spec_keys:
                raise ValueError(
                    f"carriers[] references specification_key {batch.specification_key!r} "
                    "not present in carrier_specifications[]"
                )
        pu_codes = {p.code for p in self.packaging_units}
        gd_codes = {g.code for g in self.grade_definitions}
        for spec in self.pack_specifications:
            if spec.version is not None:
                if spec.version.packaging_unit_code not in pu_codes:
                    raise ValueError(
                        f"pack_specifications[{spec.code}].version references packaging_unit_code "
                        f"{spec.version.packaging_unit_code!r} not present in packaging_units[]"
                    )
                if spec.version.grade_definition_code is not None and spec.version.grade_definition_code not in gd_codes:
                    raise ValueError(
                        f"pack_specifications[{spec.code}].version references grade_definition_code "
                        f"{spec.version.grade_definition_code!r} not present in grade_definitions[]"
                    )
        return self


def find_placeholders(config: PilotConfig) -> list[str]:
    """Walks the parsed config for any string value that is still a
    template placeholder (`REQUIRED_...` or exactly `UNKNOWN`). Returns
    dotted paths, e.g. `farm.code`. Never raises -- callers decide what to
    do with a non-empty result (APPLY refuses to start; DRY RUN reports it
    as informational)."""
    found: list[str] = []

    def walk(node, path: str) -> None:
        if isinstance(node, BaseModel):
            for name in type(node).model_fields:
                walk(getattr(node, name), f"{path}.{name}" if path else name)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")
        elif isinstance(node, str):
            if node == PLACEHOLDER_UNKNOWN or node.startswith(PLACEHOLDER_PREFIX):
                found.append(path)

    walk(config, "")
    return found


# =====================================================================
# Results
# =====================================================================


@dataclass
class StepResult:
    kind: str
    code: str
    status: str  # CREATED | EXISTING | CONFLICT | BLOCKED
    detail: str = ""
    entity_id: uuid.UUID | None = None


@dataclass
class BootstrapResult:
    dry_run: bool
    tenant_id: uuid.UUID | None = None
    farm_id: uuid.UUID | None = None
    steps: list[StepResult] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)
    operational_table_counts_before: dict[str, int] = field(default_factory=dict)
    operational_table_counts_after: dict[str, int] = field(default_factory=dict)
    aborted: bool = False
    abort_reason: str | None = None

    @property
    def has_conflicts(self) -> bool:
        return any(s.status == "CONFLICT" for s in self.steps)

    @property
    def has_blocked(self) -> bool:
        return any(s.status == "BLOCKED" for s in self.steps)

    @property
    def operational_integrity_ok(self) -> bool:
        if not self.operational_table_counts_after:
            return True
        return self.operational_table_counts_before == self.operational_table_counts_after


class PilotBootstrapAbortedError(Exception):
    """Raised by `run_bootstrap` in APPLY mode as soon as any step reports
    CONFLICT/BLOCKED -- the caller rolls back the whole outer transaction in
    response, so an aborted APPLY leaves the database exactly as it found
    it. Carries the partial `BootstrapResult` for reporting."""

    def __init__(self, result: BootstrapResult):
        self.result = result
        failed = next(s for s in result.steps if s.status in ("CONFLICT", "BLOCKED"))
        super().__init__(f"{failed.status} on {failed.kind} {failed.code!r}: {failed.detail}")


class PilotTargetNotResolvedError(Exception):
    """Tenant/User/Membership provisioning is DEPLOY-001's responsibility.
    This is raised, never silently worked around, whenever the configured
    target cannot be resolved against already-existing rows."""


class PilotConfigPlaceholderError(Exception):
    """Raised by `run_bootstrap(dry_run=False)` when the config still
    contains an unresolved `REQUIRED_*`/`UNKNOWN` placeholder. The CLI
    (`scripts/bootstrap_pilot_master_data.py`) also checks this before ever
    opening a database connection, purely to fail faster -- this is the
    authoritative check, so calling `run_bootstrap` directly (e.g. from a
    test) is never able to bypass it."""

    def __init__(self, placeholders: list[str]):
        self.placeholders = placeholders
        super().__init__(
            f"{len(placeholders)} unresolved template placeholder(s), refusing to apply: {', '.join(placeholders)}"
        )


# =====================================================================
# Target resolution (Tenant/User/Membership must already exist)
# =====================================================================


def resolve_target(db: Session, *, target: TargetConfig) -> tuple[Tenant, uuid.UUID]:
    tenant = db.execute(
        select(Tenant).where(func.lower(Tenant.code) == target.tenant_code.lower())
    ).scalar_one_or_none()
    if tenant is None:
        raise PilotTargetNotResolvedError(
            f"tenant {target.tenant_code!r} does not exist. Tenant provisioning is a DEPLOY-001 "
            "prerequisite -- this bootstrap never creates a Tenant. Provision it first, then rerun."
        )
    if tenant.status != "active":
        raise PilotTargetNotResolvedError(f"tenant {target.tenant_code!r} exists but is not active.")

    user = user_service.get_user_by_issuer_subject(
        db, oidc_issuer=target.actor.oidc_issuer, oidc_subject=target.actor.oidc_subject
    )
    if user is None:
        raise PilotTargetNotResolvedError(
            f"no User exists for oidc_issuer={target.actor.oidc_issuer!r} "
            f"oidc_subject={target.actor.oidc_subject!r}. User provisioning is a DEPLOY-001 prerequisite "
            "-- this bootstrap never creates a User. Provision the administrative user first, then rerun."
        )
    if user.status != "active":
        raise PilotTargetNotResolvedError("resolved actor User exists but is not active.")

    membership = membership_service.get_active_membership(db, tenant_id=tenant.id, user_id=user.id)
    if membership is None:
        raise PilotTargetNotResolvedError(
            "resolved actor User has no active Membership on the resolved Tenant. Membership "
            "provisioning is a DEPLOY-001 prerequisite -- this bootstrap never creates one. "
            "Provision it first, then rerun."
        )
    return tenant, user.id


# =====================================================================
# Master-data steps. Each `ensure_*` returns a StepResult and never
# raises for an expected domain conflict (DomainError subtypes are caught
# and converted to a CONFLICT/BLOCKED StepResult) -- only a genuinely
# unexpected error propagates.
# =====================================================================


def ensure_farm(db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, cfg: FarmConfig) -> StepResult:
    existing = db.execute(
        select(Farm).where(Farm.tenant_id == tenant_id, func.lower(Farm.code) == cfg.code.lower())
    ).scalar_one_or_none()
    if existing is not None:
        mismatch = [
            f
            for f, ok in (
                ("name", existing.name == cfg.name),
                ("country_code", existing.country_code == cfg.country_code),
                ("city_region", existing.city_region == cfg.city_region),
                ("timezone", existing.timezone == cfg.timezone),
            )
            if not ok
        ]
        if mismatch:
            return StepResult(
                "farm", cfg.code, "CONFLICT",
                f"existing Farm {cfg.code!r} differs on: {', '.join(mismatch)} -- refusing to overwrite",
                existing.id,
            )
        return StepResult("farm", cfg.code, "EXISTING", "already matches requested config", existing.id)
    try:
        farm = farm_service.create_farm(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, code=cfg.code, name=cfg.name,
            country_code=cfg.country_code, city_region=cfg.city_region, timezone=cfg.timezone,
        )
    except DomainError as exc:
        return StepResult("farm", cfg.code, "CONFLICT", str(exc))
    return StepResult("farm", cfg.code, "CREATED", "", farm.id)


def ensure_greenhouse(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID | None, actor_user_id: uuid.UUID,
    cfg: GreenhousePilotConfig,
) -> StepResult:
    if farm_id is None:
        return StepResult("greenhouse", cfg.code, "BLOCKED", "farm was not resolved")
    payload = GreenhouseSetupCreate(
        code=cfg.code, name=cfg.name, classification=cfg.classification,
        client_command_id=_cmd_id(tenant_id, "greenhouse", cfg.code),
        nursery=cfg.nursery, leafy=cfg.leafy, vines=None,
    )
    before = db.execute(
        select(func.count()).select_from(Location).where(
            Location.tenant_id == tenant_id, Location.farm_id == farm_id, func.lower(Location.code) == cfg.code.lower(),
        )
    ).scalar_one()
    try:
        result = farm_setup_service.create_greenhouse_setup(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, payload=payload,
        )
    except DomainError as exc:
        return StepResult("greenhouse", cfg.code, "CONFLICT", str(exc))
    status = "EXISTING" if before > 0 else "CREATED"
    return StepResult("greenhouse", cfg.code, status, f"counts={result.counts.model_dump()}", result.greenhouse_id)


def _get_or_create_location(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID,
    code: str, name: str, location_type_code: str, parent_id: uuid.UUID | None,
    greenhouse_classification: str | None = None,
) -> tuple[uuid.UUID, bool]:
    """Returns (location_id, was_created). Looks up by (parent, code) --
    never guesses; a code collision under the same parent with the wrong
    location_type is reported by the caller via the DomainError path."""
    query = select(Location).where(
        Location.tenant_id == tenant_id, Location.farm_id == farm_id, func.lower(Location.code) == code.lower(),
    )
    query = query.where(Location.parent_location_id == parent_id) if parent_id is not None else query.where(
        Location.parent_location_id.is_(None)
    )
    existing = db.execute(query).scalar_one_or_none()
    if existing is not None:
        return existing.id, False
    loc = location_service.create_location(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
        location_type_code=location_type_code, code=code, name=name, parent_location_id=parent_id,
        greenhouse_classification=greenhouse_classification, occupiable=None,
    )
    return loc.id, True


def ensure_locations(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID | None, actor_user_id: uuid.UUID,
    cfg: LocationsConfig | None,
) -> list[StepResult]:
    if cfg is None:
        return []
    if farm_id is None:
        results = []
        if cfg.packing_hall is not None:
            results.append(StepResult("location:packing_hall", cfg.packing_hall.code, "BLOCKED", "farm was not resolved"))
        if cfg.cold_store is not None:
            results.append(StepResult("location:cold_store", cfg.cold_store.code, "BLOCKED", "farm was not resolved"))
        return results

    results: list[StepResult] = []
    if cfg.packing_hall is not None:
        try:
            _loc_id, created = _get_or_create_location(
                db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
                code=cfg.packing_hall.code, name=cfg.packing_hall.name,
                location_type_code="packing_hall", parent_id=None,
            )
        except DomainError as exc:
            results.append(StepResult("location:packing_hall", cfg.packing_hall.code, "CONFLICT", str(exc)))
        else:
            results.append(
                StepResult("location:packing_hall", cfg.packing_hall.code, "CREATED" if created else "EXISTING", "", _loc_id)
            )

    if cfg.cold_store is not None:
        try:
            store_id, store_created = _get_or_create_location(
                db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
                code=cfg.cold_store.code, name=cfg.cold_store.name,
                location_type_code="cold_store", parent_id=None,
            )
        except DomainError as exc:
            results.append(StepResult("location:cold_store", cfg.cold_store.code, "CONFLICT", str(exc)))
            return results
        results.append(
            StepResult("location:cold_store", cfg.cold_store.code, "CREATED" if store_created else "EXISTING", "", store_id)
        )

        p = cfg.cold_store.positions
        codes = [f"{p.code_prefix}{str(n).zfill(p.pad_width)}" for n in range(p.start, p.end + 1)]
        existing_codes = set(
            db.execute(
                select(Location.code).where(
                    Location.parent_location_id == store_id, func.lower(Location.code).in_([c.lower() for c in codes]),
                )
            ).scalars()
        )
        if len(existing_codes) == len(codes):
            results.append(
                StepResult("location:cold_store_positions", cfg.cold_store.code, "EXISTING", f"{len(codes)} positions already present")
            )
        elif existing_codes:
            results.append(
                StepResult(
                    "location:cold_store_positions", cfg.cold_store.code, "CONFLICT",
                    f"{len(existing_codes)} of {len(codes)} positions already exist -- refusing to guess how to complete the set",
                )
            )
        else:
            try:
                created_positions = location_service.bulk_generate_children(
                    db, tenant_id=tenant_id, farm_id=farm_id, parent_id=store_id, actor_user_id=actor_user_id,
                    location_type_code="cold_store_position", code_prefix=p.code_prefix, start=p.start, end=p.end,
                    pad_width=p.pad_width, name_template=None, capacity=p.capacity,
                )
            except DomainError as exc:
                results.append(StepResult("location:cold_store_positions", cfg.cold_store.code, "CONFLICT", str(exc)))
            else:
                results.append(
                    StepResult(
                        "location:cold_store_positions", cfg.cold_store.code, "CREATED",
                        f"{len(created_positions)} positions created",
                    )
                )
    return results


def ensure_carrier_specification(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, cfg: CarrierSpecificationConfig,
) -> StepResult:
    existing = db.execute(
        select(CarrierSpecification).where(
            CarrierSpecification.tenant_id == tenant_id, func.lower(CarrierSpecification.code) == cfg.code.lower(),
        )
    ).scalar_one_or_none()
    if existing is not None:
        mismatch = [
            f
            for f, ok in (
                ("length_mm", existing.length_mm == cfg.length_mm),
                ("width_mm", existing.width_mm == cfg.width_mm),
                ("height_mm", existing.height_mm == cfg.height_mm),
                ("biological_position_count", existing.biological_position_count == cfg.biological_position_count),
            )
            if not ok
        ]
        if mismatch:
            return StepResult(
                "carrier_specification", cfg.code, "CONFLICT",
                f"existing spec {cfg.code!r} differs on: {', '.join(mismatch)} -- refusing to overwrite (specs are structurally frozen once referenced)",
                existing.id,
            )
        return StepResult("carrier_specification", cfg.code, "EXISTING", "already matches requested config", existing.id)
    try:
        spec = carrier_specification_service.register_carrier_specification(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, carrier_type_code=cfg.carrier_type_code,
            code=cfg.code, name=cfg.name, length_mm=cfg.length_mm, width_mm=cfg.width_mm,
            height_mm=cfg.height_mm, biological_position_count=cfg.biological_position_count,
        )
    except DomainError as exc:
        return StepResult("carrier_specification", cfg.code, "CONFLICT", str(exc))
    return StepResult("carrier_specification", cfg.code, "CREATED", "", spec.id)


def ensure_carrier_batch(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID | None, actor_user_id: uuid.UUID,
    cfg: CarrierBatchConfig, specification_id: uuid.UUID | None,
) -> StepResult:
    if farm_id is None or specification_id is None:
        return StepResult("carriers", cfg.code_prefix, "BLOCKED", "farm or carrier specification was not resolved")
    codes = [f"{cfg.code_prefix}{str(n).zfill(cfg.pad_width)}" for n in range(cfg.start, cfg.end + 1)]
    existing_codes = set(
        db.execute(
            select(Carrier.code).where(
                Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id,
                func.lower(Carrier.code).in_([c.lower() for c in codes]),
            )
        ).scalars()
    )
    if len(existing_codes) == len(codes):
        return StepResult("carriers", cfg.code_prefix, "EXISTING", f"{len(codes)} carriers already registered")
    if existing_codes:
        return StepResult(
            "carriers", cfg.code_prefix, "CONFLICT",
            f"{len(existing_codes)} of {len(codes)} carriers already exist -- refusing to guess how to complete the set",
        )
    try:
        created = carrier_service.bulk_register_carriers(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
            specification_id=specification_id, code_prefix=cfg.code_prefix, start=cfg.start, end=cfg.end,
            pad_width=cfg.pad_width,
        )
    except DomainError as exc:
        return StepResult("carriers", cfg.code_prefix, "CONFLICT", str(exc))
    return StepResult("carriers", cfg.code_prefix, "CREATED", f"{len(created)} carriers registered")


def ensure_crop(db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, cfg: CropConfig) -> StepResult:
    existing = db.execute(
        select(Crop).where(Crop.tenant_id == tenant_id, func.lower(Crop.code) == cfg.code.lower())
    ).scalar_one_or_none()
    if existing is not None:
        mismatch = [
            f
            for f, ok in (
                ("common_name", existing.common_name == cfg.common_name),
                ("scientific_name", existing.scientific_name == cfg.scientific_name),
                ("crop_category", existing.crop_category == cfg.crop_category),
            )
            if not ok
        ]
        if mismatch:
            return StepResult("crop", cfg.code, "CONFLICT", f"existing Crop {cfg.code!r} differs on: {', '.join(mismatch)}", existing.id)
        return StepResult("crop", cfg.code, "EXISTING", "already matches requested config", existing.id)
    try:
        crop = crop_service.register_crop(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, code=cfg.code, common_name=cfg.common_name,
            scientific_name=cfg.scientific_name, crop_category=cfg.crop_category,
        )
    except DomainError as exc:
        return StepResult("crop", cfg.code, "CONFLICT", str(exc))
    return StepResult("crop", cfg.code, "CREATED", "", crop.id)


def ensure_variety(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, crop_id: uuid.UUID | None, cfg: VarietyConfig,
) -> StepResult:
    if crop_id is None:
        return StepResult("variety", cfg.code, "BLOCKED", "crop was not resolved")
    existing = db.execute(
        select(Variety).where(Variety.tenant_id == tenant_id, Variety.crop_id == crop_id, func.lower(Variety.code) == cfg.code.lower())
    ).scalar_one_or_none()
    if existing is not None:
        mismatch = [
            f for f, ok in (
                ("name", existing.name == cfg.name),
                ("supplier_reference", existing.supplier_reference == cfg.supplier_reference),
            ) if not ok
        ]
        if mismatch:
            return StepResult("variety", cfg.code, "CONFLICT", f"existing Variety {cfg.code!r} differs on: {', '.join(mismatch)}", existing.id)
        return StepResult("variety", cfg.code, "EXISTING", "already matches requested config", existing.id)
    try:
        variety = crop_service.register_variety(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, crop_id=crop_id, code=cfg.code, name=cfg.name,
            supplier_reference=cfg.supplier_reference,
        )
    except DomainError as exc:
        return StepResult("variety", cfg.code, "CONFLICT", str(exc))
    return StepResult("variety", cfg.code, "CREATED", "", variety.id)


def ensure_production_system(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, cfg: ProductionSystemConfig,
) -> StepResult:
    existing = db.execute(
        select(ProductionSystem).where(
            ProductionSystem.tenant_id == tenant_id, func.lower(ProductionSystem.code) == cfg.code.lower(),
        )
    ).scalar_one_or_none()
    if existing is not None:
        mismatch = [
            f for f, ok in (
                ("name", existing.name == cfg.name),
                ("description", existing.description == cfg.description),
            ) if not ok
        ]
        if mismatch:
            return StepResult("production_system", cfg.code, "CONFLICT", f"existing ProductionSystem {cfg.code!r} differs on: {', '.join(mismatch)}", existing.id)
        return StepResult("production_system", cfg.code, "EXISTING", "already matches requested config", existing.id)
    try:
        ps = production_system_service.register_production_system(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, code=cfg.code, name=cfg.name, description=cfg.description,
        )
    except DomainError as exc:
        return StepResult("production_system", cfg.code, "CONFLICT", str(exc))
    return StepResult("production_system", cfg.code, "CREATED", "", ps.id)


def ensure_workflow(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, crop_id: uuid.UUID | None,
    variety_id: uuid.UUID | None, production_system_id: uuid.UUID | None, cfg: WorkflowConfig,
) -> StepResult:
    if crop_id is None or variety_id is None or production_system_id is None:
        return StepResult("workflow", cfg.code, "BLOCKED", "crop, variety, or production_system was not resolved")

    workflow = db.execute(
        select(Workflow).where(Workflow.tenant_id == tenant_id, func.lower(Workflow.code) == cfg.code.lower())
    ).scalar_one_or_none()

    if workflow is not None:
        mismatch = [
            f for f, ok in (
                ("crop_id", workflow.crop_id == crop_id),
                ("variety_id", workflow.variety_id == variety_id),
                ("production_system_id", workflow.production_system_id == production_system_id),
            ) if not ok
        ]
        if mismatch:
            return StepResult("workflow", cfg.code, "CONFLICT", f"existing Workflow {cfg.code!r} differs on: {', '.join(mismatch)}", workflow.id)
    else:
        try:
            workflow = workflow_service.register_workflow(
                db, tenant_id=tenant_id, actor_user_id=actor_user_id, crop_id=crop_id, variety_id=variety_id,
                production_system_id=production_system_id, code=cfg.code, name=cfg.name,
            )
        except DomainError as exc:
            return StepResult("workflow", cfg.code, "CONFLICT", str(exc))

    published = db.execute(
        select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id, WorkflowVersion.state == "published")
    ).scalar_one_or_none()

    if published is not None:
        stages = db.execute(select(WorkflowStage).where(WorkflowStage.workflow_version_id == published.id)).scalars().all()
        transitions = db.execute(
            select(WorkflowTransition).where(WorkflowTransition.workflow_version_id == published.id)
        ).scalars().all()
        stage_by_id = {s.id: s for s in stages}
        actual_stage_shape = {
            (s.code, s.stage_category, s.is_start, s.is_terminal, s.expected_duration_minutes) for s in stages
        }
        expected_stage_shape = {
            (s.code, s.stage_category, s.is_start, s.is_terminal, s.expected_duration_minutes) for s in cfg.stages
        }
        actual_transition_shape = {
            (t.code, stage_by_id[t.from_stage_id].code, stage_by_id[t.to_stage_id].code) for t in transitions
        }
        expected_transition_shape = {(t.code, t.from_stage_code, t.to_stage_code) for t in cfg.transitions}
        if actual_stage_shape != expected_stage_shape or actual_transition_shape != expected_transition_shape:
            return StepResult(
                "workflow", cfg.code, "CONFLICT",
                f"a published WorkflowVersion already exists for {cfg.code!r} with a different stage/transition "
                "shape -- versions are historical facts, this bootstrap never republishes over one",
                published.id,
            )
        return StepResult("workflow", cfg.code, "EXISTING", f"published version {published.version_number} already matches", published.id)

    # No published version yet -- create one, matching dev_seed_frontend_pilot.py's own established
    # sequence (draft -> stages -> transitions -> publish), generalized from config.
    try:
        version = workflow_service.create_draft_version(db, tenant_id=tenant_id, actor_user_id=actor_user_id, workflow_id=workflow.id)
        stage_ids: dict[str, uuid.UUID] = {}
        for s in cfg.stages:
            stage = workflow_service.add_stage(
                db, tenant_id=tenant_id, actor_user_id=actor_user_id, workflow_id=workflow.id, version_id=version.id,
                code=s.code, name=s.name, display_order=s.display_order, stage_category=s.stage_category,
                expected_duration_minutes=s.expected_duration_minutes,
                permitted_location_type_code=s.permitted_location_type_code,
                required_carrier_type_code=s.required_carrier_type_code, is_start=s.is_start, is_terminal=s.is_terminal,
            )
            stage_ids[s.code] = stage.id
        for t in cfg.transitions:
            workflow_service.add_transition(
                db, tenant_id=tenant_id, actor_user_id=actor_user_id, workflow_id=workflow.id, version_id=version.id,
                from_stage_id=stage_ids[t.from_stage_code], to_stage_id=stage_ids[t.to_stage_code], code=t.code, name=t.name,
            )
        published_version = workflow_service.publish_version(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, workflow_id=workflow.id, version_id=version.id,
        )
    except DomainError as exc:
        return StepResult("workflow", cfg.code, "CONFLICT", str(exc), workflow.id)
    return StepResult("workflow", cfg.code, "CREATED", f"version {published_version.version_number} published", published_version.id)


def ensure_grade_definition(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, crop_id: uuid.UUID | None,
    variety_id: uuid.UUID | None, cfg: GradeDefinitionConfig,
) -> tuple[StepResult, uuid.UUID | None]:
    """Returns (definition step, id of the resulting active/draft Version if
    `cfg.version` was configured, else None) -- the version id is needed by
    `ensure_pack_specification` when a pack spec links a grade version."""
    if crop_id is None:
        return StepResult("grade_definition", cfg.code, "BLOCKED", "crop was not resolved"), None

    command_id = _cmd_id(tenant_id, "grade_definition", cfg.code)
    pre_existing = db.execute(
        select(GradeDefinition).where(GradeDefinition.tenant_id == tenant_id, GradeDefinition.client_command_id == command_id)
    ).scalar_one_or_none()
    try:
        definition = grade_definition_service.register_grade_definition(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=command_id, code=cfg.code,
            name=cfg.name, crop_id=crop_id, variety_id=variety_id, description=cfg.description,
        )
    except DomainError as exc:
        return StepResult("grade_definition", cfg.code, "CONFLICT", str(exc)), None
    definition_step = StepResult(
        "grade_definition", cfg.code, "EXISTING" if pre_existing is not None else "CREATED", "", definition.id
    )

    if cfg.version is None:
        return definition_step, None

    version_command_id = _cmd_id(tenant_id, "grade_definition_version", cfg.code)
    try:
        version = grade_definition_service.create_draft_version(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=version_command_id,
            grade_definition_id=definition.id, spec_notes=cfg.version.spec_notes,
        )
    except DomainError as exc:
        return StepResult("grade_definition_version", cfg.code, "CONFLICT", str(exc)), None

    if not cfg.version.activate:
        return definition_step, version.id

    if version.status == "active":
        return definition_step, version.id

    activation_command_id = _cmd_id(tenant_id, "grade_definition_version_activate", cfg.code)
    effective_time = datetime.combine(cfg.version.effective_date, time.min, tzinfo=timezone.utc)
    try:
        activated = grade_definition_service.activate_version(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=activation_command_id,
            grade_definition_id=definition.id, version_id=version.id, effective_time=effective_time,
        )
    except DomainError as exc:
        return StepResult("grade_definition_version", cfg.code, "CONFLICT", str(exc)), version.id
    return definition_step, activated.id


def ensure_packaging_unit(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, cfg: PackagingUnitConfig,
) -> StepResult:
    command_id = _cmd_id(tenant_id, "packaging_unit", cfg.code)
    pre_existing = db.execute(
        select(PackagingUnit).where(PackagingUnit.tenant_id == tenant_id, PackagingUnit.client_command_id == command_id)
    ).scalar_one_or_none()
    try:
        unit = packaging_unit_service.register_packaging_unit(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=command_id, code=cfg.code, name=cfg.name,
        )
    except DomainError as exc:
        return StepResult("packaging_unit", cfg.code, "CONFLICT", str(exc))
    return StepResult("packaging_unit", cfg.code, "EXISTING" if pre_existing is not None else "CREATED", "", unit.id)


def ensure_pack_specification(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, crop_id: uuid.UUID | None,
    variety_id: uuid.UUID | None, cfg: PackSpecificationConfig,
    packaging_unit_ids: dict[str, uuid.UUID], grade_definition_version_ids: dict[str, uuid.UUID],
) -> StepResult:
    if crop_id is None:
        return StepResult("pack_specification", cfg.code, "BLOCKED", "crop was not resolved")

    command_id = _cmd_id(tenant_id, "pack_specification", cfg.code)
    pre_existing = db.execute(
        select(PackSpecification).where(PackSpecification.tenant_id == tenant_id, PackSpecification.client_command_id == command_id)
    ).scalar_one_or_none()
    try:
        spec = pack_specification_service.register_pack_specification(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=command_id, code=cfg.code,
            name=cfg.name, crop_id=crop_id, variety_id=variety_id, customer_reference=cfg.customer_reference,
        )
    except DomainError as exc:
        return StepResult("pack_specification", cfg.code, "CONFLICT", str(exc))
    step = StepResult("pack_specification", cfg.code, "EXISTING" if pre_existing is not None else "CREATED", "", spec.id)

    if cfg.version is None:
        return step

    packaging_unit_id = packaging_unit_ids.get(cfg.version.packaging_unit_code)
    if packaging_unit_id is None:
        return StepResult("pack_specification_version", cfg.code, "BLOCKED", "referenced packaging_unit was not resolved")
    grade_version_id = None
    if cfg.version.grade_definition_code is not None:
        grade_version_id = grade_definition_version_ids.get(cfg.version.grade_definition_code)
        if grade_version_id is None:
            return StepResult("pack_specification_version", cfg.code, "BLOCKED", "referenced grade_definition version was not resolved")

    version_command_id = _cmd_id(tenant_id, "pack_specification_version", cfg.code)
    try:
        version = pack_specification_service.create_draft_version(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=version_command_id,
            pack_specification_id=spec.id, grade_definition_version_id=grade_version_id,
            packaging_unit_id=packaging_unit_id, nominal_net_weight_kg=cfg.version.nominal_net_weight_kg,
            whole_units_per_pack=cfg.version.whole_units_per_pack, spec_notes=cfg.version.spec_notes,
        )
    except DomainError as exc:
        return StepResult("pack_specification_version", cfg.code, "CONFLICT", str(exc))

    if not cfg.version.activate or version.status == "active":
        return step

    activation_command_id = _cmd_id(tenant_id, "pack_specification_version_activate", cfg.code)
    effective_time = datetime.combine(cfg.version.effective_date, time.min, tzinfo=timezone.utc)
    try:
        pack_specification_service.activate_version(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=activation_command_id,
            pack_specification_id=spec.id, version_id=version.id, effective_time=effective_time,
        )
    except DomainError as exc:
        return StepResult("pack_specification_version", cfg.code, "CONFLICT", str(exc))
    return step


def ensure_seed_lot(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID | None, actor_user_id: uuid.UUID,
    crop_id: uuid.UUID | None, variety_id: uuid.UUID | None, cfg: SeedLotConfig | None,
) -> StepResult | None:
    if cfg is None:
        # Explicitly not an error -- "Seed Lot required before first Sowing,
        # but not necessarily before bootstrap framework validation."
        return None
    if farm_id is None or crop_id is None or variety_id is None:
        return StepResult("seed_lot", cfg.code, "BLOCKED", "farm, crop, or variety was not resolved")
    existing = db.execute(
        select(SeedLot).where(SeedLot.tenant_id == tenant_id, func.lower(SeedLot.code) == cfg.code.lower())
    ).scalar_one_or_none()
    if existing is not None:
        mismatch = [
            f for f, ok in (
                ("crop_id", existing.crop_id == crop_id),
                ("variety_id", existing.variety_id == variety_id),
                ("supplier_name", existing.supplier_name == cfg.supplier_name),
                ("supplier_lot_reference", existing.supplier_lot_reference == cfg.supplier_lot_reference),
                ("received_date", existing.received_date == cfg.received_date),
                ("expiry_date", existing.expiry_date == cfg.expiry_date),
            ) if not ok
        ]
        if mismatch:
            return StepResult("seed_lot", cfg.code, "CONFLICT", f"existing SeedLot {cfg.code!r} differs on: {', '.join(mismatch)}", existing.id)
        return StepResult("seed_lot", cfg.code, "EXISTING", "already matches requested config", existing.id)
    try:
        lot = sowing_service.register_seed_lot(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, crop_id=crop_id,
            variety_id=variety_id, code=cfg.code, supplier_name=cfg.supplier_name,
            supplier_lot_reference=cfg.supplier_lot_reference, received_date=cfg.received_date,
            expiry_date=cfg.expiry_date,
        )
    except DomainError as exc:
        return StepResult("seed_lot", cfg.code, "CONFLICT", str(exc))
    return StepResult("seed_lot", cfg.code, "CREATED", "", lot.id)


def _operational_table_counts(db: Session, *, tenant_id: uuid.UUID) -> dict[str, int]:
    from sqlalchemy import text

    counts: dict[str, int] = {}
    for table in _OPERATIONAL_TABLES:
        counts[table] = db.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id}  # noqa: S608 -- table name from a fixed internal tuple, never user input
        ).scalar_one()
    return counts


# =====================================================================
# Orchestration
# =====================================================================


def run_bootstrap(db: Session, *, config: PilotConfig, dry_run: bool) -> BootstrapResult:
    """Runs the full ordered sequence of master-data steps. In BOTH modes
    every step is actually attempted (dry-run's safety comes entirely from
    the caller never committing the outer transaction -- see this module's
    docstring) -- so a dry run genuinely validates what an apply would do,
    not an approximation of it.

    In APPLY mode (`dry_run=False`), raises `PilotBootstrapAbortedError` as
    soon as any step reports CONFLICT/BLOCKED, so the caller can roll back
    immediately and nothing partial is left pending. In DRY RUN mode every
    step is attempted regardless, so the full picture is reported in one
    pass."""
    result = BootstrapResult(dry_run=dry_run, placeholders=find_placeholders(config))
    if not dry_run and result.placeholders:
        raise PilotConfigPlaceholderError(result.placeholders)

    tenant, actor_user_id = resolve_target(db, target=config.target)
    result.tenant_id = tenant.id

    def record(step: StepResult) -> StepResult:
        result.steps.append(step)
        if not dry_run and step.status in ("CONFLICT", "BLOCKED"):
            raise PilotBootstrapAbortedError(result)
        return step

    result.operational_table_counts_before = _operational_table_counts(db, tenant_id=tenant.id)

    farm_step = record(ensure_farm(db, tenant_id=tenant.id, actor_user_id=actor_user_id, cfg=config.farm))
    farm_id = farm_step.entity_id if farm_step.status in ("CREATED", "EXISTING") else None
    result.farm_id = farm_id

    for gh_cfg in config.greenhouses:
        record(ensure_greenhouse(db, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=actor_user_id, cfg=gh_cfg))

    for step in ensure_locations(db, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=actor_user_id, cfg=config.locations):
        record(step)

    specification_ids: dict[str, uuid.UUID] = {}
    for spec_cfg in config.carrier_specifications:
        step = record(ensure_carrier_specification(db, tenant_id=tenant.id, actor_user_id=actor_user_id, cfg=spec_cfg))
        if step.entity_id is not None:
            specification_ids[spec_cfg.key] = step.entity_id

    for batch_cfg in config.carriers:
        record(
            ensure_carrier_batch(
                db, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=actor_user_id, cfg=batch_cfg,
                specification_id=specification_ids.get(batch_cfg.specification_key),
            )
        )

    crop_step = record(ensure_crop(db, tenant_id=tenant.id, actor_user_id=actor_user_id, cfg=config.crop))
    crop_id = crop_step.entity_id if crop_step.status in ("CREATED", "EXISTING") else None

    variety_step = record(ensure_variety(db, tenant_id=tenant.id, actor_user_id=actor_user_id, crop_id=crop_id, cfg=config.variety))
    variety_id = variety_step.entity_id if variety_step.status in ("CREATED", "EXISTING") else None

    ps_step = record(ensure_production_system(db, tenant_id=tenant.id, actor_user_id=actor_user_id, cfg=config.production_system))
    production_system_id = ps_step.entity_id if ps_step.status in ("CREATED", "EXISTING") else None

    record(
        ensure_workflow(
            db, tenant_id=tenant.id, actor_user_id=actor_user_id, crop_id=crop_id, variety_id=variety_id,
            production_system_id=production_system_id, cfg=config.workflow,
        )
    )

    grade_definition_version_ids: dict[str, uuid.UUID] = {}
    for gd_cfg in config.grade_definitions:
        gd_step, version_id = ensure_grade_definition(
            db, tenant_id=tenant.id, actor_user_id=actor_user_id, crop_id=crop_id, variety_id=variety_id, cfg=gd_cfg,
        )
        record(gd_step)
        if version_id is not None:
            grade_definition_version_ids[gd_cfg.code] = version_id

    packaging_unit_ids: dict[str, uuid.UUID] = {}
    for pu_cfg in config.packaging_units:
        step = record(ensure_packaging_unit(db, tenant_id=tenant.id, actor_user_id=actor_user_id, cfg=pu_cfg))
        if step.entity_id is not None:
            packaging_unit_ids[pu_cfg.code] = step.entity_id

    for ps_cfg in config.pack_specifications:
        record(
            ensure_pack_specification(
                db, tenant_id=tenant.id, actor_user_id=actor_user_id, crop_id=crop_id, variety_id=variety_id,
                cfg=ps_cfg, packaging_unit_ids=packaging_unit_ids, grade_definition_version_ids=grade_definition_version_ids,
            )
        )

    seed_lot_step = ensure_seed_lot(
        db, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=actor_user_id, crop_id=crop_id,
        variety_id=variety_id, cfg=config.seed_lot,
    )
    if seed_lot_step is not None:
        record(seed_lot_step)

    result.operational_table_counts_after = _operational_table_counts(db, tenant_id=tenant.id)
    return result


# =====================================================================
# Readiness check -- pure reads, never writes, safe to run at any time
# (including long after real UAT operations have created legitimate
# operational history). Answers: "does the environment described by this
# config have everything the FIRST real Sowing needs?"
# =====================================================================


@dataclass
class ReadinessItem:
    name: str
    status: str  # PASS | MISSING | CONFLICT | OPTIONAL_NOT_YET_REQUIRED
    detail: str = ""
    # True only for the expected, non-blocking-to-report "no seed_lot
    # configured yet" case -- callers (e.g. the CLI's exit code) should
    # treat this item as informational, never as a readiness failure on its
    # own, even though it correctly still says the real lot is MISSING.
    informational: bool = False


def run_readiness_check(db: Session, *, config: PilotConfig) -> list[ReadinessItem]:
    items: list[ReadinessItem] = []

    try:
        tenant, _actor_id = resolve_target(db, target=config.target)
    except PilotTargetNotResolvedError as exc:
        items.append(ReadinessItem("target tenant/user/membership", "MISSING", str(exc)))
        return items
    items.append(ReadinessItem("target tenant/user/membership", "PASS"))

    farm = db.execute(
        select(Farm).where(Farm.tenant_id == tenant.id, func.lower(Farm.code) == config.farm.code.lower())
    ).scalar_one_or_none()
    if farm is None or farm.status != "active":
        items.append(ReadinessItem(f"farm {config.farm.code}", "MISSING"))
        return items
    items.append(ReadinessItem(f"farm {config.farm.code}", "PASS"))

    for gh in config.greenhouses:
        loc = db.execute(
            select(Location).where(
                Location.tenant_id == tenant.id, Location.farm_id == farm.id, Location.parent_location_id.is_(None),
                func.lower(Location.code) == gh.code.lower(),
            )
        ).scalar_one_or_none()
        if loc is None:
            items.append(ReadinessItem(f"greenhouse {gh.code}", "MISSING"))
        elif loc.greenhouse_classification != gh.classification:
            items.append(ReadinessItem(f"greenhouse {gh.code}", "CONFLICT", f"existing classification={loc.greenhouse_classification!r}"))
        else:
            items.append(ReadinessItem(f"greenhouse {gh.code}", "PASS"))

    if config.locations is not None:
        if config.locations.packing_hall is not None:
            code = config.locations.packing_hall.code
            found = db.execute(
                select(Location.id).where(
                    Location.tenant_id == tenant.id, Location.farm_id == farm.id, func.lower(Location.code) == code.lower(),
                )
            ).scalar_one_or_none()
            items.append(ReadinessItem(f"packing hall {code}", "PASS" if found else "MISSING"))
        if config.locations.cold_store is not None:
            code = config.locations.cold_store.code
            found = db.execute(
                select(Location.id).where(
                    Location.tenant_id == tenant.id, Location.farm_id == farm.id, func.lower(Location.code) == code.lower(),
                )
            ).scalar_one_or_none()
            items.append(ReadinessItem(f"cold store {code}", "PASS" if found else "MISSING"))

    for spec in config.carrier_specifications:
        found = db.execute(
            select(CarrierSpecification.id).where(
                CarrierSpecification.tenant_id == tenant.id, func.lower(CarrierSpecification.code) == spec.code.lower(),
            )
        ).scalar_one_or_none()
        items.append(ReadinessItem(f"carrier specification {spec.code}", "PASS" if found else "MISSING"))

    for batch in config.carriers:
        codes = [f"{batch.code_prefix}{str(n).zfill(batch.pad_width)}" for n in range(batch.start, batch.end + 1)]
        count = db.execute(
            select(func.count()).select_from(Carrier).where(
                Carrier.tenant_id == tenant.id, Carrier.farm_id == farm.id, func.lower(Carrier.code).in_([c.lower() for c in codes]),
            )
        ).scalar_one()
        if count == len(codes):
            items.append(ReadinessItem(f"carriers {batch.code_prefix}*", "PASS", f"{count}/{len(codes)}"))
        elif count == 0:
            items.append(ReadinessItem(f"carriers {batch.code_prefix}*", "MISSING", f"0/{len(codes)}"))
        else:
            items.append(ReadinessItem(f"carriers {batch.code_prefix}*", "CONFLICT", f"only {count}/{len(codes)} present"))

    crop = db.execute(
        select(Crop).where(Crop.tenant_id == tenant.id, func.lower(Crop.code) == config.crop.code.lower())
    ).scalar_one_or_none()
    items.append(ReadinessItem(f"crop {config.crop.code}", "PASS" if crop else "MISSING"))

    variety = None
    if crop is not None:
        variety = db.execute(
            select(Variety).where(Variety.tenant_id == tenant.id, Variety.crop_id == crop.id, func.lower(Variety.code) == config.variety.code.lower())
        ).scalar_one_or_none()
    items.append(ReadinessItem(f"variety {config.variety.code}", "PASS" if variety else "MISSING"))

    workflow = db.execute(
        select(Workflow).where(Workflow.tenant_id == tenant.id, func.lower(Workflow.code) == config.workflow.code.lower())
    ).scalar_one_or_none()
    published = None
    if workflow is not None:
        published = db.execute(
            select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id, WorkflowVersion.state == "published")
        ).scalar_one_or_none()
    items.append(
        ReadinessItem(f"workflow {config.workflow.code} (published)", "PASS" if published is not None else "MISSING")
    )

    for gd in config.grade_definitions:
        definition = db.execute(
            select(GradeDefinition).where(GradeDefinition.tenant_id == tenant.id, func.lower(GradeDefinition.code) == gd.code.lower())
        ).scalar_one_or_none()
        if gd.version is None or not gd.version.activate:
            items.append(ReadinessItem(f"grade definition {gd.code}", "PASS" if definition else "MISSING"))
            continue
        active_version = None
        if definition is not None:
            active_version = db.execute(
                select(GradeDefinitionVersion).where(
                    GradeDefinitionVersion.grade_definition_id == definition.id, GradeDefinitionVersion.status == "active",
                )
            ).scalar_one_or_none()
        items.append(ReadinessItem(f"grade definition {gd.code} (active version)", "PASS" if active_version else "MISSING"))

    for pu in config.packaging_units:
        found = db.execute(
            select(PackagingUnit.id).where(PackagingUnit.tenant_id == tenant.id, func.lower(PackagingUnit.code) == pu.code.lower())
        ).scalar_one_or_none()
        items.append(ReadinessItem(f"packaging unit {pu.code}", "PASS" if found else "MISSING"))

    for ps in config.pack_specifications:
        spec = db.execute(
            select(PackSpecification).where(PackSpecification.tenant_id == tenant.id, func.lower(PackSpecification.code) == ps.code.lower())
        ).scalar_one_or_none()
        if ps.version is None or not ps.version.activate:
            items.append(ReadinessItem(f"pack specification {ps.code}", "PASS" if spec else "MISSING"))
            continue
        active_version = None
        if spec is not None:
            active_version = db.execute(
                select(PackSpecificationVersion).where(
                    PackSpecificationVersion.pack_specification_id == spec.id, PackSpecificationVersion.status == "active",
                )
            ).scalar_one_or_none()
        items.append(ReadinessItem(f"pack specification {ps.code} (active version)", "PASS" if active_version else "MISSING"))

    if config.seed_lot is None:
        items.append(
            ReadinessItem(
                "seed lot", "MISSING",
                "BLOCKS FIRST SOWING (no seed_lot configured; this does not block any other master data "
                "and is expected until a real lot arrives)",
                informational=True,
            )
        )
    else:
        found = db.execute(
            select(SeedLot.id).where(SeedLot.tenant_id == tenant.id, func.lower(SeedLot.code) == config.seed_lot.code.lower())
        ).scalar_one_or_none()
        if found is None:
            items.append(ReadinessItem(f"seed lot {config.seed_lot.code}", "MISSING", "MISSING -- BLOCKS FIRST SOWING"))
        else:
            items.append(ReadinessItem(f"seed lot {config.seed_lot.code}", "PASS"))

    return items
