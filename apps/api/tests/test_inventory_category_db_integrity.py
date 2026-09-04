"""STORE-INV-001B: InventoryCategory DB-level integrity backstops -- proven
via direct SQL, bypassing the service layer entirely, mirroring
test_packaging_unit_db_integrity.py's own approach."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.services import inventory_category_service


def _register(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="CHEMICAL", name="Chemical",
    )
    defaults.update(overrides)
    return inventory_category_service.register_inventory_category(db_session, **defaults)


@pytest.mark.integration
def test_hard_delete_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _register(db_session, tenant)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM inventory_categories WHERE id = :id"), {"id": category.id})


@pytest.mark.integration
def test_code_mutable_via_service_name_update_but_frozen_at_db_level(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _register(db_session, tenant)
    inventory_category_service.update_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category.id, name="Chemical (renamed)",
    )
    refreshed = inventory_category_service.get_inventory_category(
        db_session, tenant_id=tenant.id, category_id=category.id
    )
    assert refreshed.code == "CHEMICAL"


@pytest.mark.integration
def test_code_immutable_at_db_level(db_session, active_context) -> None:
    category = _register(db_session, active_context[0])
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE inventory_categories SET code = 'CHANGED' WHERE id = :id"), {"id": category.id}
            )


@pytest.mark.integration
def test_invalid_status_rejected_at_db_level(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _register(db_session, tenant)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE inventory_categories SET status = 'retired' WHERE id = :id"), {"id": category.id}
            )


@pytest.mark.integration
def test_case_insensitive_code_uniqueness_at_db_level(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _register(db_session, tenant, code="MEDIA")
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO inventory_categories (id, tenant_id, code, name, status, "
                    "client_command_id, request_fingerprint) "
                    "VALUES (:id, :tid, 'media', 'Media dup', 'active', :cmd, 'x')"
                ),
                {"id": uuid.uuid4(), "tid": tenant.id, "cmd": uuid.uuid4()},
            )
