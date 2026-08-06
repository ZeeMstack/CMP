"""Real two-connection concurrency tests for CMP-015: overlapping
consumption cannot overdraw a shared source lot, the exact-duplicate
packing command race resolves to exactly one event, and a same
finished-goods-lot-code race resolves to exactly one winner. Same
committed-connection racing pattern as test_produce_lot_ledger_concurrency.py."""
import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import packing_service
from app.services.errors import DuplicateFinishedGoodsLotCodeError, InsufficientProduceLotBalanceError
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, now


@pytest.mark.integration
def test_overlapping_concurrent_consumption_cannot_overdraw(test_engine) -> None:
    """Two threads each try to consume 7kg from a 10kg lot at the same
    time — at most one may succeed; the loser must fail with insufficient
    balance, never with a negative-balance data corruption."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = packing_service.record_packing(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                finished_goods_lot_code=f"FG-{name}-{scenario['suffix']}", package_count=1,
                packed_output_weight_kg=Decimal("7.000"), process_loss_weight_kg=Decimal("0"),
                rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[
                    {"harvested_produce_lot_id": scenario["lot_a_id"], "consumed_weight_kg": Decimal("7.000"), "consumed_whole_unit_count": None, "note": None}
                ],
            )
            results[name] = ("ok", event.id)
        except InsufficientProduceLotBalanceError as exc:
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
        assert not t_a.is_alive() and not t_b.is_alive()
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("insufficient") == 1, results

        with test_engine.connect() as verify_conn:
            balance = verify_conn.execute(
                text(
                    "SELECT COALESCE(sum(weight_delta_kg), 0) FROM produce_lot_ledger_entries "
                    "WHERE produce_lot_id = :lid"
                ),
                {"lid": scenario["lot_a_id"]},
            ).scalar_one()
        assert balance >= 0, "the lot's balance must never go negative under concurrent consumption"
        assert balance == Decimal("3.000"), "exactly one 7kg consumption must have succeeded against the 10kg lot"
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_exact_duplicate_packing_command_race_creates_one_event(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()
    command_id = uuid.uuid4()
    code = f"FG-RACE-{scenario['suffix']}"

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = packing_service.record_packing(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=command_id, effective_time=effective_time,
                finished_goods_lot_code=code, package_count=1, packed_output_weight_kg=Decimal("5.000"),
                process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[
                    {"harvested_produce_lot_id": scenario["lot_a_id"], "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}
                ],
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
            event_count = verify_conn.execute(
                text("SELECT count(*) FROM packing_events WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]}
            ).scalar_one()
            debit_count = verify_conn.execute(
                text("SELECT count(*) FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid AND entry_kind = 'packing_consumption'"),
                {"lid": scenario["lot_a_id"]},
            ).scalar_one()
        assert event_count == 1
        assert debit_count == 1
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_same_finished_goods_lot_code_race_leaves_one_winner(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_b_weight="10.000", lot_a_count=None, lot_b_count=None)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()
    code = f"FG-COLLIDE-{scenario['suffix']}"

    def worker(name: str, lot_id) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = packing_service.record_packing(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                finished_goods_lot_code=code, package_count=1, packed_output_weight_kg=Decimal("1.000"),
                process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[
                    {"harvested_produce_lot_id": lot_id, "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": None, "note": None}
                ],
            )
            results[name] = ("ok", event.id)
        except DuplicateFinishedGoodsLotCodeError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", scenario["lot_a_id"]))
    t_b = threading.Thread(target=worker, args=("b", scenario["lot_b_id"]))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
        with test_engine.connect() as verify_conn:
            lot_count = verify_conn.execute(
                text("SELECT count(*) FROM finished_goods_lots WHERE tenant_id = :tid AND lower(code) = lower(:code)"),
                {"tid": scenario["tenant_id"], "code": code},
            ).scalar_one()
        assert lot_count == 1, "only the winning packing command may leave a finished-goods lot behind"
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_two_concurrent_commands_consuming_exact_final_weight_both_succeed(test_engine) -> None:
    """Two racing commands each request exactly half of a 10kg lot (5kg
    each) — since 5 + 5 == 10 exactly, both must succeed once serialized by
    the source-lot row lock, leaving the lot at exactly zero — proving the
    lock forces correct sequential balance re-evaluation rather than both
    racers reading the same stale pre-lock balance."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = packing_service.record_packing(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=now(),
                finished_goods_lot_code=f"FG-{name}-{scenario['suffix']}", package_count=1,
                packed_output_weight_kg=Decimal("5.000"), process_loss_weight_kg=Decimal("0"),
                rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[
                    {"harvested_produce_lot_id": scenario["lot_a_id"], "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}
                ],
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
        with test_engine.connect() as verify_conn:
            balance = verify_conn.execute(
                text("SELECT COALESCE(sum(weight_delta_kg), 0) FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid"),
                {"lid": scenario["lot_a_id"]},
            ).scalar_one()
        assert balance == Decimal("0.000") or balance == Decimal("0")
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_overlapping_multi_lot_commands_reversed_order_no_deadlock(test_engine) -> None:
    """Two separate packing commands each consume a small amount from BOTH
    shared lots, but list them in reversed order in their own payload —
    the service must sort source-lot IDs before locking (mirroring
    batch_derivation_service's own deadlock-avoidance idiom), so both
    commands complete without ever deadlocking regardless of client-
    supplied line order."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_b_weight="10.000", lot_a_count=None, lot_b_count=None)
    lot_a_id, lot_b_id = scenario["lot_a_id"], scenario["lot_b_id"]
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def worker(name: str, first_lot, second_lot) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = packing_service.record_packing(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=now(),
                finished_goods_lot_code=f"FG-{name}-{scenario['suffix']}", package_count=1,
                packed_output_weight_kg=Decimal("2.000"), process_loss_weight_kg=Decimal("0"),
                rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[
                    {"harvested_produce_lot_id": first_lot, "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": None, "note": None},
                    {"harvested_produce_lot_id": second_lot, "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": None, "note": None},
                ],
            )
            results[name] = ("ok", event.id)
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    # A lists (lot_a, lot_b); B lists the reverse (lot_b, lot_a) — the
    # service's own sorted-locking must make the lock-acquisition order
    # identical for both regardless of this client-supplied order.
    t_a = threading.Thread(target=worker, args=("a", lot_a_id, lot_b_id))
    t_b = threading.Thread(target=worker, args=("b", lot_b_id, lot_a_id))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        assert results["a"][0] == "ok" and results["b"][0] == "ok", results
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])
