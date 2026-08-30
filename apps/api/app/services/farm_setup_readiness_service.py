"""PILOT-SETUP-001B8: product Setup Checklist / Readiness.

Read-only, persisted-state readiness for one Farm -- deliberately separate
from `pilot_bootstrap_service.run_readiness_check`, which evaluates a
hand-authored YAML `PilotConfig` for the admin bootstrap CLI (config-file
identity strings compared against the database) and is never suitable to
back a product/UI endpoint. This module never reads a config file, never
compares against `REQUIRED_*` placeholders, and never depends on the
bootstrap script -- every check queries actual Tenant/Farm rows.

Readiness is staged into four milestones, matching the real operational
chain (Seed Lot -> Sowing -> Germination -> Seedling -> Inter Leafy Greens
-> Production Transfer -> Leafy Production -> Harvest -> Grading -> Packing
-> Cold Storage):

- SOWING: can this Farm start the first real Sowing?
- PRODUCTION: can material move Nursery -> Inter Leafy Greens -> Leafy
  Production?
- POST_HARVEST: can harvested product be graded, packed, and structurally
  stored?
- FULL_PILOT: aggregates the three above. No extra items are added here --
  Dispatch/Traceability/Recall were audited against the real service layer
  (`dispatch_service`, `traceability_service`) and neither one has any
  structural master-data dependency (no location-type check, no required
  master row) the way Grading/Packing genuinely do on Packing Hall/Cold
  Store/Grade Definition -- so inventing a Dispatch-Area or similar item
  here would violate the "don't add requirements merely because the module
  exists" rule.

Sowing is deliberately unaffected by Grade/Pack/Cold Store configuration --
those only ever appear under POST_HARVEST/FULL_PILOT.

--- Coherent-chain algorithm (Sowing) ---

Rule 1 (CLAUDE.md) forbids branching on a literal crop/variety/customer
name, but says nothing against reading the platform's own generic
vocabulary (location types like `zone`/`grow_table`, carrier types like
`seed_tray`/`nursery_cultivation_plate`) -- these are global, migration-
seeded catalog rows every tenant shares, exactly like `greenhouse_
classification`, not a tenant's crop-specific configuration. This module
reads that generic vocabulary the same way `pilot_bootstrap_service` and
every farm-setup/movement service already do.

A tenant may configure multiple Crops/Varieties/Workflows at once (CMP is
crop-agnostic), so "does a Crop exist" is not enough -- three unrelated rows
each existing does not mean any one of them can actually support a Sowing
together (see B8 ticket's "Multiple Configurations" section). Instead this
walks every structurally valid link:

    Crop (active) -> Variety (active, same crop)
                   -> Workflow (active, same crop + same Production System,
                      and workflow.variety_id is NULL [applies to every
                      variety of the crop] or equals this Variety)
                   -> a PUBLISHED WorkflowVersion of that Workflow

For every such candidate chain, this reads its `is_start` WorkflowStage's
`required_carrier_type_id` (if any) and checks:

  - a CarrierSpecification of that carrier type is registered (tenant-wide)
  - at least one physical Carrier of that type is registered for this Farm
  - a SeedLot exists for this exact (Farm, Crop, Variety)

The candidate with the most of those three sub-checks passing is reported
(ties broken by Workflow code, then Variety code, for determinism) -- this
is "the smallest correct V1" the ticket calls for: it never reports READY
because unrelated rows merely coexist, but it also never forces the
operator to pick a target crop up front. If literally no structurally
coherent chain exists yet (no Workflow links an existing Crop/Variety/
Production System at all), the Crop/Variety/Production System items still
report PASS/MISSING independently (their own existence is real, even before
a workflow links them), while the Workflow/Seed-Tray/Seed-Lot items report
MISSING against the platform's own designated Sowing-stage carrier type
(`seed_tray`) as the only well-defined fallback -- never a fabricated
"ready" verdict.

--- Production / Post-Harvest ---

These are structural, not per-crop: any tenant's Nursery/Leafy Production
physical topology and Packing Hall/Cold Store/Grade/Pack/Packaging-Unit
configuration serve every crop equally, so they are evaluated once, not per
coherent chain.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.carrier import Carrier
from app.models.carrier_specification import CarrierSpecification
from app.models.carrier_type import CarrierType
from app.models.crop import Crop
from app.models.grade_definition import GradeDefinition
from app.models.grade_definition_version import GradeDefinitionVersion
from app.models.location import Location
from app.models.location_type import LocationType
from app.models.pack_specification import PackSpecification
from app.models.pack_specification_version import PackSpecificationVersion
from app.models.packaging_unit import PackagingUnit
from app.models.production_system import ProductionSystem
from app.models.seed_lot import SeedLot
from app.models.variety import Variety
from app.models.workflow import Workflow
from app.models.workflow_stage import WorkflowStage
from app.models.workflow_version import WorkflowVersion
from app.schemas.farm_setup_readiness import (
    FarmSetupReadinessItem,
    FarmSetupReadinessMilestone,
    FarmSetupReadinessRead,
)
from app.services import farm_service

# Platform-seeded, tenant-independent vocabulary (see module docstring).
_SEED_TRAY_CARRIER_TYPE = "seed_tray"
_NURSERY_PLATE_CARRIER_TYPE = "nursery_cultivation_plate"
_PRODUCTION_PLATE_CARRIER_TYPE = "production_cultivation_plate"


def _item(code: str, label: str, ok: bool, *, detail: str = "", not_applicable: bool = False) -> FarmSetupReadinessItem:
    if not_applicable:
        status = "not_applicable"
    else:
        status = "pass" if ok else "missing"
    return FarmSetupReadinessItem(code=code, label=label, status=status, detail=detail)


def _milestone(code: str, label: str, items: list[FarmSetupReadinessItem]) -> FarmSetupReadinessMilestone:
    ready = all(item.status in ("pass", "not_applicable") for item in items)
    return FarmSetupReadinessMilestone(
        code=code, label=label, status="ready" if ready else "incomplete", items=items
    )


def _type_id_map(db: Session, model: type, codes: tuple[str, ...]) -> dict[str, uuid.UUID]:
    rows = db.execute(select(model.code, model.id).where(model.code.in_(codes))).all()
    return {code: type_id for code, type_id in rows}


def _location_child_exists(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    parent_type_id: uuid.UUID | None,
    parent_classification: str | None,
    child_type_id: uuid.UUID,
) -> bool:
    """True if an active Location of `child_type_id` exists as a child of
    an active Location of `parent_type_id` (optionally classification-
    scoped), both within this Farm."""
    parent = aliased(Location)
    child = aliased(Location)
    query = select(child.id).join(parent, child.parent_location_id == parent.id).where(
        child.tenant_id == tenant_id,
        child.farm_id == farm_id,
        child.status == "active",
        child.location_type_id == child_type_id,
        parent.tenant_id == tenant_id,
        parent.farm_id == farm_id,
        parent.status == "active",
    )
    if parent_type_id is not None:
        query = query.where(parent.location_type_id == parent_type_id)
    if parent_classification is not None:
        query = query.where(parent.greenhouse_classification == parent_classification)
    return db.execute(query.limit(1)).first() is not None


def _nursery_structure_ok(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_type_ids: dict[str, uuid.UUID]
) -> bool:
    """At least one active Nursery greenhouse has BOTH a Seeding Station and
    a Germination Chamber as direct children -- a coherent single greenhouse,
    not two unrelated Nursery greenhouses each missing half the structure."""
    greenhouse_type_id = location_type_ids["greenhouse"]
    seeding_ok_greenhouses = select(Location.parent_location_id).where(
        Location.tenant_id == tenant_id, Location.farm_id == farm_id, Location.status == "active",
        Location.location_type_id == location_type_ids["seeding_station"],
    )
    chamber_ok_greenhouses = select(Location.parent_location_id).where(
        Location.tenant_id == tenant_id, Location.farm_id == farm_id, Location.status == "active",
        Location.location_type_id == location_type_ids["germination_chamber"],
    )
    found = db.execute(
        select(Location.id).where(
            Location.tenant_id == tenant_id, Location.farm_id == farm_id, Location.status == "active",
            Location.location_type_id == greenhouse_type_id,
            Location.greenhouse_classification == "nursery",
            Location.id.in_(seeding_ok_greenhouses),
            Location.id.in_(chamber_ok_greenhouses),
        ).limit(1)
    ).first()
    return found is not None


def _carrier_type_id(db: Session, code: str) -> uuid.UUID | None:
    return db.execute(select(CarrierType.id).where(CarrierType.code == code)).scalar_one_or_none()


def _carrier_specification_active(db: Session, *, tenant_id: uuid.UUID, carrier_type_id: uuid.UUID | None) -> bool:
    if carrier_type_id is None:
        return False
    return db.execute(
        select(CarrierSpecification.id).where(
            CarrierSpecification.tenant_id == tenant_id,
            CarrierSpecification.carrier_type_id == carrier_type_id,
            CarrierSpecification.status == "active",
        ).limit(1)
    ).first() is not None


def _physical_carriers_registered(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, carrier_type_id: uuid.UUID | None
) -> bool:
    if carrier_type_id is None:
        return False
    return db.execute(
        select(Carrier.id).where(
            Carrier.tenant_id == tenant_id, Carrier.farm_id == farm_id,
            Carrier.carrier_type_id == carrier_type_id, Carrier.status == "active",
        ).limit(1)
    ).first() is not None


@dataclass
class _SowingChain:
    crop_id: uuid.UUID
    crop_code: str
    variety_id: uuid.UUID
    variety_code: str
    production_system_code: str
    workflow_code: str
    required_carrier_type_id: uuid.UUID | None
    spec_ok: bool
    carriers_ok: bool
    seed_lot_ok: bool

    @property
    def score(self) -> int:
        checks = [self.seed_lot_ok]
        if self.required_carrier_type_id is not None:
            checks += [self.spec_ok, self.carriers_ok]
        return sum(1 for c in checks if c)

    @property
    def max_score(self) -> int:
        return 3 if self.required_carrier_type_id is not None else 1


def _find_best_sowing_chain(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> _SowingChain | None:
    rows = db.execute(
        select(Crop, Variety, ProductionSystem, Workflow, WorkflowStage.required_carrier_type_id)
        .select_from(Workflow)
        .join(Crop, and_(Crop.tenant_id == Workflow.tenant_id, Crop.id == Workflow.crop_id))
        .join(
            ProductionSystem,
            and_(
                ProductionSystem.tenant_id == Workflow.tenant_id,
                ProductionSystem.id == Workflow.production_system_id,
            ),
        )
        .join(Variety, and_(Variety.tenant_id == Workflow.tenant_id, Variety.crop_id == Crop.id))
        .join(
            WorkflowVersion,
            and_(WorkflowVersion.workflow_id == Workflow.id, WorkflowVersion.state == "published"),
        )
        .outerjoin(
            WorkflowStage,
            and_(WorkflowStage.workflow_version_id == WorkflowVersion.id, WorkflowStage.is_start.is_(True)),
        )
        .where(
            Workflow.tenant_id == tenant_id,
            Workflow.status == "active",
            Crop.status == "active",
            ProductionSystem.status == "active",
            Variety.status == "active",
            or_(Workflow.variety_id.is_(None), Workflow.variety_id == Variety.id),
        )
    ).all()

    best: _SowingChain | None = None
    for crop, variety, production_system, workflow, required_carrier_type_id in rows:
        spec_ok = _carrier_specification_active(db, tenant_id=tenant_id, carrier_type_id=required_carrier_type_id)
        carriers_ok = _physical_carriers_registered(
            db, tenant_id=tenant_id, farm_id=farm_id, carrier_type_id=required_carrier_type_id
        )
        seed_lot_ok = db.execute(
            select(SeedLot.id).where(
                SeedLot.tenant_id == tenant_id, SeedLot.farm_id == farm_id,
                SeedLot.crop_id == crop.id, SeedLot.variety_id == variety.id, SeedLot.status == "active",
            ).limit(1)
        ).first() is not None

        candidate = _SowingChain(
            crop_id=crop.id, crop_code=crop.code, variety_id=variety.id, variety_code=variety.code,
            production_system_code=production_system.code, workflow_code=workflow.code,
            required_carrier_type_id=required_carrier_type_id,
            spec_ok=spec_ok, carriers_ok=carriers_ok, seed_lot_ok=seed_lot_ok,
        )
        if best is None or candidate.score > best.score or (
            candidate.score == best.score
            and (candidate.workflow_code, candidate.variety_code) < (best.workflow_code, best.variety_code)
        ):
            best = candidate
    return best


def _sowing_milestone(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_type_ids: dict[str, uuid.UUID]
) -> FarmSetupReadinessMilestone:
    items: list[FarmSetupReadinessItem] = []

    items.append(_item("farm_exists", "Farm exists", True))
    items.append(
        _item(
            "nursery_structure",
            "Nursery greenhouse with Seeding Station and Germination Chamber",
            _nursery_structure_ok(db, tenant_id=tenant_id, farm_id=farm_id, location_type_ids=location_type_ids),
        )
    )

    any_crop = db.execute(select(Crop.id).where(Crop.tenant_id == tenant_id, Crop.status == "active").limit(1)).first() is not None
    any_variety = db.execute(
        select(Variety.id).join(Crop, Crop.id == Variety.crop_id).where(
            Variety.tenant_id == tenant_id, Variety.status == "active", Crop.status == "active",
        ).limit(1)
    ).first() is not None
    any_production_system = db.execute(
        select(ProductionSystem.id).where(
            ProductionSystem.tenant_id == tenant_id, ProductionSystem.status == "active"
        ).limit(1)
    ).first() is not None

    chain = _find_best_sowing_chain(db, tenant_id=tenant_id, farm_id=farm_id)

    items.append(_item("crop_configured", "Crop configured", any_crop))
    items.append(_item("variety_configured", "Variety configured", any_variety))
    items.append(_item("production_system_configured", "Production System configured", any_production_system))

    if chain is not None:
        items.append(
            _item(
                "published_workflow",
                "Published Workflow linking Crop, Variety, and Production System",
                True,
                detail=f"{chain.workflow_code} ({chain.crop_code}/{chain.variety_code}/{chain.production_system_code})",
            )
        )
        if chain.required_carrier_type_id is not None:
            items.append(_item("seed_tray_specification", "Seed Tray Carrier Specification registered", chain.spec_ok))
            items.append(_item("physical_seed_trays", "Physical Seed Trays registered", chain.carriers_ok))
        else:
            items.append(
                _item(
                    "seed_tray_specification", "Seed Tray Carrier Specification registered", True, not_applicable=True,
                    detail="the coherent Workflow's start stage declares no required carrier type",
                )
            )
            items.append(
                _item(
                    "physical_seed_trays", "Physical Seed Trays registered", True, not_applicable=True,
                    detail="the coherent Workflow's start stage declares no required carrier type",
                )
            )
        items.append(
            _item(
                "seed_lot",
                "Real Seed Lot registered for the Crop/Variety",
                chain.seed_lot_ok,
                detail=f"{chain.crop_code}/{chain.variety_code}",
            )
        )
    else:
        items.append(
            _item(
                "published_workflow",
                "Published Workflow linking Crop, Variety, and Production System",
                False,
                detail="no published Workflow coherently links an existing Crop, Variety, and Production System yet",
            )
        )
        fallback_carrier_type_id = _carrier_type_id(db, _SEED_TRAY_CARRIER_TYPE)
        items.append(
            _item(
                "seed_tray_specification",
                "Seed Tray Carrier Specification registered",
                _carrier_specification_active(db, tenant_id=tenant_id, carrier_type_id=fallback_carrier_type_id),
            )
        )
        items.append(
            _item(
                "physical_seed_trays",
                "Physical Seed Trays registered",
                _physical_carriers_registered(
                    db, tenant_id=tenant_id, farm_id=farm_id, carrier_type_id=fallback_carrier_type_id
                ),
            )
        )
        any_seed_lot = db.execute(
            select(SeedLot.id).where(
                SeedLot.tenant_id == tenant_id, SeedLot.farm_id == farm_id, SeedLot.status == "active"
            ).limit(1)
        ).first() is not None
        items.append(
            _item(
                "seed_lot", "Real Seed Lot registered for the Crop/Variety", any_seed_lot,
                detail="no coherent Crop/Variety chain yet -- showing whether any Seed Lot exists for this Farm",
            )
        )

    return _milestone("sowing", "Sowing Readiness", items)


def _production_milestone(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_type_ids: dict[str, uuid.UUID]
) -> FarmSetupReadinessMilestone:
    items: list[FarmSetupReadinessItem] = []

    items.append(
        _item(
            "nursery_intersalads_structure",
            "Nursery Inter Leafy Greens (InterSalads) structure",
            _nursery_intersalads_structure_ok(db, tenant_id=tenant_id, farm_id=farm_id, location_type_ids=location_type_ids),
        )
    )

    nursery_plate_type_id = _carrier_type_id(db, _NURSERY_PLATE_CARRIER_TYPE)
    items.append(
        _item(
            "nursery_cultivation_plate_specification",
            "Nursery Cultivation Plate Specification registered",
            _carrier_specification_active(db, tenant_id=tenant_id, carrier_type_id=nursery_plate_type_id),
        )
    )
    items.append(
        _item(
            "physical_nursery_cultivation_plates",
            "Physical Nursery Cultivation Plates registered",
            _physical_carriers_registered(db, tenant_id=tenant_id, farm_id=farm_id, carrier_type_id=nursery_plate_type_id),
        )
    )

    items.append(
        _item(
            "leafy_production_structure",
            "Leafy Production greenhouse with Zone -> Span -> Grow Table",
            _leafy_production_structure_ok(db, tenant_id=tenant_id, farm_id=farm_id, location_type_ids=location_type_ids),
        )
    )

    production_plate_type_id = _carrier_type_id(db, _PRODUCTION_PLATE_CARRIER_TYPE)
    items.append(
        _item(
            "production_cultivation_plate_specification",
            "Production Cultivation Plate Specification registered",
            _carrier_specification_active(db, tenant_id=tenant_id, carrier_type_id=production_plate_type_id),
        )
    )
    items.append(
        _item(
            "physical_production_cultivation_plates",
            "Physical Production Cultivation Plates registered",
            _physical_carriers_registered(
                db, tenant_id=tenant_id, farm_id=farm_id, carrier_type_id=production_plate_type_id
            ),
        )
    )

    return _milestone("production", "Production Readiness", items)


def _nursery_intersalads_structure_ok(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_type_ids: dict[str, uuid.UUID]
) -> bool:
    intersalads_with_table = select(Location.parent_location_id).where(
        Location.tenant_id == tenant_id, Location.farm_id == farm_id, Location.status == "active",
        Location.location_type_id == location_type_ids["intersalads_table"],
    )
    found = db.execute(
        select(Location.id).where(
            Location.tenant_id == tenant_id, Location.farm_id == farm_id, Location.status == "active",
            Location.location_type_id == location_type_ids["intersalads"],
            Location.id.in_(intersalads_with_table),
        ).limit(1)
    ).first()
    return found is not None


def _leafy_production_structure_ok(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_type_ids: dict[str, uuid.UUID]
) -> bool:
    zone = aliased(Location)
    span = aliased(Location)
    table = aliased(Location)
    greenhouse = aliased(Location)
    found = db.execute(
        select(table.id)
        .join(span, table.parent_location_id == span.id)
        .join(zone, span.parent_location_id == zone.id)
        .join(greenhouse, zone.parent_location_id == greenhouse.id)
        .where(
            table.tenant_id == tenant_id, table.farm_id == farm_id, table.status == "active",
            table.location_type_id == location_type_ids["grow_table"],
            span.tenant_id == tenant_id, span.farm_id == farm_id, span.status == "active",
            span.location_type_id == location_type_ids["span"],
            zone.tenant_id == tenant_id, zone.farm_id == farm_id, zone.status == "active",
            zone.location_type_id == location_type_ids["zone"],
            greenhouse.tenant_id == tenant_id, greenhouse.farm_id == farm_id, greenhouse.status == "active",
            greenhouse.location_type_id == location_type_ids["greenhouse"],
            greenhouse.greenhouse_classification == "leafy_greens",
        )
        .limit(1)
    ).first()
    return found is not None


def _post_harvest_milestone(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, location_type_ids: dict[str, uuid.UUID]
) -> FarmSetupReadinessMilestone:
    items: list[FarmSetupReadinessItem] = []

    packing_hall_ok = db.execute(
        select(Location.id).where(
            Location.tenant_id == tenant_id, Location.farm_id == farm_id, Location.status == "active",
            Location.location_type_id == location_type_ids["packing_hall"],
        ).limit(1)
    ).first() is not None
    items.append(_item("packing_hall_location", "Packing Hall location configured", packing_hall_ok))

    cold_store_ok = db.execute(
        select(Location.id).where(
            Location.tenant_id == tenant_id, Location.farm_id == farm_id, Location.status == "active",
            Location.location_type_id == location_type_ids["cold_store"],
        ).limit(1)
    ).first() is not None
    items.append(_item("cold_store_location", "Cold Store location configured", cold_store_ok))

    cold_store_position_ok = _location_child_exists(
        db, tenant_id=tenant_id, farm_id=farm_id,
        parent_type_id=location_type_ids["cold_store"], parent_classification=None,
        child_type_id=location_type_ids["cold_store_position"],
    )
    items.append(_item("cold_store_position_structure", "Cold Store position structure configured", cold_store_position_ok))

    grade_ok = db.execute(
        select(GradeDefinitionVersion.id)
        .join(GradeDefinition, GradeDefinition.id == GradeDefinitionVersion.grade_definition_id)
        .where(
            GradeDefinition.tenant_id == tenant_id, GradeDefinitionVersion.tenant_id == tenant_id,
            GradeDefinitionVersion.status == "active",
        )
        .limit(1)
    ).first() is not None
    items.append(_item("grade_definition_active_version", "Grade Definition with an active version", grade_ok))

    packaging_unit_ok = db.execute(
        select(PackagingUnit.id).where(PackagingUnit.tenant_id == tenant_id, PackagingUnit.status == "active").limit(1)
    ).first() is not None
    items.append(_item("packaging_unit_active", "Active Packaging Unit", packaging_unit_ok))

    pack_spec_ok = db.execute(
        select(PackSpecificationVersion.id)
        .join(PackSpecification, PackSpecification.id == PackSpecificationVersion.pack_specification_id)
        .where(
            PackSpecification.tenant_id == tenant_id, PackSpecificationVersion.tenant_id == tenant_id,
            PackSpecificationVersion.status == "active",
        )
        .limit(1)
    ).first() is not None
    items.append(_item("pack_specification_active_version", "Pack Specification with an active version", pack_spec_ok))

    return _milestone("post_harvest", "Post-Harvest Readiness", items)


_LOCATION_TYPE_CODES = (
    "greenhouse", "seeding_station", "germination_chamber", "intersalads", "intersalads_table",
    "zone", "span", "grow_table", "packing_hall", "cold_store", "cold_store_position",
)


def evaluate_farm_setup_readiness(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID
) -> FarmSetupReadinessRead:
    """Pure read. Raises `FarmNotFoundError` (via `farm_service.get_farm`)
    for a cross-tenant or nonexistent Farm -- callers should translate that
    into a 404, never leaking whether the Farm exists in another tenant."""
    farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    location_type_ids = _type_id_map(db, LocationType, _LOCATION_TYPE_CODES)

    sowing = _sowing_milestone(db, tenant_id=tenant_id, farm_id=farm_id, location_type_ids=location_type_ids)
    production = _production_milestone(db, tenant_id=tenant_id, farm_id=farm_id, location_type_ids=location_type_ids)
    post_harvest = _post_harvest_milestone(db, tenant_id=tenant_id, farm_id=farm_id, location_type_ids=location_type_ids)

    full_pilot_items = list(sowing.items) + list(production.items) + list(post_harvest.items)
    full_pilot = _milestone("full_pilot", "Full Pilot Readiness", full_pilot_items)

    milestones = [sowing, production, post_harvest, full_pilot]
    overall = "ready" if all(m.status == "ready" for m in milestones) else "incomplete"

    return FarmSetupReadinessRead(farm_id=str(farm_id), overall=overall, milestones=milestones)
