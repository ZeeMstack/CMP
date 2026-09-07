"""STORE-INV-002A.1: InventoryItemSeedProfile ("Seed Details") tests."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.services import goods_receipt_service, inventory_item_seed_profile_service
from app.services.errors import (
    InventoryItemSeedProfileAlreadyExistsError,
    InventoryItemSeedProfileCreationBlockedError,
    InventoryItemSeedProfileStructurallyLockedError,
)
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_crop_and_variety, build_item, uom_id


@pytest.mark.integration
def test_create_update_remove_seed_profile_before_use(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "SEED"), actor_user_id=user.id)
    crop, variety = build_crop_and_variety(db_session, tenant, actor_user_id=user.id)
    crop2, variety2 = build_crop_and_variety(db_session, tenant, actor_user_id=user.id)

    profile = inventory_item_seed_profile_service.register_seed_profile(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        inventory_item_id=item.id, crop_id=crop.id, variety_id=variety.id,
    )
    assert profile.crop_id == crop.id

    updated = inventory_item_seed_profile_service.update_seed_profile(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        profile_id=profile.id, crop_id=crop2.id, variety_id=variety2.id,
    )
    assert updated.crop_id == crop2.id

    inventory_item_seed_profile_service.remove_seed_profile(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        profile_id=profile.id,
    )
    assert inventory_item_seed_profile_service.get_seed_profile_for_item(
        db_session, tenant_id=tenant.id, inventory_item_id=item.id
    ) is None

    removal_audit = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "inventory_item_seed_profile.removed", AuditEvent.entity_id == profile.id
        )
    ).scalar_one()
    assert removal_audit == 1


@pytest.mark.integration
def test_remove_already_removed_profile_is_idempotent_noop(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "SEED"), actor_user_id=user.id)
    crop, variety = build_crop_and_variety(db_session, tenant, actor_user_id=user.id)
    profile = inventory_item_seed_profile_service.register_seed_profile(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        inventory_item_id=item.id, crop_id=crop.id, variety_id=variety.id,
    )
    inventory_item_seed_profile_service.remove_seed_profile(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), profile_id=profile.id,
    )
    # Second removal of an already-gone profile: silent no-op, not an error.
    inventory_item_seed_profile_service.remove_seed_profile(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), profile_id=profile.id,
    )


@pytest.mark.integration
def test_cannot_create_second_profile_for_same_item(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "SEED"), actor_user_id=user.id)
    crop, variety = build_crop_and_variety(db_session, tenant, actor_user_id=user.id)
    inventory_item_seed_profile_service.register_seed_profile(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        inventory_item_id=item.id, crop_id=crop.id, variety_id=variety.id,
    )
    with pytest.raises(InventoryItemSeedProfileAlreadyExistsError):
        inventory_item_seed_profile_service.register_seed_profile(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            inventory_item_id=item.id, crop_id=crop.id, variety_id=variety.id,
        )


@pytest.mark.integration
def test_seed_profile_frozen_after_first_posted_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "SEED"), actor_user_id=user.id,
        lot_tracking_required=True,
    )
    crop, variety = build_crop_and_variety(db_session, tenant, actor_user_id=user.id)
    crop2, variety2 = build_crop_and_variety(db_session, tenant, actor_user_id=user.id)
    profile = inventory_item_seed_profile_service.register_seed_profile(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        inventory_item_id=item.id, crop_id=crop.id, variety_id=variety.id,
    )

    goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[
            GoodsReceiptLineInput(
                inventory_item_id=item.id, entered_quantity=Decimal("100"),
                entered_uom_id=uom_id(db_session, "SEED"),
            )
        ],
    )

    with pytest.raises(InventoryItemSeedProfileStructurallyLockedError):
        inventory_item_seed_profile_service.update_seed_profile(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            profile_id=profile.id, crop_id=crop2.id, variety_id=variety2.id,
        )
    with pytest.raises(InventoryItemSeedProfileStructurallyLockedError):
        inventory_item_seed_profile_service.remove_seed_profile(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            profile_id=profile.id,
        )


@pytest.mark.integration
def test_historically_non_seed_item_cannot_later_become_seed(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id, lot_tracking_required=True,
    )
    crop, variety = build_crop_and_variety(db_session, tenant, actor_user_id=user.id)

    goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[
            GoodsReceiptLineInput(
                inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"),
                manufacturer_name="Yara", manufacturer_lot_reference="Y-001",
            )
        ],
    )

    with pytest.raises(InventoryItemSeedProfileCreationBlockedError):
        inventory_item_seed_profile_service.register_seed_profile(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            inventory_item_id=item.id, crop_id=crop.id, variety_id=variety.id,
        )
