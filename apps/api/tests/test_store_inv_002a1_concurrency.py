"""STORE-INV-002A.1: deterministic two-connection concurrency proofs --
negative-adjustment races, canonical InventoryLot creation races, and
split-vs-adjustment races against the same cohort. Mirrors
test_farm_setup_idempotency_concurrency.py's own pattern: two independent
DB connections/sessions (never the shared, rollback-only `db_session`
fixture) and `threading.Barrier` for start synchronization -- no sleeps."""
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.goods_receipt_line import GoodsReceiptLine
from app.services import (
    goods_receipt_service,
    inventory_existence_ledger_service,
)
from app.services.errors import ConflictingInventoryLotIdentityError, InsufficientCohortBalanceError
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_item, split_cohort_for_test, uom_id
from tests._traceability_scenario import build_committed_tenant_farm


@dataclass
class _Scenario:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    farm_id: uuid.UUID
    item_id: uuid.UUID


def _committed_item(test_engine, *, lot_tracking_required=False) -> _Scenario:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        tenant, user, farm = build_committed_tenant_farm(session)
        category = build_category(session, tenant, actor_user_id=user.id)
        item = build_item(
            session, tenant, category.id, uom_id(session, "kg"), actor_user_id=user.id,
            lot_tracking_required=lot_tracking_required,
        )
        session.commit()
        return _Scenario(tenant_id=tenant.id, user_id=user.id, farm_id=farm.id, item_id=item.id)
    finally:
        session.close()
        conn.close()


def _receive_cohort(test_engine, *, scenario: _Scenario, quantity: Decimal) -> uuid.UUID:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        receipt = goods_receipt_service.record_goods_receipt(
            session, tenant_id=scenario.tenant_id, farm_id=scenario.farm_id, actor_user_id=scenario.user_id,
            client_command_id=uuid.uuid4(), received_at=datetime.now(timezone.utc), supplier_name=None,
            external_system=None, external_document_id=None, notes=None,
            lines=[
                GoodsReceiptLineInput(
                    inventory_item_id=scenario.item_id, entered_quantity=quantity,
                    entered_uom_id=uom_id(session, "kg"),
                )
            ],
        )
        line = session.execute(
            select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
        ).scalar_one()
        cohort_id = line.id
        session.commit()
        return cohort_id
    finally:
        session.close()
        conn.close()


def _adjustment_worker(test_engine, results, name, *, tenant_id, actor_user_id, cohort_id, delta, barrier) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        entry = inventory_existence_ledger_service.record_adjustment(
            session, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, quantity_delta=delta, effective_time=datetime.now(timezone.utc),
            reason=f"concurrency test {name}",
        )
        results[name] = ("ok", entry.id)
    except InsufficientCohortBalanceError as exc:
        session.rollback()
        results[name] = ("insufficient_balance", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_two_concurrent_adjustments_never_drive_balance_negative(test_engine) -> None:
    scenario = _committed_item(test_engine)
    cohort_id = _receive_cohort(test_engine, scenario=scenario, quantity=Decimal("100"))

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    # Each adjustment alone is safe (100-60=40); both together would go
    # negative (100-60-60=-20) -- the cohort row lock must serialize them so
    # exactly one succeeds and the other is correctly rejected, never both
    # succeeding and producing a negative balance.
    t_a = threading.Thread(
        target=_adjustment_worker, args=(test_engine, results, "a"),
        kwargs=dict(tenant_id=scenario.tenant_id, actor_user_id=scenario.user_id, cohort_id=cohort_id, delta=Decimal("-60"), barrier=barrier),
    )
    t_b = threading.Thread(
        target=_adjustment_worker, args=(test_engine, results, "b"),
        kwargs=dict(tenant_id=scenario.tenant_id, actor_user_id=scenario.user_id, cohort_id=cohort_id, delta=Decimal("-60"), barrier=barrier),
    )
    t_a.start(); t_b.start()
    t_a.join(timeout=15); t_b.join(timeout=15)

    outcomes = {results["a"][0], results["b"][0]}
    assert outcomes == {"ok", "insufficient_balance"}, results

    final_balance = inventory_existence_ledger_service.get_cohort_balance(
        Session(bind=test_engine.connect()), cohort_id=cohort_id
    )
    assert final_balance == Decimal("40")


def _lot_resolve_worker(test_engine, results, name, *, tenant_id, farm_id, actor_user_id, item_id, barrier) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        receipt = goods_receipt_service.record_goods_receipt(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id,
            client_command_id=uuid.uuid4(), received_at=datetime.now(timezone.utc), supplier_name=None,
            external_system=None, external_document_id=None, notes=None,
            lines=[
                GoodsReceiptLineInput(
                    inventory_item_id=item_id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(session, "kg"),
                    manufacturer_name="ConcurrentCo", manufacturer_lot_reference="RACE-001",
                )
            ],
        )
        line = session.execute(
            select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
        ).scalar_one()
        results[name] = ("ok", line.inventory_lot_id)
        session.commit()
    except ConflictingInventoryLotIdentityError as exc:
        session.rollback()
        results[name] = ("conflict", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_concurrent_lot_creation_never_duplicates_canonical_identity(test_engine) -> None:
    scenario = _committed_item(test_engine, lot_tracking_required=True)

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    t_a = threading.Thread(
        target=_lot_resolve_worker, args=(test_engine, results, "a"),
        kwargs=dict(
            tenant_id=scenario.tenant_id, farm_id=scenario.farm_id, actor_user_id=scenario.user_id,
            item_id=scenario.item_id, barrier=barrier,
        ),
    )
    t_b = threading.Thread(
        target=_lot_resolve_worker, args=(test_engine, results, "b"),
        kwargs=dict(
            tenant_id=scenario.tenant_id, farm_id=scenario.farm_id, actor_user_id=scenario.user_id,
            item_id=scenario.item_id, barrier=barrier,
        ),
    )
    t_a.start(); t_b.start()
    t_a.join(timeout=15); t_b.join(timeout=15)

    for name in ("a", "b"):
        assert results[name][0] == "ok", results

    from app.models.inventory_lot import InventoryLot

    session = Session(bind=test_engine.connect())
    try:
        lot_rows = session.execute(
            select(InventoryLot).where(
                InventoryLot.tenant_id == scenario.tenant_id, InventoryLot.inventory_item_id == scenario.item_id,
                InventoryLot.manufacturer_lot_reference == "RACE-001",
            )
        ).scalars().all()
        assert len(lot_rows) == 1
        assert results["a"][1] == results["b"][1] == lot_rows[0].id
    finally:
        session.close()


@pytest.mark.integration
def test_lot_identity_collision_is_retried_and_transparently_reused(test_engine, monkeypatch) -> None:
    """Deterministic (non-threaded) proof that losing the canonical-
    InventoryLot-identity race is retried once by `record_goods_receipt`
    and transparently reuses the winner's row (docs/domain/
    STORE_INVENTORY_MODEL.md §7), rather than surfacing a hard conflict for
    what is actually a benign concurrent duplicate. The failed first
    attempt calls `_next_code` once (racing to create its own row); the
    retry's own `_find_canonical` then finds the now-committed winner
    directly and reuses it WITHOUT ever calling `_next_code` again -- so
    `_next_code` being called exactly once, combined with the receipt
    ending up pointing at the winner's `InventoryLot` id and no second row
    ever existing, is the correct, complete proof of transparent reuse.

    The threaded test above proves the same code is safe under real
    concurrent connections, but thread/GIL scheduling cannot reliably force
    the exact race window (a competing commit strictly between our own
    `_find_canonical` check and our own INSERT) -- it is entirely possible
    for one racer to run to completion, including its own commit, before
    the other's first SELECT even executes, in which case the retry branch
    this test targets is never actually exercised (this is exactly what was
    observed while investigating this behavior: the threaded test above
    passed even before the retry existed). A monkeypatch forces that exact
    window instead, so this test fails if the retry-on-collision behavior
    regresses even when the threaded test above still happens to pass.
    Uses genuinely committed tenant/farm/item (`_committed_item`), not the
    shared rollback-only `db_session` fixture, since the competing
    "winner" write below needs a real second connection that can actually
    see this test's own rows."""
    scenario = _committed_item(test_engine, lot_tracking_required=True)

    from app.models.inventory_lot import InventoryLot
    from app.services import inventory_lot_service

    winner_lot_id = uuid.uuid4()
    real_next_code = inventory_lot_service._next_code
    calls = {"n": 0}

    def _collide_once_then_real_next_code(db, *, tenant_id, inventory_item_id, item_code):
        calls["n"] += 1
        if calls["n"] == 1:
            # Our own `_find_canonical` (called just before `_next_code`)
            # has already run and found nothing. Commit the SAME canonical
            # identity on a genuinely separate connection now, strictly
            # before our own INSERT below -- simulating a concurrent
            # receipt winning the race in that exact window.
            other = Session(bind=test_engine.connect())
            try:
                other.add(InventoryLot(
                    id=winner_lot_id, tenant_id=tenant_id, inventory_item_id=inventory_item_id,
                    code="LOT-RACE-WINNER", manufacturer_name="RaceCo", manufacturer_lot_reference="RACE-001",
                    manufacturing_date=None, expiry_date=None, created_by_user_id=scenario.user_id,
                ))
                other.commit()
            finally:
                other.close()
        return real_next_code(db, tenant_id=tenant_id, inventory_item_id=inventory_item_id, item_code=item_code)

    monkeypatch.setattr(inventory_lot_service, "_next_code", _collide_once_then_real_next_code)

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        receipt = goods_receipt_service.record_goods_receipt(
            session, tenant_id=scenario.tenant_id, farm_id=scenario.farm_id, actor_user_id=scenario.user_id,
            client_command_id=uuid.uuid4(), received_at=datetime.now(timezone.utc), supplier_name=None,
            external_system=None, external_document_id=None, notes=None,
            lines=[GoodsReceiptLineInput(
                inventory_item_id=scenario.item_id, entered_quantity=Decimal("10"),
                entered_uom_id=uom_id(session, "kg"), manufacturer_name="RaceCo",
                manufacturer_lot_reference="RACE-001",
            )],
        )
        session.commit()

        assert calls["n"] == 1, "the retry's own _find_canonical should reuse the winner without calling _next_code again"
        line = session.execute(
            select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
        ).scalar_one()
        assert line.inventory_lot_id == winner_lot_id

        lot_rows = session.execute(
            select(InventoryLot).where(
                InventoryLot.tenant_id == scenario.tenant_id, InventoryLot.inventory_item_id == scenario.item_id,
            )
        ).scalars().all()
        assert len(lot_rows) == 1, "the loser's failed attempt must never leave behind a second, orphaned lot row"
    finally:
        session.close()
        conn.close()


def _split_worker(test_engine, results, name, *, tenant_id, actor_user_id, cohort_id, allocation, barrier) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        children = split_cohort_for_test(
            session, tenant_id=tenant_id, actor_user_id=actor_user_id, source_cohort_id=cohort_id,
            allocations=[allocation], reason=f"concurrency split {name}", effective_time=datetime.now(timezone.utc),
        )
        results[name] = ("ok", [c.id for c in children])
    except InsufficientCohortBalanceError as exc:
        session.rollback()
        results[name] = ("insufficient", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_split_and_adjustment_race_serialize_on_cohort_lock(test_engine) -> None:
    scenario = _committed_item(test_engine)
    cohort_id = _receive_cohort(test_engine, scenario=scenario, quantity=Decimal("100"))

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    t_a = threading.Thread(
        target=_split_worker, args=(test_engine, results, "split"),
        kwargs=dict(tenant_id=scenario.tenant_id, actor_user_id=scenario.user_id, cohort_id=cohort_id, allocation=Decimal("70"), barrier=barrier),
    )
    t_b = threading.Thread(
        target=_adjustment_worker, args=(test_engine, results, "adjust"),
        kwargs=dict(tenant_id=scenario.tenant_id, actor_user_id=scenario.user_id, cohort_id=cohort_id, delta=Decimal("-50"), barrier=barrier),
    )
    t_a.start(); t_b.start()
    t_a.join(timeout=15); t_b.join(timeout=15)

    # Both operations serialize on the cohort's row lock -- whichever goes
    # first sees the full 100; the second sees the post-first balance. Since
    # 70 (split) + 50 (adjustment) = 120 > 100, at most one of the two can
    # fully succeed if they land in an order that would otherwise overdraw;
    # both succeeding is only valid if they serialize correctly and the
    # second still fits against the remaining balance in some order -- what
    # must NEVER happen is a negative final balance.
    final_balance = inventory_existence_ledger_service.get_cohort_balance(
        Session(bind=test_engine.connect()), cohort_id=cohort_id
    )
    assert final_balance >= Decimal("0")
    assert results["split"][0] in ("ok", "insufficient")
    assert results["adjust"][0] in ("ok", "insufficient_balance")
