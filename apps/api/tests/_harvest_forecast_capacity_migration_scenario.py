"""Shared, non-collected scenario builders for PILOT-PLAN-001A migration
proofs (`tests/test_harvest_forecast_capacity_migration.py`). Same
committed-connection + `session_replication_role`-guarded cleanup pattern
`tests/_planning_migration_scenario.py` established. Not a test file
itself (pytest's default `test_*.py` discovery glob does not match this
name)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    capacity_plan_service,
    crop_batch_service,
    crop_service,
    farm_service,
    harvest_forecast_service,
    location_service,
    membership_service,
    production_system_service,
    tenant_service,
    unit_of_measure_service,
    user_service,
    workflow_service,
)


def _now():
    return datetime.now(timezone.utc)


def require_cmp_test(test_engine) -> None:
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup (session_replication_role) against "
            f"database {current_db!r}; this cleanup is only permitted against 'cmp_test'"
        )


def _committed_tenant_farm(session, suffix):
    tenant = tenant_service.create_tenant(session, code=f"plan-cap-mig-{suffix}", name="Forecast Migration Tenant")
    user = user_service.create_user(
        session, oidc_issuer="plan-cap-mig", oidc_subject=suffix, email=f"plan-cap-mig-{suffix}@example.com",
        display_name="Forecast Migration User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Forecast Migration Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    return tenant, user, farm


def build_batch_harvest_forecast_scenario(test_engine):
    """The lightest possible PLAN-001A forecast history: one committed
    Crop Batch and one committed `BatchHarvestForecast` row."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]
    tenant, user, farm = _committed_tenant_farm(session, suffix)

    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"var-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ps-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"wf-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id)
    seeding = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=complete.id, code="ADVANCE", name="Advance",
    )
    workflow_service.publish_version(session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id)
    batch = crop_batch_service.create_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"batch-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )

    kg_uom = next(u for u in unit_of_measure_service.list_uoms(session) if u.code == "kg")
    forecast = harvest_forecast_service.record_batch_harvest_forecast(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), window_start_date=date(2026, 9, 20), window_end_date=date(2026, 9, 25),
        low_quantity=Decimal("900"), expected_quantity=Decimal("1000"), high_quantity=Decimal("1100"),
        quantity_uom_id=kg_uom.id, basis="grower_estimate", effective_time=_now(), notes=None, revision_reason=None,
    )

    result = {"tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "forecast_id": forecast.id}
    session.close()
    conn.close()
    return result


def build_capacity_allocation_scenario(test_engine):
    """The lightest possible PLAN-001A capacity history: one committed
    Location (with configured capacity) and one committed
    `ProductionCapacityAllocation` row."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]
    tenant, user, farm = _committed_tenant_farm(session, suffix)

    greenhouse = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="greenhouse",
        code=f"gh-{suffix}", name="GH", parent_location_id=None, greenhouse_classification="nursery",
        occupiable=None,
    )
    chamber = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="germination_chamber",
        code=f"gc-{suffix}", name="Chamber", parent_location_id=greenhouse.id, greenhouse_classification=None,
        occupiable=True, capacity=5,
    )
    allocation = capacity_plan_service.create_capacity_allocation(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        location_id=chamber.id, production_system_id=None, planned_start_date=date(2026, 10, 1),
        planned_end_date=date(2026, 10, 10), planned_capacity_amount=3, source_seeding_program_line_id=None,
        source_crop_batch_id=None, notes=None,
    )

    result = {"tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "allocation_id": allocation.id}
    session.close()
    conn.close()
    return result


def cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        for table in (
            "production_capacity_allocations",
            "batch_harvest_forecasts",
            "sowing_event_lines",
            "batch_carrier_assignments",
            "sowing_events",
            "seed_lots",
            "carriers",
            "batch_stage_runs",
            "batch_stage_transitions",
            "crop_batches",
            "workflow_transitions",
            "workflow_stages",
            "workflow_versions",
            "workflows",
            "production_systems",
            "varieties",
            "crops",
            "locations",
            "audit_events",
            "tenant_memberships",
            "farms",
        ):
            conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
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
