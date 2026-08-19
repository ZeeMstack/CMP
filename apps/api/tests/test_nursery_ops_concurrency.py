"""NURSERY-OPS-001 sections 19-20/44D-E/45: deterministic concurrency
proofs for the atomic Sowing command. Like
test_farm_setup_idempotency_concurrency.py and
test_occupancy_capacity_concurrency.py, uses independent DB connections/
sessions (never a shared, rollback-only `db_session`) and
`threading.Barrier` for start synchronization -- no sleeps."""
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.farm_setup import GreenhouseSetupCreate, NurserySectionConfig, NurserySetupConfig
from app.services import carrier_service, crop_service, farm_setup_service, nursery_service, production_system_service, sowing_service, workflow_service
from app.services.errors import CarrierAlreadyAssignedError, SowingCommandReusedWithDifferentPayloadError
from tests._traceability_scenario import cleanup_traceability_scenario
from tests.conftest import ensure_seed_tray_specification


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine, *, tray_count=4):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    from app.services import farm_service, membership_service, tenant_service, user_service

    tenant = tenant_service.create_tenant(session, code=f"nurs-conc-{suffix}", name="Nursery Concurrency Tenant")
    user = user_service.create_user(
        session, oidc_issuer="nurs-conc", oidc_subject=suffix, email=f"nurs-conc-{suffix}@example.com",
        display_name="Nursery Conc User",
    )
    membership_service.add_membership(session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Nursery Conc Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )

    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}", common_name="Iceberg Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}", name="Mamutik",
        supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Nursery Tray", description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Iceberg Nursery",
    )
    version = workflow_service.create_draft_version(session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id)
    seeding_stage = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding", expected_duration_minutes=None,
        permitted_location_type_code=None, required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete_stage = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed", expected_duration_minutes=None,
        permitted_location_type_code=None, required_carrier_type_code=None, is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding_stage.id, to_stage_id=complete_stage.id, code="ADVANCE-1", name="Advance 1",
    )
    workflow_service.publish_version(session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id)

    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None, received_date=None, expiry_date=None,
    )
    setup = farm_setup_service.create_greenhouse_setup(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"NUR-{suffix}", name="Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(seeding_station=NurserySectionConfig(code=f"SEED-{suffix}")),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    seeding_station_id = structure.nursery_seeding_stations[0].id

    seed_tray_spec = ensure_seed_tray_specification(session, tenant_id=tenant.id, actor_user_id=user.id)
    carriers = [
        carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id,
            code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, tray_count + 1)
    ]

    session.commit()
    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "seed_lot_id": seed_lot.id,
        "seeding_station_id": seeding_station_id, "carrier_ids": [c.id for c in carriers],
    }
    session.close()
    conn.close()
    return result


def _sow_worker(test_engine, results, name, *, tenant_id, farm_id, user_id, client_command_id, seed_lot_id, seeding_station_id, carrier_ids, effective_time, barrier):
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        event = nursery_service.sow_new_batch(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
            client_command_id=client_command_id, seed_lot_id=seed_lot_id, seeding_station_id=seeding_station_id,
            seeding_machine_id=None, effective_time=effective_time, note=None,
            trays=[{"carrier_id": cid, "sown_site_count": 100, "seeds_sown": 100} for cid in carrier_ids],
        )
        results[name] = ("ok", event.batch_id)
    except SowingCommandReusedWithDifferentPayloadError as exc:
        session.rollback()
        results[name] = ("reused_conflict", str(exc))
    except CarrierAlreadyAssignedError as exc:
        session.rollback()
        results[name] = ("tray_conflict", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


def _run_pair(test_engine, *, scenario, ccid_a, ccid_b, carriers_a, carriers_b, effective_time):
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    t_a = threading.Thread(
        target=_sow_worker, args=(test_engine, results, "a"),
        kwargs=dict(
            tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
            client_command_id=ccid_a, seed_lot_id=scenario["seed_lot_id"], seeding_station_id=scenario["seeding_station_id"],
            carrier_ids=carriers_a, effective_time=effective_time, barrier=barrier,
        ),
    )
    t_b = threading.Thread(
        target=_sow_worker, args=(test_engine, results, "b"),
        kwargs=dict(
            tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
            client_command_id=ccid_b, seed_lot_id=scenario["seed_lot_id"], seeding_station_id=scenario["seeding_station_id"],
            carrier_ids=carriers_b, effective_time=effective_time, barrier=barrier,
        ),
    )
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)
    assert not t_a.is_alive() and not t_b.is_alive()
    return results


@pytest.mark.integration
def test_concurrent_identical_command_id_and_payload_resolves_to_single_batch(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, tray_count=2)
    try:
        ccid = uuid.uuid4()
        effective_time = _now()
        results = _run_pair(
            test_engine, scenario=scenario, ccid_a=ccid, ccid_b=ccid,
            carriers_a=scenario["carrier_ids"], carriers_b=scenario["carrier_ids"], effective_time=effective_time,
        )
        assert results["a"][0] == "ok", results
        assert results["b"][0] == "ok", results
        assert results["a"][1] == results["b"][1], "both calls must resolve to the SAME crop batch"

        check_conn = test_engine.connect()
        try:
            batch_count = check_conn.execute(
                text("SELECT COUNT(*) FROM crop_batches WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]}
            ).scalar_one()
            event_count = check_conn.execute(
                text("SELECT COUNT(*) FROM sowing_events WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]}
            ).scalar_one()
            assignment_count = check_conn.execute(
                text("SELECT COUNT(*) FROM batch_carrier_assignments WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]}
            ).scalar_one()
        finally:
            check_conn.close()
        assert batch_count == 1, "no duplicate Crop Batch may be created"
        assert event_count == 1, "exactly one logical Sowing command may exist for this client_command_id"
        assert assignment_count == 2, "exactly one set of tray allocations may exist"
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_identical_command_id_different_payload_never_produces_two_batches(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, tray_count=2)
    try:
        ccid = uuid.uuid4()
        effective_time = _now()
        results = _run_pair(
            test_engine, scenario=scenario, ccid_a=ccid, ccid_b=ccid,
            carriers_a=[scenario["carrier_ids"][0]], carriers_b=[scenario["carrier_ids"][1]],
            effective_time=effective_time,
        )
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("reused_conflict") == 1, results

        check_conn = test_engine.connect()
        try:
            batch_count = check_conn.execute(
                text("SELECT COUNT(*) FROM crop_batches WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]}
            ).scalar_one()
        finally:
            check_conn.close()
        assert batch_count == 1, "only the winning payload's Crop Batch may exist"
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_different_commands_claiming_the_same_tray_exactly_one_wins(test_engine) -> None:
    """Section 20/45: two DIFFERENT Sowing commands (different
    client_command_id, so NOT serialized by the advisory lock) both try to
    claim the SAME Seed Tray. Exactly one may succeed; the DB-level
    exclusivity (`ux_batch_carrier_assignments_active_carrier`) is the
    ultimate backstop behind `_sow_batch_core`'s own row-locking."""
    scenario = _build_committed_scenario(test_engine, tray_count=1)
    try:
        shared_tray = scenario["carrier_ids"][0]
        effective_time = _now()
        results = _run_pair(
            test_engine, scenario=scenario, ccid_a=uuid.uuid4(), ccid_b=uuid.uuid4(),
            carriers_a=[shared_tray], carriers_b=[shared_tray], effective_time=effective_time,
        )
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("tray_conflict") == 1, results

        check_conn = test_engine.connect()
        try:
            active_count = check_conn.execute(
                text(
                    "SELECT COUNT(*) FROM batch_carrier_assignments WHERE tenant_id = :tid "
                    "AND carrier_id = :cid AND released_effective_time IS NULL"
                ),
                {"tid": scenario["tenant_id"], "cid": shared_tray},
            ).scalar_one()
            batch_count = check_conn.execute(
                text("SELECT COUNT(*) FROM crop_batches WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]}
            ).scalar_one()
        finally:
            check_conn.close()
        assert active_count == 1, "never two active allocations for the same tray"
        assert batch_count == 1, "only the winning command's Crop Batch may exist"
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])
