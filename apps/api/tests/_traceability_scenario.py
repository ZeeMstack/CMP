"""Shared, non-collected scenario helpers for CMP-019 traceability tests.
Builds a full crop/variety/workflow/batch/seed-lot/carrier scaffold (mirrors
tests/test_batch_derivation.py's own `_build_batch_with_assignments`), plus
harvest/pack/storage/dispatch convenience wrappers. Not a test file itself
(pytest's default `test_*.py` discovery glob does not match this name)."""
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    carrier_service,
    crop_service,
    crop_batch_service,
    dispatch_service,
    farm_service,
    finished_goods_storage_service,
    harvest_service,
    location_service,
    membership_service,
    packing_service,
    production_system_service,
    sowing_service,
    tenant_service,
    user_service,
    workflow_service,
)
from tests._packing_scenario import require_cmp_test


@contextmanager
def committed_connection(test_engine):
    """Yields a Session bound to a fresh connection, always closing both
    (session first, then connection) on the way out -- success or
    exception -- so a mid-scenario failure can never leave an open
    transaction behind to block a later `cleanup_traceability_scenario`
    call in the caller's own `finally`. Callers are still responsible for
    their own explicit `session.commit()` calls at whatever points their
    scenario needs them."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        yield session
    finally:
        session.close()
        conn.close()


def now():
    return datetime.now(timezone.utc)


def build_committed_tenant_farm(db: Session, *, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:10]
    tenant = tenant_service.create_tenant(db, code=f"trace-{suffix}", name="Traceability Tenant")
    user = user_service.create_user(
        db, oidc_issuer="trace", oidc_subject=suffix, email=f"trace-{suffix}@example.com", display_name="Trace User",
    )
    membership_service.add_membership(db, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
    farm = farm_service.create_farm(
        db, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Trace Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    return tenant, user, farm


def build_workflow_scaffold(db: Session, tenant, user, farm, *, suffix=None):
    """Crop/variety/production-system/workflow (SEEDING -> HARVESTING ->
    COMPLETE) -- published, ready for batches. Returns a dict reusable by
    `sow_new_batch` for one or more independent batches sharing the same
    workflow/version (required for `merge_batches`, which rejects sources
    that don't share workflow, version, and current stage)."""
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg", scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Nursery Tray", description=None,
    )
    workflow = workflow_service.register_workflow(
        db, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id)
    seeding = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    harvesting = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="HARVESTING", name="Harvesting", display_order=1, stage_category="harvesting",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=harvesting.id, code="ADV-1", name="Advance 1",
    )
    workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=harvesting.id, to_stage_id=complete.id, code="ADV-2", name="Advance 2",
    )
    workflow_service.publish_version(db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id)
    return {"crop": crop, "variety": variety, "workflow": workflow, "version": version, "transition_1": t1}


def sow_new_batch(db: Session, tenant, user, farm, scaffold: dict, *, carrier_count=2, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    crop, variety, workflow, t1 = scaffold["crop"], scaffold["variety"], scaffold["workflow"], scaffold["transition_1"]
    batch = crop_batch_service.create_batch(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    carriers = [
        carrier_service.register_carrier(
            db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, carrier_count + 1)
    ]
    sowing_service.sow_batch(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=now(), note=None,
        lines=[{"carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 20, "seed_count": 20, "line_note": None} for c in carriers],
    )
    assignments = sowing_service.list_batch_carriers(db, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_by_carrier_code = {a.carrier.code: a.id for a in assignments}
    assignment_ids = [assignment_by_carrier_code[c.code] for c in carriers]
    crop_batch_service.transition_stage(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=now(), reason=None,
    )
    return {
        "batch": batch, "seed_lot": seed_lot, "carriers": carriers, "assignment_ids": assignment_ids,
        **scaffold,
    }


def build_batch_with_assignments(db: Session, tenant, user, farm, *, carrier_count=2, suffix=None):
    """Convenience wrapper: a fresh workflow scaffold plus one batch sown
    under it -- the common single-batch case."""
    suffix = suffix or uuid.uuid4().hex[:8]
    scaffold = build_workflow_scaffold(db, tenant, user, farm, suffix=suffix)
    return sow_new_batch(db, tenant, user, farm, scaffold, carrier_count=carrier_count, suffix=suffix)


def harvest_all(db: Session, tenant, user, farm, *, batch_id, assignment_ids, weight_per_line=Decimal("5.000"), suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    event = harvest_service.record_harvest(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), effective_time=now(), produce_lot_code=f"HLOT-{suffix}", note=None,
        source_lines=[
            {"batch_carrier_assignment_id": aid, "harvested_weight_kg": weight_per_line, "whole_unit_count": None, "note": None}
            for aid in assignment_ids
        ],
    )
    lot_id = db.execute(
        __import__("sqlalchemy").text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": event.id}
    ).scalar_one()
    return event, lot_id


def pack_lot(db: Session, tenant, user, farm, *, produce_lot_id, weight=Decimal("5.000"), package_count=5, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    event = packing_service.record_packing(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=now(), finished_goods_lot_code=f"FG-{suffix}", package_count=package_count,
        packed_output_weight_kg=weight, process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"),
        note=None,
        input_lines=[{"harvested_produce_lot_id": produce_lot_id, "consumed_weight_kg": weight, "consumed_whole_unit_count": None, "note": None}],
    )
    detail = packing_service.get_packing_event(db, tenant_id=tenant.id, farm_id=farm.id, packing_event_id=event.id)
    return detail.finished_goods_lot.id, event.id


def pack_multi(db: Session, tenant, user, farm, *, produce_lot_ids_and_weights: list[tuple], package_count=5, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    total = sum(w for _, w in produce_lot_ids_and_weights)
    event = packing_service.record_packing(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=now(), finished_goods_lot_code=f"FG-{suffix}", package_count=package_count,
        packed_output_weight_kg=total, process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"),
        note=None,
        input_lines=[
            {"harvested_produce_lot_id": lot_id, "consumed_weight_kg": w, "consumed_whole_unit_count": None, "note": None}
            for lot_id, w in produce_lot_ids_and_weights
        ],
    )
    detail = packing_service.get_packing_event(db, tenant_id=tenant.id, farm_id=farm.id, packing_event_id=event.id)
    return detail.finished_goods_lot.id, event.id


def create_cold_store_position(db: Session, tenant, user, farm, *, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    cold_store = location_service.create_location(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="cold_store",
        code=f"CS-{suffix}", name="Cold Store", parent_location_id=None, greenhouse_classification=None, occupiable=None,
    )
    return location_service.create_location(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="cold_store_position",
        code=f"POS-{suffix}", name="Position", parent_location_id=cold_store.id, greenhouse_classification=None, occupiable=None,
    )


def place(db: Session, tenant, user, farm, *, finished_goods_lot_id, destination_location_id, weight=Decimal("2.000"), count=2):
    return finished_goods_storage_service.record_movement(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=now(), finished_goods_lot_id=finished_goods_lot_id, movement_kind="place",
        source_location_id=None, destination_location_id=destination_location_id, moved_weight_kg=weight,
        moved_package_count=count, note=None,
    )


def dispatch(db: Session, tenant, user, farm, *, finished_goods_lot_id, weight=Decimal("1.000"), count=1, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    return dispatch_service.record_dispatch(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=now(), code=f"DISP-{suffix}", external_reference=None, note=None,
        lines=[{"finished_goods_lot_id": finished_goods_lot_id, "dispatched_weight_kg": weight, "dispatched_package_count": count}],
    )


def cleanup_traceability_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    """Like `_packing_scenario.cleanup_scenario`, extended with the
    batch-derivation (split/merge) tables that scenario never needed to
    know about."""
    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM finished_goods_ledger_entries WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM finished_goods_storage_movements WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM dispatch_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM dispatch_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM packing_input_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM finished_goods_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM packing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvested_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM quality_hold_releases WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM quality_holds WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_event_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        # CMP-FE-002A: transplant_* tables are new to this shared cleanup --
        # earlier CMP-019 scenarios never called transplant_service. Without
        # these deletes, transplant_events/lines/allocations survive the
        # (session_replication_role=replica, FK-checks-disabled)
        # batch_carrier_assignments delete below as orphaned rows, which
        # then fail test_migrations.py's CMP-011 downgrade guard (it counts
        # live transplant rows, oblivious to orphaning). Allocations must
        # precede source/destination lines; both must precede events; all
        # three must precede batch_carrier_assignments.
        conn.execute(text("DELETE FROM transplant_allocations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_destination_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_assignment_transfers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_carrier_assignments WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM seed_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        # CMP-FE-002A: occupancies/movements are new to this shared cleanup --
        # earlier CMP-019 scenarios never created crop-batch-carrier
        # occupancy (only finished_goods_storage_movements, already handled
        # above). occupancies must precede movements (opened_by_movement_id
        # FK); both must precede carriers/locations.
        conn.execute(text("DELETE FROM occupancies WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM movements WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_runs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_derivation_sources WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_derivation_outputs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crop_batches WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_derivation_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_stages WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_versions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflows WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM production_systems WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM varieties WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crops WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM locations WHERE tenant_id = :tid"), {"tid": tenant_id})
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
