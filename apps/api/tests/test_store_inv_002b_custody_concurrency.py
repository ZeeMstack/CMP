"""STORE-INV-002B: the four required two-real-connection concurrency
proofs for physical custody / putaway -- same barrier-based pattern as
`test_finished_goods_storage_concurrency.py` and
`test_store_inv_002a2_quality_concurrency.py`."""
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services import inventory_existence_ledger_service, inventory_quality_service, inventory_storage_service
from app.services.errors import (
    ExistenceBelowCustodyError,
    InsufficientNotPutAwayQuantityError,
    InsufficientStorageBinBalanceError,
    InventoryQuantityCohortSplitAllocationExceedsBalanceError,
)
from tests._store_custody_scenario import build_scenario, build_store_bin, receive_cohort


def _now():
    return datetime.now(timezone.utc)


# --- A. two putaways competing for the same not-put-away quantity ----------


def _putaway_worker(test_engine, results, name, *, tenant_id, farm_id, actor_user_id, cohort_id, location_id, quantity, barrier) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        movement = inventory_storage_service.record_putaway(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=location_id,
            quantity=quantity, effective_time=_now(),
        )
        results[name] = ("ok", movement.id)
    except InsufficientNotPutAwayQuantityError as exc:
        session.rollback()
        results[name] = ("insufficient", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_two_concurrent_putaways_never_overallocate_not_put_away(test_engine) -> None:
    """Cohort has 100 not-put-away. Two threads each try to put away 70 into
    two DIFFERENT bins (together 140 > 100). The cohort lock must serialize
    them: exactly one succeeds, the other observes the already-reduced
    not-put-away balance."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("100"),
        )
        bin_a_id = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"]).id
        bin_b_id = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"]).id
        session.commit()
    finally:
        session.close()
        conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    threads = [
        threading.Thread(
            target=_putaway_worker, args=(test_engine, results, "a"),
            kwargs=dict(
                tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                cohort_id=cohort_id, location_id=bin_a_id, quantity=Decimal("70"), barrier=barrier,
            ),
        ),
        threading.Thread(
            target=_putaway_worker, args=(test_engine, results, "b"),
            kwargs=dict(
                tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                cohort_id=cohort_id, location_id=bin_b_id, quantity=Decimal("70"), barrier=barrier,
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
        not_put_away = inventory_storage_service.get_cohort_not_put_away(session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id)
        assert not_put_away == Decimal("30")
    finally:
        session.close()
        conn.close()


# --- B. two transfers competing for the same source-bin balance ------------


def _transfer_worker(test_engine, results, name, *, tenant_id, farm_id, actor_user_id, cohort_id, source_id, dest_id, quantity, barrier) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        movement = inventory_storage_service.record_transfer(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, source_location_id=source_id,
            destination_location_id=dest_id, quantity=quantity, effective_time=_now(),
        )
        results[name] = ("ok", movement.id)
    except InsufficientStorageBinBalanceError as exc:
        session.rollback()
        results[name] = ("insufficient", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_two_concurrent_transfers_never_overdraw_source_bin(test_engine) -> None:
    """Bin A holds 100. Two threads each transfer 70 out of A into two
    DIFFERENT destination bins (together 140 > 100) -- at most one may
    succeed."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("100"),
        )
        bin_source_id = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"]).id
        bin_c_id = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"]).id
        bin_d_id = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"]).id
        session.commit()
        inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_source_id,
            quantity=Decimal("100"), effective_time=_now(),
        )
        session.commit()
    finally:
        session.close()
        conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    threads = [
        threading.Thread(
            target=_transfer_worker, args=(test_engine, results, "a"),
            kwargs=dict(
                tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                cohort_id=cohort_id, source_id=bin_source_id, dest_id=bin_c_id, quantity=Decimal("70"), barrier=barrier,
            ),
        ),
        threading.Thread(
            target=_transfer_worker, args=(test_engine, results, "b"),
            kwargs=dict(
                tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                cohort_id=cohort_id, source_id=bin_source_id, dest_id=bin_d_id, quantity=Decimal("70"), barrier=barrier,
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
        source_balance = inventory_existence_ledger_service.get_cohort_bin_balance(session, cohort_id=cohort_id, location_id=bin_source_id)
        assert source_balance == Decimal("30")
        assert source_balance >= 0
    finally:
        session.close()
        conn.close()


# --- C. transfer vs existence-decreasing adjustment -------------------------


def _adjustment_worker(test_engine, results, name, *, tenant_id, actor_user_id, cohort_id, delta, barrier) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        entry = inventory_existence_ledger_service.record_adjustment(
            session, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, quantity_delta=delta, effective_time=_now(), reason="race test adjustment",
        )
        results[name] = ("ok", entry.id)
    except ExistenceBelowCustodyError as exc:
        session.rollback()
        results[name] = ("below_custody", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_transfer_vs_existence_decreasing_adjustment_never_leaves_custody_exceeding_existence(test_engine) -> None:
    """100 received, 90 put away into a bin (10 not-put-away). One thread
    transfers 40 of the 90 to a second bin (existence-neutral, custody
    unchanged in total); the other concurrently tries to adjust existence
    down by -95 (would leave existence at 5, below the 90 total custody).
    Both lock the same cohort row, so they serialize: the transfer always
    succeeds (custody-neutral in total), and the adjustment is rejected
    for violating the existence >= custody invariant regardless of
    ordering."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("100"),
        )
        bin_a_id = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"]).id
        bin_b_id = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"]).id
        session.commit()
        inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_a_id,
            quantity=Decimal("90"), effective_time=_now(),
        )
        session.commit()
    finally:
        session.close()
        conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def transfer_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            movement = inventory_storage_service.record_transfer(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), cohort_id=cohort_id, source_location_id=bin_a_id,
                destination_location_id=bin_b_id, quantity=Decimal("40"), effective_time=_now(),
            )
            results["transfer"] = ("ok", movement.id)
        except Exception as exc:  # pragma: no cover
            session.rollback()
            results["transfer"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    threads = [
        threading.Thread(target=transfer_worker),
        threading.Thread(
            target=_adjustment_worker, args=(test_engine, results, "adjustment"),
            kwargs=dict(
                tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], cohort_id=cohort_id,
                delta=Decimal("-95"), barrier=barrier,
            ),
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not any(t.is_alive() for t in threads), "a deadlock would leave a thread hung past the join timeout"
    assert results["transfer"][0] == "ok", results
    assert results["adjustment"][0] == "below_custody", results

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        existence = inventory_existence_ledger_service.get_cohort_balance(session, cohort_id=cohort_id)
        total_custody = inventory_existence_ledger_service.get_cohort_total_custody(session, cohort_id=cohort_id)
        assert existence >= total_custody
        assert existence == Decimal("100")
        assert total_custody == Decimal("90")
    finally:
        session.close()
        conn.close()


# --- D. partial Quality split vs concurrent transfer of the same bin -------


@pytest.mark.integration
def test_partial_quality_split_vs_concurrent_transfer_same_bin(test_engine) -> None:
    """80 sits in Bin A. One thread applies a partial Quality HOLD to 50 of
    it, bucketed against Bin A (a logical custody reclassification: 50
    would move from the parent cohort to a new child cohort, still inside
    Bin A); the other thread concurrently transfers 50 of Bin A's own
    balance to Bin B. Both lock the SAME source cohort row first, so they
    serialize through that one lock exactly like an ordinary partial-vs-
    partial race: whichever acquires it first proceeds against Bin A's
    then-current 80 and succeeds; the second re-reads the bin balance
    post-lock and observes only 30 left -- rejected. Either winner is
    legitimate; both winning is not (80 cannot cover two independent
    50-unit claims), and the bin's total custody must always still sum to
    exactly 80 across whichever cohorts and bins hold it afterward."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("80"),
        )
        bin_a_id = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"]).id
        bin_b_id = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"]).id
        session.commit()
        inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_a_id,
            quantity=Decimal("80"), effective_time=_now(),
        )
        session.commit()
    finally:
        session.close()
        conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def quality_split_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            child = inventory_quality_service.apply_quality_disposition_to_partial_quantity(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                source_cohort_id=cohort_id, quantity=Decimal("50"), disposition="HELD", effective_time=_now(),
                reason="race test partial hold", custody_location_id=bin_a_id,
            )
            results["quality_split"] = ("ok", child.id)
        except InventoryQuantityCohortSplitAllocationExceedsBalanceError as exc:
            session.rollback()
            results["quality_split"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            session.rollback()
            results["quality_split"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def transfer_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            movement = inventory_storage_service.record_transfer(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), cohort_id=cohort_id, source_location_id=bin_a_id,
                destination_location_id=bin_b_id, quantity=Decimal("50"), effective_time=_now(),
            )
            results["transfer"] = ("ok", movement.id)
        except InsufficientStorageBinBalanceError as exc:
            session.rollback()
            results["transfer"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            session.rollback()
            results["transfer"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    threads = [threading.Thread(target=quality_split_worker), threading.Thread(target=transfer_worker)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not any(t.is_alive() for t in threads), "a deadlock would leave a thread hung past the join timeout"
    # Both operations lock the SAME source cohort row first (`_lock_cohort`
    # in both `apply_quality_disposition_to_partial_quantity` and
    # `record_transfer`), so whichever acquires it first proceeds to
    # completion against Bin A's then-current 80, and the second observes
    # the already-reduced 30 left for the parent cohort -- either winner is
    # a legitimate serialization, but never both (80 cannot cover two
    # independent 50-unit claims against the same bin/cohort)."""
    outcomes = {results["quality_split"][0], results["transfer"][0]}
    assert "error" not in outcomes, results
    ok_count = sum(1 for v in results.values() if v[0] == "ok")
    assert ok_count == 1, results

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        parent_bin_balance = inventory_existence_ledger_service.get_cohort_bin_balance(session, cohort_id=cohort_id, location_id=bin_a_id)
        child_bin_balance = Decimal("0")
        if results["quality_split"][0] == "ok":
            child_id = results["quality_split"][1]
            child_bin_balance = inventory_existence_ledger_service.get_cohort_bin_balance(session, cohort_id=child_id, location_id=bin_a_id)
        bin_b_balance = inventory_existence_ledger_service.get_cohort_bin_balance(session, cohort_id=cohort_id, location_id=bin_b_id)
        assert parent_bin_balance >= 0
        assert parent_bin_balance + child_bin_balance + bin_b_balance == Decimal("80")
    finally:
        session.close()
        conn.close()
