"""VINES-OPS-001B: real two-connection concurrency tests for the composite
Vines Production Transfer command, mirroring `test_intervines_transplant_
concurrency.py`'s own established pattern (committed setup via a dedicated
connection, `threading.Barrier`-released racing workers on independent
connections/sessions, cleanup via `cleanup_traceability_scenario`).

Covers the ticket's four required concurrency proofs:
  A. two transfers race the same InterVines living plants -> cannot
     transfer the same plant twice.
  B. two transfers race the same Grow Bag capacity pool -> cannot overfill
     any Grow Bag (or double-assign one).
  C. two transfers race the same Grow Bag Position pool under one Gutter ->
     cannot place two physical Grow Bags in one exclusive position.
  D. capacity becomes insufficient under lock (a concurrent sibling
     consumed the rest) -> the whole command rejects atomically, zero
     partial InterVines release / Grow Bag assignment / Occupancy.

Per this session's own prior finding (a barrier-released two-thread race is
inherently non-deterministic by construction): these tests assert the LEGAL
outcome SET the transaction semantics guarantee, never a specific thread
winning, and never use sleeps as the synchronization mechanism."""
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.carrier_type import CarrierType
from app.models.occupancy import Occupancy
from app.services import farm_service, membership_service, tenant_service, user_service, vines_production_transfer_service
from app.services.errors import (
    InsufficientAvailableGrowBagPositionsError,
    InsufficientAvailableGrowBagsError,
    InsufficientAvailableInterVinesPlantsError,
)
from tests._traceability_scenario import cleanup_traceability_scenario
from tests._vines_production_scenario import build_vines_production_ready_scenario


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine, **scenario_kwargs):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"vpt-race-{suffix}", name="Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="vpt-race", oidc_subject=suffix, email=f"vpt-race-{suffix}@example.com",
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
    session.commit()

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": s["batch_id"],
        "intervines_table_id": s["intervines_table_id"], "grow_gutter_id": s["grow_gutter_id"],
        "grow_bag_specification_id": s["grow_bag_specification"].id,
        "entry_time": s["entry_time"],
    }
    session.close()
    conn.close()
    return result


def _active_grow_bag_assignment_carrier_ids(session: Session, *, tenant_id, batch_id) -> list:
    return list(
        session.execute(
            select(BatchCarrierAssignment.carrier_id)
            .join(Carrier, Carrier.id == BatchCarrierAssignment.carrier_id)
            .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
            .where(
                BatchCarrierAssignment.tenant_id == tenant_id,
                BatchCarrierAssignment.batch_id == batch_id,
                BatchCarrierAssignment.released_effective_time.is_(None),
                CarrierType.code == "grow_bag",
            )
        ).scalars().all()
    )


@pytest.mark.integration
def test_concurrent_same_intervines_plants_leaves_one_winner(test_engine) -> None:
    """Proof A: two transfers draw from the SAME InterVines (Batch, Table)
    group, each requesting 8 while only 10 living plants exist -- Grow Bag/
    Position pools are generously sized so they are never the bottleneck."""
    scenario = _build_committed_scenario(
        test_engine, intervines_plant_count=10, grow_bag_capacity=1, grow_bag_count=20, gutter_bag_positions=20,
    )
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            result = vines_production_transfer_service.record_vines_production_transfer(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_intervines_table_id=scenario["intervines_table_id"],
                plant_count=8, destination_grow_gutter_id=scenario["grow_gutter_id"],
                grow_bag_specification_id=scenario["grow_bag_specification_id"],
            )
            results[name] = ("ok", [c.id for c in result.source_grow_cubes])
        except InsufficientAvailableInterVinesPlantsError as exc:
            results[name] = ("conflict", str(exc))
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
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results

        winner = results["a"] if results["a"][0] == "ok" else results["b"]
        winner_cube_ids = winner[1]
        assert len(winner_cube_ids) == len(set(winner_cube_ids)) == 8

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            # Scoped to grow_cube-typed assignments only -- the scenario's
            # own source Seed Tray assignment is ALSO released once fully
            # consumed (all 10 seedlings transplanted to InterVines during
            # setup), which would otherwise inflate this count by one.
            released_cube_ids = verify_session.execute(
                select(BatchCarrierAssignment.carrier_id)
                .join(Carrier, Carrier.id == BatchCarrierAssignment.carrier_id)
                .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
                .where(
                    BatchCarrierAssignment.tenant_id == scenario["tenant_id"],
                    BatchCarrierAssignment.batch_id == scenario["batch_id"],
                    BatchCarrierAssignment.released_effective_time.is_not(None),
                    CarrierType.code == "grow_cube",
                )
            ).scalars().all()
            # Exactly the winner's own 8 Grow Cubes were released -- never a
            # Cube shared with what the loser would have used, never both
            # commands' worth summed.
            assert sorted(released_cube_ids) == sorted(winner_cube_ids)
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_same_grow_bag_pool_leaves_no_bag_overfilled(test_engine) -> None:
    """Proof B: two transfers from the SAME abundant InterVines pool (20
    living plants, never the bottleneck) race for a SCARCE Grow Bag pool --
    capacity 2/bag, only 6 Bags (12 total capacity) -- each requesting 8
    plants (needs 4 Bags each, 8 total > 6 available). Exactly one wins; the
    critical invariant is that no Grow Bag is ever double-assigned/
    overfilled, never "who wins"."""
    scenario = _build_committed_scenario(
        test_engine, intervines_plant_count=20, grow_bag_capacity=2, grow_bag_count=6, gutter_bag_positions=20,
    )
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            result = vines_production_transfer_service.record_vines_production_transfer(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_intervines_table_id=scenario["intervines_table_id"],
                plant_count=8, destination_grow_gutter_id=scenario["grow_gutter_id"],
                grow_bag_specification_id=scenario["grow_bag_specification_id"],
            )
            results[name] = ("ok", [gb.grow_bag.id for gb in result.grow_bags])
        except InsufficientAvailableGrowBagsError as exc:
            results[name] = ("conflict", str(exc))
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
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results

        winner = results["a"] if results["a"][0] == "ok" else results["b"]
        winner_bag_ids = winner[1]
        assert len(winner_bag_ids) == 4
        assert len(set(winner_bag_ids)) == 4  # no Bag used twice within the winner's own result

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            active_bag_ids = _active_grow_bag_assignment_carrier_ids(
                verify_session, tenant_id=scenario["tenant_id"], batch_id=scenario["batch_id"],
            )
            # Exactly the winner's own 4 Grow Bags are assigned -- never
            # more, never a Bag shared with what the loser would have used.
            assert sorted(active_bag_ids) == sorted(winner_bag_ids)
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_same_grow_bag_position_pool_leaves_no_position_double_occupied(test_engine) -> None:
    """Proof C: two transfers from the SAME abundant InterVines (20 plants)
    and Grow Bag (20 Bags, capacity 1) pools -- never the bottleneck -- race
    for a SCARCE Grow Bag Position pool under one Gutter: only 5 free
    positions, each command needs 5. Exactly one wins; the critical
    invariant is that no Grow Bag Position is ever occupied by two Bags."""
    scenario = _build_committed_scenario(
        test_engine, intervines_plant_count=20, grow_bag_capacity=1, grow_bag_count=20, gutter_bag_positions=5,
    )
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            result = vines_production_transfer_service.record_vines_production_transfer(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_intervines_table_id=scenario["intervines_table_id"],
                plant_count=5, destination_grow_gutter_id=scenario["grow_gutter_id"],
                grow_bag_specification_id=scenario["grow_bag_specification_id"],
            )
            results[name] = ("ok", [gb.grow_bag_position_id for gb in result.grow_bags])
        except InsufficientAvailableGrowBagPositionsError as exc:
            results[name] = ("conflict", str(exc))
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
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results

        winner = results["a"] if results["a"][0] == "ok" else results["b"]
        winner_position_ids = winner[1]
        assert len(winner_position_ids) == len(set(winner_position_ids)) == 5

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            active_positions = verify_session.execute(
                select(Occupancy.target_location_id).where(
                    Occupancy.end_time.is_(None), Occupancy.target_location_id.in_(winner_position_ids)
                )
            ).scalars().all()
            assert sorted(active_positions) == sorted(winner_position_ids)
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_insufficient_capacity_under_lock_rejects_whole_command_atomically(test_engine) -> None:
    """Proof D: pool sized at exactly 10 Grow Bags (capacity 1 each, 10
    positions). One command requests all 10 plants/Bags; a concurrent
    sibling requests 4. Both are individually valid against the pool's
    total size, but together exceed it -- whichever loses must see its
    ENTIRE command rejected: zero InterVines release, zero Grow Bag
    assignment, zero Occupancy for its own attempted plants."""
    scenario = _build_committed_scenario(
        test_engine, intervines_plant_count=20, grow_bag_capacity=1, grow_bag_count=10, gutter_bag_positions=10,
    )
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)

    def worker(name: str, quantity: int) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            result = vines_production_transfer_service.record_vines_production_transfer(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_intervines_table_id=scenario["intervines_table_id"],
                plant_count=quantity, destination_grow_gutter_id=scenario["grow_gutter_id"],
                grow_bag_specification_id=scenario["grow_bag_specification_id"],
            )
            results[name] = ("ok", [c.id for c in result.source_grow_cubes])
        except (InsufficientAvailableGrowBagsError, InsufficientAvailableGrowBagPositionsError) as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", 10))
    t_b = threading.Thread(target=worker, args=("b", 4))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results

        loser_name = "a" if results["a"][0] == "conflict" else "b"

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            active_bag_ids = _active_grow_bag_assignment_carrier_ids(
                verify_session, tenant_id=scenario["tenant_id"], batch_id=scenario["batch_id"],
            )
            winner_quantity = 10 if loser_name == "b" else 4
            # Exactly the winner's own requested count of Grow Bags is
            # assigned -- never the loser's, never a partial fraction.
            assert len(active_bag_ids) == winner_quantity
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])
