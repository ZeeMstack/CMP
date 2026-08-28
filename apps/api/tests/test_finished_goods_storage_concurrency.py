"""Real two-connection concurrency tests for CMP-018: overlapping
placements/transfers/releases cannot overdraw a shared finished-goods lot
or a shared storage location, dispatch and placement correctly serialize
through the single finished-goods-lot lock (release-before-dispatch holds
under real races, not just sequential calls), and a destination location
being deactivated concurrently with a placement into it cannot let a
movement commit against stale eligibility. Same barrier-based, two-
real-connection racing pattern as test_dispatch_concurrency.py."""
import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import dispatch_service, finished_goods_storage_service
from app.services.errors import (
    InactiveDestinationLocationError,
    InsufficientStorageLocationBalanceError,
    InsufficientUnplacedQuantityError,
)
from tests._dispatch_scenario import now, pack_one
from tests._packing_scenario import build_committed_scenario, cleanup_scenario
from tests._storage_scenario import create_cold_store, create_cold_store_position, place_one, release_one


def _read_available_and_placed(test_engine, fg_lot_id) -> tuple[Decimal, int, Decimal, int]:
    with test_engine.connect() as conn:
        available_weight, available_count = conn.execute(
            text(
                "SELECT COALESCE(SUM(weight_delta_kg), 0), COALESCE(SUM(package_count_delta), 0) "
                "FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = :lid"
            ),
            {"lid": fg_lot_id},
        ).one()
        placed_weight, placed_count = conn.execute(
            text(
                "SELECT "
                "COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_weight_kg "
                "  WHEN movement_kind = 'release' THEN -moved_weight_kg ELSE 0 END), 0), "
                "COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_package_count "
                "  WHEN movement_kind = 'release' THEN -moved_package_count ELSE 0 END), 0) "
                "FROM finished_goods_storage_movements WHERE finished_goods_lot_id = :lid"
            ),
            {"lid": fg_lot_id},
        ).one()
    return available_weight, available_count, placed_weight, placed_count


@pytest.mark.integration
def test_concurrent_placements_together_exceed_unplaced_only_one_succeeds(test_engine) -> None:
    """8kg/8 available, fully unplaced. Two threads each place 5kg/5 into
    separate positions -- individually fit, together (10) exceed the 8kg
    unplaced -- at most one may succeed."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=8, packed_output_weight_kg=Decimal("8.000"))
    cold_store = create_cold_store(scenario, session)
    pos_a = create_cold_store_position(scenario, session, cold_store_id=cold_store.id, code_suffix="-A")
    pos_b = create_cold_store_position(scenario, session, cold_store_id=cold_store.id, code_suffix="-B")
    pos_a_id, pos_b_id = pos_a.id, pos_b.id
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()

    def worker(name: str, dest_id) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            movement = finished_goods_storage_service.record_movement(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                finished_goods_lot_id=fg_lot_id, movement_kind="place", source_location_id=None,
                destination_location_id=dest_id, moved_weight_kg=Decimal("5.000"), moved_package_count=5, note=None,
            )
            results[name] = ("ok", movement.id)
        except InsufficientUnplacedQuantityError as exc:
            results[name] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", pos_a_id))
    t_b = threading.Thread(target=worker, args=("b", pos_b_id))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("insufficient") == 1, results

        available_weight, available_count, placed_weight, placed_count = _read_available_and_placed(test_engine, fg_lot_id)
        assert placed_weight == Decimal("5.000")
        assert placed_count == 5
        assert available_weight >= placed_weight
        assert available_count >= placed_count
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_releases_together_exceed_one_source_location(test_engine) -> None:
    """8kg/8 placed into a single position. Two threads each release
    5kg/5 from it -- individually fit, together (10) exceed the 8kg held
    there -- at most one may succeed."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=8, packed_output_weight_kg=Decimal("8.000"))
    cold_store = create_cold_store(scenario, session)
    pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
    pos_id = pos.id
    session.commit()
    place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_id, moved_weight_kg=Decimal("8.000"), moved_package_count=8)
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            movement = finished_goods_storage_service.record_movement(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                finished_goods_lot_id=fg_lot_id, movement_kind="release", source_location_id=pos_id,
                destination_location_id=None, moved_weight_kg=Decimal("5.000"), moved_package_count=5, note=None,
            )
            results[name] = ("ok", movement.id)
        except InsufficientStorageLocationBalanceError as exc:
            results[name] = ("insufficient", str(exc))
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
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("insufficient") == 1, results

        available_weight, available_count, placed_weight, placed_count = _read_available_and_placed(test_engine, fg_lot_id)
        assert placed_weight == Decimal("3.000")
        assert placed_count == 3
        assert placed_weight >= 0 and placed_count >= 0
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_transfer_vs_release_same_source_race(test_engine) -> None:
    """8kg/8 placed into position A. One thread transfers 5kg/5 from A to
    B; the other releases 5kg/5 from A -- individually fit, together (10)
    exceed the 8kg held at A -- at most one may succeed."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=8, packed_output_weight_kg=Decimal("8.000"))
    cold_store = create_cold_store(scenario, session)
    pos_a = create_cold_store_position(scenario, session, cold_store_id=cold_store.id, code_suffix="-A")
    pos_b = create_cold_store_position(scenario, session, cold_store_id=cold_store.id, code_suffix="-B")
    pos_a_id, pos_b_id = pos_a.id, pos_b.id
    session.commit()
    place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_a_id, moved_weight_kg=Decimal("8.000"), moved_package_count=8)
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()

    def transfer_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            movement = finished_goods_storage_service.record_movement(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                finished_goods_lot_id=fg_lot_id, movement_kind="transfer", source_location_id=pos_a_id,
                destination_location_id=pos_b_id, moved_weight_kg=Decimal("5.000"), moved_package_count=5, note=None,
            )
            results["transfer"] = ("ok", movement.id)
        except InsufficientStorageLocationBalanceError as exc:
            results["transfer"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results["transfer"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def release_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            movement = finished_goods_storage_service.record_movement(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                finished_goods_lot_id=fg_lot_id, movement_kind="release", source_location_id=pos_a_id,
                destination_location_id=None, moved_weight_kg=Decimal("5.000"), moved_package_count=5, note=None,
            )
            results["release"] = ("ok", movement.id)
        except InsufficientStorageLocationBalanceError as exc:
            results["release"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results["release"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=transfer_worker)
    t_b = threading.Thread(target=release_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        outcomes = [results["transfer"][0], results["release"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("insufficient") == 1, results

        with test_engine.connect() as verify_conn:
            balance_a = verify_conn.execute(
                text(
                    "SELECT "
                    "COALESCE(SUM(CASE WHEN destination_location_id = :loc THEN moved_weight_kg ELSE 0 END), 0) "
                    "- COALESCE(SUM(CASE WHEN source_location_id = :loc THEN moved_weight_kg ELSE 0 END), 0) "
                    "FROM finished_goods_storage_movements "
                    "WHERE finished_goods_lot_id = :lid AND (source_location_id = :loc OR destination_location_id = :loc)"
                ),
                {"loc": pos_a_id, "lid": fg_lot_id},
            ).scalar_one()
        assert balance_a >= 0, "position A's balance must never go negative under concurrent transfer/release"
        assert balance_a == Decimal("3.000")
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_dispatch_vs_place_race_serializes_through_lot_lock(test_engine) -> None:
    """8kg/8 available, fully unplaced. One thread places the full 8kg/8
    into a position; the other dispatches the full 8kg/8 -- both compete
    for the same unplaced quantity, serialized entirely through the
    shared finished-goods-lot lock (dispatch's v3 ledger trigger and the
    movement trigger both lock that same row first) -- at most one may
    succeed, and the post-race invariant (available >= placed, in both
    dimensions) must hold regardless of which one won."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=8, packed_output_weight_kg=Decimal("8.000"))
    cold_store = create_cold_store(scenario, session)
    pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
    pos_id = pos.id
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()

    def place_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            movement = finished_goods_storage_service.record_movement(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                finished_goods_lot_id=fg_lot_id, movement_kind="place", source_location_id=None,
                destination_location_id=pos_id, moved_weight_kg=Decimal("8.000"), moved_package_count=8, note=None,
            )
            results["place"] = ("ok", movement.id)
        except InsufficientUnplacedQuantityError as exc:
            results["place"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results["place"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def dispatch_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = dispatch_service.record_dispatch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                code=f"DISP-RACE-{scenario['suffix']}", external_reference=None, note=None, dispatch_temperature_c=Decimal("4.0"),
                lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("8.000"), "dispatched_package_count": 8}],
            )
            results["dispatch"] = ("ok", event.id)
        except InsufficientUnplacedQuantityError as exc:
            results["dispatch"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results["dispatch"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=place_worker)
    t_b = threading.Thread(target=dispatch_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        outcomes = [results["place"][0], results["dispatch"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("insufficient") == 1, results

        available_weight, available_count, placed_weight, placed_count = _read_available_and_placed(test_engine, fg_lot_id)
        assert available_weight >= placed_weight, "available weight must never fall below physically placed weight"
        assert available_count >= placed_count, "available package count must never fall below physically placed count"
        assert available_weight >= 0 and available_count >= 0
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_release_vs_dispatch_maintains_release_before_dispatch_invariant(test_engine) -> None:
    """8kg/8 available, all 8kg/8 already placed into one position (0kg
    unplaced). One thread releases the full 8kg/8 (freeing capacity for
    dispatch); the other simultaneously attempts to dispatch the full
    8kg/8. Whichever transaction wins the shared finished-goods-lot lock
    first determines the outcome (release always succeeds since nothing
    else touches its own source balance; dispatch succeeds only if it
    acquires the lock after release has already committed) -- both are
    legitimate serializations. What must hold regardless of interleaving
    is the invariant itself: release always succeeds, dispatch is never
    granted more than currently-unplaced quantity, and the lot never ends
    up with available weight/count below what remains physically placed."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=8, packed_output_weight_kg=Decimal("8.000"))
    cold_store = create_cold_store(scenario, session)
    pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
    pos_id = pos.id
    session.commit()
    place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_id, moved_weight_kg=Decimal("8.000"), moved_package_count=8)
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()

    def release_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            movement = finished_goods_storage_service.record_movement(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                finished_goods_lot_id=fg_lot_id, movement_kind="release", source_location_id=pos_id,
                destination_location_id=None, moved_weight_kg=Decimal("8.000"), moved_package_count=8, note=None,
            )
            results["release"] = ("ok", movement.id)
        except Exception as exc:  # pragma: no cover
            results["release"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def dispatch_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = dispatch_service.record_dispatch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                code=f"DISP-RVD-{scenario['suffix']}", external_reference=None, note=None, dispatch_temperature_c=Decimal("4.0"),
                lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("8.000"), "dispatched_package_count": 8}],
            )
            results["dispatch"] = ("ok", event.id)
        except InsufficientUnplacedQuantityError as exc:
            results["dispatch"] = ("rejected", str(exc))
        except Exception as exc:  # pragma: no cover
            results["dispatch"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=release_worker)
    t_b = threading.Thread(target=dispatch_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        assert results["release"][0] == "ok", results
        assert results["dispatch"][0] in ("ok", "rejected"), results

        available_weight, available_count, placed_weight, placed_count = _read_available_and_placed(test_engine, fg_lot_id)
        assert available_weight >= placed_weight
        assert available_count >= placed_count
        if results["dispatch"][0] == "ok":
            assert available_weight == Decimal("0.000") and placed_weight == Decimal("0.000")
        else:
            assert available_weight == Decimal("8.000") and placed_weight == Decimal("0.000")
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_location_eligibility_race_deactivation_vs_placement(test_engine) -> None:
    """One transaction places 2kg/2 into a destination position while
    another concurrently deactivates that same position -- because the
    movement locks the destination row before its final eligibility
    check, either the deactivation commits first (and placement correctly
    rejects on an inactive destination) or placement holds the lock and
    completes first (and the deactivation, an unconditional update,
    always eventually succeeds afterward). No movement may ever commit
    against a destination that was already inactive at commit time."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=8, packed_output_weight_kg=Decimal("8.000"))
    cold_store = create_cold_store(scenario, session)
    pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
    pos_id = pos.id
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()

    def place_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            movement = finished_goods_storage_service.record_movement(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                finished_goods_lot_id=fg_lot_id, movement_kind="place", source_location_id=None,
                destination_location_id=pos_id, moved_weight_kg=Decimal("2.000"), moved_package_count=2, note=None,
            )
            results["place"] = ("ok", movement.id)
        except InactiveDestinationLocationError as exc:
            results["place"] = ("rejected", str(exc))
        except Exception as exc:  # pragma: no cover
            results["place"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def deactivate_worker() -> None:
        conn = test_engine.connect()
        trans = conn.begin()
        try:
            barrier.wait(timeout=10)
            conn.execute(text("UPDATE locations SET status = 'inactive' WHERE id = :id"), {"id": pos_id})
            trans.commit()
            results["deactivate"] = ("ok", None)
        except Exception as exc:  # pragma: no cover
            trans.rollback()
            results["deactivate"] = ("error", repr(exc))
        finally:
            conn.close()

    t_a = threading.Thread(target=place_worker)
    t_b = threading.Thread(target=deactivate_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        assert results["deactivate"][0] == "ok", results
        assert results["place"][0] in ("ok", "rejected"), results

        with test_engine.connect() as verify_conn:
            movement_count = verify_conn.execute(
                text(
                    "SELECT count(*) FROM finished_goods_storage_movements "
                    "WHERE destination_location_id = :loc AND finished_goods_lot_id = :lid"
                ),
                {"loc": pos_id, "lid": fg_lot_id},
            ).scalar_one()
            final_status = verify_conn.execute(
                text("SELECT status FROM locations WHERE id = :id"), {"id": pos_id}
            ).scalar_one()
        assert final_status == "inactive", "the unconditional deactivation must always eventually take effect"
        if results["place"][0] == "ok":
            assert movement_count == 1, "a successful placement must leave exactly one movement row behind"
        else:
            assert movement_count == 0, "a rejected placement must never leave a movement row behind"
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


def _insert_dispatch_issue_direct_sql(conn, *, scenario, fg_lot_id, weight: Decimal, count: int, effective_time):
    """Direct-SQL dispatch_event + dispatch_line + dispatch_issue ledger
    row, bypassing dispatch_service entirely -- same construction as
    test_dispatch_concurrency.py's own
    test_direct_sql_overlapping_dispatch_issue_inserts_cannot_overdraw."""
    event_id = uuid.uuid4()
    line_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO dispatch_events (id, tenant_id, farm_id, code, effective_time, actor_user_id, "
            "client_command_id, request_fingerprint, external_reference, note) "
            "VALUES (:id, :tid, :fid, :code, :eff, :uid, :ccid, 'fp', NULL, NULL)"
        ),
        {
            "id": event_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
            "code": f"DIRECT-{uuid.uuid4().hex[:8]}", "eff": effective_time, "uid": scenario["user_id"],
            "ccid": uuid.uuid4(),
        },
    )
    conn.execute(
        text(
            "INSERT INTO dispatch_lines (id, tenant_id, farm_id, dispatch_event_id, finished_goods_lot_id, "
            "dispatched_weight_kg, dispatched_package_count) VALUES (:id, :tid, :fid, :eid, :lid, :weight, :count)"
        ),
        {
            "id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "eid": event_id,
            "lid": fg_lot_id, "weight": weight, "count": count,
        },
    )
    recorded_time = conn.execute(
        text("SELECT recorded_time FROM dispatch_events WHERE id = :id"), {"id": event_id}
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO finished_goods_ledger_entries "
            "(id, tenant_id, farm_id, finished_goods_lot_id, dispatch_line_id, entry_kind, weight_delta_kg, "
            "package_count_delta, effective_time, recorded_time, actor_user_id, note) "
            "VALUES (:id, :tid, :fid, :lid, :line_id, 'dispatch_issue', :neg_weight, :neg_count, :eff, :rec, :uid, NULL)"
        ),
        {
            "id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "lid": fg_lot_id,
            "line_id": line_id, "neg_weight": -weight, "neg_count": -count, "eff": effective_time,
            "rec": recorded_time, "uid": scenario["user_id"],
        },
    )


@pytest.mark.integration
def test_direct_sql_dispatch_vs_place_race_maintains_invariant(test_engine) -> None:
    """Database-level proof, independent of both dispatch_service and
    finished_goods_storage_service: two direct-SQL connections race for
    the same 8kg/8 of unplaced quantity on an 8kg/8 finished-goods lot --
    one inserts a full-quantity 'place' movement (locking the finished-
    goods lot FOR UPDATE first, exactly as the movement's own immediate
    trigger and the application service both do), the other inserts a
    full-quantity dispatch_issue ledger row the same way. Both writers
    lock the *same* finished_goods_lots row before doing anything else,
    so they serialize through that one row with no other lock resource
    involved -- exactly the global lock order this ticket's own model
    requires. At most one may succeed; the loser must fail on its own
    trigger's balance/placement check, never on a deadlock, and the
    final state must never show available weight or count below
    physically placed weight or count."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=8, packed_output_weight_kg=Decimal("8.000"))
    cold_store = create_cold_store(scenario, session)
    pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
    pos_id = pos.id
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()

    def place_worker() -> None:
        conn = test_engine.connect()
        trans = conn.begin()
        try:
            barrier.wait(timeout=10)
            # Explicit lock first -- the same discipline
            # finished_goods_storage_service.record_movement and the
            # movement table's own immediate trigger both use -- so
            # whichever transaction arrives first proceeds through the
            # whole sequence uninterrupted rather than racing a later
            # lock upgrade inside the trigger.
            conn.execute(text("SELECT 1 FROM finished_goods_lots WHERE id = :lid FOR UPDATE"), {"lid": fg_lot_id})
            conn.execute(
                text(
                    "INSERT INTO finished_goods_storage_movements "
                    "(id, tenant_id, farm_id, finished_goods_lot_id, movement_kind, source_location_id, "
                    "destination_location_id, moved_weight_kg, moved_package_count, effective_time, "
                    "actor_user_id, client_command_id, request_fingerprint, note) "
                    "VALUES (:id, :tid, :fid, :lot, 'place', NULL, :dest, 8.000, 8, :eff, :actor, :ccid, 'fp', NULL)"
                ),
                {
                    "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "lot": fg_lot_id,
                    "dest": pos_id, "eff": effective_time, "actor": scenario["user_id"], "ccid": uuid.uuid4(),
                },
            )
            trans.commit()
            results["place"] = ("ok", None)
        except Exception as exc:
            trans.rollback()
            results["place"] = ("rejected", repr(exc))
        finally:
            conn.close()

    def dispatch_worker() -> None:
        conn = test_engine.connect()
        trans = conn.begin()
        try:
            barrier.wait(timeout=10)
            conn.execute(text("SELECT 1 FROM finished_goods_lots WHERE id = :lid FOR UPDATE"), {"lid": fg_lot_id})
            _insert_dispatch_issue_direct_sql(
                conn, scenario=scenario, fg_lot_id=fg_lot_id, weight=Decimal("8.000"), count=8,
                effective_time=effective_time,
            )
            trans.commit()
            results["dispatch"] = ("ok", None)
        except Exception as exc:
            trans.rollback()
            results["dispatch"] = ("rejected", repr(exc))
        finally:
            conn.close()

    t_a = threading.Thread(target=place_worker)
    t_b = threading.Thread(target=dispatch_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        outcomes = [results["place"][0], results["dispatch"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("rejected") == 1, results

        available_weight, available_count, placed_weight, placed_count = _read_available_and_placed(test_engine, fg_lot_id)
        assert available_weight >= placed_weight, "available weight must never fall below physically placed weight"
        assert available_count >= placed_count, "available package count must never fall below physically placed count"
        assert available_weight >= 0 and available_count >= 0
        assert placed_weight >= 0 and placed_count >= 0
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])
