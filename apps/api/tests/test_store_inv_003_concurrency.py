"""STORE-INV-003: the four required two-real-connection concurrency proofs
for Reservation & Issue -- same barrier-based pattern as
`test_store_inv_002b_custody_concurrency.py`."""
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services import inventory_availability_service, inventory_issue_service, inventory_reservation_service
from app.services.errors import (
    InsufficientAvailableToIssueError,
    InsufficientReservationBalanceError,
    InsufficientStorageBinBalanceError,
)
from app.services.inventory_issue_service import IssueLineInput
from app.services.inventory_reservation_service import ReservationLineInput
from tests._store_reservation_scenario import build_scenario, receive_and_putaway


def _now():
    return datetime.now(timezone.utc)


# --- A. two reservations competing for the same Item/Farm availability -----


def _reserve_worker(test_engine, results, name, *, tenant_id, farm_id, actor_user_id, item_id, quantity, barrier) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        reservation = inventory_reservation_service.create_reservation(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
            purpose=f"race-{name}", effective_time=_now(), lines=[ReservationLineInput(inventory_item_id=item_id, quantity=quantity)],
        )
        results[name] = ("ok", reservation.id)
    except InsufficientAvailableToIssueError as exc:
        session.rollback()
        results[name] = ("insufficient", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_two_concurrent_reservations_never_over_reserve(test_engine) -> None:
    """10 usable in Store. Two threads each try to reserve 7 (together
    14 > 10) -- exactly one may succeed."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        receive_and_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
    finally:
        session.close()
        conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    threads = [
        threading.Thread(
            target=_reserve_worker, args=(test_engine, results, "a"),
            kwargs=dict(
                tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                item_id=scenario["item_id"], quantity=Decimal("7"), barrier=barrier,
            ),
        ),
        threading.Thread(
            target=_reserve_worker, args=(test_engine, results, "b"),
            kwargs=dict(
                tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                item_id=scenario["item_id"], quantity=Decimal("7"), barrier=barrier,
            ),
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not any(t.is_alive() for t in threads), "a deadlock would leave a thread hung past the join timeout"
    outcomes = {results["a"][0], results["b"][0]}
    assert outcomes == {"ok", "insufficient"}, results

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        reserved = inventory_availability_service.get_item_reserved_quantity(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
        )
        assert reserved == Decimal("7")
        available = inventory_availability_service.get_item_available_to_issue(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
        )
        assert available == Decimal("3")
    finally:
        session.close()
        conn.close()


# --- B. direct Issue races Reservation for the same Item/Farm --------------


def _issue_worker(test_engine, results, name, *, tenant_id, farm_id, actor_user_id, item_id, cohort_id, bin_id, quantity, barrier) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        issue = inventory_issue_service.record_issue(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
            purpose=f"race-{name}", effective_time=_now(),
            lines=[IssueLineInput(inventory_item_id=item_id, inventory_quantity_cohort_id=cohort_id, source_location_id=bin_id, quantity=quantity)],
        )
        results[name] = ("ok", issue.id)
    except InsufficientAvailableToIssueError as exc:
        session.rollback()
        results[name] = ("insufficient", str(exc))
    except Exception as exc:  # pragma: no cover
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_direct_issue_cannot_steal_quantity_required_by_committed_reservation(test_engine) -> None:
    """10 usable/in-Store. One thread reserves 8, the other directly issues
    5 (together 13 > 10) -- both racing the SAME Item/Farm availability
    advisory lock, so exactly one may succeed; Available to issue must
    never go negative afterward."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id, bin_id = receive_and_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
    finally:
        session.close()
        conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    threads = [
        threading.Thread(
            target=_reserve_worker, args=(test_engine, results, "reserve"),
            kwargs=dict(
                tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                item_id=scenario["item_id"], quantity=Decimal("8"), barrier=barrier,
            ),
        ),
        threading.Thread(
            target=_issue_worker, args=(test_engine, results, "issue"),
            kwargs=dict(
                tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                item_id=scenario["item_id"], cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("5"), barrier=barrier,
            ),
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not any(t.is_alive() for t in threads), "a deadlock would leave a thread hung past the join timeout"
    outcomes = {results["reserve"][0], results["issue"][0]}
    assert outcomes == {"ok", "insufficient"}, results
    assert not (results["reserve"][0] == "ok" and results["issue"][0] == "ok"), "8 + 5 must never both succeed against 10"

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        available = inventory_availability_service.get_item_available_to_issue(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
        )
        assert available >= Decimal("0")
    finally:
        session.close()
        conn.close()


# --- C. two Issues race the same Bin/cohort ---------------------------------


@pytest.mark.integration
def test_two_concurrent_issues_never_overdraw_same_bin(test_engine) -> None:
    """10 in one Bin. Two threads each try to issue 7 (together 14 > 10)
    -- exactly one may succeed."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id, bin_id = receive_and_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
    finally:
        session.close()
        conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            issue = inventory_issue_service.record_issue(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), purpose=f"race-{name}",
                effective_time=_now(),
                lines=[
                    IssueLineInput(
                        inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                        source_location_id=bin_id, quantity=Decimal("7"),
                    )
                ],
            )
            results[name] = ("ok", issue.id)
        except InsufficientStorageBinBalanceError as exc:
            session.rollback()
            results[name] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            session.rollback()
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    threads = [threading.Thread(target=worker, args=("a",)), threading.Thread(target=worker, args=("b",))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not any(t.is_alive() for t in threads), "a deadlock would leave a thread hung past the join timeout"
    outcomes = {results["a"][0], results["b"][0]}
    assert outcomes == {"ok", "insufficient"}, results

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        from app.services.inventory_existence_ledger_service import get_cohort_bin_balance

        remaining = get_cohort_bin_balance(session, cohort_id=cohort_id, location_id=bin_id)
        assert remaining == Decimal("3")
        assert remaining >= Decimal("0")
    finally:
        session.close()
        conn.close()


# --- D. Issue-against-reservation races reservation release ----------------


@pytest.mark.integration
def test_issue_against_reservation_races_release_never_goes_negative(test_engine) -> None:
    """Reservation line has 10 remaining. One thread issues 7 against it,
    the other releases 7 (together 14 > 10) -- exactly one may succeed;
    remaining balance never goes negative and is never double-spent."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id, bin_id = receive_and_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        reservation = inventory_reservation_service.create_reservation(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), purpose="Race D", effective_time=_now(),
            lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("10"))],
        )
        line = inventory_reservation_service.list_reservation_lines(
            session, tenant_id=scenario["tenant_id"], reservation_id=reservation.id
        )[0]
        line_id = line.id
    finally:
        session.close()
        conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def issue_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            issue = inventory_issue_service.record_issue(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), purpose="Race D issue",
                effective_time=_now(),
                lines=[
                    IssueLineInput(
                        inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                        source_location_id=bin_id, quantity=Decimal("7"), reservation_line_id=line_id,
                    )
                ],
            )
            results["issue"] = ("ok", issue.id)
        except InsufficientReservationBalanceError as exc:
            session.rollback()
            results["issue"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            session.rollback()
            results["issue"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def release_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            entry = inventory_reservation_service.release_reservation_line(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), reservation_line_id=line_id, quantity=Decimal("7"), effective_time=_now(),
            )
            results["release"] = ("ok", entry.id)
        except InsufficientReservationBalanceError as exc:
            session.rollback()
            results["release"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            session.rollback()
            results["release"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    threads = [threading.Thread(target=issue_worker), threading.Thread(target=release_worker)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not any(t.is_alive() for t in threads), "a deadlock would leave a thread hung past the join timeout"
    outcomes = {results["issue"][0], results["release"][0]}
    assert outcomes == {"ok", "insufficient"}, results
    assert not (results["issue"][0] == "ok" and results["release"][0] == "ok"), "7 + 7 must never both succeed against 10"

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        remaining = inventory_reservation_service.get_reservation_line_remaining(session, reservation_line_id=line_id)
        assert remaining == Decimal("3")
        assert remaining >= Decimal("0")
    finally:
        session.close()
        conn.close()
