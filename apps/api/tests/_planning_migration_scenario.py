"""Shared, non-collected scenario builders for PLANNING-OPS-001 migration
proofs (`tests/test_planning_migration.py`). Same committed-connection +
`session_replication_role`-guarded cleanup pattern
`tests/_grade_definition_scenario.py`/`tests/_recall_scenario.py` already
established. Not a test file itself (pytest's default `test_*.py` discovery
glob does not match this name)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    farm_service,
    membership_service,
    planning_service,
    production_system_service,
    sowing_service,
    tenant_service,
    unit_of_measure_service,
    user_service,
    workflow_service,
)
from tests.conftest import ensure_seed_tray_specification


def now():
    return datetime.now(timezone.utc)


def require_cmp_test(test_engine) -> None:
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup (session_replication_role) against "
            f"database {current_db!r}; this cleanup is only permitted against 'cmp_test'"
        )


def _committed_tenant_farm_crop(session, suffix):
    tenant = tenant_service.create_tenant(session, code=f"plan-mig-{suffix}", name="Planning Migration Tenant")
    user = user_service.create_user(
        session, oidc_issuer="plan-mig", oidc_subject=suffix, email=f"plan-mig-{suffix}@example.com",
        display_name="Planning Migration User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Planning Migration Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"var-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    return tenant, user, farm, crop, variety


def build_requirement_only_scenario(test_engine):
    """The lightest possible Planning history: one committed
    `ProductionRequirement` row, nothing else."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]
    tenant, user, farm, crop, variety = _committed_tenant_farm_crop(session, suffix)

    kg_uom = next(u for u in unit_of_measure_service.list_uoms(session) if u.code == "kg")
    requirement = planning_service.create_production_requirement(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        crop_id=crop.id, variety_id=variety.id, required_by_date=date(2026, 10, 15),
        required_quantity=Decimal("30000"), quantity_uom_id=kg_uom.id, reference=None, notes=None,
    )

    result = {"tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "requirement_id": requirement.id}
    session.close()
    conn.close()
    return result


def build_requirement_and_line_scenario(test_engine):
    """A committed `ProductionRequirement` plus one committed
    `SeedingProgramLine` -- no actual Sowing linked."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]
    tenant, user, farm, crop, variety = _committed_tenant_farm_crop(session, suffix)

    kg_uom = next(u for u in unit_of_measure_service.list_uoms(session) if u.code == "kg")
    seed_uom = next(u for u in unit_of_measure_service.list_uoms(session) if u.code == "SEED")
    requirement = planning_service.create_production_requirement(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        crop_id=crop.id, variety_id=variety.id, required_by_date=date(2026, 10, 15),
        required_quantity=Decimal("30000"), quantity_uom_id=kg_uom.id, reference=None, notes=None,
    )
    line = planning_service.create_seeding_program_line(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        production_requirement_id=requirement.id, client_command_id=uuid.uuid4(), planned_sow_date=date(2026, 9, 1),
        crop_id=crop.id, variety_id=variety.id, planned_quantity=Decimal("20000"),
        planned_quantity_uom_id=seed_uom.id, expected_coverage_quantity=Decimal("10000"),
        expected_coverage_uom_id=kg_uom.id, notes=None,
    )

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "requirement_id": requirement.id,
        "line_id": line.id,
    }
    session.close()
    conn.close()
    return result


def build_linked_sowing_scenario(test_engine):
    """A committed `ProductionRequirement` + `SeedingProgramLine`, plus one
    real Crop Batch/`SowingEvent` whose `seeding_program_line_id` actually
    references it -- the deepest downgrade-guard case (a real Sowing's own
    provenance link, not just planning-side rows)."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]
    tenant, user, farm, crop, variety = _committed_tenant_farm_crop(session, suffix)

    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ps-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"wf-{suffix}", name="Migration Workflow",
    )
    version = workflow_service.create_draft_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code=None, is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=complete.id, code="ADVANCE", name="Advance",
    )
    workflow_service.publish_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"lot-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier = carrier_service.register_carrier(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code=f"ST-{suffix}-0001", issued_date=None,
    )

    kg_uom = next(u for u in unit_of_measure_service.list_uoms(session) if u.code == "kg")
    seed_uom = next(u for u in unit_of_measure_service.list_uoms(session) if u.code == "SEED")
    requirement = planning_service.create_production_requirement(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        crop_id=crop.id, variety_id=variety.id, required_by_date=date(2026, 10, 15),
        required_quantity=Decimal("30000"), quantity_uom_id=kg_uom.id, reference=None, notes=None,
    )
    line = planning_service.create_seeding_program_line(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        production_requirement_id=requirement.id, client_command_id=uuid.uuid4(), planned_sow_date=date(2026, 9, 1),
        crop_id=crop.id, variety_id=variety.id, planned_quantity=Decimal("20000"),
        planned_quantity_uom_id=seed_uom.id, expected_coverage_quantity=Decimal("10000"),
        expected_coverage_uom_id=kg_uom.id, notes=None,
    )
    event = sowing_service.sow_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=now(), note=None,
        lines=[{"carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": 100, "seed_count": 100}],
        seeding_program_line_id=line.id,
    )
    assert event.seeding_program_line_id == line.id

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "requirement_id": requirement.id,
        "line_id": line.id, "batch_id": batch.id, "sowing_event_id": event.id,
    }
    session.close()
    conn.close()
    return result


def cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM sowing_event_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_carrier_assignments WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM seeding_program_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM production_requirements WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM seed_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        if conn.execute(text("SELECT to_regclass('carrier_specifications')")).scalar() is not None:
            conn.execute(text("DELETE FROM carrier_specifications WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_runs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crop_batches WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_stages WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_versions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflows WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM production_systems WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM varieties WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crops WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    except Exception:
        trans.rollback()
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        raise
    else:
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()
