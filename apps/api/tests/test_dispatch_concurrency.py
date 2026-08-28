"""Real two-connection concurrency tests for CMP-017: overlapping
dispatches cannot overdraw a shared finished-goods lot, the exact-
duplicate dispatch command race resolves to exactly one event, a same-
command-id-but-different-payload race leaves exactly one winner and one
conflict, a same dispatch-code race leaves exactly one winner, and
multi-lot dispatches listing their lines in reversed order never
deadlock against each other. Same committed-connection racing pattern as
test_packing_concurrency.py."""
import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import dispatch_service
from app.services.errors import (
    DispatchCommandReusedWithDifferentPayloadError,
    DuplicateDispatchCodeError,
    InsufficientFinishedGoodsBalanceError,
)
from tests._dispatch_scenario import now, pack_one
from tests._packing_scenario import build_committed_scenario, cleanup_scenario


@pytest.mark.integration
def test_overlapping_concurrent_dispatch_cannot_overdraw(test_engine) -> None:
    """Two threads each try to dispatch 5kg from an 8kg finished-goods lot
    at the same time -- at most one may succeed; the loser must fail with
    insufficient balance, never with a negative-balance data corruption."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=8, packed_output_weight_kg=Decimal("8.000"))
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
            event = dispatch_service.record_dispatch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                code=f"DISP-{name}-{scenario['suffix']}", external_reference=None, note=None, dispatch_temperature_c=Decimal("4.0"),
                lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("5.000"), "dispatched_package_count": 5}],
            )
            results[name] = ("ok", event.id)
        except InsufficientFinishedGoodsBalanceError as exc:
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
                    "SELECT COALESCE(sum(weight_delta_kg), 0) FROM finished_goods_ledger_entries "
                    "WHERE finished_goods_lot_id = :lid"
                ),
                {"lid": fg_lot_id},
            ).scalar_one()
        assert balance >= 0, "the lot's balance must never go negative under concurrent dispatch"
        assert balance == Decimal("3.000"), "exactly one 5kg dispatch must have succeeded against the 8kg lot"
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_exact_duplicate_dispatch_command_race_creates_one_event(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()
    command_id = uuid.uuid4()
    code = f"DISP-RACE-{scenario['suffix']}"

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = dispatch_service.record_dispatch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=command_id, effective_time=effective_time,
                code=code, external_reference=None, note=None, dispatch_temperature_c=Decimal("4.0"),
                lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("3.000"), "dispatched_package_count": 3}],
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
                text("SELECT count(*) FROM dispatch_events WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]}
            ).scalar_one()
            line_count = verify_conn.execute(
                text("SELECT count(*) FROM dispatch_lines WHERE dispatch_event_id = :eid"), {"eid": results["a"][1]}
            ).scalar_one()
            issue_count = verify_conn.execute(
                text(
                    "SELECT count(*) FROM finished_goods_ledger_entries "
                    "WHERE finished_goods_lot_id = :lid AND entry_kind = 'dispatch_issue'"
                ),
                {"lid": fg_lot_id},
            ).scalar_one()
        assert event_count == 1
        assert line_count == 1
        assert issue_count == 1
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_same_command_id_different_payload_race_leaves_one_winner(test_engine) -> None:
    """Two threads race with the same client_command_id but genuinely
    different line payloads -- exactly one must succeed as a new event;
    the other must lose to
    DispatchCommandReusedWithDifferentPayloadError, never silently
    succeed with the wrong payload or create a second event."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()
    command_id = uuid.uuid4()

    def worker(name: str, weight: str, count: int) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = dispatch_service.record_dispatch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=command_id, effective_time=effective_time,
                code=f"DISP-{name}-{scenario['suffix']}", external_reference=None, note=None, dispatch_temperature_c=Decimal("4.0"),
                lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal(weight), "dispatched_package_count": count}],
            )
            results[name] = ("ok", event.id)
        except DispatchCommandReusedWithDifferentPayloadError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", "1.000", 1))
    t_b = threading.Thread(target=worker, args=("b", "2.000", 2))
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
            event_count = verify_conn.execute(
                text("SELECT count(*) FROM dispatch_events WHERE tenant_id = :tid AND client_command_id = :cid"),
                {"tid": scenario["tenant_id"], "cid": command_id},
            ).scalar_one()
        assert event_count == 1, "the losing conflict must not leave a second event behind"
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_same_dispatch_code_race_leaves_one_winner(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None, lot_b_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_a, _ = pack_one(scenario, session, lot_key="lot_a_id", package_count=10, packed_output_weight_kg=Decimal("8.000"), code_suffix="-A")
    fg_lot_b, _ = pack_one(scenario, session, lot_key="lot_b_id", package_count=5, packed_output_weight_kg=Decimal("4.000"), code_suffix="-B")
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()
    code = f"DISP-COLLIDE-{scenario['suffix']}"

    def worker(name: str, lot_id) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = dispatch_service.record_dispatch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                code=code, external_reference=None, note=None, dispatch_temperature_c=Decimal("4.0"),
                lines=[{"finished_goods_lot_id": lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1}],
            )
            results[name] = ("ok", event.id)
        except DuplicateDispatchCodeError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", fg_lot_a))
    t_b = threading.Thread(target=worker, args=("b", fg_lot_b))
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
            event_count = verify_conn.execute(
                text("SELECT count(*) FROM dispatch_events WHERE farm_id = :fid AND lower(code) = lower(:code)"),
                {"fid": scenario["farm_id"], "code": code},
            ).scalar_one()
        assert event_count == 1, "only the winning dispatch command may leave an event behind"
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_overlapping_multi_lot_dispatches_reversed_order_no_deadlock(test_engine) -> None:
    """Two separate dispatch commands each dispatch a small amount from
    BOTH shared finished-goods lots, but list them in reversed order in
    their own payload -- the service must sort finished-goods-lot ids
    before locking, so both commands complete without ever deadlocking
    regardless of client-supplied line order."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_b_weight="10.000", lot_a_count=None, lot_b_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_a, _ = pack_one(scenario, session, lot_key="lot_a_id", package_count=10, packed_output_weight_kg=Decimal("8.000"), code_suffix="-A")
    fg_lot_b, _ = pack_one(scenario, session, lot_key="lot_b_id", package_count=10, packed_output_weight_kg=Decimal("8.000"), code_suffix="-B")
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    # Captured once, shared by both threads -- calling now() independently
    # inside each worker is a wall-clock race: whichever thread's insert
    # actually lands second (serialized by the lot locks either way) can
    # legitimately end up with an earlier self-captured timestamp than the
    # other's already-posted ledger entry, tripping the monotonic
    # effective-time check for reasons having nothing to do with deadlock
    # avoidance -- the thing this test exists to prove.
    effective_time = now()

    def worker(name: str, first_lot, second_lot) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = dispatch_service.record_dispatch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=effective_time,
                code=f"DISP-{name}-{scenario['suffix']}", external_reference=None, note=None, dispatch_temperature_c=Decimal("4.0"),
                lines=[
                    {"finished_goods_lot_id": first_lot, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1},
                    {"finished_goods_lot_id": second_lot, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1},
                ],
            )
            results[name] = ("ok", event.id)
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    # A lists (fg_a, fg_b); B lists the reverse (fg_b, fg_a) -- the
    # service's own sorted-locking must make the lock-acquisition order
    # identical for both regardless of this client-supplied order.
    t_a = threading.Thread(target=worker, args=("a", fg_lot_a, fg_lot_b))
    t_b = threading.Thread(target=worker, args=("b", fg_lot_b, fg_lot_a))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        assert results["a"][0] == "ok" and results["b"][0] == "ok", results
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_overlapping_dispatch_issue_inserts_cannot_overdraw(test_engine) -> None:
    """CMP-017 verification pass: proves database-level overdraw
    enforcement independently of dispatch_service. Two direct-SQL
    connections each construct a fully valid-looking dispatch_event +
    dispatch_line + dispatch_issue (5kg each) against the same 8kg
    finished-goods lot -- bypassing the service entirely -- racing an
    explicit `FOR UPDATE` lock on the lot row at the same instant via a
    barrier, exactly mirroring the lock-before-insert discipline
    dispatch_service itself uses (see DISPATCH_MODEL.md: a direct-SQL
    writer that instead inserts its dispatch_line *before* explicitly
    locking the lot would race that INSERT's own implicit FK share-lock
    against the immediate trigger's later FOR UPDATE upgrade and could
    deadlock -- a documented limitation of not pre-locking, not exercised
    here). Since 5 + 5 = 10 > 8, at most one may succeed; the loser must
    fail on the trigger's own balance check, never on a deadlock, and the
    final balance must never go negative."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=8, packed_output_weight_kg=Decimal("8.000"))
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()

    def worker(name: str) -> None:
        conn = test_engine.connect()
        trans = conn.begin()
        event_id = uuid.uuid4()
        line_id = uuid.uuid4()
        try:
            barrier.wait(timeout=10)
            # The contested resource, locked explicitly and first -- the
            # same discipline dispatch_service.record_dispatch itself
            # uses -- so whichever transaction arrives first proceeds
            # through the whole sequence uninterrupted, and the other
            # simply waits here rather than racing a later lock upgrade.
            conn.execute(text("SELECT 1 FROM finished_goods_lots WHERE id = :lid FOR UPDATE"), {"lid": fg_lot_id})
            conn.execute(
                text(
                    "INSERT INTO dispatch_events "
                    "(id, tenant_id, farm_id, code, effective_time, actor_user_id, client_command_id, "
                    "request_fingerprint, external_reference, note) "
                    "VALUES (:id, :tid, :fid, :code, :eff, :uid, :ccid, :fp, NULL, NULL)"
                ),
                {
                    "id": event_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                    "code": f"DISP-RACE-{name}-{scenario['suffix']}", "eff": effective_time,
                    "uid": scenario["user_id"], "ccid": uuid.uuid4(), "fp": f"direct-sql-race-{name}",
                },
            )
            conn.execute(
                text(
                    "INSERT INTO dispatch_lines "
                    "(id, tenant_id, farm_id, dispatch_event_id, finished_goods_lot_id, dispatched_weight_kg, "
                    "dispatched_package_count) VALUES (:id, :tid, :fid, :eid, :lid, 5.000, 5)"
                ),
                {
                    "id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "eid": event_id,
                    "lid": fg_lot_id,
                },
            )
            # recorded_time is server-generated (func.now()) at INSERT
            # time -- the trigger requires the issue's own recorded_time
            # to match the owning event's exactly, so it must be read back
            # rather than assumed equal to effective_time.
            recorded_time = conn.execute(
                text("SELECT recorded_time FROM dispatch_events WHERE id = :eid"), {"eid": event_id}
            ).scalar_one()
            # This INSERT's own trigger re-locks the same lot row FOR
            # UPDATE -- a no-op within this same transaction, since the
            # explicit lock above already holds it -- then computes the
            # prior balance from already-committed rows only.
            conn.execute(
                text(
                    "INSERT INTO finished_goods_ledger_entries "
                    "(id, tenant_id, farm_id, finished_goods_lot_id, dispatch_line_id, entry_kind, "
                    "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "VALUES (:id, :tid, :fid, :lid, :line_id, 'dispatch_issue', -5.000, -5, :eff, :rec, :uid, NULL)"
                ),
                {
                    "id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "lid": fg_lot_id,
                    "line_id": line_id, "eff": effective_time, "rec": recorded_time, "uid": scenario["user_id"],
                },
            )
            trans.commit()
            results[name] = ("ok", line_id)
        except Exception as exc:
            trans.rollback()
            results[name] = ("rejected", repr(exc))
        finally:
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
        assert outcomes.count("rejected") == 1, results
        loser = results["a"] if results["a"][0] == "rejected" else results["b"]
        assert "negative available" in loser[1], loser

        with test_engine.connect() as verify_conn:
            weight_balance = verify_conn.execute(
                text(
                    "SELECT COALESCE(sum(weight_delta_kg), 0) FROM finished_goods_ledger_entries "
                    "WHERE finished_goods_lot_id = :lid"
                ),
                {"lid": fg_lot_id},
            ).scalar_one()
            count_balance = verify_conn.execute(
                text(
                    "SELECT COALESCE(sum(package_count_delta), 0) FROM finished_goods_ledger_entries "
                    "WHERE finished_goods_lot_id = :lid"
                ),
                {"lid": fg_lot_id},
            ).scalar_one()
        assert weight_balance >= 0, "weight balance must never go negative under concurrent direct-SQL dispatch"
        assert count_balance >= 0, "package count balance must never go negative under concurrent direct-SQL dispatch"
        assert weight_balance == Decimal("3.000")
        assert count_balance == 3
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])
