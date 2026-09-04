"""STORE-INV-001B: InventoryItem DB-level integrity backstops -- proven via
direct SQL, bypassing the service layer entirely."""
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.unit_of_measure import UnitOfMeasure
from app.services import inventory_category_service, inventory_item_service


def _uom_id(db_session, code: str) -> uuid.UUID:
    return db_session.execute(select(UnitOfMeasure.id).where(UnitOfMeasure.code == code)).scalar_one()


def _category(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="SPARE", name="Spare Parts",
    )
    defaults.update(overrides)
    return inventory_category_service.register_inventory_category(db_session, **defaults)


def _register(db_session, tenant, category_id, base_uom_id, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="PUMP-01", name="Pump",
        category_id=category_id, base_uom_id=base_uom_id, lot_tracking_required=False,
        expiry_tracking_required=False, qc_release_required=False,
    )
    defaults.update(overrides)
    return inventory_item_service.register_inventory_item(db_session, **defaults)


@pytest.mark.integration
def test_hard_delete_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(db_session, tenant, category.id, _uom_id(db_session, "EA"))
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM inventory_items WHERE id = :id"), {"id": item.id})


@pytest.mark.integration
def test_expiry_requires_lot_tracking_rejected_at_db_level(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(db_session, tenant, category.id, _uom_id(db_session, "kg"))
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "UPDATE inventory_items SET lot_tracking_required = false, expiry_tracking_required = true "
                    "WHERE id = :id"
                ),
                {"id": item.id},
            )


@pytest.mark.integration
def test_qc_release_requires_lot_tracking_rejected_at_db_level(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(db_session, tenant, category.id, _uom_id(db_session, "kg"))
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "UPDATE inventory_items SET lot_tracking_required = false, qc_release_required = true "
                    "WHERE id = :id"
                ),
                {"id": item.id},
            )


@pytest.mark.integration
def test_code_immutable_at_db_level(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(db_session, tenant, category.id, _uom_id(db_session, "EA"))
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE inventory_items SET code = 'CHANGED' WHERE id = :id"), {"id": item.id}
            )


@pytest.mark.integration
def test_invalid_status_rejected_at_db_level(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _category(db_session, tenant)
    item = _register(db_session, tenant, category.id, _uom_id(db_session, "kg"))
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE inventory_items SET status = 'retired' WHERE id = :id"), {"id": item.id}
            )


@pytest.mark.integration
def test_cross_tenant_category_fk_rejected_at_db_level(db_session, active_context) -> None:
    """The composite (tenant_id, inventory_category_id) FK proves tenant
    isolation is a DB guarantee, not merely a service-layer check."""
    from app.services import tenant_service

    tenant, _user, _headers = active_context
    other_tenant = tenant_service.create_tenant(db_session, code="inv-item-fk-tenant-b", name="Tenant B")
    other_category = _category(db_session, other_tenant, code="OTHER")
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO inventory_items (id, tenant_id, code, name, inventory_category_id, "
                    "base_uom_id, lot_tracking_required, expiry_tracking_required, qc_release_required, "
                    "status, client_command_id, request_fingerprint) "
                    "VALUES (:id, :tid, 'CROSS', 'Cross Tenant', :cat_id, :uom_id, false, false, false, "
                    "'active', :cmd, 'x')"
                ),
                {
                    "id": uuid.uuid4(), "tid": tenant.id, "cat_id": other_category.id,
                    "uom_id": _uom_id(db_session, "EA"), "cmd": uuid.uuid4(),
                },
            )
