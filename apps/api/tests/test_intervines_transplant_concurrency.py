"""VINES-OPS-001A: real two-connection concurrency tests for the composite
InterVines Transplant command, mirroring `test_intersalads_transplant_
concurrency.py`'s own established pattern (committed setup via a dedicated
connection, `threading.Barrier`-released racing workers on independent
connections/sessions, cleanup via `cleanup_traceability_scenario`).

Covers the ticket's three required concurrency proofs:
  A. two commands compete for the same Seedling source's available quantity
     -> cannot over-transfer (`_record_transplant_core`'s own unmodified
     locking; this composite adds no new logic here).
  B. two commands compete for the same Grow Cube pool -> no Grow Cube is
     ever assigned twice.
  C. one command requests N Grow Cubes but fewer are actually free under
     lock (because a concurrent sibling consumed the rest) -> the whole
     command rejects atomically, with zero partial Grow Cube placement.

Per this session's own prior finding (a barrier-released two-thread race is
inherently non-deterministic by construction, not merely occasionally
flaky): these tests assert the LEGAL outcome SET the transaction semantics
guarantee, never a specific thread winning, and never use sleeps as the
synchronization mechanism."""
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
from app.services import (
    carrier_service,
    farm_service,
    intervines_transplant_service,
    membership_service,
    tenant_service,
    user_service,
)
from app.services.errors import (
    InsufficientAvailableGrowCubesError,
    InvalidTransplantEffectiveTimeError,
    SourceAssignmentAlreadyReleasedError,
)
from tests._traceability_scenario import cleanup_traceability_scenario
from tests._transplant_scenario import build_transplant_ready_scenario

DESTINATION_TYPE = "grow_cube"


def _now():
    return datetime.now(timezone.utc)


def _active_grow_cube_assignment_carrier_ids(session: Session, *, tenant_id, batch_id) -> list:
    """Every currently-active `BatchCarrierAssignment.carrier_id` for this
    Batch whose Carrier is `grow_cube`-typed -- deliberately excludes the
    Batch's own source Seed Tray assignment(s), which legitimately remain
    active (unreleased) here too whenever a partial transfer leaves a
    remainder, and are a different Carrier type entirely."""
    return list(
        session.execute(
            select(BatchCarrierAssignment.carrier_id)
            .join(Carrier, Carrier.id == BatchCarrierAssignment.carrier_id)
            .join(CarrierType, CarrierType.id == Carrier.carrier_type_id)
            .where(
                BatchCarrierAssignment.tenant_id == tenant_id,
                BatchCarrierAssignment.batch_id == batch_id,
                BatchCarrierAssignment.released_effective_time.is_(None),
                CarrierType.code == DESTINATION_TYPE,
            )
        ).scalars().all()
    )


def _build_committed_scenario(test_engine, *, tray_count=2, normal=100, extra_grow_cubes=0, grow_cube_prefix="GC-RACE-"):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"ivt-race-{suffix}", name="Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="ivt-race", oidc_subject=suffix, email=f"ivt-race-{suffix}@example.com",
        display_name="Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s = build_transplant_ready_scenario(
        session, tenant, user, farm, suffix=suffix, tray_count=tray_count, normal=normal,
        transplanting_required_type=DESTINATION_TYPE, intervines_table_count=1,
        # An InterVines Table holds many Grow Cubes at once -- a NULL
        # `capacity` defaults to effectively exclusive (1) in `movement_
        # service`, so every racing worker below needs headroom well above
        # its own requested quantity.
        intervines_table_capacity=1000,
    )
    if extra_grow_cubes > 0:
        carrier_service.bulk_register_carriers(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code=DESTINATION_TYPE, code_prefix=f"{grow_cube_prefix}{suffix[:6]}-", start=1,
            end=extra_grow_cubes, pad_width=4,
        )
    session.commit()

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": s["batch_id"],
        "source_assignment_ids": s["source_assignment_ids"],
        "table_id": s["intervines_table_ids"][0],
        "entry_time": s["entry_time"],
    }
    session.close()
    conn.close()
    return result


@pytest.mark.integration
def test_concurrent_same_seedling_source_leaves_one_winner(test_engine) -> None:
    """Proof A: two InterVines Transplant commands draw from the SAME
    Seedling source Tray, at the same `effective_time`, each requesting
    fewer plants than the source's own available balance alone but together
    exceeding it. Exactly one must win; the loser observes either the
    source already released, or -- since both share the exact same
    `effective_time` -- refuses to backdate behind the winner's freshly
    committed checkpoint. Both are `_record_transplant_core`'s own
    pre-existing, unmodified concurrency protection."""
    scenario = _build_committed_scenario(test_engine, tray_count=1, normal=10, extra_grow_cubes=20)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    source_id = scenario["source_assignment_ids"][0]
    table_id = scenario["table_id"]

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            result = intervines_transplant_service.record_intervines_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_assignment_id=source_id, plant_count=8,
                destination_location_id=table_id, grow_cube_specification_id=None,
            )
            results[name] = ("ok", result.id)
        except (SourceAssignmentAlreadyReleasedError, InvalidTransplantEffectiveTimeError) as exc:
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
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_same_grow_cube_pool_leaves_no_cube_assigned_twice(test_engine) -> None:
    """Proof B: two InterVines Transplant commands from two DIFFERENT
    Seedling source Trays (so proof A's own source-lock contention never
    fires here) race for the SAME Grow Cube pool, each requesting 6 while
    only 10 total exist. Both requests are individually satisfiable, but
    together they are not -- exactly one must win; the loser sees
    `InsufficientAvailableGrowCubesError`. The critical invariant is never
    "who wins" but that no Grow Cube is ever double-assigned: verified
    directly against `batch_carrier_assignments`/`occupancies` after both
    threads finish."""
    scenario = _build_committed_scenario(test_engine, tray_count=2, normal=50, extra_grow_cubes=6)  # 4 base + 6 = 10
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    table_id = scenario["table_id"]

    def worker(name: str, source_id) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            result = intervines_transplant_service.record_intervines_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_assignment_id=source_id, plant_count=6,
                destination_location_id=table_id, grow_cube_specification_id=None,
            )
            results[name] = ("ok", [gc.carrier.id for gc in result.grow_cubes])
        except InsufficientAvailableGrowCubesError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", scenario["source_assignment_ids"][0]))
    t_b = threading.Thread(target=worker, args=("b", scenario["source_assignment_ids"][1]))
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
        winner_carrier_ids = winner[1]
        assert len(winner_carrier_ids) == 6
        assert len(set(winner_carrier_ids)) == 6  # no duplicate within the winner's own result

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            active_assignments = _active_grow_cube_assignment_carrier_ids(
                verify_session, tenant_id=scenario["tenant_id"], batch_id=scenario["batch_id"],
            )
            # Exactly the winner's 6 Grow Cubes are assigned -- never more,
            # never a Cube shared with what the loser would have used.
            assert sorted(active_assignments) == sorted(winner_carrier_ids)

            # Scoped to the InterVines Table itself -- a global, unscoped
            # query would also pick up unrelated active Occupancies (e.g.
            # the scenario's own germination trolley in its chamber, an
            # ASSET occupant with a NULL `occupant_carrier_id`).
            active_occupancies = verify_session.execute(
                select(Occupancy.occupant_carrier_id).where(
                    Occupancy.target_location_id == table_id, Occupancy.end_time.is_(None)
                )
            ).scalars().all()
            assert sorted(active_occupancies) == sorted(winner_carrier_ids)
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_insufficient_grow_cubes_rejects_whole_command_atomically(test_engine) -> None:
    """Proof C: pool sized at exactly 10 Grow Cubes. One command requests
    all 10; a concurrent sibling (different source Tray) requests 5. Both
    numbers are individually valid against the pool's total size, but
    together exceed it -- whichever command loses the race must see its
    ENTIRE command rejected, with zero Grow Cube placed (never a partial 5-
    of-10 or a partial fraction of its own request)."""
    scenario = _build_committed_scenario(test_engine, tray_count=2, normal=50, extra_grow_cubes=6)  # 4 base + 6 = 10
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    table_id = scenario["table_id"]

    def worker(name: str, source_id, quantity: int) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            result = intervines_transplant_service.record_intervines_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_assignment_id=source_id, plant_count=quantity,
                destination_location_id=table_id, grow_cube_specification_id=None,
            )
            results[name] = ("ok", [gc.carrier.id for gc in result.grow_cubes])
        except InsufficientAvailableGrowCubesError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", scenario["source_assignment_ids"][0], 10))
    t_b = threading.Thread(target=worker, args=("b", scenario["source_assignment_ids"][1], 5))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results

        winner_name = "a" if results["a"][0] == "ok" else "b"
        winner_quantity = 10 if winner_name == "a" else 5
        loser_name = "b" if winner_name == "a" else "a"
        loser_source_id = scenario["source_assignment_ids"][0 if loser_name == "a" else 1]

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            loser_assignment = verify_session.get(BatchCarrierAssignment, loser_source_id)
            # The loser's OWN source Tray assignment was never released --
            # no partial biological accounting either, not just no partial
            # Grow Cube placement.
            assert loser_assignment.released_effective_time is None

            active_assignment_count = _active_grow_cube_assignment_carrier_ids(
                verify_session, tenant_id=scenario["tenant_id"], batch_id=scenario["batch_id"],
            )
            # Exactly the winner's own requested count of Grow Cubes is
            # occupied -- never the loser's, never a partial fraction of
            # either, never both summed.
            assert len(active_assignment_count) == winner_quantity
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])
