"""STORE-INV-002A.2 CTO closure pass: high-value two-connection concurrency
proofs -- exactly the four scenarios the closure pass called for, no
broader matrix. Mirrors `test_store_inv_002a1_concurrency.py`'s own
pattern exactly (independent DB connections/sessions, `threading.Barrier`
for start synchronization, no sleeps)."""
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.inventory_quality_command import InventoryQualityCommand
from app.models.quality_disposition_event import QualityDispositionEvent
from app.services import goods_receipt_service, inventory_existence_ledger_service, inventory_quality_service, user_service
from app.services.errors import (
    InsufficientCohortBalanceError,
    InvalidQualityDispositionTransitionError,
    InventoryQuantityCohortSplitAllocationExceedsBalanceError,
    QualityCorrectionTargetNotCurrentError,
    QualityDispositionCommandReusedWithDifferentPayloadError,
)
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_item, uom_id
from tests._traceability_scenario import build_committed_tenant_farm


@dataclass
class _Scenario:
    tenant_id: uuid.UUID
    receiver_user_id: uuid.UUID
    farm_id: uuid.UUID
    item_id: uuid.UUID


def _committed_item(test_engine, *, qc_release_required: bool = False) -> _Scenario:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        tenant, user, farm = build_committed_tenant_farm(session)
        category = build_category(session, tenant, actor_user_id=user.id)
        item = build_item(
            session, tenant, category.id, uom_id(session, "kg"), actor_user_id=user.id,
            lot_tracking_required=qc_release_required, qc_release_required=qc_release_required,
        )
        session.commit()
        return _Scenario(tenant_id=tenant.id, receiver_user_id=user.id, farm_id=farm.id, item_id=item.id)
    finally:
        session.close()
        conn.close()


def _receive_cohort(test_engine, *, scenario: _Scenario, quantity: Decimal) -> uuid.UUID:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        receipt = goods_receipt_service.record_goods_receipt(
            session, tenant_id=scenario.tenant_id, farm_id=scenario.farm_id, actor_user_id=scenario.receiver_user_id,
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


def _committed_actor(test_engine, *, suffix: str) -> uuid.UUID:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        user = user_service.create_user(
            session, oidc_issuer="https://issuer.example", oidc_subject=f"conc-{suffix}-{uuid.uuid4().hex[:6]}",
            email=f"conc-{suffix}-{uuid.uuid4().hex[:6]}@example.com", display_name="Concurrency Actor",
        )
        session.commit()
        return user.id
    finally:
        session.close()
        conn.close()


def _committed_event(
    test_engine, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, cohort_id: uuid.UUID, disposition: str,
    effective_time: datetime,
) -> uuid.UUID:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        event = inventory_quality_service.record_quality_disposition(
            session, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, disposition=disposition, effective_time=effective_time,
        )
        event_id = event.id
        session.commit()
        return event_id
    finally:
        session.close()
        conn.close()


# --- 1. correction vs new Quality decision ----------------------------------


def _correct_worker(test_engine, results, name, *, tenant_id, actor_user_id, cohort_id, target_event_id, barrier) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        reversal, _replacement = inventory_quality_service.correct_quality_disposition(
            session, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, target_event_id=target_event_id, reason="race test correction",
            replacement_disposition=None, effective_time=datetime.now(timezone.utc),
        )
        results[name] = ("ok", reversal.id)
    except QualityCorrectionTargetNotCurrentError as exc:
        session.rollback()
        results[name] = ("stale", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


def _record_worker(test_engine, results, name, *, tenant_id, actor_user_id, cohort_id, disposition, barrier) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        event = inventory_quality_service.record_quality_disposition(
            session, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, disposition=disposition, effective_time=datetime.now(timezone.utc),
        )
        results[name] = ("ok", event.id)
    except InvalidQualityDispositionTransitionError as exc:
        session.rollback()
        results[name] = ("invalid_transition", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_correction_vs_new_decision_never_both_succeed(test_engine) -> None:
    """A correction targeting the cohort's current HELD event races a new
    HOLD_RELEASED disposition on the same cohort. Whichever wins the
    cohort lock determines the other's fate, but the two outcomes can
    never both succeed: if the correction goes first (reverting to
    implicit RELEASED), the HOLD_RELEASED record becomes an illegal
    transition (RELEASED has no HOLD_RELEASED transition); if the record
    goes first, the correction's target is no longer current and is
    rejected as stale. Exactly one of the two always succeeds."""
    scenario = _committed_item(test_engine)
    cohort_id = _receive_cohort(test_engine, scenario=scenario, quantity=Decimal("100"))
    held_event_id = _committed_event(
        test_engine, tenant_id=scenario.tenant_id, actor_user_id=scenario.receiver_user_id, cohort_id=cohort_id,
        disposition="HELD", effective_time=datetime.now(timezone.utc),
    )
    other_actor = _committed_actor(test_engine, suffix="corr")

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    threads = [
        threading.Thread(
            target=_correct_worker, args=(test_engine, results, "correct"),
            kwargs=dict(
                tenant_id=scenario.tenant_id, actor_user_id=other_actor, cohort_id=cohort_id,
                target_event_id=held_event_id, barrier=barrier,
            ),
        ),
        threading.Thread(
            target=_record_worker, args=(test_engine, results, "record"),
            kwargs=dict(
                tenant_id=scenario.tenant_id, actor_user_id=scenario.receiver_user_id, cohort_id=cohort_id,
                disposition="HOLD_RELEASED", barrier=barrier,
            ),
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    outcomes = {results["correct"][0], results["record"][0]}
    assert "error" not in outcomes, results
    ok_count = sum(1 for v in results.values() if v[0] == "ok")
    assert ok_count == 1, results


# --- 2. two partial dispositions competing for the same source balance -----


def _partial_worker(
    test_engine, results, name, *, tenant_id, actor_user_id, cohort_id, quantity, disposition, barrier,
) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        child = inventory_quality_service.apply_quality_disposition_to_partial_quantity(
            session, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
            source_cohort_id=cohort_id, quantity=quantity, disposition=disposition,
            effective_time=datetime.now(timezone.utc), reason=f"race test {name}",
        )
        results[name] = ("ok", child.id)
    except InventoryQuantityCohortSplitAllocationExceedsBalanceError as exc:
        session.rollback()
        results[name] = ("insufficient", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_two_concurrent_partial_dispositions_never_overallocate(test_engine) -> None:
    """Cohort balance 100; two concurrent partial actions request 70 and 50
    respectively (together 120 > 100). The cohort lock must serialize them:
    exactly one succeeds, the other is rejected once it observes the
    already-reduced balance -- total allocation never exceeds the source's
    original balance."""
    scenario = _committed_item(test_engine)
    cohort_id = _receive_cohort(test_engine, scenario=scenario, quantity=Decimal("100"))

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    threads = [
        threading.Thread(
            target=_partial_worker, args=(test_engine, results, "a"),
            kwargs=dict(
                tenant_id=scenario.tenant_id, actor_user_id=scenario.receiver_user_id, cohort_id=cohort_id,
                quantity=Decimal("70"), disposition="HELD", barrier=barrier,
            ),
        ),
        threading.Thread(
            target=_partial_worker, args=(test_engine, results, "b"),
            kwargs=dict(
                tenant_id=scenario.tenant_id, actor_user_id=scenario.receiver_user_id, cohort_id=cohort_id,
                quantity=Decimal("50"), disposition="REJECTED", barrier=barrier,
            ),
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    outcomes = {results["a"][0], results["b"][0]}
    assert outcomes == {"ok", "insufficient"}, results

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        source_balance = inventory_existence_ledger_service.get_cohort_balance(session, cohort_id=cohort_id)
        children = session.execute(
            select(func.count()).select_from(
                select(QualityDispositionEvent.inventory_quantity_cohort_id).where(
                    QualityDispositionEvent.command_id.in_(
                        select(InventoryQualityCommand.id).where(
                            InventoryQualityCommand.inventory_quantity_cohort_id == cohort_id,
                            InventoryQualityCommand.operation_kind == "PARTIAL",
                        )
                    )
                ).subquery()
            )
        ).scalar_one()
        assert children == 1
        assert source_balance >= 0
    finally:
        session.close()
        conn.close()


# --- 3. partial disposition vs quantity adjustment --------------------------


def _adjustment_worker(test_engine, results, name, *, tenant_id, actor_user_id, cohort_id, delta, barrier) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        entry = inventory_existence_ledger_service.record_adjustment(
            session, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, quantity_delta=delta, effective_time=datetime.now(timezone.utc),
            reason="race test adjustment",
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
def test_partial_disposition_vs_adjustment_never_drives_balance_negative(test_engine) -> None:
    """Cohort balance 100; a partial disposition requests 80, a concurrent
    adjustment requests -30 (together would overdraw by 10). Both acquire
    the SAME cohort `FOR UPDATE` lock (`.1`'s own lock target, reused
    unchanged by `.2`), so they serialize naturally: exactly one succeeds,
    the other is rejected once it observes the already-reduced balance."""
    scenario = _committed_item(test_engine)
    cohort_id = _receive_cohort(test_engine, scenario=scenario, quantity=Decimal("100"))

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    threads = [
        threading.Thread(
            target=_partial_worker, args=(test_engine, results, "partial"),
            kwargs=dict(
                tenant_id=scenario.tenant_id, actor_user_id=scenario.receiver_user_id, cohort_id=cohort_id,
                quantity=Decimal("80"), disposition="HELD", barrier=barrier,
            ),
        ),
        threading.Thread(
            target=_adjustment_worker, args=(test_engine, results, "adjustment"),
            kwargs=dict(
                tenant_id=scenario.tenant_id, actor_user_id=scenario.receiver_user_id, cohort_id=cohort_id,
                delta=Decimal("-30"), barrier=barrier,
            ),
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    outcomes = {results["partial"][0], results["adjustment"][0]}
    assert "error" not in outcomes, results
    ok_count = sum(1 for v in results.values() if v[0] == "ok")
    assert ok_count == 1, results

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        balance = inventory_existence_ledger_service.get_cohort_balance(session, cohort_id=cohort_id)
        assert balance >= 0
    finally:
        session.close()
        conn.close()


# --- 4. cross-cohort same-client-command-id race ----------------------------


def _record_with_fixed_command_id_worker(
    test_engine, results, name, *, tenant_id, actor_user_id, cohort_id, client_command_id, barrier,
) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        event = inventory_quality_service.record_quality_disposition(
            session, tenant_id=tenant_id, actor_user_id=actor_user_id, client_command_id=client_command_id,
            cohort_id=cohort_id, disposition="RELEASED", effective_time=datetime.now(timezone.utc),
        )
        results[name] = ("ok", event.id)
    except QualityDispositionCommandReusedWithDifferentPayloadError as exc:
        session.rollback()
        results[name] = ("conflict", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_cross_cohort_same_client_command_id_never_creates_two_commands(test_engine) -> None:
    """THE core proof for the command-idempotency fix: two DIFFERENT
    cohorts (different `FOR UPDATE` locks, so they cannot serialize
    against each other via cohort locking alone) are targeted by
    concurrent RELEASE commands sharing the SAME `client_command_id`. The
    `inventory_quality_commands` table's own `(tenant_id, client_command_id)`
    unique index is the only thing that can prevent two logical commands
    from being created -- exactly one request succeeds, the other is
    rejected as a payload conflict (different cohort_id embedded in its
    fingerprint), and only one `InventoryQualityCommand` row ever exists
    for this `client_command_id`."""
    # qc_release_required=True so both cohorts start RECEIVED_QUARANTINED --
    # RELEASED is a legal transition from there (unlike from implicit
    # RELEASED, which would make this a transition-legality test instead
    # of an idempotency-race test). Both actors are fresh, non-receiver
    # users, so segregation-of-duty never interferes either.
    scenario = _committed_item(test_engine, qc_release_required=True)
    cohort_a = _receive_cohort(test_engine, scenario=scenario, quantity=Decimal("50"))
    cohort_b = _receive_cohort(test_engine, scenario=scenario, quantity=Decimal("50"))
    actor_a = _committed_actor(test_engine, suffix="xa")
    actor_b = _committed_actor(test_engine, suffix="xb")
    shared_client_command_id = uuid.uuid4()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    threads = [
        threading.Thread(
            target=_record_with_fixed_command_id_worker, args=(test_engine, results, "a"),
            kwargs=dict(
                tenant_id=scenario.tenant_id, actor_user_id=actor_a, cohort_id=cohort_a,
                client_command_id=shared_client_command_id, barrier=barrier,
            ),
        ),
        threading.Thread(
            target=_record_with_fixed_command_id_worker, args=(test_engine, results, "b"),
            kwargs=dict(
                tenant_id=scenario.tenant_id, actor_user_id=actor_b, cohort_id=cohort_b,
                client_command_id=shared_client_command_id, barrier=barrier,
            ),
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    outcomes = {results["a"][0], results["b"][0]}
    assert outcomes == {"ok", "conflict"}, results

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        command_count = session.execute(
            select(func.count()).select_from(InventoryQualityCommand).where(
                InventoryQualityCommand.tenant_id == scenario.tenant_id,
                InventoryQualityCommand.client_command_id == shared_client_command_id,
            )
        ).scalar_one()
        assert command_count == 1
    finally:
        session.close()
        conn.close()
