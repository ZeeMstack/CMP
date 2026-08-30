"""PILOT-SETUP-001B8: persisted-state Setup Checklist / Readiness. Every
scenario is built through the real service layer -- either directly
(farm/crop/variety/... services) or via `pilot_bootstrap_service.
run_bootstrap` (itself just a thin, in-process orchestration over those same
services) -- never raw SQL. This is a distinct, product-facing read model
from `pilot_bootstrap_service.run_readiness_check`, which evaluates a
hand-authored YAML `PilotConfig`, not real persisted Farm state."""

from datetime import date

import pytest
from fastapi import status

from app.models.farm import Farm
from app.services import farm_service, membership_service, tenant_service, user_service
from app.services.errors import FarmNotFoundError
from app.services.farm_setup_readiness_service import evaluate_farm_setup_readiness
from app.services.pilot_bootstrap_service import PilotConfig, run_bootstrap


@pytest.fixture
def pilot_target(db_session):
    tenant = tenant_service.create_tenant(db_session, code="rdy-tenant", name="Readiness Tenant")
    user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject="rdy-admin",
        email="rdy-admin@example.com", display_name="Readiness Admin",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None,
    )
    target = {"tenant_code": "rdy-tenant", "actor": {"oidc_issuer": user.oidc_issuer, "oidc_subject": user.oidc_subject}}
    return tenant, user, target


def _config(
    target: dict,
    *,
    seed_lot: bool = True,
    intersalads: bool = True,
    post_harvest: bool = True,
    sowing_requires_carrier: bool = True,
) -> dict:
    nursery: dict = {
        "seeding_station": {"code": "SEED-STN-1"},
        "germination_chamber": {"code": "GC-01", "trolley_capacity": 4},
    }
    if intersalads:
        nursery["intersalads_tables"] = {"code_prefix": "ISA-", "start": 1, "end": 2, "pad_width": 2}

    cfg: dict = {
        "target": target,
        "farm": {"code": "PF-01", "name": "Pilot Farm", "country_code": "MY", "city_region": None, "timezone": "Asia/Kuala_Lumpur"},
        "greenhouses": [
            {"code": "NUR-01", "name": "Nursery", "classification": "nursery", "nursery": nursery},
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
                {
                    "code": "SOWING", "name": "Sowing", "display_order": 1, "stage_category": "seeding",
                    "is_start": True,
                    **({"required_carrier_type_code": "seed_tray"} if sowing_requires_carrier else {}),
                },
                {"code": "GROWING", "name": "Growing", "display_order": 2, "stage_category": "production"},
                {"code": "DONE", "name": "Done", "display_order": 3, "stage_category": "completed", "is_terminal": True},
            ],
            "transitions": [
                {"code": "T1", "name": "Sowing -> Growing", "from_stage_code": "SOWING", "to_stage_code": "GROWING"},
                {"code": "T2", "name": "Growing -> Done", "from_stage_code": "GROWING", "to_stage_code": "DONE"},
            ],
        },
    }
    if post_harvest:
        cfg["grade_definitions"] = [
            {"code": "GRADE-A", "name": "Grade A", "version": {"activate": True, "effective_date": date(2026, 1, 1)}},
        ]
        cfg["packaging_units"] = [{"code": "PU-CRATE", "name": "Crate"}]
        cfg["pack_specifications"] = [
            {
                "code": "PACK-A", "name": "Pack A",
                "version": {
                    "packaging_unit_code": "PU-CRATE", "grade_definition_code": "GRADE-A",
                    "nominal_net_weight_kg": "1.5", "activate": True, "effective_date": date(2026, 1, 2),
                },
            },
        ]
    if seed_lot:
        cfg["seed_lot"] = {"code": "SEEDLOT-001", "supplier_name": "Real Supplier", "received_date": date(2026, 1, 1)}
    return cfg


def _bootstrap(db_session, target: dict, **kwargs):
    config = PilotConfig.model_validate(_config(target, **kwargs))
    result = run_bootstrap(db_session, config=config, dry_run=False)
    farm = db_session.get(Farm, result.farm_id)
    return result, farm


# --- 1. empty Farm -----------------------------------------------------------


def test_empty_farm_all_milestones_incomplete(db_session, pilot_target):
    tenant, user, _target = pilot_target
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="EMPTY-01", name="Empty Farm",
        country_code="MY", city_region=None, timezone="Asia/Kuala_Lumpur",
    )
    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert read.overall == "incomplete"
    by_code = {m.code: m for m in read.milestones}
    assert by_code["sowing"].status == "incomplete"
    assert by_code["production"].status == "incomplete"
    assert by_code["post_harvest"].status == "incomplete"
    assert by_code["full_pilot"].status == "incomplete"
    farm_item = next(i for i in by_code["sowing"].items if i.code == "farm_exists")
    assert farm_item.status == "pass"


# --- 2. full sowing chain complete -> READY ----------------------------------


def test_complete_sowing_chain_is_ready(db_session, pilot_target):
    tenant, _user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, post_harvest=False)
    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    sowing = next(m for m in read.milestones if m.code == "sowing")
    assert sowing.status == "ready", [(i.code, i.status, i.detail) for i in sowing.items]


# --- 3. missing Seed Lot -> Sowing INCOMPLETE --------------------------------


def test_missing_seed_lot_makes_sowing_incomplete(db_session, pilot_target):
    tenant, _user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, seed_lot=False, post_harvest=False)
    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    sowing = next(m for m in read.milestones if m.code == "sowing")
    assert sowing.status == "incomplete"
    seed_lot_item = next(i for i in sowing.items if i.code == "seed_lot")
    assert seed_lot_item.status == "missing"


# --- 4. downstream Grade/Pack missing does NOT block Sowing ------------------


def test_downstream_grade_pack_missing_does_not_block_sowing(db_session, pilot_target):
    tenant, _user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, post_harvest=False)
    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    by_code = {m.code: m for m in read.milestones}
    assert by_code["sowing"].status == "ready"
    assert by_code["post_harvest"].status == "incomplete"


# --- 5. Production requirements missing --------------------------------------


def test_production_incomplete_when_intersalads_structure_missing(db_session, pilot_target):
    tenant, _user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, intersalads=False, post_harvest=False)
    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    production = next(m for m in read.milestones if m.code == "production")
    assert production.status == "incomplete"
    item = next(i for i in production.items if i.code == "nursery_intersalads_structure")
    assert item.status == "missing"
    # Sowing does not depend on Production's InterSalads structure.
    sowing = next(m for m in read.milestones if m.code == "sowing")
    assert sowing.status == "ready"


# --- 6. Production requirements complete -> READY ----------------------------


def test_production_ready_when_structure_and_carriers_complete(db_session, pilot_target):
    tenant, _user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, post_harvest=False)
    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    production = next(m for m in read.milestones if m.code == "production")
    assert production.status == "ready", [(i.code, i.status, i.detail) for i in production.items]


# --- 7. Post-Harvest requirements missing ------------------------------------


def test_post_harvest_incomplete_when_grade_pack_missing(db_session, pilot_target):
    tenant, _user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, post_harvest=False)
    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    post_harvest = next(m for m in read.milestones if m.code == "post_harvest")
    assert post_harvest.status == "incomplete"
    codes_missing = {i.code for i in post_harvest.items if i.status == "missing"}
    assert {"grade_definition_active_version", "packaging_unit_active", "pack_specification_active_version"} <= codes_missing


# --- 8. Post-Harvest requirements complete -> READY --------------------------


def test_post_harvest_ready_when_complete(db_session, pilot_target):
    tenant, _user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, post_harvest=True)
    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    post_harvest = next(m for m in read.milestones if m.code == "post_harvest")
    assert post_harvest.status == "ready", [(i.code, i.status, i.detail) for i in post_harvest.items]


# --- 9. Full Pilot aggregates correctly --------------------------------------


def test_full_pilot_ready_only_when_everything_is_ready(db_session, pilot_target):
    tenant, _user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, post_harvest=True, seed_lot=True)
    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    by_code = {m.code: m for m in read.milestones}
    assert by_code["sowing"].status == "ready"
    assert by_code["production"].status == "ready"
    assert by_code["post_harvest"].status == "ready"
    assert by_code["full_pilot"].status == "ready"
    assert read.overall == "ready"


def test_full_pilot_incomplete_if_any_milestone_incomplete(db_session, pilot_target):
    tenant, _user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, post_harvest=False, seed_lot=True)
    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    by_code = {m.code: m for m in read.milestones}
    assert by_code["sowing"].status == "ready"
    assert by_code["full_pilot"].status == "incomplete"
    assert read.overall == "incomplete"


# --- 10. unrelated incomplete Crop/Workflow does not invalidate a valid chain -


def test_unrelated_incomplete_workflow_does_not_break_a_valid_chain(db_session, pilot_target):
    tenant, user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, post_harvest=False)

    # A second, unrelated, unpublished/incoherent Crop+Workflow in the same tenant.
    from app.services import crop_service, production_system_service, workflow_service

    other_crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="OTHER-CROP",
        common_name="Other Crop", scientific_name=None, crop_category="leafy_green",
    )
    other_ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="OTHER-PS", name="Other PS", description=None,
    )
    workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=other_crop.id, variety_id=None,
        production_system_id=other_ps.id, code="OTHER-WF", name="Other Workflow",
    )  # never given a draft/published version -- deliberately incoherent/incomplete

    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    sowing = next(m for m in read.milestones if m.code == "sowing")
    assert sowing.status == "ready"


# --- 11. mismatched Crop/Variety/Workflow does not create a false READY -----


def test_mismatched_variety_workflow_linkage_does_not_falsely_report_ready(db_session, pilot_target):
    tenant, user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, post_harvest=False)

    from app.services import crop_service, workflow_service

    # A Variety of the SAME crop, but no Workflow links it, and no Seed Lot
    # exists for it -- three independently-existing rows must not combine
    # into a false coherent-chain READY.
    from app.models.crop import Crop

    crop = db_session.query(Crop).filter(Crop.tenant_id == tenant.id, Crop.code == "ICE-PILOT").one()

    orphan_variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id,
        code="ORPHAN-VAR", name="Orphan Variety", supplier_reference=None,
    )

    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    sowing = next(m for m in read.milestones if m.code == "sowing")
    # Still READY via the original coherent chain -- the orphan variety must
    # not be reported as though it were sowing-ready on its own.
    assert sowing.status == "ready"
    seed_lot_item = next(i for i in sowing.items if i.code == "seed_lot")
    assert orphan_variety.code not in seed_lot_item.detail


# --- 12. cross-tenant Farm -> 404 (service-level: FarmNotFoundError) --------


def test_cross_tenant_farm_raises_not_found(db_session, pilot_target):
    tenant, _user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, post_harvest=False)

    other_tenant = tenant_service.create_tenant(db_session, code="other-tenant", name="Other Tenant")
    with pytest.raises(FarmNotFoundError):
        evaluate_farm_setup_readiness(db_session, tenant_id=other_tenant.id, farm_id=farm.id)


# --- 13. permission enforced (HTTP layer) + 404 over the API ----------------


@pytest.fixture
def _dev_auth_enabled(monkeypatch):
    """Mirrors `test_carrier_specification.py`'s own local fixture: forces
    `settings.enable_dev_auth` on for exactly this test, so the dev-header
    HTTP auth path is exercised regardless of the developer's ambient
    `.env` value."""
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)


def test_endpoint_requires_authentication_and_enforces_tenant_isolation(
    client, active_context_with_farm, _dev_auth_enabled
):
    tenant, _user, headers, farm = active_context_with_farm

    unauthenticated = client.get(f"/farms/{farm.id}/setup-readiness")
    assert unauthenticated.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    ok = client.get(f"/farms/{farm.id}/setup-readiness", headers=headers)
    assert ok.status_code == status.HTTP_200_OK
    body = ok.json()
    assert body["farm_id"] == str(farm.id)
    assert {m["code"] for m in body["milestones"]} == {"sowing", "production", "post_harvest", "full_pilot"}

    import uuid as uuid_module

    missing = client.get(f"/farms/{uuid_module.uuid4()}/setup-readiness", headers=headers)
    assert missing.status_code == status.HTTP_404_NOT_FOUND


# --- 14. no writes/audit/operational events produced ------------------------


def test_readiness_evaluation_produces_no_audit_events(db_session, pilot_target):
    tenant, _user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, post_harvest=True)

    from sqlalchemy import func, select

    from app.models.audit_event import AuditEvent

    before = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tenant.id)
    ).scalar_one()
    evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    after = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tenant.id)
    ).scalar_one()
    assert before == after


# --- 15. no YAML/bootstrap file required -------------------------------------


def test_service_signature_has_no_config_file_dependency(db_session, pilot_target):
    tenant, _user, target = pilot_target
    _result, farm = _bootstrap(db_session, target, post_harvest=True)
    # Calling with only tenant_id/farm_id (no config, no file path) succeeds --
    # this is the entire point of a persisted-state readiness service.
    read = evaluate_farm_setup_readiness(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert read.farm_id == str(farm.id)
