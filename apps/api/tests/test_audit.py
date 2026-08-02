import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.services import tenant_service
from app.services.errors import DuplicateTenantCodeError


@pytest.mark.integration
def test_tenant_creation_appends_audit_event_in_same_transaction(db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="t-audit-1", name="T1")

    event = db_session.execute(
        select(AuditEvent).where(AuditEvent.entity_id == tenant.id, AuditEvent.action == "tenant.created")
    ).scalar_one()

    assert event.tenant_id == tenant.id
    assert event.entity_type == "tenant"
    assert event.event_data["code"] == "t-audit-1"


@pytest.mark.integration
def test_failed_tenant_creation_leaves_no_audit_event(db_session) -> None:
    tenant_service.create_tenant(db_session, code="t-audit-2", name="Original")
    with pytest.raises(DuplicateTenantCodeError):
        tenant_service.create_tenant(db_session, code="T-AUDIT-2", name="Duplicate")

    count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "tenant.created",
            AuditEvent.event_data["code"].astext.ilike("t-audit-2"),
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.integration
def test_direct_update_of_audit_event_is_rejected_by_postgres(db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="t-audit-3", name="T3")
    event = db_session.execute(select(AuditEvent).where(AuditEvent.entity_id == tenant.id)).scalar_one()

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE audit_events SET action = 'tampered' WHERE id = :id"),
                {"id": event.id},
            )


@pytest.mark.integration
def test_direct_delete_of_audit_event_is_rejected_by_postgres(db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="t-audit-4", name="T4")
    event = db_session.execute(select(AuditEvent).where(AuditEvent.entity_id == tenant.id)).scalar_one()

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM audit_events WHERE id = :id"), {"id": event.id})
