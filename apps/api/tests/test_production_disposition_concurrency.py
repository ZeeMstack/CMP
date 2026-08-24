"""LEAFY-OPS-001 BUILD section 21: real two-connection concurrency proof for
Production Biological Disposition, mirroring `test_seedling_disposition_
concurrency.py`'s established pattern exactly: committed setup data via a
dedicated connection, `threading.Barrier(2)`, two worker threads each with
their OWN `test_engine.connect()`/`Session`."""
import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.production_disposition_event import ProductionDispositionEvent
from app.services import production_disposition_service

pytestmark = pytest.mark.integration


def _build_committed_plate_scenario(test_engine, *, opening_count=5):
    from app.services import farm_service, membership_service, tenant_service, user_service

    from tests.test_leafy_production_transfer import (
        _leafy_setup, _nursery_plate_source_scenario, _production_plates, _record, _simple_allocation,
        _simple_destination, _simple_source,
    )

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"pd-race-{suffix}", name="Production Disposition Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="pd-race", oidc_subject=suffix, email=f"pd-race-{suffix}@example.com",
        display_name="Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s, aids = _nursery_plate_source_scenario(session, tenant, user, farm, suffix=suffix, opening_count=opening_count)
    table_ids = _leafy_setup(session, tenant, user, farm, suffix=suffix)
    plates, _spec = _production_plates(session, tenant, user, farm, suffix=suffix, count=1)
    result = _record(
        session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=opening_count)],
        [_simple_allocation(aids[0], plates[0].id, opening_count)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )
    root_id = result.destination_lines[0].destination_batch_carrier_assignment_id
    session.commit()

    out = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": s["batch"].id,
        "root_id": root_id, "et": s["transfer_ready_time"] + timedelta(hours=2),
    }
    session.close()
    conn.close()
    return out


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    from tests._traceability_scenario import cleanup_traceability_scenario

    cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_reductions_racing_below_zero(test_engine, attempt) -> None:
    """current = 5. Operator A records loss 4; Operator B simultaneously
    records loss 4. Only one may succeed -- the other must be rejected,
    never both, and the final authoritative population must never go
    negative."""
    scenario = _build_committed_plate_scenario(test_engine, opening_count=5)
    try:
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def worker(name: str) -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                command = production_disposition_service.record_disposition(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    batch_carrier_assignment_id=scenario["root_id"], plant_loss_count=4, reason_code="dead",
                    effective_time=scenario["et"], note=None,
                )
                results[name] = ("ok", command.id)
            except Exception as exc:  # pragma: no cover -- includes expected balance rejection
                results[name] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=worker, args=("a",))
        t_b = threading.Thread(target=worker, args=("b",))
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            events = verify_session.execute(
                select(ProductionDispositionEvent).where(
                    ProductionDispositionEvent.population_root_batch_carrier_assignment_id == scenario["root_id"]
                )
            ).scalars().all()
            assert len(events) == 1
            living = production_disposition_service.get_current_living_population(
                verify_session, root_batch_carrier_assignment_id=scenario["root_id"]
            )
            assert living == 1
            assert living >= 0
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_corrections_of_same_target_race(test_engine, attempt) -> None:
    """Two concurrent CORRECT commands targeting the exact same
    zero-exhausting REDUCTION -- must never both succeed; exactly one
    restoration BCA must ever exist for this target."""
    scenario = _build_committed_plate_scenario(test_engine, opening_count=5)
    conn0 = test_engine.connect()
    session0 = Session(bind=conn0)
    exhaust = production_disposition_service.record_disposition(
        session0, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), batch_carrier_assignment_id=scenario["root_id"], plant_loss_count=5,
        reason_code="dead", effective_time=scenario["et"], note=None,
    )
    target_event = session0.execute(
        select(ProductionDispositionEvent).where(ProductionDispositionEvent.command_id == exhaust.id)
    ).scalar_one()
    target_event_id = target_event.id
    session0.commit()
    session0.close()
    conn0.close()

    try:
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def worker(name: str) -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                command = production_disposition_service.correct_disposition(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    target_event_id=target_event_id, corrected=None,
                )
                results[name] = ("ok", command.id)
            except Exception as exc:  # pragma: no cover -- includes expected already-corrected rejection
                results[name] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=worker, args=("a",))
        t_b = threading.Thread(target=worker, args=("b",))
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            restored = verify_session.execute(
                select(BatchCarrierAssignment).where(
                    BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == scenario["root_id"]
                )
            ).scalars().all()
            assert len(restored) == 1
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])
