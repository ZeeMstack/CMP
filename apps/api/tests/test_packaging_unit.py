"""POSTHARVEST-OPS-001B: PackagingUnit model/service/idempotency/audit
tests. Mirrors test_grade_definition.py's own fixture conventions."""
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.services import packaging_unit_service, tenant_service
from app.services.errors import (
    DuplicatePackagingUnitCodeError,
    PackagingUnitCommandReusedWithDifferentPayloadError,
    PackagingUnitNotActiveError,
    PackagingUnitNotFoundError,
    PackagingUnitRetirementReusedWithDifferentPayloadError,
)


def _register(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="CARTON", name="Carton",
    )
    defaults.update(overrides)
    return packaging_unit_service.register_packaging_unit(db_session, **defaults)


def _retire(db_session, tenant, unit, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), packaging_unit_id=unit.id,
    )
    defaults.update(overrides)
    return packaging_unit_service.retire_packaging_unit(db_session, **defaults)


def _second_tenant(db_session, *, code="packaging-unit-tenant-b"):
    return tenant_service.create_tenant(db_session, code=code, name="Tenant B")


def _audit_count(db_session, *, action, entity_id):
    return db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == action, AuditEvent.entity_id == entity_id
        )
    ).scalar_one()


@pytest.mark.integration
def test_create_packaging_unit(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)
    assert unit.code == "CARTON"
    assert unit.status == "active"


@pytest.mark.integration
def test_tenant_unique_code_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _register(db_session, tenant, code="DUPE")
    with pytest.raises(DuplicatePackagingUnitCodeError):
        _register(db_session, tenant, code="dupe", client_command_id=uuid.uuid4())


@pytest.mark.integration
def test_same_code_allowed_across_different_tenants(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    _register(db_session, tenant_a, code="SHARED")
    tenant_b = _second_tenant(db_session)
    unit_b = _register(db_session, tenant_b, code="SHARED")
    assert unit_b.tenant_id == tenant_b.id


@pytest.mark.integration
def test_new_unit_starts_active(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)
    assert unit.status == "active"
    assert unit.retirement_client_command_id is None


@pytest.mark.integration
def test_explicit_retire(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)
    retired = _retire(db_session, tenant, unit)
    assert retired.status == "retired"
    assert retired.retirement_client_command_id is not None


@pytest.mark.integration
def test_retired_unit_cannot_be_retired_again(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)
    _retire(db_session, tenant, unit)
    with pytest.raises(PackagingUnitNotActiveError):
        _retire(db_session, tenant, unit, client_command_id=uuid.uuid4())


@pytest.mark.integration
def test_hard_delete_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM packaging_units WHERE id = :id"), {"id": unit.id})


@pytest.mark.integration
def test_identity_mutation_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("UPDATE packaging_units SET code = 'CHANGED' WHERE id = :id"), {"id": unit.id})


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
    with pytest.raises(PackagingUnitCommandReusedWithDifferentPayloadError):
        _register(db_session, tenant, client_command_id=command_id, code="B")


@pytest.mark.integration
def test_exact_retire_replay_returns_original(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)
    command_id = uuid.uuid4()
    first = _retire(db_session, tenant, unit, client_command_id=command_id)
    second = _retire(db_session, tenant, unit, client_command_id=command_id)
    assert first.id == second.id
    assert second.status == "retired"


@pytest.mark.integration
def test_mismatched_retire_replay_conflicts(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit_a = _register(db_session, tenant, code="A")
    unit_b = _register(db_session, tenant, code="B")
    command_id = uuid.uuid4()
    _retire(db_session, tenant, unit_a, client_command_id=command_id)
    with pytest.raises(PackagingUnitRetirementReusedWithDifferentPayloadError):
        _retire(db_session, tenant, unit_b, client_command_id=command_id)


@pytest.mark.integration
def test_tenant_isolation_read(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    unit = _register(db_session, tenant_a)
    tenant_b = _second_tenant(db_session)
    with pytest.raises(PackagingUnitNotFoundError):
        packaging_unit_service.get_packaging_unit(db_session, tenant_id=tenant_b.id, packaging_unit_id=unit.id)


@pytest.mark.integration
def test_create_and_retire_audit_events(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)
    _retire(db_session, tenant, unit)
    assert _audit_count(db_session, action="packaging_unit.created", entity_id=unit.id) == 1
    assert _audit_count(db_session, action="packaging_unit.retired", entity_id=unit.id) == 1
