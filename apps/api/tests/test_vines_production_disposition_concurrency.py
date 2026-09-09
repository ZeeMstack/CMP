"""VINES-OPS-002: real two-connection concurrency proofs for Vines Grow
Cube disposition, mirroring `test_production_disposition_concurrency.py`'s
own established pattern exactly (committed setup via a dedicated connection,
`threading.Barrier(2)`, two worker threads each with their OWN
`test_engine.connect()`/`Session`).

A. two operators race to dispose the SAME Grow Cube -> exactly one succeeds.
B. two operators dispose DIFFERENT Grow Cubes in the SAME Grow Bag
   concurrently -> both succeed, population correctly reflects both losses.
C. a loss races another biological command affecting the same plant (a
   second, different-reason disposition of the same Grow Cube) -> no
   negative/double-consumed population -- same mechanism as A, proven with a
   different reason_code to rule out a fingerprint-replay false pass."""
import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.production_disposition_event import ProductionDispositionEvent
from app.models.production_disposition_event_grow_cube import ProductionDispositionEventGrowCube
from app.services import production_disposition_service, vines_production_transfer_service


def _build_committed_scenario(test_engine, **scenario_kwargs):
    from app.services import farm_service, membership_service, tenant_service, user_service

    from tests._vines_production_scenario import build_vines_production_ready_scenario

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"vd-race-{suffix}", name="Vines Disposition Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="vd-race", oidc_subject=suffix, email=f"vd-race-{suffix}@example.com",
        display_name="Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s = build_vines_production_ready_scenario(session, tenant, user, farm, suffix=suffix, **scenario_kwargs)
    transfer = vines_production_transfer_service.record_vines_production_transfer(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
        source_intervines_table_id=s["intervines_table_id"], plant_count=scenario_kwargs["intervines_plant_count"],
        destination_grow_gutter_id=s["grow_gutter_id"], grow_bag_specification_id=s["grow_bag_specification"].id,
    )
    session.commit()

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": s["batch"].id,
        "loss_time": s["entry_time"] + timedelta(hours=3),
        "bag_assignment_ids": [gb.destination_batch_carrier_assignment_id for gb in transfer.grow_bags],
        "source_grow_cube_ids": [c.id for c in transfer.source_grow_cubes],
    }
    session.close()
    conn.close()
    return result


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    from tests._traceability_scenario import cleanup_traceability_scenario

    cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
@pytest.mark.parametrize("attempt", range(5))
def test_proof_a_concurrent_dispose_same_grow_cube_exactly_one_succeeds(test_engine, attempt) -> None:
    scenario = _build_committed_scenario(
        test_engine, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1, gutter_bag_positions=1,
    )
    try:
        bag_assignment_id = scenario["bag_assignment_ids"][0]
        gc_id = scenario["source_grow_cube_ids"][0]
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def worker(name: str) -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                command = production_disposition_service.record_grow_cube_disposition(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    batch_carrier_assignment_id=bag_assignment_id, grow_cube_carrier_ids=[gc_id],
                    reason_code="dead", effective_time=scenario["loss_time"], note=None,
                )
                results[name] = ("ok", command.id)
            except Exception as exc:  # pragma: no cover -- includes expected already-disposed rejection
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
            gc_rows = verify_session.execute(
                select(ProductionDispositionEventGrowCube).where(
                    ProductionDispositionEventGrowCube.grow_cube_carrier_id == gc_id
                )
            ).scalars().all()
            assert len(gc_rows) == 1
            living = production_disposition_service.get_current_living_population(
                verify_session, root_batch_carrier_assignment_id=bag_assignment_id
            )
            assert living == 0
            assert living >= 0
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])


@pytest.mark.integration
@pytest.mark.parametrize("attempt", range(3))
def test_proof_b_concurrent_dispose_different_grow_cubes_same_bag_both_succeed(test_engine, attempt) -> None:
    scenario = _build_committed_scenario(
        test_engine, intervines_plant_count=2, grow_bag_capacity=2, grow_bag_count=1, gutter_bag_positions=1,
    )
    try:
        bag_assignment_id = scenario["bag_assignment_ids"][0]
        gc_a, gc_b = scenario["source_grow_cube_ids"][0], scenario["source_grow_cube_ids"][1]
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def worker(name: str, gc_id: uuid.UUID) -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                command = production_disposition_service.record_grow_cube_disposition(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    batch_carrier_assignment_id=bag_assignment_id, grow_cube_carrier_ids=[gc_id],
                    reason_code="dead", effective_time=scenario["loss_time"], note=None,
                )
                results[name] = ("ok", command.id)
            except Exception as exc:  # pragma: no cover
                results[name] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=worker, args=("a", gc_a))
        t_b = threading.Thread(target=worker, args=("b", gc_b))
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes == ["ok", "ok"], results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            living = production_disposition_service.get_current_living_population(
                verify_session, root_batch_carrier_assignment_id=bag_assignment_id
            )
            assert living == 0  # both of the bag's 2 plants correctly consumed, never double-counted
            reduction_events = verify_session.execute(
                select(ProductionDispositionEvent).where(
                    ProductionDispositionEvent.population_root_batch_carrier_assignment_id == bag_assignment_id,
                    ProductionDispositionEvent.event_kind == "REDUCTION",
                )
            ).scalars().all()
            assert len(reduction_events) == 2
            disposed_ids = {
                r for (r,) in verify_session.execute(
                    select(ProductionDispositionEventGrowCube.grow_cube_carrier_id).where(
                        ProductionDispositionEventGrowCube.production_disposition_event_id.in_(
                            [e.id for e in reduction_events]
                        )
                    )
                ).all()
            }
            assert disposed_ids == {gc_a, gc_b}
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])


@pytest.mark.integration
@pytest.mark.parametrize("attempt", range(5))
def test_proof_c_second_disposition_of_same_plant_with_different_reason_still_rejected(test_engine, attempt) -> None:
    """Same mechanism as Proof A, using two DIFFERENT reason_codes so a
    fingerprint-based idempotent-replay short-circuit could never produce a
    false "both ok" pass -- the second, distinct command must still be
    rejected as an already-disposed Grow Cube, never a double-consumed
    population."""
    scenario = _build_committed_scenario(
        test_engine, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1, gutter_bag_positions=1,
    )
    try:
        bag_assignment_id = scenario["bag_assignment_ids"][0]
        gc_id = scenario["source_grow_cube_ids"][0]
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def worker(name: str, reason_code: str) -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                command = production_disposition_service.record_grow_cube_disposition(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    batch_carrier_assignment_id=bag_assignment_id, grow_cube_carrier_ids=[gc_id],
                    reason_code=reason_code, effective_time=scenario["loss_time"], note=None,
                )
                results[name] = ("ok", command.id)
            except Exception as exc:  # pragma: no cover -- includes expected already-disposed rejection
                results[name] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=worker, args=("a", "dead"))
        t_b = threading.Thread(target=worker, args=("b", "disease_removal"))
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("error") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            living = production_disposition_service.get_current_living_population(
                verify_session, root_batch_carrier_assignment_id=bag_assignment_id
            )
            assert living == 0
            assert living >= 0
            gc_rows = verify_session.execute(
                select(ProductionDispositionEventGrowCube).where(
                    ProductionDispositionEventGrowCube.grow_cube_carrier_id == gc_id
                )
            ).scalars().all()
            assert len(gc_rows) == 1
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])
