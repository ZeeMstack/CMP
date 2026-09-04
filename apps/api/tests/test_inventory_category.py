"""STORE-INV-001B: InventoryCategory service/idempotency/audit tests.
Mirrors test_packaging_unit.py's own fixture conventions, widened for a
reversible active<->inactive lifecycle with its own per-direction
idempotency pair."""
import uuid

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.services import inventory_category_service, tenant_service
from app.services.errors import (
    DuplicateInventoryCategoryCodeError,
    InventoryCategoryCommandReusedWithDifferentPayloadError,
    InventoryCategoryDeactivationReusedWithDifferentPayloadError,
    InventoryCategoryNotActiveError,
    InventoryCategoryNotFoundError,
    InventoryCategoryNotInactiveError,
    InventoryCategoryReactivationReusedWithDifferentPayloadError,
)


def _register(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="SEED", name="Seed",
    )
    defaults.update(overrides)
    return inventory_category_service.register_inventory_category(db_session, **defaults)


def _second_tenant(db_session, *, code="inv-category-tenant-b"):
    return tenant_service.create_tenant(db_session, code=code, name="Tenant B")


def _audit_count(db_session, *, action, entity_id):
    return db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == action, AuditEvent.entity_id == entity_id
        )
    ).scalar_one()


@pytest.mark.integration
def test_create_inventory_category(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    category = _register(db_session, tenant)
    assert category.code == "SEED"
    assert category.status == "active"


@pytest.mark.integration
def test_tenant_unique_code_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _register(db_session, tenant, code="DUPE")
    with pytest.raises(DuplicateInventoryCategoryCodeError):
        _register(db_session, tenant, code="dupe", client_command_id=uuid.uuid4())


@pytest.mark.integration
def test_same_code_allowed_across_different_tenants(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    _register(db_session, tenant_a, code="SHARED")
    tenant_b = _second_tenant(db_session)
    category_b = _register(db_session, tenant_b, code="SHARED")
    assert category_b.tenant_id == tenant_b.id


@pytest.mark.integration
def test_exact_create_replay_returns_original(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    command_id = uuid.uuid4()
    first = _register(db_session, tenant, client_command_id=command_id)
    second = _register(db_session, tenant, client_command_id=command_id)
    assert first.id == second.id


@pytest.mark.integration
def test_mismatched_create_replay_conflicts(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    command_id = uuid.uuid4()
    _register(db_session, tenant, client_command_id=command_id, code="A")
    with pytest.raises(InventoryCategoryCommandReusedWithDifferentPayloadError):
        _register(db_session, tenant, client_command_id=command_id, code="B")


@pytest.mark.integration
def test_update_name(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _register(db_session, tenant)
    updated = inventory_category_service.update_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category.id, name="Seed (renamed)",
    )
    assert updated.name == "Seed (renamed)"
    assert updated.code == "SEED"


@pytest.mark.integration
def test_deactivate_then_reactivate_cycle(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _register(db_session, tenant)

    deactivated = inventory_category_service.deactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category.id,
    )
    assert deactivated.status == "inactive"

    with pytest.raises(InventoryCategoryNotActiveError):
        inventory_category_service.deactivate_inventory_category(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            category_id=category.id,
        )

    reactivated = inventory_category_service.reactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category.id,
    )
    assert reactivated.status == "active"

    with pytest.raises(InventoryCategoryNotInactiveError):
        inventory_category_service.reactivate_inventory_category(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            category_id=category.id,
        )

    # A second full cycle proves the two directions never collide on one
    # shared idempotency column.
    inventory_category_service.deactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category.id,
    )
    twice_reactivated = inventory_category_service.reactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category.id,
    )
    assert twice_reactivated.status == "active"


@pytest.mark.integration
def test_exact_deactivate_replay_returns_original(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _register(db_session, tenant)
    command_id = uuid.uuid4()
    first = inventory_category_service.deactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        category_id=category.id,
    )
    second = inventory_category_service.deactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        category_id=category.id,
    )
    assert first.id == second.id
    assert second.status == "inactive"


@pytest.mark.integration
def test_mismatched_deactivate_replay_conflicts(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category_a = _register(db_session, tenant, code="A")
    category_b = _register(db_session, tenant, code="B")
    command_id = uuid.uuid4()
    inventory_category_service.deactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        category_id=category_a.id,
    )
    with pytest.raises(InventoryCategoryDeactivationReusedWithDifferentPayloadError):
        inventory_category_service.deactivate_inventory_category(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
            category_id=category_b.id,
        )


@pytest.mark.integration
def test_mismatched_reactivate_replay_conflicts(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category_a = _register(db_session, tenant, code="A")
    category_b = _register(db_session, tenant, code="B")
    inventory_category_service.deactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category_a.id,
    )
    inventory_category_service.deactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category_b.id,
    )
    command_id = uuid.uuid4()
    inventory_category_service.reactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        category_id=category_a.id,
    )
    with pytest.raises(InventoryCategoryReactivationReusedWithDifferentPayloadError):
        inventory_category_service.reactivate_inventory_category(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
            category_id=category_b.id,
        )


@pytest.mark.integration
def test_tenant_isolation_read(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    category = _register(db_session, tenant_a)
    tenant_b = _second_tenant(db_session)
    with pytest.raises(InventoryCategoryNotFoundError):
        inventory_category_service.get_inventory_category(
            db_session, tenant_id=tenant_b.id, category_id=category.id
        )


@pytest.mark.integration
def test_create_update_deactivate_reactivate_audit_events(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    category = _register(db_session, tenant)
    inventory_category_service.update_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category.id, name="Renamed",
    )
    inventory_category_service.deactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category.id,
    )
    inventory_category_service.reactivate_inventory_category(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        category_id=category.id,
    )
    assert _audit_count(db_session, action="inventory_category.created", entity_id=category.id) == 1
    assert _audit_count(db_session, action="inventory_category.updated", entity_id=category.id) == 1
    assert _audit_count(db_session, action="inventory_category.deactivated", entity_id=category.id) == 1
    assert _audit_count(db_session, action="inventory_category.reactivated", entity_id=category.id) == 1
