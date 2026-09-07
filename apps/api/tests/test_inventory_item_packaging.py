"""STORE-INV-002A.1: InventoryItemPackaging service/idempotency tests."""
import uuid
from decimal import Decimal

import pytest

from app.services import (
    goods_receipt_service,
    inventory_item_packaging_service,
)
from app.services.errors import (
    DuplicateInventoryItemPackagingCodeError,
    InventoryItemPackagingCommandReusedWithDifferentPayloadError,
    InventoryItemPackagingNotActiveError,
    InventoryItemPackagingStructurallyLockedError,
)
from tests._store_inv_scenario import build_category, build_item, uom_id


@pytest.mark.integration
def test_create_packaging(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = build_category(db_session, tenant)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), lot_tracking_required=True)
    packaging = inventory_item_packaging_service.register_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        inventory_item_id=item.id, code="bag-25kg", display_name="25kg Bag", package_quantity=Decimal("25"),
    )
    assert packaging.code == "bag-25kg"
    assert packaging.status == "active"
    assert packaging.package_quantity == Decimal("25")


@pytest.mark.integration
def test_create_packaging_idempotent_replay(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = build_category(db_session, tenant)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"))
    ccid = uuid.uuid4()
    first = inventory_item_packaging_service.register_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=ccid, inventory_item_id=item.id,
        code="BAG-25KG", display_name="25kg Bag", package_quantity=Decimal("25"),
    )
    second = inventory_item_packaging_service.register_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=ccid, inventory_item_id=item.id,
        code="BAG-25KG", display_name="25kg Bag", package_quantity=Decimal("25"),
    )
    assert first.id == second.id


@pytest.mark.integration
def test_create_packaging_reused_command_different_payload(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = build_category(db_session, tenant)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"))
    ccid = uuid.uuid4()
    inventory_item_packaging_service.register_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=ccid, inventory_item_id=item.id,
        code="BAG-25KG", display_name="25kg Bag", package_quantity=Decimal("25"),
    )
    with pytest.raises(InventoryItemPackagingCommandReusedWithDifferentPayloadError):
        inventory_item_packaging_service.register_inventory_item_packaging(
            db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=ccid, inventory_item_id=item.id,
            code="BAG-50KG", display_name="50kg Bag", package_quantity=Decimal("50"),
        )


@pytest.mark.integration
def test_duplicate_code_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = build_category(db_session, tenant)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"))
    inventory_item_packaging_service.register_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        inventory_item_id=item.id, code="BAG-25KG", display_name="25kg Bag", package_quantity=Decimal("25"),
    )
    with pytest.raises(DuplicateInventoryItemPackagingCodeError):
        inventory_item_packaging_service.register_inventory_item_packaging(
            db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
            inventory_item_id=item.id, code="bag-25kg", display_name="Other", package_quantity=Decimal("30"),
        )


@pytest.mark.integration
def test_deactivate_and_reactivate_packaging(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = build_category(db_session, tenant)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"))
    packaging = inventory_item_packaging_service.register_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        inventory_item_id=item.id, code="BAG-25KG", display_name="25kg Bag", package_quantity=Decimal("25"),
    )
    deactivated = inventory_item_packaging_service.deactivate_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), packaging_id=packaging.id,
    )
    assert deactivated.status == "inactive"
    with pytest.raises(InventoryItemPackagingNotActiveError):
        inventory_item_packaging_service.deactivate_inventory_item_packaging(
            db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
            packaging_id=packaging.id,
        )
    reactivated = inventory_item_packaging_service.reactivate_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), packaging_id=packaging.id,
    )
    assert reactivated.status == "active"


@pytest.mark.integration
def test_package_quantity_freezes_after_first_receipt_use(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    packaging = inventory_item_packaging_service.register_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        inventory_item_id=item.id, code="BAG-25KG", display_name="25kg Bag", package_quantity=Decimal("25"),
    )
    # display_name-only update remains allowed pre- and post-use.
    inventory_item_packaging_service.update_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        packaging_id=packaging.id, display_name="Renamed Bag", package_quantity=Decimal("25"),
    )

    from datetime import datetime, timezone
    from app.services.goods_receipt_service import GoodsReceiptLineInput

    goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, packaging_id=packaging.id, package_count=4)],
    )

    with pytest.raises(InventoryItemPackagingStructurallyLockedError):
        inventory_item_packaging_service.update_inventory_item_packaging(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            packaging_id=packaging.id, display_name="Renamed Bag Again", package_quantity=Decimal("30"),
        )
    # display_name-only change remains allowed even after use -- only the
    # quantity itself is structurally frozen.
    still_ok = inventory_item_packaging_service.update_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        packaging_id=packaging.id, display_name="Renamed Bag Again", package_quantity=Decimal("25"),
    )
    assert still_ok.display_name == "Renamed Bag Again"


@pytest.mark.integration
def test_inactive_packaging_rejected_on_new_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    packaging = inventory_item_packaging_service.register_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        inventory_item_id=item.id, code="BAG-25KG", display_name="25kg Bag", package_quantity=Decimal("25"),
    )
    inventory_item_packaging_service.deactivate_inventory_item_packaging(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        packaging_id=packaging.id,
    )

    from datetime import datetime, timezone
    from app.services.goods_receipt_service import GoodsReceiptLineInput
    from app.services.errors import InventoryItemPackagingNotActiveError

    with pytest.raises(InventoryItemPackagingNotActiveError):
        goods_receipt_service.record_goods_receipt(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
            external_document_id=None, notes=None,
            lines=[GoodsReceiptLineInput(inventory_item_id=item.id, packaging_id=packaging.id, package_count=4)],
        )
