"""STORE-INV-002A.1: InventoryItem structural-field freeze after first
posted GoodsReceiptLine (docs/domain/STORE_INVENTORY_MODEL.md §O/§T)."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services import goods_receipt_service, inventory_item_service
from app.services.errors import InventoryItemPolicyFrozenError
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_item, uom_id


@pytest.mark.integration
def test_structural_fields_freeze_after_first_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)

    goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"))],
    )

    with pytest.raises(InventoryItemPolicyFrozenError):
        inventory_item_service.update_inventory_item(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            item_id=item.id, name=item.name, category_id=item.inventory_category_id,
            base_uom_id=uom_id(db_session, "g"), lot_tracking_required=item.lot_tracking_required,
            expiry_tracking_required=item.expiry_tracking_required, qc_release_required=item.qc_release_required,
        )

    with pytest.raises(InventoryItemPolicyFrozenError):
        inventory_item_service.update_inventory_item(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            item_id=item.id, name=item.name, category_id=item.inventory_category_id,
            base_uom_id=item.base_uom_id, lot_tracking_required=True,
            expiry_tracking_required=item.expiry_tracking_required, qc_release_required=item.qc_release_required,
        )


@pytest.mark.integration
def test_renaming_after_receipt_still_allowed(db_session, active_context_with_farm) -> None:
    """Only the structural fields freeze -- name/category/status remain
    editable per InventoryItem's existing, unchanged rules."""
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)

    goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"))],
    )

    updated = inventory_item_service.update_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        item_id=item.id, name="Renamed Item", category_id=item.inventory_category_id,
        base_uom_id=item.base_uom_id, lot_tracking_required=item.lot_tracking_required,
        expiry_tracking_required=item.expiry_tracking_required, qc_release_required=item.qc_release_required,
    )
    assert updated.name == "Renamed Item"


@pytest.mark.integration
def test_inactive_item_cannot_receive(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    inventory_item_service.deactivate_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), item_id=item.id,
    )
    from app.services.errors import GoodsReceiptItemNotActiveError

    with pytest.raises(GoodsReceiptItemNotActiveError):
        goods_receipt_service.record_goods_receipt(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
            external_document_id=None, notes=None,
            lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"))],
        )
