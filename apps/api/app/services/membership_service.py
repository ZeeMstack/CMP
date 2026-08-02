import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.membership import TenantMembership
from app.services.audit import append_audit_event
from app.services.errors import DuplicateMembershipError


def add_membership(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role_code: str,
    actor_user_id: uuid.UUID | None,
) -> TenantMembership:
    membership = TenantMembership(tenant_id=tenant_id, user_id=user_id, role_code=role_code)
    db.add(membership)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateMembershipError(f"{tenant_id}:{user_id}") from exc

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="membership.created",
        entity_type="tenant_membership",
        entity_id=membership.id,
        event_data={"user_id": str(user_id), "role_code": role_code},
    )

    db.commit()
    db.refresh(membership)
    return membership
