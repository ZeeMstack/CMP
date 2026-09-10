import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.membership import TenantMembership
from app.models.tenant import Tenant
from app.models.user import User
from app.services.audit import append_audit_event
from app.services.errors import (
    DuplicateMembershipError,
    LastActiveTenantAdminError,
    MembershipAlreadyActiveForUserError,
    MembershipNotActiveError,
    MembershipNotFoundError,
    MembershipNotInactiveError,
)

_TENANT_ADMIN_ROLE_CODE = "tenant_admin"


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
    """Creates a membership -- or, if history already exists for this exact
    (tenant_id, user_id) pair with no currently-active row, deterministically
    reactivates one historical row instead of inserting a new one
    (AUTHZ-OPS-001 CTO correction pass; CLAUDE.md rule 7 -- never
    proliferate duplicate historical rows for what is really the same
    membership lifecycle; mirrors `reactivate_membership`'s own
    reuse-the-same-row semantics).

    The DB only guarantees at most one ACTIVE row per (tenant_id, user_id)
    (`ux_tenant_memberships_active_tenant_user`) -- nothing prevents
    several REMOVED rows accumulating over repeated deactivate/re-add
    cycles (this was possible even before this function deduplicated at
    all: every prior `add_membership` call for an already-removed pair
    simply inserted another row). This reads and locks the FULL set of
    rows for (tenant_id, user_id) -- never assumes a single-row result,
    which would raise `MultipleResultsFound` (or behave nondeterministically)
    the moment more than one removed row exists -- and:

    1. an ACTIVE row is present -> `DuplicateMembershipError` (unchanged).
    2. no active row, but one or more REMOVED rows exist -> reactivates
       the most-recently-updated one (ties broken by `id`, both stable,
       already-indexed columns), leaving every OTHER historical removed
       row exactly as it was -- never creates a new row, never
       collapses/deletes the others.
    3. no rows at all -> creates a new membership, exactly as before.

    Row(s) are locked (`FOR UPDATE`) in this same deterministic order so a
    concurrent call for the same pair serializes rather than racing past
    this check."""
    candidates = list(
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == user_id)
            .order_by(TenantMembership.updated_at.desc(), TenantMembership.id.desc())
            .with_for_update()
        )
        .scalars()
        .all()
    )

    active = next((m for m in candidates if m.status == "active"), None)
    if active is not None:
        raise DuplicateMembershipError(f"{tenant_id}:{user_id}")

    if candidates:
        # No active row above -- every remaining candidate is 'removed'.
        # Already ordered most-recently-updated first, so candidates[0]
        # is the deterministic pick; every other row is left untouched.
        existing = candidates[0]
        role_before = existing.role_code
        existing.role_code = role_code
        existing.status = "active"
        db.flush()

        append_audit_event(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="membership.reactivated",
            entity_type="tenant_membership",
            entity_id=existing.id,
            event_data={
                "role_code_before": role_before,
                "role_code_after": role_code,
                "reactivated_via": "add_membership",
            },
        )
        db.commit()
        db.refresh(existing)
        return existing

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


def list_memberships_for_tenant(db: Session, *, tenant_id: uuid.UUID) -> list[tuple[TenantMembership, User]]:
    """AUTHZ-OPS-001: every membership (active AND removed) for the Users &
    Roles administration screen -- unlike `list_active_memberships_for_user`,
    this deliberately does NOT filter to active-only: an admin must still
    see a deactivated colleague's row (with a Reactivate action), not have
    it silently vanish. Joined with User so the caller never needs a
    separate N+1 lookup to render email/display_name. Deterministic order:
    display name, then email, so the UI never needs its own tie-break."""
    rows = db.execute(
        select(TenantMembership, User)
        .join(User, User.id == TenantMembership.user_id)
        .where(TenantMembership.tenant_id == tenant_id)
        .order_by(User.display_name, User.email)
    ).all()
    return [(membership, user) for membership, user in rows]


def _lock_membership(db: Session, *, tenant_id: uuid.UUID, membership_id: uuid.UUID) -> TenantMembership:
    membership = db.execute(
        select(TenantMembership)
        .where(TenantMembership.id == membership_id, TenantMembership.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if membership is None:
        raise MembershipNotFoundError(str(membership_id))
    return membership


def _lock_active_tenant_admin_memberships(db: Session, *, tenant_id: uuid.UUID) -> list[TenantMembership]:
    """Locks (FOR UPDATE) every currently-active tenant_admin membership row
    for this tenant, in a fixed canonical order (ascending `id`). Every
    caller that might need this protection acquires it FIRST, in this same
    order, before locking any other single membership row -- the standard
    "acquire contested locks in one fixed global order" deadlock-prevention
    idiom. Without this, two concurrent requests demoting/deactivating two
    *different* admins could each lock their own target row first and then
    block waiting on each other's, a classic crosswise deadlock. Locking
    this small set unconditionally (even when the target later turns out
    not to be a tenant_admin at all) is a deliberate, cheap simplification
    over a conditional "only lock the batch if the target looks like an
    admin" optimization, which would reopen a race between an unlocked peek
    read and the actual protected decision (CLAUDE.md rule 11 / AUTHZ-OPS-001
    section 11 -- "do not overengineer broader distributed locking" cuts
    the other way here: the simple unconditional lock is both safer and
    less code than a conditional one)."""
    return list(
        db.execute(
            select(TenantMembership)
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.role_code == _TENANT_ADMIN_ROLE_CODE,
                TenantMembership.status == "active",
            )
            .order_by(TenantMembership.id)
            .with_for_update()
        )
        .scalars()
        .all()
    )


def change_role(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    new_role_code: str,
    actor_user_id: uuid.UUID | None,
) -> TenantMembership:
    """AUTHZ-OPS-001: changes an existing membership's role_code. Blocked
    when the target is the tenant's last active tenant_admin AND the new
    role is something else -- last-admin protection only ever applies to an
    actually-active tenant_admin row losing that role, never to an already-
    inactive one or a lateral tenant_admin -> tenant_admin no-op."""
    active_admins = _lock_active_tenant_admin_memberships(db, tenant_id=tenant_id)
    membership = _lock_membership(db, tenant_id=tenant_id, membership_id=membership_id)

    role_before = membership.role_code
    if (
        membership.status == "active"
        and role_before == _TENANT_ADMIN_ROLE_CODE
        and new_role_code != _TENANT_ADMIN_ROLE_CODE
    ):
        remaining = [m for m in active_admins if m.id != membership_id]
        if not remaining:
            raise LastActiveTenantAdminError(str(membership_id))

    membership.role_code = new_role_code
    db.flush()

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="membership.role_changed",
        entity_type="tenant_membership",
        entity_id=membership.id,
        event_data={"role_code_before": role_before, "role_code_after": new_role_code},
    )

    db.commit()
    db.refresh(membership)
    return membership


def deactivate_membership(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
) -> TenantMembership:
    """AUTHZ-OPS-001: sets an active membership to 'removed'. Never hard-
    deletes the row (CLAUDE.md rule 7) -- the same historical membership is
    reused by `reactivate_membership` below. Blocked when the target is the
    tenant's last active tenant_admin membership."""
    active_admins = _lock_active_tenant_admin_memberships(db, tenant_id=tenant_id)
    membership = _lock_membership(db, tenant_id=tenant_id, membership_id=membership_id)

    if membership.status != "active":
        raise MembershipNotActiveError(str(membership_id))

    if membership.role_code == _TENANT_ADMIN_ROLE_CODE:
        remaining = [m for m in active_admins if m.id != membership_id]
        if not remaining:
            raise LastActiveTenantAdminError(str(membership_id))

    membership.status = "removed"
    db.flush()

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="membership.deactivated",
        entity_type="tenant_membership",
        entity_id=membership.id,
        event_data={"role_code": membership.role_code},
    )

    db.commit()
    db.refresh(membership)
    return membership


def reactivate_membership(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    membership_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
) -> TenantMembership:
    """AUTHZ-OPS-001: reuses the same historical membership row (CLAUDE.md
    rule 7 -- no new row is created), restoring it to 'active' with its
    last-known role_code unchanged. Rejected if the same user has since
    been given a different active membership row in this tenant -- the
    partial unique index (`ux_tenant_memberships_active_tenant_user`) would
    otherwise be violated; caught here as a friendly domain error rather
    than a raw IntegrityError."""
    membership = _lock_membership(db, tenant_id=tenant_id, membership_id=membership_id)

    if membership.status != "removed":
        raise MembershipNotInactiveError(str(membership_id))

    membership.status = "active"
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise MembershipAlreadyActiveForUserError(str(membership_id)) from exc

    append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="membership.reactivated",
        entity_type="tenant_membership",
        entity_id=membership.id,
        event_data={"role_code": membership.role_code},
    )

    db.commit()
    db.refresh(membership)
    return membership
