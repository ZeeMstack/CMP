"""STORE-INV-001B: InventoryItem service/idempotency/audit tests."""
import uuid

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.unit_of_measure import UnitOfMeasure
from app.services import inventory_category_service, inventory_item_service, tenant_service
from app.services.errors import (
    DuplicateInventoryItemCodeError,
    InventoryCategoryInactiveForAssignmentError,
    InventoryCategoryNotInTenantError,
    InventoryItemCommandReusedWithDifferentPayloadError,
    InventoryItemDeactivationReusedWithDifferentPayloadError,
    InventoryItemNotActiveError,
    InventoryItemNotFoundError,
    InventoryItemNotInactiveError,
    InventoryItemReactivationReusedWithDifferentPayloadError,
    InventoryItemTrackingPolicyInvalidError,
    InventoryItemUpdateReusedWithDifferentPayloadError,
    UnitOfMeasureNotFoundError,
)


def _uom_id(db_session, code: str) -> uuid.UUID:
    return db_session.execute(select(UnitOfMeasure.id).where(UnitOfMeasure.code == code)).scalar_one()


def _category(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="SEED", name="Seed",
    )
    defaults.update(overrides)
    return inventory_category_service.register_inventory_category(db_session, **defaults)


def _register(db_session, tenant, category_id, base_uom_id, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="MAMUTIK-SEED",
        name="Mamutik Seed", category_id=category_id, base_uom_id=base_uom_id, lot_tracking_required=False,
        expiry_tracking_required=False, qc_release_required=False,
    )
    defaults.update(overrides)
    return inventory_item_service.register_inventory_item(db_session, **defaults)


def _second_tenant(db_session, *, code="inv-item-tenant-b"):
    return tenant_service.create_tenant(db_session, code=code, name="Tenant B")


def _audit_count(db_session, *, action, entity_id):
    return db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == action, AuditEvent.entity_id == entity_id
        )
    ).scalar_one()


@pytest.mark.integration
def test_create_inventory_item(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(db_session, tenant, category.id, _uom_id(db_session, "SEED"))
    assert item.code == "MAMUTIK-SEED"
    assert item.status == "active"
    assert item.inventory_category_id == category.id


@pytest.mark.integration
def test_tenant_unique_code_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    uom_id = _uom_id(db_session, "SEED")
    _register(db_session, tenant, category.id, uom_id, code="DUPE")
    with pytest.raises(DuplicateInventoryItemCodeError):
        _register(db_session, tenant, category.id, uom_id, code="dupe", client_command_id=uuid.uuid4())


@pytest.mark.integration
def test_unknown_category_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    with pytest.raises(InventoryCategoryNotInTenantError):
        _register(db_session, tenant, uuid.uuid4(), _uom_id(db_session, "SEED"))


@pytest.mark.integration
def test_category_from_other_tenant_rejected(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = _second_tenant(db_session)
    category_b = _category(db_session, tenant_b)
    with pytest.raises(InventoryCategoryNotInTenantError):
        _register(db_session, tenant_a, category_b.id, _uom_id(db_session, "SEED"))


@pytest.mark.integration
def test_create_with_inactive_category_rejected(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _category(db_session, tenant)
    inventory_category_service.deactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category.id,
    )
    with pytest.raises(InventoryCategoryInactiveForAssignmentError):
        _register(db_session, tenant, category.id, _uom_id(db_session, "kg"))


@pytest.mark.integration
def test_update_to_inactive_category_rejected(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    active_category = _category(db_session, tenant, code="ACTIVE-CAT")
    other_category = _category(db_session, tenant, code="OTHER-CAT")
    inventory_category_service.deactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=other_category.id,
    )
    item = _register(db_session, tenant, active_category.id, _uom_id(db_session, "kg"))
    with pytest.raises(InventoryCategoryInactiveForAssignmentError):
        inventory_item_service.update_inventory_item(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            item_id=item.id, name=item.name, category_id=other_category.id, base_uom_id=item.base_uom_id,
            lot_tracking_required=False, expiry_tracking_required=False, qc_release_required=False,
        )


@pytest.mark.integration
def test_existing_item_survives_category_deactivation(db_session, active_context) -> None:
    """docs/domain/STORE_INVENTORY_MODEL.md §5: category deactivation is
    never blocked by existing references, and an item's own existing
    assignment to a since-deactivated category remains valid -- including
    resubmitting that same category unchanged while editing other fields."""
    tenant, user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(db_session, tenant, category.id, _uom_id(db_session, "kg"))

    # Deactivating the category must not be blocked by this reference.
    deactivated = inventory_category_service.deactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category.id,
    )
    assert deactivated.status == "inactive"

    # The item itself is untouched and still readable/listed normally.
    still_there = inventory_item_service.get_inventory_item(db_session, tenant_id=tenant.id, item_id=item.id)
    assert still_there.inventory_category_id == category.id

    # Renaming the item, resubmitting its own (now-inactive) category
    # unchanged, must still succeed.
    renamed = inventory_item_service.update_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), item_id=item.id,
        name="Renamed While Category Inactive", category_id=category.id, base_uom_id=item.base_uom_id,
        lot_tracking_required=False, expiry_tracking_required=False, qc_release_required=False,
    )
    assert renamed.name == "Renamed While Category Inactive"
    assert renamed.inventory_category_id == category.id


@pytest.mark.integration
def test_unknown_base_uom_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    with pytest.raises(UnitOfMeasureNotFoundError):
        _register(db_session, tenant, category.id, uuid.uuid4())


@pytest.mark.integration
def test_expiry_requires_lot_tracking(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    with pytest.raises(InventoryItemTrackingPolicyInvalidError):
        _register(
            db_session, tenant, category.id, _uom_id(db_session, "kg"),
            lot_tracking_required=False, expiry_tracking_required=True,
        )


@pytest.mark.integration
def test_qc_release_requires_lot_tracking(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    with pytest.raises(InventoryItemTrackingPolicyInvalidError):
        _register(
            db_session, tenant, category.id, _uom_id(db_session, "kg"),
            lot_tracking_required=False, qc_release_required=True,
        )


@pytest.mark.integration
def test_lot_tracking_with_expiry_and_qc_release_allowed(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(
        db_session, tenant, category.id, _uom_id(db_session, "kg"),
        lot_tracking_required=True, expiry_tracking_required=True, qc_release_required=True,
    )
    assert item.lot_tracking_required is True
    assert item.expiry_tracking_required is True
    assert item.qc_release_required is True


@pytest.mark.integration
def test_exact_create_replay_returns_original(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    command_id = uuid.uuid4()
    uom_id = _uom_id(db_session, "kg")
    first = _register(db_session, tenant, category.id, uom_id, client_command_id=command_id)
    second = _register(db_session, tenant, category.id, uom_id, client_command_id=command_id)
    assert first.id == second.id


@pytest.mark.integration
def test_mismatched_create_replay_conflicts(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    uom_id = _uom_id(db_session, "kg")
    command_id = uuid.uuid4()
    _register(db_session, tenant, category.id, uom_id, client_command_id=command_id, code="A")
    with pytest.raises(InventoryItemCommandReusedWithDifferentPayloadError):
        _register(db_session, tenant, category.id, uom_id, client_command_id=command_id, code="B")


@pytest.mark.integration
def test_update_mutable_fields_including_base_uom(db_session, active_context) -> None:
    """docs/domain/STORE_INVENTORY_MODEL.md §5: base_uom IS editable in
    STORE-INV-001B -- no InventoryLot exists yet to freeze against."""
    tenant, user, _headers = active_context
    category_a = _category(db_session, tenant, code="A")
    category_b = _category(db_session, tenant, code="B")
    item = _register(db_session, tenant, category_a.id, _uom_id(db_session, "g"))

    updated = inventory_item_service.update_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), item_id=item.id,
        name="Calcium Nitrate", category_id=category_b.id, base_uom_id=_uom_id(db_session, "kg"),
        lot_tracking_required=True, expiry_tracking_required=True, qc_release_required=False,
    )
    assert updated.name == "Calcium Nitrate"
    assert updated.inventory_category_id == category_b.id
    assert updated.base_uom_id == _uom_id(db_session, "kg")
    assert updated.lot_tracking_required is True
    assert updated.expiry_tracking_required is True
    assert updated.code == "MAMUTIK-SEED"


@pytest.mark.integration
def test_update_enforces_tracking_policy(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(db_session, tenant, category.id, _uom_id(db_session, "kg"))
    with pytest.raises(InventoryItemTrackingPolicyInvalidError):
        inventory_item_service.update_inventory_item(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            item_id=item.id, name=item.name, category_id=category.id, base_uom_id=item.base_uom_id,
            lot_tracking_required=False, expiry_tracking_required=True, qc_release_required=False,
        )


@pytest.mark.integration
def test_exact_update_replay_returns_original(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(db_session, tenant, category.id, _uom_id(db_session, "kg"))
    command_id = uuid.uuid4()
    first = inventory_item_service.update_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id, item_id=item.id,
        name="Renamed", category_id=category.id, base_uom_id=item.base_uom_id, lot_tracking_required=False,
        expiry_tracking_required=False, qc_release_required=False,
    )
    second = inventory_item_service.update_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id, item_id=item.id,
        name="Renamed", category_id=category.id, base_uom_id=item.base_uom_id, lot_tracking_required=False,
        expiry_tracking_required=False, qc_release_required=False,
    )
    assert first.id == second.id


@pytest.mark.integration
def test_mismatched_update_replay_conflicts(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(db_session, tenant, category.id, _uom_id(db_session, "kg"))
    command_id = uuid.uuid4()
    inventory_item_service.update_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id, item_id=item.id,
        name="First Name", category_id=category.id, base_uom_id=item.base_uom_id, lot_tracking_required=False,
        expiry_tracking_required=False, qc_release_required=False,
    )
    with pytest.raises(InventoryItemUpdateReusedWithDifferentPayloadError):
        inventory_item_service.update_inventory_item(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
            item_id=item.id, name="Second Name", category_id=category.id, base_uom_id=item.base_uom_id,
            lot_tracking_required=False, expiry_tracking_required=False, qc_release_required=False,
        )


@pytest.mark.integration
def test_deactivate_then_reactivate_cycle(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(db_session, tenant, category.id, _uom_id(db_session, "kg"))

    deactivated = inventory_item_service.deactivate_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), item_id=item.id,
    )
    assert deactivated.status == "inactive"

    with pytest.raises(InventoryItemNotActiveError):
        inventory_item_service.deactivate_inventory_item(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            item_id=item.id,
        )

    reactivated = inventory_item_service.reactivate_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), item_id=item.id,
    )
    assert reactivated.status == "active"

    with pytest.raises(InventoryItemNotInactiveError):
        inventory_item_service.reactivate_inventory_item(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            item_id=item.id,
        )


@pytest.mark.integration
def test_mismatched_deactivate_replay_conflicts(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _category(db_session, tenant)
    uom_id = _uom_id(db_session, "kg")
    item_a = _register(db_session, tenant, category.id, uom_id, code="A")
    item_b = _register(db_session, tenant, category.id, uom_id, code="B")
    command_id = uuid.uuid4()
    inventory_item_service.deactivate_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id, item_id=item_a.id,
    )
    with pytest.raises(InventoryItemDeactivationReusedWithDifferentPayloadError):
        inventory_item_service.deactivate_inventory_item(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
            item_id=item_b.id,
        )


@pytest.mark.integration
def test_mismatched_reactivate_replay_conflicts(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _category(db_session, tenant)
    uom_id = _uom_id(db_session, "kg")
    item_a = _register(db_session, tenant, category.id, uom_id, code="A")
    item_b = _register(db_session, tenant, category.id, uom_id, code="B")
    inventory_item_service.deactivate_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), item_id=item_a.id,
    )
    inventory_item_service.deactivate_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), item_id=item_b.id,
    )
    command_id = uuid.uuid4()
    inventory_item_service.reactivate_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id, item_id=item_a.id,
    )
    with pytest.raises(InventoryItemReactivationReusedWithDifferentPayloadError):
        inventory_item_service.reactivate_inventory_item(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
            item_id=item_b.id,
        )


@pytest.mark.integration
def test_tenant_isolation_read(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    category = _category(db_session, tenant_a)
    item = _register(db_session, tenant_a, category.id, _uom_id(db_session, "kg"))
    tenant_b = _second_tenant(db_session)
    with pytest.raises(InventoryItemNotFoundError):
        inventory_item_service.get_inventory_item(db_session, tenant_id=tenant_b.id, item_id=item.id)


@pytest.mark.integration
def test_list_filters_by_category_and_status(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category_a = _category(db_session, tenant, code="A")
    category_b = _category(db_session, tenant, code="B")
    uom_id = _uom_id(db_session, "kg")
    item_a = _register(db_session, tenant, category_a.id, uom_id, code="ITEM-A")
    _register(db_session, tenant, category_b.id, uom_id, code="ITEM-B")
    inventory_item_service.deactivate_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), item_id=item_a.id,
    )

    by_category = inventory_item_service.list_inventory_items(
        db_session, tenant_id=tenant.id, category_id=category_a.id
    )
    assert [i.code for i in by_category] == ["ITEM-A"]

    active_only = inventory_item_service.list_inventory_items(db_session, tenant_id=tenant.id, status="active")
    assert "ITEM-A" not in [i.code for i in active_only]
    assert "ITEM-B" in [i.code for i in active_only]


@pytest.mark.integration
def test_create_update_deactivate_reactivate_audit_events(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(db_session, tenant, category.id, _uom_id(db_session, "kg"))
    inventory_item_service.update_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), item_id=item.id,
        name="Renamed", category_id=category.id, base_uom_id=item.base_uom_id, lot_tracking_required=False,
        expiry_tracking_required=False, qc_release_required=False,
    )
    inventory_item_service.deactivate_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), item_id=item.id,
    )
    inventory_item_service.reactivate_inventory_item(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), item_id=item.id,
    )
    assert _audit_count(db_session, action="inventory_item.created", entity_id=item.id) == 1
    assert _audit_count(db_session, action="inventory_item.updated", entity_id=item.id) == 1
    assert _audit_count(db_session, action="inventory_item.deactivated", entity_id=item.id) == 1
    assert _audit_count(db_session, action="inventory_item.reactivated", entity_id=item.id) == 1
