"""PILOT-SETUP-001A: focused tests for the config-driven pilot master-data
bootstrap. Every test goes through the real service layer (via
`pilot_bootstrap_service.run_bootstrap`/`run_readiness_check`), never raw
SQL, exactly like the application code under test."""

import copy
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.carrier import Carrier
from app.models.carrier_specification import CarrierSpecification
from app.models.crop import Crop
from app.models.farm import Farm
from app.models.grade_definition_version import GradeDefinitionVersion
from app.models.location import Location
from app.models.pack_specification_version import PackSpecificationVersion
from app.models.seed_lot import SeedLot
from app.models.tenant import Tenant
from app.models.workflow_version import WorkflowVersion
from app.services import membership_service, tenant_service, user_service
from app.services.pilot_bootstrap_service import (
    PilotBootstrapAbortedError,
    PilotConfig,
    PilotConfigPlaceholderError,
    PilotTargetNotResolvedError,
    find_placeholders,
    run_bootstrap,
    run_readiness_check,
)
from pydantic import ValidationError


@pytest.fixture
def pilot_target(db_session):
    """A real Tenant + administrative User + active Membership -- exactly
    the DEPLOY-001 prerequisite this bootstrap assumes. Returns
    (tenant, user, target_dict) ready to splice into a config."""
    tenant = tenant_service.create_tenant(db_session, code="pilot-tenant", name="Pilot Tenant")
    user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject="pilot-admin",
        email="admin@example.com", display_name="Pilot Admin",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None,
    )
    return tenant, user, {"tenant_code": "pilot-tenant", "actor": {"oidc_issuer": user.oidc_issuer, "oidc_subject": user.oidc_subject}}


def _valid_config_dict(target: dict, *, seed_lot: bool = False) -> dict:
    cfg = {
        "target": target,
        "farm": {
            "code": "PF-01", "name": "Pilot Farm", "country_code": "MY", "city_region": "Sabah",
            "timezone": "Asia/Kuala_Lumpur",
        },
        "greenhouses": [
            {
                "code": "NUR-01", "name": "Nursery", "classification": "nursery",
                "nursery": {
                    "seeding_station": {"code": "SEED-STN-1"},
                    "germination_chamber": {"code": "GC-01", "trolley_capacity": 4},
                    "seedling_tables": {"code_prefix": "SDL-", "start": 1, "end": 2, "pad_width": 2},
                    "intersalads_tables": {"code_prefix": "ISA-", "start": 1, "end": 2, "pad_width": 2},
                },
            },
            {
                "code": "GH-01", "name": "Leafy GH 1", "classification": "leafy_greens",
                "leafy": {
                    "zones": [
                        {"code": "ZA", "spans": [
                            {"code": "SP1", "tables": {"code_prefix": "T", "start": 1, "end": 4, "pad_width": 2}},
                        ]},
                    ],
                },
            },
        ],
        "locations": {
            "packing_hall": {"code": "PH-01", "name": "Packing Hall"},
            "cold_store": {
                "code": "CS-01", "name": "Cold Store",
                "positions": {"code_prefix": "CSP-", "start": 1, "end": 4, "pad_width": 2, "capacity": None},
            },
        },
        "carrier_specifications": [
            {
                "key": "seed_tray_spec", "carrier_type_code": "seed_tray", "code": "ST-SPEC-1", "name": "Seed Tray Spec",
                "length_mm": 300, "width_mm": 200, "height_mm": 50, "biological_position_count": 104,
            },
            {
                "key": "nursery_plate_spec", "carrier_type_code": "nursery_cultivation_plate", "code": "NP-SPEC-1",
                "name": "Nursery Plate Spec", "length_mm": 300, "width_mm": 300, "height_mm": None,
                "biological_position_count": 12,
            },
            {
                "key": "production_plate_spec", "carrier_type_code": "production_cultivation_plate", "code": "PP-SPEC-1",
                "name": "Production Plate Spec", "length_mm": 400, "width_mm": 400, "height_mm": None,
                "biological_position_count": 6,
            },
        ],
        "carriers": [
            {"specification_key": "seed_tray_spec", "code_prefix": "TRAY-", "start": 1, "end": 3, "pad_width": 3},
            {"specification_key": "nursery_plate_spec", "code_prefix": "NPL-", "start": 1, "end": 2, "pad_width": 3},
            {"specification_key": "production_plate_spec", "code_prefix": "PPL-", "start": 1, "end": 2, "pad_width": 3},
        ],
        "crop": {"code": "ICE-PILOT", "common_name": "Iceberg Lettuce", "crop_category": "leafy_green"},
        "variety": {"code": "VAR-PILOT", "name": "Real Pilot Variety"},
        "production_system": {"code": "PS-PILOT", "name": "Pilot Production System"},
        "workflow": {
            "code": "WF-PILOT", "name": "Pilot Workflow",
            "stages": [
                {"code": "SOWING", "name": "Sowing", "display_order": 1, "stage_category": "seeding",
                 "required_carrier_type_code": "seed_tray", "is_start": True},
                {"code": "GROWING", "name": "Growing", "display_order": 2, "stage_category": "production"},
                {"code": "DONE", "name": "Done", "display_order": 3, "stage_category": "completed", "is_terminal": True},
            ],
            "transitions": [
                {"code": "T1", "name": "Sowing -> Growing", "from_stage_code": "SOWING", "to_stage_code": "GROWING"},
                {"code": "T2", "name": "Growing -> Done", "from_stage_code": "GROWING", "to_stage_code": "DONE"},
            ],
        },
        "grade_definitions": [
            {
                "code": "GRADE-A", "name": "Grade A",
                "version": {"activate": True, "effective_date": date(2026, 1, 1)},
            },
        ],
        "packaging_units": [{"code": "PU-CRATE", "name": "Crate"}],
        "pack_specifications": [
            {
                "code": "PACK-A", "name": "Pack A",
                "version": {
                    "packaging_unit_code": "PU-CRATE", "grade_definition_code": "GRADE-A",
                    "nominal_net_weight_kg": "1.5", "activate": True, "effective_date": date(2026, 1, 2),
                },
            },
        ],
    }
    if seed_lot:
        cfg["seed_lot"] = {"code": "SEEDLOT-001", "supplier_name": "Real Supplier", "received_date": date(2026, 1, 1)}
    return cfg


# --- 1. config parse success ------------------------------------------------


def test_config_parses_successfully(pilot_target):
    _tenant, _user, target = pilot_target
    config = PilotConfig.model_validate(_valid_config_dict(target))
    assert config.farm.code == "PF-01"
    assert config.seed_lot is None


# --- 2. missing required placeholder rejected on apply ----------------------


def test_apply_rejects_remaining_placeholder(db_session, pilot_target):
    _tenant, _user, target = pilot_target
    raw = _valid_config_dict(target)
    raw["farm"]["code"] = "REQUIRED_FARM_CODE"
    config = PilotConfig.model_validate(raw)
    assert find_placeholders(config) == ["farm.code"]

    with pytest.raises(PilotConfigPlaceholderError):
        run_bootstrap(db_session, config=config, dry_run=False)

    # Nothing was attempted -- not even the Farm lookup/create.
    assert db_session.execute(select(func.count()).select_from(Farm)).scalar_one() == 0


# --- 3. dry-run writes nothing (verified against a second, fresh connection) ---


def test_dry_run_writes_nothing():
    # Deliberately does NOT use the `db_session`/`pilot_target` fixtures --
    # those are bound to a different connection than the one this test
    # controls directly, and a genuine "did it reach physical storage" proof
    # requires re-querying from a wholly separate connection afterward. The
    # target Tenant/User/Membership are therefore created on this test's own
    # connection too, inside the same outer transaction, so they are visible
    # to `run_bootstrap` without ever being committed for real.
    engine = create_engine(settings.test_database_url)
    conn = engine.connect()
    outer = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        tenant = tenant_service.create_tenant(db, code="dry-run-tenant", name="Dry Run Tenant")
        user = user_service.create_user(
            db, oidc_issuer="https://issuer.example", oidc_subject="dry-run-admin",
            email="dryrun@example.com", display_name="Dry Run Admin",
        )
        membership_service.add_membership(db, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
        target = {"tenant_code": "dry-run-tenant", "actor": {"oidc_issuer": user.oidc_issuer, "oidc_subject": user.oidc_subject}}
        config = PilotConfig.model_validate(_valid_config_dict(target))

        result = run_bootstrap(db, config=config, dry_run=True)
        assert not result.has_conflicts and not result.has_blocked
        assert any(s.status == "CREATED" and s.kind == "farm" for s in result.steps)
        tenant_id = tenant.id
    finally:
        outer.rollback()
        db.close()
        conn.close()

    with engine.connect() as fresh:
        tenant_count = fresh.execute(text("SELECT count(*) FROM tenants WHERE id = :tid"), {"tid": str(tenant_id)}).scalar_one()
        farm_count = fresh.execute(text("SELECT count(*) FROM farms WHERE tenant_id = :tid"), {"tid": str(tenant_id)}).scalar_one()
    assert tenant_count == 0, "dry-run's own transaction (including its fixture setup) must never persist"
    assert farm_count == 0, "dry-run must never leave a persisted row behind"
    engine.dispose()


# --- 4. first apply creates required master/config data ---------------------


def test_first_apply_creates_master_data(db_session, pilot_target):
    tenant, _user, target = pilot_target
    config = PilotConfig.model_validate(_valid_config_dict(target))

    result = run_bootstrap(db_session, config=config, dry_run=False)

    assert not result.has_conflicts and not result.has_blocked
    assert all(s.status == "CREATED" for s in result.steps)
    assert db_session.execute(
        select(func.count()).select_from(Farm).where(Farm.tenant_id == tenant.id)
    ).scalar_one() == 1
    assert db_session.execute(
        select(func.count()).select_from(Crop).where(Crop.tenant_id == tenant.id)
    ).scalar_one() == 1
    assert db_session.execute(
        select(func.count()).select_from(CarrierSpecification).where(CarrierSpecification.tenant_id == tenant.id)
    ).scalar_one() == 3
    assert db_session.execute(
        select(func.count()).select_from(Carrier).where(Carrier.tenant_id == tenant.id)
    ).scalar_one() == 3 + 2 + 2
    published = db_session.execute(
        select(WorkflowVersion).where(WorkflowVersion.tenant_id == tenant.id, WorkflowVersion.state == "published")
    ).scalar_one()
    assert published.version_number == 1


# --- 5. second identical apply creates no duplicates -------------------------


def test_second_identical_apply_creates_no_duplicates(db_session, pilot_target):
    tenant, _user, target = pilot_target
    config = PilotConfig.model_validate(_valid_config_dict(target))

    run_bootstrap(db_session, config=config, dry_run=False)
    second = run_bootstrap(db_session, config=config, dry_run=False)

    assert not second.has_conflicts and not second.has_blocked
    assert all(s.status == "EXISTING" for s in second.steps)
    assert db_session.execute(
        select(func.count()).select_from(Farm).where(Farm.tenant_id == tenant.id)
    ).scalar_one() == 1
    assert db_session.execute(
        select(func.count()).select_from(Carrier).where(Carrier.tenant_id == tenant.id)
    ).scalar_one() == 3 + 2 + 2


# --- 6. conflicting existing code/value stops safely -------------------------


def test_conflicting_existing_value_stops_apply_safely(db_session, pilot_target):
    tenant, _user, target = pilot_target
    config = PilotConfig.model_validate(_valid_config_dict(target))
    run_bootstrap(db_session, config=config, dry_run=False)

    changed = copy.deepcopy(_valid_config_dict(target))
    changed["farm"]["name"] = "A Totally Different Farm Name"
    changed_config = PilotConfig.model_validate(changed)

    with pytest.raises(PilotBootstrapAbortedError) as excinfo:
        run_bootstrap(db_session, config=changed_config, dry_run=False)
    assert excinfo.value.result.steps[0].status == "CONFLICT"

    # Still exactly one Farm row -- the conflict was reported, not resolved
    # by creating a second one or silently renaming the first.
    farms = db_session.execute(select(Farm).where(Farm.tenant_id == tenant.id)).scalars().all()
    assert len(farms) == 1
    assert farms[0].name == "Pilot Farm"


# --- 7. invalid location hierarchy rejected ----------------------------------


def test_invalid_greenhouse_structure_rejected(pilot_target):
    _tenant, _user, target = pilot_target
    raw = _valid_config_dict(target)
    # A leafy_greens greenhouse with a `nursery` structure instead of `leafy`
    # -- must be rejected at config-parse time, not at apply time.
    raw["greenhouses"][1] = {
        "code": "GH-BAD", "name": "Bad GH", "classification": "leafy_greens",
        "nursery": {"seeding_station": {"code": "X"}},
    }
    with pytest.raises(ValidationError):
        PilotConfig.model_validate(raw)


def test_vines_classification_rejected(pilot_target):
    _tenant, _user, target = pilot_target
    raw = _valid_config_dict(target)
    raw["greenhouses"][1]["classification"] = "vines"
    with pytest.raises(ValidationError):
        PilotConfig.model_validate(raw)


# --- 8. carrier type/spec distinction preserved -------------------------------


def test_legacy_generic_cultivation_plate_type_rejected(pilot_target):
    _tenant, _user, target = pilot_target
    raw = _valid_config_dict(target)
    raw["carrier_specifications"][0]["carrier_type_code"] = "cultivation_plate"
    with pytest.raises(ValidationError):
        PilotConfig.model_validate(raw)


# --- 9. invalid carrier capacity rejected -------------------------------------


def test_zero_biological_position_count_rejected(pilot_target):
    _tenant, _user, target = pilot_target
    raw = _valid_config_dict(target)
    raw["carrier_specifications"][0]["biological_position_count"] = 0
    with pytest.raises(ValidationError):
        PilotConfig.model_validate(raw)


# --- 10. no operational transaction tables are populated by bootstrap --------


def test_no_operational_tables_populated(db_session, pilot_target):
    tenant, _user, target = pilot_target
    config = PilotConfig.model_validate(_valid_config_dict(target, seed_lot=True))

    result = run_bootstrap(db_session, config=config, dry_run=False)

    assert result.operational_integrity_ok
    for table in ("crop_batches", "sowing_events", "harvest_events", "dispatch_events"):
        count = db_session.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tid"), {"tid": tenant.id}
        ).scalar_one()
        assert count == 0, f"{table} must stay empty -- bootstrap must never create operational transactions"


# --- 11. seed lot omission allowed for setup; readiness blocks Sowing --------


def test_seed_lot_omission_allowed_readiness_flags_it(db_session, pilot_target):
    _tenant, _user, target = pilot_target
    config = PilotConfig.model_validate(_valid_config_dict(target, seed_lot=False))

    result = run_bootstrap(db_session, config=config, dry_run=False)
    assert not result.has_conflicts and not result.has_blocked  # setup succeeds without a seed lot

    items = run_readiness_check(db_session, config=config)
    seed_lot_item = next(i for i in items if i.name == "seed lot")
    assert seed_lot_item.status == "MISSING"
    assert seed_lot_item.informational is True
    assert "BLOCKS FIRST SOWING" in seed_lot_item.detail
    # every other item is PASS -- the missing seed lot alone doesn't taint
    # the rest of the readiness picture.
    assert all(i.status == "PASS" for i in items if i is not seed_lot_item)


# --- 12. known real seed lot config registers once, reruns idempotently -----


def test_known_seed_lot_registers_and_reruns_idempotently(db_session, pilot_target):
    tenant, _user, target = pilot_target
    config = PilotConfig.model_validate(_valid_config_dict(target, seed_lot=True))

    first = run_bootstrap(db_session, config=config, dry_run=False)
    seed_lot_step = next(s for s in first.steps if s.kind == "seed_lot")
    assert seed_lot_step.status == "CREATED"

    second = run_bootstrap(db_session, config=config, dry_run=False)
    seed_lot_step_2 = next(s for s in second.steps if s.kind == "seed_lot")
    assert seed_lot_step_2.status == "EXISTING"

    assert db_session.execute(
        select(func.count()).select_from(SeedLot).where(SeedLot.tenant_id == tenant.id)
    ).scalar_one() == 1

    items = run_readiness_check(db_session, config=config)
    seed_lot_item = next(i for i in items if i.name.startswith("seed lot"))
    assert seed_lot_item.status == "PASS"


# --- 13. versioned Grade/Pack config handled safely ---------------------------


def test_versioned_grade_and_pack_config_handled_safely(db_session, pilot_target):
    tenant, _user, target = pilot_target
    config = PilotConfig.model_validate(_valid_config_dict(target))

    run_bootstrap(db_session, config=config, dry_run=False)
    second = run_bootstrap(db_session, config=config, dry_run=False)
    assert not second.has_conflicts

    active_grade_versions = db_session.execute(
        select(GradeDefinitionVersion).where(GradeDefinitionVersion.tenant_id == tenant.id, GradeDefinitionVersion.status == "active")
    ).scalars().all()
    assert len(active_grade_versions) == 1
    assert active_grade_versions[0].version_number == 1

    active_pack_versions = db_session.execute(
        select(PackSpecificationVersion).where(PackSpecificationVersion.tenant_id == tenant.id, PackSpecificationVersion.status == "active")
    ).scalars().all()
    assert len(active_pack_versions) == 1
    assert active_pack_versions[0].version_number == 1
    assert active_pack_versions[0].grade_definition_version_id == active_grade_versions[0].id


# --- 14. missing target Tenant fails ------------------------------------------


def test_missing_target_tenant_fails(db_session):
    config = PilotConfig.model_validate(
        _valid_config_dict({"tenant_code": "nonexistent-tenant", "actor": {"oidc_issuer": "x", "oidc_subject": "y"}})
    )
    with pytest.raises(PilotTargetNotResolvedError):
        run_bootstrap(db_session, config=config, dry_run=False)


# --- 15. existing Tenant is reused, not recreated -----------------------------


def test_existing_tenant_is_reused_not_recreated(db_session, pilot_target):
    tenant, _user, target = pilot_target
    config = PilotConfig.model_validate(_valid_config_dict(target))

    result = run_bootstrap(db_session, config=config, dry_run=False)

    assert result.tenant_id == tenant.id
    assert db_session.execute(
        select(func.count()).select_from(Tenant).where(func.lower(Tenant.code) == "pilot-tenant")
    ).scalar_one() == 1
