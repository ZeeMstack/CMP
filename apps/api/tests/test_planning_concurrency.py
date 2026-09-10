"""PLANNING-OPS-001 focused concurrency proof (scenario B from the ticket):
two DIFFERENT, legitimate actual Sowings (different batches, different
carriers) racing to link to the SAME Seeding Program Line must both
succeed -- a plan line is guidance, never a hard consumption/capacity
constraint (the ticket explicitly says not to fabricate one). Mirrors
`test_sowing_concurrency.py`'s real two-connection thread/barrier
infrastructure exactly."""
import threading
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.sowing_event import SowingEvent
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


def _now():
    return datetime.now(timezone.utc)


def _build_planning_committed_scenario(test_engine):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"plan-race-{suffix}", name="Plan Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="plan-race", oidc_subject=suffix, email=f"plan-race-{suffix}@example.com",
        display_name="Plan Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Plan Race Farm",
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
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ps-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"wf-{suffix}", name="Race Workflow",
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
    batches = [
        crop_batch_service.create_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            code=f"BATCH-{suffix}-{n}", workflow_id=workflow.id, effective_time=_now(),
        )
        for n in range(1, 3)
    ]
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"lot-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(session, tenant_id=tenant.id, actor_user_id=user.id)
    carriers = [
        carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id, code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, 3)
    ]

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
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id,
        "batch_ids": [b.id for b in batches], "seed_lot_id": seed_lot.id,
        "carrier_ids": [c.id for c in carriers], "line_id": line.id, "requirement_id": requirement.id,
    }
    session.close()
    conn.close()
    return result


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
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
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


def _line(carrier_id, seed_lot_id):
    return {"carrier_id": carrier_id, "seed_lot_id": seed_lot_id, "sown_site_count": 200, "seed_count": 200}


@pytest.mark.integration
def test_concurrent_sowings_of_different_batches_both_link_to_same_plan_line(test_engine) -> None:
    """Scenario B: two legitimate, DIFFERENT Sowing commands (different
    batches, different carriers, no shared exclusivity constraint) racing
    to reference the same Seeding Program Line must BOTH succeed -- the
    plan line is guidance only, never a hard capacity gate CMP would have
    to fabricate."""
    scenario = _build_planning_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()

    def worker(name: str, batch_id, carrier_id) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = sowing_service.sow_batch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=batch_id, client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None,
                lines=[_line(carrier_id, scenario["seed_lot_id"])],
                seeding_program_line_id=scenario["line_id"],
            )
            results[name] = ("ok", event.id)
        except Exception as exc:  # pragma: no cover - surfaced via assertion below
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", scenario["batch_ids"][0], scenario["carrier_ids"][0]))
    t_b = threading.Thread(target=worker, args=("b", scenario["batch_ids"][1], scenario["carrier_ids"][1]))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        assert results["a"][0] == "ok", results
        assert results["b"][0] == "ok", results

        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            linked_count = session.execute(
                select(SowingEvent).where(SowingEvent.seeding_program_line_id == scenario["line_id"])
            ).scalars().all()
            assert len(linked_count) == 2
            assert {e.batch_id for e in linked_count} == set(scenario["batch_ids"])
        finally:
            session.close()
            conn.close()
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])
