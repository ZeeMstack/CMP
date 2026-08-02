from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.services.audit import append_audit_event
from app.services.errors import DuplicateTenantCodeError


def create_tenant(db: Session, *, code: str, name: str) -> Tenant:
    tenant = Tenant(code=code, name=name)
    db.add(tenant)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateTenantCodeError(code) from exc

    append_audit_event(
        db,
        tenant_id=tenant.id,
        actor_user_id=None,
        action="tenant.created",
        entity_type="tenant",
        entity_id=tenant.id,
        event_data={"code": tenant.code, "name": tenant.name},
    )

    db.commit()
    db.refresh(tenant)
    return tenant
