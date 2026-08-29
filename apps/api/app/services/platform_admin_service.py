import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.platform_admin import PlatformAdmin


def get_active_platform_admin(db: Session, *, user_id: uuid.UUID, lock: bool = False) -> PlatformAdmin | None:
    """The one active-assignment row for a user, if any -- relies on the
    partial unique index (user_id) WHERE revoked_at IS NULL to guarantee at
    most one match, mirroring `membership_service.get_active_membership`'s
    identical shape for TenantMembership."""
    query = select(PlatformAdmin).where(PlatformAdmin.user_id == user_id, PlatformAdmin.revoked_at.is_(None))
    if lock:
        query = query.with_for_update()
    return db.execute(query).scalar_one_or_none()


def is_platform_admin(db: Session, *, user_id: uuid.UUID) -> bool:
    return get_active_platform_admin(db, user_id=user_id) is not None


def grant_platform_admin(
    db: Session,
    *,
    user_id: uuid.UUID,
    granted_by_user_id: uuid.UUID | None,
    reason: str | None = None,
) -> PlatformAdmin:
    """Idempotent: a user who already holds an active assignment gets that
    same row back unchanged -- granting twice never creates a second active
    authority or a duplicate row. A genuinely tenant-less platform action
    (no tenant_id exists on PlatformAdmin, by design) -- no AuditEvent is
    recorded here, mirroring `user_service.create_user`'s identical
    precedent for a tenant-less action (AuditEvent.tenant_id is NOT NULL;
    there is no tenant to attribute a platform-admin grant to). The row's
    own granted_at/granted_by_user_id/reason fields are this action's
    permanent record instead."""
    existing = get_active_platform_admin(db, user_id=user_id)
    if existing is not None:
        return existing

    grant = PlatformAdmin(
        user_id=user_id,
        granted_by_user_id=granted_by_user_id,
        reason=reason,
        granted_at=datetime.now(timezone.utc),
    )
    db.add(grant)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        # A concurrent grant won the race for the active-uniqueness index --
        # return the winner rather than raising; granting is idempotent, not
        # first-writer-wins-and-everyone-else-fails.
        existing = get_active_platform_admin(db, user_id=user_id)
        if existing is not None:
            return existing
        raise
    db.commit()
    db.refresh(grant)
    return grant


def revoke_platform_admin(
    db: Session,
    *,
    user_id: uuid.UUID,
    revoked_by_user_id: uuid.UUID | None,
) -> PlatformAdmin | None:
    """Idempotent no-op if the user holds no active assignment -- never
    raises, never fabricates a row. Revocation is a soft state change on
    the existing row (`revoked_at`/`revoked_by_user_id` set), never a
    delete -- the grant remains a permanent historical fact. A subsequent
    `grant_platform_admin` call for the same user creates a NEW row (this
    one no longer matches `revoked_at IS NULL`), preserving this cycle's
    facts unchanged."""
    active = get_active_platform_admin(db, user_id=user_id, lock=True)
    if active is None:
        return None
    active.revoked_at = datetime.now(timezone.utc)
    active.revoked_by_user_id = revoked_by_user_id
    db.flush()
    db.commit()
    db.refresh(active)
    return active
