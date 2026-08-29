import uuid

from sqlalchemy import select
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


def list_tenants(db: Session) -> list[Tenant]:
    """PILOT-SETUP-001B2: platform-level Tenant metadata listing (no
    operational data of any kind). Deterministic order -- name, then code --
    mirroring `membership_service.list_active_memberships_for_user`'s own
    tie-break convention."""
    return list(db.execute(select(Tenant).order_by(Tenant.name, Tenant.code)).scalars())


def get_tenant(db: Session, *, tenant_id: uuid.UUID) -> Tenant | None:
    """PILOT-SETUP-001B2: single-Tenant platform-level read by id. Returns
    None for an unknown id -- callers map that to 404."""
    return db.get(Tenant, tenant_id)
