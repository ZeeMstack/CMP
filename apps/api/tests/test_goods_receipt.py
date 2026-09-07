"""STORE-INV-002A.1: `record_goods_receipt` atomicity/idempotency/isolation
tests."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.goods_receipt import GoodsReceipt
from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.inventory_quantity_cohort import InventoryQuantityCohort
from app.models.quality_disposition_event import QualityDispositionEvent
from app.models.seed_lot import SeedLot
from app.services import goods_receipt_service, inventory_item_seed_profile_service
from app.services.errors import (
    GoodsReceiptCommandReusedWithDifferentPayloadError,
    GoodsReceiptItemNotActiveError,
    GoodsReceiptLineValidationError,
    GoodsReceiptNotFoundError,
    InventoryItemNotFoundError,
)
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_crop_and_variety, build_item, uom_id


@pytest.mark.integration
def test_atomic_multi_line_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item_a = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    item_b = build_item(db_session, tenant, category.id, uom_id(db_session, "EA"), actor_user_id=user.id)

    receipt = goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name="Acme Supplies", external_system=None,
        external_document_id=None, notes=None,
        lines=[
            GoodsReceiptLineInput(inventory_item_id=item_a.id, entered_quantity=Decimal("500"), entered_uom_id=uom_id(db_session, "kg")),
            GoodsReceiptLineInput(inventory_item_id=item_b.id, entered_quantity=Decimal("100"), entered_uom_id=uom_id(db_session, "EA")),
        ],
    )
    lines = db_session.execute(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
    ).scalars().all()
    assert len(lines) == 2
    cohort_count = db_session.execute(
        select(func.count()).select_from(InventoryQuantityCohort).where(
            InventoryQuantityCohort.source_goods_receipt_line_id.in_([l.id for l in lines])
        )
    ).scalar_one()
    assert cohort_count == 2


@pytest.mark.integration
def test_bad_line_rolls_back_entire_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item_a = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)

    with pytest.raises(InventoryItemNotFoundError):
        goods_receipt_service.record_goods_receipt(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
            external_document_id=None, notes=None,
            lines=[
                GoodsReceiptLineInput(inventory_item_id=item_a.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg")),
                GoodsReceiptLineInput(inventory_item_id=uuid.uuid4(), entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg")),
            ],
        )
    # Scoped to this test's own tenant (freshly created per test by
    # `active_context_with_farm`), never a bare global table count -- a
    # committed-connection test elsewhere in the same pytest run must never
    # be able to poison this assertion (docs/testing/
    # TEST_DATABASE_RELIABILITY.md; STORE-INV-002A.1 CTO integrity review).
    receipt_count = db_session.execute(
        select(func.count()).select_from(GoodsReceipt).where(GoodsReceipt.tenant_id == tenant.id)
    ).scalar_one()
    assert receipt_count == 0
    line_count = db_session.execute(
        select(func.count()).select_from(GoodsReceiptLine).where(GoodsReceiptLine.tenant_id == tenant.id)
    ).scalar_one()
    assert line_count == 0


@pytest.mark.integration
def test_inactive_item_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    from app.services import inventory_item_service

    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    inventory_item_service.deactivate_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), item_id=item.id,
    )
    with pytest.raises(GoodsReceiptItemNotActiveError):
        goods_receipt_service.record_goods_receipt(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
            external_document_id=None, notes=None,
            lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"))],
        )


@pytest.mark.integration
def test_direct_uom_conversion(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    receipt = goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("2000"), entered_uom_id=uom_id(db_session, "g"))],
    )
    line = db_session.execute(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
    ).scalar_one()
    assert line.base_quantity == Decimal("2.000")
    assert line.conversion_factor_applied == Decimal("0.001")


@pytest.mark.integration
def test_invalid_conversion_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "EA"), actor_user_id=user.id)
    with pytest.raises(GoodsReceiptLineValidationError):
        goods_receipt_service.record_goods_receipt(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
            external_document_id=None, notes=None,
            lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "SEED"))],
        )


@pytest.mark.integration
def test_idempotent_replay_returns_same_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    ccid = uuid.uuid4()
    effective = datetime.now(timezone.utc)
    kwargs = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        received_at=effective, supplier_name=None, external_system=None, external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"))],
    )
    first = goods_receipt_service.record_goods_receipt(db_session, **kwargs)
    second = goods_receipt_service.record_goods_receipt(db_session, **kwargs)
    assert first.id == second.id
    # Scoped to this exact command, not a bare global table count -- see
    # note in test_bad_line_rolls_back_entire_receipt above.
    receipt_count = db_session.execute(
        select(func.count()).select_from(GoodsReceipt).where(GoodsReceipt.client_command_id == ccid)
    ).scalar_one()
    assert receipt_count == 1


@pytest.mark.integration
def test_reused_command_id_different_payload_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    ccid = uuid.uuid4()
    goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"))],
    )
    with pytest.raises(GoodsReceiptCommandReusedWithDifferentPayloadError):
        goods_receipt_service.record_goods_receipt(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
            received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
            external_document_id=None, notes=None,
            lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("20"), entered_uom_id=uom_id(db_session, "kg"))],
        )


@pytest.mark.integration
def test_tenant_and_farm_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    from app.services import tenant_service

    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    receipt = goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"))],
    )
    other_tenant = tenant_service.create_tenant(db_session, code="other-tenant", name="Other Tenant")
    with pytest.raises(GoodsReceiptNotFoundError):
        goods_receipt_service.get_goods_receipt(
            db_session, tenant_id=other_tenant.id, farm_id=farm.id, receipt_id=receipt.id
        )


@pytest.mark.integration
def test_seed_linked_receipt_creates_farm_seed_lot(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "SEED"), actor_user_id=user.id,
        lot_tracking_required=True,
    )
    crop, variety = build_crop_and_variety(db_session, tenant, actor_user_id=user.id)
    inventory_item_seed_profile_service.register_seed_profile(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        inventory_item_id=item.id, crop_id=crop.id, variety_id=variety.id,
    )

    receipt = goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[
            GoodsReceiptLineInput(
                inventory_item_id=item.id, entered_quantity=Decimal("10000"), entered_uom_id=uom_id(db_session, "SEED"),
                manufacturer_name="RijkZwaan", manufacturer_lot_reference="RZ123", seed_crop_id=crop.id,
                seed_variety_id=variety.id, seed_lot_code="RZ123-SEEDLOT",
            )
        ],
    )
    line = db_session.execute(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
    ).scalar_one()
    seed_lot = db_session.execute(
        select(SeedLot).where(SeedLot.inventory_lot_id == line.inventory_lot_id, SeedLot.farm_id == farm.id)
    ).scalar_one()
    assert seed_lot.code == "RZ123-SEEDLOT"
    assert seed_lot.supplier_lot_reference == "RZ123"


@pytest.mark.integration
def test_qc_required_item_receipt_auto_opens_quarantine(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id,
        lot_tracking_required=True, qc_release_required=True,
    )
    receipt = goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"))],
    )
    line = db_session.execute(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
    ).scalar_one()
    events = db_session.execute(
        select(QualityDispositionEvent).where(QualityDispositionEvent.inventory_quantity_cohort_id == line.id)
    ).scalars().all()
    assert len(events) == 1
    assert events[0].event_kind == "RECEIVED_QUARANTINED"


@pytest.mark.integration
def test_non_qc_item_receipt_has_no_opening_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    receipt = goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"))],
    )
    line = db_session.execute(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
    ).scalar_one()
    event_count = db_session.execute(
        select(func.count()).select_from(QualityDispositionEvent).where(
            QualityDispositionEvent.inventory_quantity_cohort_id == line.id
        )
    ).scalar_one()
    assert event_count == 0


@pytest.mark.integration
def test_non_lot_tracked_item_cohort_has_null_lot(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "EA"), actor_user_id=user.id)
    receipt = goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("100"), entered_uom_id=uom_id(db_session, "EA"))],
    )
    line = db_session.execute(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
    ).scalar_one()
    assert line.inventory_lot_id is None
    cohort = db_session.execute(
        select(InventoryQuantityCohort).where(InventoryQuantityCohort.id == line.id)
    ).scalar_one()
    assert cohort.inventory_lot_id is None

    from app.services import inventory_existence_read_service
    total = inventory_existence_read_service.get_item_existence(db_session, tenant_id=tenant.id, inventory_item_id=item.id)
    assert total == Decimal("100.000")


@pytest.mark.integration
def test_non_lot_tracked_item_rejects_manufacturer_fields(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "EA"), actor_user_id=user.id)
    with pytest.raises(GoodsReceiptLineValidationError):
        goods_receipt_service.record_goods_receipt(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
            external_document_id=None, notes=None,
            lines=[
                GoodsReceiptLineInput(
                    inventory_item_id=item.id, entered_quantity=Decimal("100"), entered_uom_id=uom_id(db_session, "EA"),
                    manufacturer_name="Someone",
                )
            ],
        )
