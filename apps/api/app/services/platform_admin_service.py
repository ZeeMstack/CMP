import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.platform_admin import PlatformAdmin
from app.services import user_service
from app.services.errors import AdminIdentityEmailMismatchError


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


@dataclass(frozen=True)
class FirstAdminBootstrapResult:
    """Plain-value snapshot of the User resolved/created and the
    PlatformAdmin grant established by `bootstrap_first_platform_admin`,
    captured while the outer transaction is still open -- never live ORM
    objects, which would be detached the moment that function's own
    `Session` is closed. Mirrors `platform_tenant_service.
    TenantOnboardingResult`'s identical reasoning."""

    user_id: uuid.UUID
    user_oidc_issuer: str
    user_oidc_subject: str
    user_email: str
    user_display_name: str
    user_status: str
    user_created: bool

    platform_admin_id: uuid.UUID
    platform_admin_granted_at: datetime
    already_active_platform_admin: bool


def bootstrap_first_platform_admin(
    db_engine: Engine,
    *,
    oidc_issuer: str,
    oidc_subject: str,
    email: str,
    display_name: str,
    reason: str | None = None,
) -> FirstAdminBootstrapResult:
    """DEPLOY-001A: the narrow, DB-credential-gated bootstrap path for a
    blank production database's very first platform administrator --
    resolves-or-creates a User by exact `(oidc_issuer, oidc_subject)`
    identity and grants it platform-admin authority, atomically: both
    succeed together, or neither survives. There is deliberately no
    unauthenticated HTTP route that does this (mirrors `grant_platform_
    admin`/`revoke_platform_admin`'s own precedent, which this function
    composes with rather than duplicates). Never touches `TenantContext`,
    never creates a `Tenant` or `TenantMembership`, never creates a
    password or any other local credential -- identity is always an OIDC
    issuer+subject pair, exactly as real bearer authentication resolves it.

    Reuses the exact transaction pattern `platform_tenant_service.
    onboard_tenant` already established for composing independently-
    committing services atomically: owns its own `Connection`, begins one
    outer transaction, and binds a `Session` to it with
    `join_transaction_mode="create_savepoint"` so `user_service.create_
    user`'s and `grant_platform_admin`'s own internal `db.commit()` calls
    each only release a SAVEPOINT -- this function alone commits (both
    steps succeeded) or rolls back (either step raised) the real outer
    transaction, once, at the end. A failure at the authority-grant step
    therefore leaves no newly-created User behind.

    Raises:
    - `AdminIdentityEmailMismatchError` -- an existing User was resolved by
      identity, but `email` does not match that User's own recorded email
      (never silently overwritten) -- mirrors `onboard_tenant`'s identical
      rule for the identical situation.
    - `DuplicateUserIdentityError` -- a concurrent bootstrap attempt won a
      race to create the same new identity first.

    Idempotent for an already-active platform admin: `grant_platform_
    admin`'s own idempotency is unchanged, surfaced here via `already_
    active_platform_admin` on the result rather than raising."""
    conn = db_engine.connect()
    outer_trans = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        existing_user = user_service.get_user_by_issuer_subject(
            db, oidc_issuer=oidc_issuer, oidc_subject=oidc_subject
        )
        if existing_user is not None:
            if existing_user.email != email:
                raise AdminIdentityEmailMismatchError(
                    f"resolved User for oidc_issuer={oidc_issuer!r} oidc_subject={oidc_subject!r} already has "
                    f"email {existing_user.email!r}, which does not match the supplied {email!r} -- refusing "
                    "to silently overwrite an existing identity's email"
                )
            user = existing_user
            user_created = False
        else:
            user = user_service.create_user(
                db, oidc_issuer=oidc_issuer, oidc_subject=oidc_subject, email=email, display_name=display_name
            )
            user_created = True

        already_active = is_platform_admin(db, user_id=user.id)
        grant = grant_platform_admin(db, user_id=user.id, granted_by_user_id=None, reason=reason)

        # Captured as plain values now, while the outer transaction (and
        # therefore every attribute below) is still fully live -- never
        # touched again after `outer_trans.commit()`/`.rollback()` below.
        result = FirstAdminBootstrapResult(
            user_id=user.id,
            user_oidc_issuer=user.oidc_issuer,
            user_oidc_subject=user.oidc_subject,
            user_email=user.email,
            user_display_name=user.display_name,
            user_status=user.status,
            user_created=user_created,
            platform_admin_id=grant.id,
            platform_admin_granted_at=grant.granted_at,
            already_active_platform_admin=already_active,
        )
    except Exception:
        outer_trans.rollback()
        raise
    else:
        outer_trans.commit()
        return result
    finally:
        db.close()
        conn.close()
