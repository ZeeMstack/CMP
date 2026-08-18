"""DOMAIN-FARM-002 section 22: deterministic concurrency proofs for
capacity-aware occupancy. Real two-connection races (see
`test_movement_concurrency.py`'s own module docstring for why a shared,
rollback-only session cannot demonstrate a genuine Postgres-level conflict).
No sleeps -- coordination is via `threading.Barrier`, and correctness is
decided by the DB-layer row lock inside `enforce_occupancy_insert_integrity`
(migration f91c366cfe57), not by service pre-check ordering alone.
"""
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import asset_service, farm_service, location_service, membership_service, tenant_service, user_service
from app.services.errors import TargetOccupiedError
from tests.conftest import ensure_seed_tray_specification


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine, *, location_capacity: int, position_capacity: int, num_trolleys: int, num_trays: int):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"cap-{suffix}", name="Capacity Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="cap-race", oidc_subject=suffix, email=f"cap-{suffix}@example.com", display_name="Cap Race User"
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Cap Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    greenhouse = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code=f"gh-{suffix}", name="GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    # NURSERY-OPS-002A: the frozen authoritative model -- a Germination
    # Trolley occupies the Chamber Location directly (no chamber_position).
    position = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code=f"gc-{suffix}", name="Chamber",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=True, capacity=location_capacity,
    )
    trolleys = [
        asset_service.register_asset(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            asset_type_code="germination_trolley", code=f"GT-{suffix}-{i}", name=f"Trolley {i}", commissioned_date=None,
        )
        for i in range(num_trolleys)
    ]

    carrier_trolley = asset_service.register_asset(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-slot-{suffix}", name="Slot Trolley", commissioned_date=None,
    )
    positions = asset_service.generate_positions(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=carrier_trolley.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix=f"SH-{suffix}-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2, slot_capacity=position_capacity,
    )
    slot = next(p for p in positions if p.position_kind == "slot")

    from app.services import carrier_service

    seed_tray_spec = ensure_seed_tray_specification(session, tenant_id=tenant.id, actor_user_id=user.id)
    trays = [
        carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id, code=f"ST-{suffix}-{i}", issued_date=None,
        )
        for i in range(num_trays)
    ]

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id,
        "position_id": position.id, "trolley_ids": [t.id for t in trolleys],
        "slot_id": slot.id, "tray_ids": [t.id for t in trays],
    }
    session.close()
    conn.close()
    return result


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM occupancies WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM movements WHERE tenant_id = :tid"), {"tid": tenant_id})
        if conn.execute(text("SELECT to_regclass('carrier_specifications')")).scalar() is not None:
            conn.execute(text("DELETE FROM carrier_specifications WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM asset_positions WHERE asset_id IN (SELECT id FROM assets WHERE tenant_id = :tid)"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM assets WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM locations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


def _place_worker(test_engine, results, name, *, tenant_id, farm_id, user_id, occupant_kind, occupant_id, target_kind, target_id, barrier, effective_time):
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        from app.services import movement_service

        movement = movement_service.execute_movement(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
            client_command_id=uuid.uuid4(), effective_time=effective_time,
            occupant_kind=occupant_kind, occupant_id=occupant_id,
            destination_kind=target_kind, destination_id=target_id, reason=None,
        )
        results[name] = ("ok", movement.id)
    except TargetOccupiedError as exc:
        results[name] = ("conflict", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


def _run_pair(test_engine, *, tenant_id, farm_id, user_id, occupant_kind, occupant_a, occupant_b, target_kind, target_id):
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()

    t_a = threading.Thread(
        target=_place_worker, args=(test_engine, results, "a"),
        kwargs=dict(tenant_id=tenant_id, farm_id=farm_id, user_id=user_id, occupant_kind=occupant_kind,
                    occupant_id=occupant_a, target_kind=target_kind, target_id=target_id,
                    barrier=barrier, effective_time=effective_time),
    )
    t_b = threading.Thread(
        target=_place_worker, args=(test_engine, results, "b"),
        kwargs=dict(tenant_id=tenant_id, farm_id=farm_id, user_id=user_id, occupant_kind=occupant_kind,
                    occupant_id=occupant_b, target_kind=target_kind, target_id=target_id,
                    barrier=barrier, effective_time=effective_time),
    )
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)
    assert not t_a.is_alive() and not t_b.is_alive()
    return results


@pytest.mark.integration
def test_case_a_capacity_one_empty_target_exactly_one_winner(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, location_capacity=1, position_capacity=1, num_trolleys=2, num_trays=0)
    try:
        results = _run_pair(
            test_engine, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
            occupant_kind="asset", occupant_a=scenario["trolley_ids"][0], occupant_b=scenario["trolley_ids"][1],
            target_kind="location", target_id=scenario["position_id"],
        )
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results

        conn = test_engine.connect()
        try:
            active_count = conn.execute(
                text("SELECT COUNT(*) FROM occupancies WHERE target_location_id = :tid AND end_time IS NULL"),
                {"tid": scenario["position_id"]},
            ).scalar_one()
        finally:
            conn.close()
        assert active_count == 1
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_case_b_capacity_two_one_existing_occupant_race_for_last_slot(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, location_capacity=2, position_capacity=1, num_trolleys=3, num_trays=0)
    try:
        # Pre-fill one of the two slots, committed, before the race starts.
        conn = test_engine.connect()
        session = Session(bind=conn)
        from app.services import movement_service

        movement_service.execute_movement(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley_ids"][0],
            destination_kind="location", destination_id=scenario["position_id"], reason=None,
        )
        session.close()
        conn.close()

        results = _run_pair(
            test_engine, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
            occupant_kind="asset", occupant_a=scenario["trolley_ids"][1], occupant_b=scenario["trolley_ids"][2],
            target_kind="location", target_id=scenario["position_id"],
        )
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results

        conn = test_engine.connect()
        try:
            active_count = conn.execute(
                text("SELECT COUNT(*) FROM occupancies WHERE target_location_id = :tid AND end_time IS NULL"),
                {"tid": scenario["position_id"]},
            ).scalar_one()
        finally:
            conn.close()
        assert active_count == 2
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


def _reduce_capacity_worker(test_engine, results, name, *, table: str, target_id, new_capacity, barrier):
    conn = test_engine.connect()
    try:
        barrier.wait(timeout=10)
        trans = conn.begin()
        try:
            conn.execute(text(f"UPDATE {table} SET capacity = :cap WHERE id = :id"), {"cap": new_capacity, "id": target_id})
            trans.commit()
            results[name] = ("ok", None)
        except Exception as exc:
            trans.rollback()
            results[name] = ("conflict", repr(exc))
    finally:
        conn.close()


@pytest.mark.integration
def test_case_d_location_capacity_reduction_races_with_occupancy_insert(test_engine) -> None:
    """DOMAIN-FARM-002.1 section 7: capacity=2 with 1 existing active
    occupant. Transaction A inserts a second occupant (bringing the count to
    2, exactly at capacity). Transaction B concurrently reduces capacity to
    1. Both operations serialize on the SAME locations row -- A's INSERT
    trigger takes `SELECT ... FOR UPDATE` on it, B's UPDATE inherently locks
    it -- so exactly one must commit and the other must fail. The impossible
    final state (capacity=1, active_count=2) must never be reached,
    regardless of which one wins."""
    scenario = _build_committed_scenario(test_engine, location_capacity=2, position_capacity=1, num_trolleys=2, num_trays=0)
    try:
        conn = test_engine.connect()
        session = Session(bind=conn)
        from app.services import movement_service

        movement_service.execute_movement(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley_ids"][0],
            destination_kind="location", destination_id=scenario["position_id"], reason=None,
        )
        session.close()
        conn.close()

        barrier = threading.Barrier(2)
        results: dict[str, object] = {}
        effective_time = _now()

        t_insert = threading.Thread(
            target=_place_worker, args=(test_engine, results, "insert"),
            kwargs=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                        occupant_kind="asset", occupant_id=scenario["trolley_ids"][1], target_kind="location",
                        target_id=scenario["position_id"], barrier=barrier, effective_time=effective_time),
        )
        t_reduce = threading.Thread(
            target=_reduce_capacity_worker, args=(test_engine, results, "reduce"),
            kwargs=dict(table="locations", target_id=scenario["position_id"], new_capacity=1, barrier=barrier),
        )
        t_insert.start()
        t_reduce.start()
        t_insert.join(timeout=15)
        t_reduce.join(timeout=15)
        assert not t_insert.is_alive() and not t_reduce.is_alive()

        outcomes = [results["insert"][0], results["reduce"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results

        conn = test_engine.connect()
        try:
            capacity, active_count = conn.execute(
                text(
                    "SELECT l.capacity, (SELECT COUNT(*) FROM occupancies o WHERE o.target_location_id = l.id AND o.end_time IS NULL) "
                    "FROM locations l WHERE l.id = :id"
                ),
                {"id": scenario["position_id"]},
            ).one()
        finally:
            conn.close()
        # The impossible combination must never occur, regardless of winner.
        assert not (capacity == 1 and active_count == 2), (capacity, active_count, results)
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_case_e_asset_position_capacity_reduction_races_with_occupancy_insert(test_engine) -> None:
    """AssetPosition equivalent of case D -- the implementation is not
    mechanically identical (different trigger, different table), so this is
    exercised as its own race rather than assumed from the Location case."""
    scenario = _build_committed_scenario(test_engine, location_capacity=1, position_capacity=2, num_trolleys=0, num_trays=2)
    try:
        conn = test_engine.connect()
        session = Session(bind=conn)
        from app.services import movement_service

        movement_service.execute_movement(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="carrier", occupant_id=scenario["tray_ids"][0],
            destination_kind="asset_position", destination_id=scenario["slot_id"], reason=None,
        )
        session.close()
        conn.close()

        barrier = threading.Barrier(2)
        results: dict[str, object] = {}
        effective_time = _now()

        t_insert = threading.Thread(
            target=_place_worker, args=(test_engine, results, "insert"),
            kwargs=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
                        occupant_kind="carrier", occupant_id=scenario["tray_ids"][1], target_kind="asset_position",
                        target_id=scenario["slot_id"], barrier=barrier, effective_time=effective_time),
        )
        t_reduce = threading.Thread(
            target=_reduce_capacity_worker, args=(test_engine, results, "reduce"),
            kwargs=dict(table="asset_positions", target_id=scenario["slot_id"], new_capacity=1, barrier=barrier),
        )
        t_insert.start()
        t_reduce.start()
        t_insert.join(timeout=15)
        t_reduce.join(timeout=15)
        assert not t_insert.is_alive() and not t_reduce.is_alive()

        outcomes = [results["insert"][0], results["reduce"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results

        conn = test_engine.connect()
        try:
            capacity, active_count = conn.execute(
                text(
                    "SELECT p.capacity, (SELECT COUNT(*) FROM occupancies o WHERE o.target_asset_position_id = p.id AND o.end_time IS NULL) "
                    "FROM asset_positions p WHERE p.id = :id"
                ),
                {"id": scenario["slot_id"]},
            ).one()
        finally:
            conn.close()
        assert not (capacity == 1 and active_count == 2), (capacity, active_count, results)
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_case_c_asset_position_capacity_two_race_for_last_slot(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, location_capacity=1, position_capacity=2, num_trolleys=0, num_trays=3)
    try:
        conn = test_engine.connect()
        session = Session(bind=conn)
        from app.services import movement_service

        movement_service.execute_movement(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="carrier", occupant_id=scenario["tray_ids"][0],
            destination_kind="asset_position", destination_id=scenario["slot_id"], reason=None,
        )
        session.close()
        conn.close()

        results = _run_pair(
            test_engine, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"],
            occupant_kind="carrier", occupant_a=scenario["tray_ids"][1], occupant_b=scenario["tray_ids"][2],
            target_kind="asset_position", target_id=scenario["slot_id"],
        )
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results

        conn = test_engine.connect()
        try:
            active_count = conn.execute(
                text("SELECT COUNT(*) FROM occupancies WHERE target_asset_position_id = :tid AND end_time IS NULL"),
                {"tid": scenario["slot_id"]},
            ).scalar_one()
        finally:
            conn.close()
        assert active_count == 2
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])
