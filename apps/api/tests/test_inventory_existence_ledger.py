"""STORE-INV-002A.1: existence ledger -- Adjustment, Reversal, and the
internal cohort-split primitive."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.goods_receipt_line import GoodsReceiptLine
from app.services import goods_receipt_service, inventory_existence_ledger_service
from app.services.errors import (
    InsufficientCohortBalanceError,
    InventoryAdjustmentCommandReusedWithDifferentPayloadError,
    InventoryExistenceReversalCommandReusedWithDifferentPayloadError,
    InventoryExistenceReversalOfReversalError,
    InventoryExistenceReversalTargetAlreadyReversedError,
    InventoryQuantityCohortSplitAllocationExceedsBalanceError,
)
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_item, split_cohort_for_test, uom_id


def _receive_cohort_id(db, tenant, farm, user, item, quantity: Decimal):
    receipt = goods_receipt_service.record_goods_receipt(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=quantity, entered_uom_id=uom_id(db, "kg"))],
    )
    line = db.execute(select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)).scalar_one()
    return line.id


@pytest.mark.integration
def test_adjustment_positive_and_negative(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    cohort_id = _receive_cohort_id(db_session, tenant, farm, user, item, Decimal("100"))

    inventory_existence_ledger_service.record_adjustment(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, quantity_delta=Decimal("-2"), effective_time=datetime.now(timezone.utc),
        reason="Physical recount variance",
    )
    balance = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    assert balance == Decimal("98")

    inventory_existence_ledger_service.record_adjustment(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, quantity_delta=Decimal("5"), effective_time=datetime.now(timezone.utc),
        reason="Found extra stock",
    )
    balance = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    assert balance == Decimal("103")


@pytest.mark.integration
def test_adjustment_cannot_drive_balance_negative(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    cohort_id = _receive_cohort_id(db_session, tenant, farm, user, item, Decimal("10"))

    with pytest.raises(InsufficientCohortBalanceError):
        inventory_existence_ledger_service.record_adjustment(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, quantity_delta=Decimal("-20"), effective_time=datetime.now(timezone.utc),
            reason="Too much",
        )


@pytest.mark.integration
def test_adjustment_idempotent_replay_and_conflict(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    cohort_id = _receive_cohort_id(db_session, tenant, farm, user, item, Decimal("10"))
    ccid = uuid.uuid4()
    effective = datetime.now(timezone.utc)
    first = inventory_existence_ledger_service.record_adjustment(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=ccid, cohort_id=cohort_id,
        quantity_delta=Decimal("-1"), effective_time=effective, reason="test",
    )
    second = inventory_existence_ledger_service.record_adjustment(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=ccid, cohort_id=cohort_id,
        quantity_delta=Decimal("-1"), effective_time=effective, reason="test",
    )
    assert first.id == second.id
    with pytest.raises(InventoryAdjustmentCommandReusedWithDifferentPayloadError):
        inventory_existence_ledger_service.record_adjustment(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=ccid, cohort_id=cohort_id,
            quantity_delta=Decimal("-2"), effective_time=effective, reason="different",
        )


@pytest.mark.integration
def test_reversal_exact_negation_and_double_reversal_blocked(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    cohort_id = _receive_cohort_id(db_session, tenant, farm, user, item, Decimal("50"))

    adjustment = inventory_existence_ledger_service.record_adjustment(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), cohort_id=cohort_id,
        quantity_delta=Decimal("-10"), effective_time=datetime.now(timezone.utc), reason="oops",
    )
    assert inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id) == Decimal("40")

    reversal = inventory_existence_ledger_service.reverse_ledger_entry(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        target_entry_id=adjustment.id, reason="correcting the mistake",
    )
    assert reversal.quantity_delta_base == Decimal("10")
    assert inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id) == Decimal("50")

    with pytest.raises(InventoryExistenceReversalTargetAlreadyReversedError):
        inventory_existence_ledger_service.reverse_ledger_entry(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            target_entry_id=adjustment.id, reason="again",
        )

    with pytest.raises(InventoryExistenceReversalOfReversalError):
        inventory_existence_ledger_service.reverse_ledger_entry(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            target_entry_id=reversal.id, reason="reversing a reversal",
        )


@pytest.mark.integration
def test_reversal_idempotent_replay(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    cohort_id = _receive_cohort_id(db_session, tenant, farm, user, item, Decimal("50"))
    adjustment = inventory_existence_ledger_service.record_adjustment(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), cohort_id=cohort_id,
        quantity_delta=Decimal("-5"), effective_time=datetime.now(timezone.utc), reason="oops",
    )
    ccid = uuid.uuid4()
    first = inventory_existence_ledger_service.reverse_ledger_entry(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=ccid,
        target_entry_id=adjustment.id, reason="fix",
    )
    second = inventory_existence_ledger_service.reverse_ledger_entry(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=ccid,
        target_entry_id=adjustment.id, reason="fix",
    )
    assert first.id == second.id
    with pytest.raises(InventoryExistenceReversalCommandReusedWithDifferentPayloadError):
        inventory_existence_ledger_service.reverse_ledger_entry(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=ccid,
            target_entry_id=adjustment.id, reason="different reason",
        )


@pytest.mark.integration
def test_split_cohort_partial_and_full(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    cohort_id = _receive_cohort_id(db_session, tenant, farm, user, item, Decimal("500"))

    children = split_cohort_for_test(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, source_cohort_id=cohort_id,
        allocations=[Decimal("450"), Decimal("50")], reason="partial QC split",
        effective_time=datetime.now(timezone.utc),
    )
    assert len(children) == 2
    source_balance = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    assert source_balance == Decimal("0")
    child_balances = sorted(
        inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=c.id) for c in children
    )
    assert child_balances == [Decimal("50"), Decimal("450")]
    # total existence unchanged
    assert source_balance + sum(child_balances) == Decimal("500")
    for child in children:
        assert child.inventory_item_id == item.id
        assert child.source_goods_receipt_line_id == cohort_id


@pytest.mark.integration
def test_split_partial_leaves_source_with_remainder(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    cohort_id = _receive_cohort_id(db_session, tenant, farm, user, item, Decimal("500"))

    children = split_cohort_for_test(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, source_cohort_id=cohort_id,
        allocations=[Decimal("100")], reason="later partial hold", effective_time=datetime.now(timezone.utc),
    )
    source_balance = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    assert source_balance == Decimal("400")
    assert inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=children[0].id) == Decimal("100")


@pytest.mark.integration
def test_split_allocation_exceeding_balance_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    cohort_id = _receive_cohort_id(db_session, tenant, farm, user, item, Decimal("100"))
    with pytest.raises(InventoryQuantityCohortSplitAllocationExceedsBalanceError):
        split_cohort_for_test(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, source_cohort_id=cohort_id,
            allocations=[Decimal("60"), Decimal("60")], reason="too much",
            effective_time=datetime.now(timezone.utc),
        )
