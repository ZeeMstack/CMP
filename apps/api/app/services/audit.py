import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent


def append_audit_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    event_data: dict,
    request_id: str | None = None,
) -> AuditEvent:
    """Adds an audit event to the given session. Does not flush or commit —
    participates in the caller's transaction so entity + audit stay atomic."""
    event = AuditEvent(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        effective_time=datetime.now(timezone.utc),
        request_id=request_id,
        event_data=event_data,
    )
    db.add(event)
    return event
