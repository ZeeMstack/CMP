"""STORE-INV-002A.1: InventoryLot tenant-wide identity/matching tests."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.services import goods_receipt_service
from app.services.errors import ConflictingInventoryLotIdentityError
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_item, uom_id


def _receive(db, tenant, farm, user, item, **line_kwargs):
    return goods_receipt_service.record_goods_receipt(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, **line_kwargs)],
    )


@pytest.mark.integration
def test_same_manufacturer_and_reference_resolves_same_lot(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id, lot_tracking_required=True,
    )
    r1 = _receive(
        db_session, tenant, farm, user, item, entered_quantity=Decimal("250"), entered_uom_id=uom_id(db_session, "kg"),
        manufacturer_name="Yara", manufacturer_lot_reference="CN001", expiry_date=date(2027, 12, 31),
    )
    r2 = _receive(
        db_session, tenant, farm, user, item, entered_quantity=Decimal("125"), entered_uom_id=uom_id(db_session, "kg"),
        manufacturer_name="yara ", manufacturer_lot_reference=" cn001", expiry_date=date(2027, 12, 31),
    )
    from app.models.goods_receipt_line import GoodsReceiptLine
    from sqlalchemy import select
    lot_id_1 = db_session.execute(
        select(GoodsReceiptLine.inventory_lot_id).where(GoodsReceiptLine.goods_receipt_id == r1.id)
    ).scalar_one()
    lot_id_2 = db_session.execute(
        select(GoodsReceiptLine.inventory_lot_id).where(GoodsReceiptLine.goods_receipt_id == r2.id)
    ).scalar_one()
    assert lot_id_1 == lot_id_2


@pytest.mark.integration
def test_different_manufacturer_same_reference_creates_distinct_lots(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id, lot_tracking_required=True,
    )
    from app.models.goods_receipt_line import GoodsReceiptLine
    from sqlalchemy import select

    r1 = _receive(
        db_session, tenant, farm, user, item, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"),
        manufacturer_name="Manufacturer A", manufacturer_lot_reference="12345",
    )
    r2 = _receive(
        db_session, tenant, farm, user, item, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"),
        manufacturer_name="Manufacturer B", manufacturer_lot_reference="12345",
    )
    lot_id_1 = db_session.execute(
        select(GoodsReceiptLine.inventory_lot_id).where(GoodsReceiptLine.goods_receipt_id == r1.id)
    ).scalar_one()
    lot_id_2 = db_session.execute(
        select(GoodsReceiptLine.inventory_lot_id).where(GoodsReceiptLine.goods_receipt_id == r2.id)
    ).scalar_one()
    assert lot_id_1 != lot_id_2


@pytest.mark.integration
def test_incomplete_manufacturer_identity_never_auto_matches(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id, lot_tracking_required=True,
    )
    from app.models.goods_receipt_line import GoodsReceiptLine
    from sqlalchemy import select

    r1 = _receive(db_session, tenant, farm, user, item, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"))
    r2 = _receive(db_session, tenant, farm, user, item, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"))
    lot_id_1 = db_session.execute(
        select(GoodsReceiptLine.inventory_lot_id).where(GoodsReceiptLine.goods_receipt_id == r1.id)
    ).scalar_one()
    lot_id_2 = db_session.execute(
        select(GoodsReceiptLine.inventory_lot_id).where(GoodsReceiptLine.goods_receipt_id == r2.id)
    ).scalar_one()
    assert lot_id_1 != lot_id_2 and lot_id_1 is not None and lot_id_2 is not None


@pytest.mark.integration
def test_same_canonical_identity_null_vs_known_expiry_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id, lot_tracking_required=True,
    )
    _receive(
        db_session, tenant, farm, user, item, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"),
        manufacturer_name="Yara", manufacturer_lot_reference="CN777",
    )
    with pytest.raises(ConflictingInventoryLotIdentityError):
        _receive(
            db_session, tenant, farm, user, item, entered_quantity=Decimal("5"),
            entered_uom_id=uom_id(db_session, "kg"), manufacturer_name="Yara", manufacturer_lot_reference="CN777",
            expiry_date=date(2028, 1, 1),
        )


@pytest.mark.integration
def test_same_canonical_identity_conflicting_known_expiry(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id, lot_tracking_required=True,
    )
    _receive(
        db_session, tenant, farm, user, item, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"),
        manufacturer_name="Yara", manufacturer_lot_reference="CN888", expiry_date=date(2027, 1, 1),
    )
    with pytest.raises(ConflictingInventoryLotIdentityError):
        _receive(
            db_session, tenant, farm, user, item, entered_quantity=Decimal("5"),
            entered_uom_id=uom_id(db_session, "kg"), manufacturer_name="Yara", manufacturer_lot_reference="CN888",
            expiry_date=date(2028, 1, 1),
        )


@pytest.mark.integration
def test_lot_resolves_across_farms_tenant_wide(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    from app.services import farm_service

    farm_a = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="farm-a", name="Farm A",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    farm_b = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="farm-b", name="Farm B",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id, lot_tracking_required=True,
    )
    from app.models.goods_receipt_line import GoodsReceiptLine
    from sqlalchemy import select

    r1 = _receive(
        db_session, tenant, farm_a, user, item, entered_quantity=Decimal("250"),
        entered_uom_id=uom_id(db_session, "kg"), manufacturer_name="Yara", manufacturer_lot_reference="MG-500",
    )
    r2 = _receive(
        db_session, tenant, farm_b, user, item, entered_quantity=Decimal("100"),
        entered_uom_id=uom_id(db_session, "kg"), manufacturer_name="Yara", manufacturer_lot_reference="MG-500",
    )
    lot_id_1 = db_session.execute(
        select(GoodsReceiptLine.inventory_lot_id).where(GoodsReceiptLine.goods_receipt_id == r1.id)
    ).scalar_one()
    lot_id_2 = db_session.execute(
        select(GoodsReceiptLine.inventory_lot_id).where(GoodsReceiptLine.goods_receipt_id == r2.id)
    ).scalar_one()
    assert lot_id_1 == lot_id_2

    from app.services import inventory_existence_read_service
    total = inventory_existence_read_service.get_lot_existence(db_session, tenant_id=tenant.id, inventory_lot_id=lot_id_1)
    assert total == Decimal("350.000")
