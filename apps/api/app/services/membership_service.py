import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.membership import TenantMembership
from app.models.tenant import Tenant
from app.services.audit import append_audit_event
from app.services.errors import DuplicateMembershipError


def get_active_membership(db: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> TenantMembership | None:
    """The one active-membership row for (tenant, user), if any -- relies
    on the partial unique index (tenant_id, user_id) WHERE status='active'
    to guarantee at most one match."""
    return db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
        )
    ).scalar_one_or_none()


def list_active_memberships_for_user(db: Session, *, user_id: uuid.UUID) -> list[tuple[TenantMembership, Tenant]]:
    """Every currently-usable (membership, tenant) pair for a user --
    membership active AND tenant active, joined and filtered set-based in
    one query (never N+1). A removed membership or an inactive tenant is
    silently excluded, not flagged -- callers (e.g. GET /auth/me) must
    only ever see access that is actually usable right now. Deterministic
    order: tenant name, then code, so callers never need their own
    tie-break logic."""
    rows = db.execute(
        select(TenantMembership, Tenant)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
            Tenant.status == "active",
        )
        .order_by(Tenant.name, Tenant.code)
    ).all()
    return [(membership, tenant) for membership, tenant in rows]


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
