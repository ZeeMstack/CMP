"""Real two-connection concurrency tests for CMP-014, mirroring
test_harvest_concurrency.py: committed setup data via a dedicated
connection so two independent sessions can genuinely race, with cleanup
bypassing append-only/no-delete triggers via `session_replication_role =
replica`, scoped to this test only, hardened with the `cmp_test` guard and
explicit `DEFAULT` restore."""
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    farm_service,
    harvest_service,
    membership_service,
    produce_lot_ledger_service,
    production_system_service,
    sowing_service,
    tenant_service,
    user_service,
    workflow_service,
)
from app.services.errors import DuplicateProduceLotCodeError


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine, *, carrier_count=4):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"ledger-race-{suffix}", name="Ledger Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="ledger-race", oidc_subject=suffix, email=f"ledger-race-{suffix}@example.com",
        display_name="Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"var-{suffix}",
        name="Variety", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ps-{suffix}", name="System", description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"wf-{suffix}", name="Workflow",
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
    harvesting = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="HARVESTING", name="Harvesting", display_order=1, stage_category="harvesting",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=harvesting.id, code="ADV-1", name="Advance 1",
    )
    workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=harvesting.id, to_stage_id=complete.id, code="ADV-2", name="Advance 2",
    )
    workflow_service.publish_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"batch-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"lot-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    carriers = [
        carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"tray-{suffix}-{n}", issued_date=None,
        )
        for n in range(carrier_count)
    ]
    sowing_service.sow_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[
            {"carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 50, "seed_count": 50, "line_note": None}
            for c in carriers
        ],
    )
    assignments = sowing_service.list_batch_carriers(session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_by_carrier = {a.carrier.code: a.id for a in assignments}
    assignment_ids = [assignment_by_carrier[c.code] for c in carriers]

    crop_batch_service.transition_stage(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=_now(), reason=None,
    )

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": batch.id,
        "assignment_ids": assignment_ids, "suffix": suffix,
    }
    session.close()
    conn.close()
    return result


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup (session_replication_role) against "
            f"database {current_db!r}; this cleanup is only permitted against 'cmp_test'"
        )

    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvested_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_event_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_carrier_assignments WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM seed_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
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


@pytest.mark.integration
def test_concurrent_duplicate_harvest_command_creates_one_receipt(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, carrier_count=1)
    aid = scenario["assignment_ids"][0]
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()
    command_id = uuid.uuid4()
    lot_code = f"RACE-{scenario['suffix']}"

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = harvest_service.record_harvest(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=command_id,
                effective_time=effective_time, produce_lot_code=lot_code, note=None,
                source_lines=[{"batch_carrier_assignment_id": aid, "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
            )
            results[name] = ("ok", event.id)
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a",))
    t_b = threading.Thread(target=worker, args=("b",))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        assert results["a"][0] == "ok" and results["b"][0] == "ok", results
        assert results["a"][1] == results["b"][1]

        with test_engine.connect() as verify_conn:
            receipt_count = verify_conn.execute(
                text("SELECT count(*) FROM produce_lot_ledger_entries WHERE harvest_event_id = :eid"),
                {"eid": results["a"][1]},
            ).scalar_one()
        assert receipt_count == 1, "both racing callers of the same command id must see exactly one receipt"
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_same_lot_code_leaves_exactly_one_receipt(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, carrier_count=2)
    aids = scenario["assignment_ids"]
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()
    lot_code = f"COLLIDE-{scenario['suffix']}"

    def worker(name: str, aid: uuid.UUID) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = harvest_service.record_harvest(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, produce_lot_code=lot_code, note=None,
                source_lines=[{"batch_carrier_assignment_id": aid, "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
            )
            results[name] = ("ok", event.id)
        except DuplicateProduceLotCodeError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", aids[0]))
    t_b = threading.Thread(target=worker, args=("b", aids[1]))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results

        winner = results["a"] if results["a"][0] == "ok" else results["b"]
        with test_engine.connect() as verify_conn:
            total_receipts = verify_conn.execute(
                text(
                    "SELECT count(*) FROM produce_lot_ledger_entries r "
                    "JOIN harvest_events e ON e.id = r.harvest_event_id "
                    "WHERE e.batch_id = :bid"
                ),
                {"bid": scenario["batch_id"]},
            ).scalar_one()
        assert total_receipts == 1, "only the winning harvest may leave a receipt behind"
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_ledger_reads_unaffected_by_concurrent_unrelated_harvest(test_engine) -> None:
    """A background thread repeatedly reads an existing lot's ledger/balance
    while a foreground thread commits a brand-new, unrelated harvest on the
    same batch — proves reads never block on or are corrupted by a
    concurrent write to a different lot."""
    scenario = _build_committed_scenario(test_engine, carrier_count=2)
    aids = scenario["assignment_ids"]

    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    existing_event = harvest_service.record_harvest(
        setup_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
        effective_time=_now(), produce_lot_code=f"EXIST-{scenario['suffix']}", note=None,
        source_lines=[{"batch_carrier_assignment_id": aids[0], "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
    )
    existing_lot_id = setup_session.execute(
        text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": existing_event.id}
    ).scalar_one()
    setup_session.close()
    setup_conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    stop = threading.Event()

    def reader() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            reads = 0
            while not stop.wait(timeout=0.01) and reads < 200:
                balance = produce_lot_ledger_service.get_balance(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    produce_lot_id=existing_lot_id,
                )
                assert balance.entry_count == 1
                assert balance.available_weight_kg == Decimal("1.000")
                reads += 1
            results["reader"] = ("ok", reads)
        except Exception as exc:  # pragma: no cover
            results["reader"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def writer() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = harvest_service.record_harvest(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=_now(), produce_lot_code=f"NEW-{scenario['suffix']}", note=None,
                source_lines=[{"batch_carrier_assignment_id": aids[1], "harvested_weight_kg": Decimal("2.000"), "whole_unit_count": None, "note": None}],
            )
            results["writer"] = ("ok", event.id)
        except Exception as exc:  # pragma: no cover
            results["writer"] = ("error", repr(exc))
        finally:
            stop.set()
            session.close()
            conn.close()

    t_reader = threading.Thread(target=reader)
    t_writer = threading.Thread(target=writer)
    t_reader.start()
    t_writer.start()
    t_reader.join(timeout=15)
    t_writer.join(timeout=15)

    try:
        assert not t_reader.is_alive() and not t_writer.is_alive()
        assert results["writer"][0] == "ok", results
        assert results["reader"][0] == "ok", results
        assert results["reader"][1] > 0, "the reader must have completed at least one read during the race"
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])
