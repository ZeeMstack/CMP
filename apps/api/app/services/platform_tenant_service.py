"""PILOT-SETUP-001B2: platform-admin-gated Tenant onboarding orchestration.

Composes three already-existing, independently-committing services --
`tenant_service.create_tenant`, `user_service.get_user_by_issuer_subject` /
`create_user`, `membership_service.add_membership` -- into ONE atomic
onboarding command: Tenant created, initial admin User resolved-or-created,
active `tenant_admin` TenantMembership established. All three succeed
together, or none of their writes survive.

Transaction strategy
---------------------
None of the three underlying services is modified, and none is called
through the ordinary request-scoped `Session` FastAPI's `get_db` dependency
hands routes (there, `Session.commit()` is a real, immediate PostgreSQL
COMMIT -- three sequential calls would be three separate transactions, not
one atomic unit).

Instead this module reuses the exact transaction pattern already
established in this codebase for the identical problem --
`app.services.pilot_bootstrap_service` (composing many committing services
atomically) and `scripts/bootstrap_pilot_master_data.py` (the caller that
owns the transaction): open one explicit `Connection`, begin one outer
transaction on it, and bind an ORM `Session` to that connection with
`join_transaction_mode="create_savepoint"`. Under that mode every internal
`db.commit()` the three services call only releases a SAVEPOINT -- the real
outer transaction stays open until THIS function commits it (all three
steps succeeded) or rolls it back (any step raised). This gives "the whole
onboarding lands, or none of it does" for free, with zero changes to
`tenant_service`, `user_service`, or `membership_service`.

This function owns its own `Connection`/`Session` end-to-end (opened and
closed here) rather than accepting a caller-supplied `Session` -- mirroring
`app.services.traceability_service`'s own precedent for a service that
needs a transaction shape the shared request-scoped `Session` cannot
provide. Callers (the platform Tenant router) pass the SQLAlchemy `Engine`
(via the existing `app.core.db.get_engine` FastAPI dependency), not a
`Session`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.services import membership_service, tenant_service, user_service
from app.services.errors import AdminIdentityEmailMismatchError


@dataclass(frozen=True)
class TenantOnboardingResult:
    """Plain-value snapshot of the three rows created/resolved by
    `onboard_tenant`, captured while the outer transaction is still open --
    never live ORM objects, which would be detached (and any non-preloaded
    attribute access unsafe) the moment this function's own `Session` is
    closed. Enough fields to populate `TenantRead`/`UserRead`/
    `MembershipRead` directly, with no second database round-trip."""

    tenant_id: uuid.UUID
    tenant_code: str
    tenant_name: str
    tenant_status: str

    admin_user_id: uuid.UUID
    admin_user_oidc_issuer: str
    admin_user_oidc_subject: str
    admin_user_email: str
    admin_user_display_name: str
    admin_user_status: str
    admin_user_created: bool

    membership_id: uuid.UUID
    membership_status: str
    membership_role_code: str


def onboard_tenant(
    db_engine: Engine,
    *,
    tenant_code: str,
    tenant_name: str,
    admin_oidc_issuer: str,
    admin_oidc_subject: str,
    admin_email: str,
    admin_display_name: str,
) -> TenantOnboardingResult:
    """Creates a Tenant, resolves-or-creates its initial administrative
    User by exact (oidc_issuer, oidc_subject) identity, and establishes an
    active `tenant_admin` TenantMembership linking them -- atomically.

    Raises (propagated from the underlying services, or raised directly
    below), always leaving the database exactly as it was found on any
    failure:

    - `DuplicateTenantCodeError` -- `tenant_code` already exists.
    - `AdminIdentityEmailMismatchError` -- an existing User was resolved by
      identity, but `admin_email` does not match that User's own recorded
      email (never silently overwritten).
    - `DuplicateUserIdentityError` -- a concurrent onboarding request won a
      race to create the same new identity first.
    - `DuplicateMembershipError` -- a concurrent request won a race to
      create the same active Membership first.

    Never creates a duplicate User row for an OIDC identity that already
    exists, and never creates more than one active Membership for
    (tenant, user) -- both already guaranteed by the underlying services'
    own database-level uniqueness, re-verified here only as ordinary
    exception propagation (no bespoke retry/merge logic)."""
    conn = db_engine.connect()
    outer_trans = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        tenant = tenant_service.create_tenant(db, code=tenant_code, name=tenant_name)

        existing_user = user_service.get_user_by_issuer_subject(
            db, oidc_issuer=admin_oidc_issuer, oidc_subject=admin_oidc_subject
        )
        if existing_user is not None:
            if existing_user.email != admin_email:
                raise AdminIdentityEmailMismatchError(
                    f"resolved User for oidc_issuer={admin_oidc_issuer!r} oidc_subject={admin_oidc_subject!r} "
                    f"already has email {existing_user.email!r}, which does not match the supplied "
                    f"{admin_email!r} -- refusing to silently overwrite an existing identity's email"
                )
            admin_user = existing_user
            admin_user_created = False
        else:
            admin_user = user_service.create_user(
                db,
                oidc_issuer=admin_oidc_issuer,
                oidc_subject=admin_oidc_subject,
                email=admin_email,
                display_name=admin_display_name,
            )
            admin_user_created = True

        membership = membership_service.add_membership(
            db,
            tenant_id=tenant.id,
            user_id=admin_user.id,
            role_code="tenant_admin",
            actor_user_id=None,
        )

        # Captured as plain values now, while the outer transaction (and
        # therefore every attribute below) is still fully live -- never
        # touched again after `outer_trans.commit()`/`.rollback()` below.
        result = TenantOnboardingResult(
            tenant_id=tenant.id,
            tenant_code=tenant.code,
            tenant_name=tenant.name,
            tenant_status=tenant.status,
            admin_user_id=admin_user.id,
            admin_user_oidc_issuer=admin_user.oidc_issuer,
            admin_user_oidc_subject=admin_user.oidc_subject,
            admin_user_email=admin_user.email,
            admin_user_display_name=admin_user.display_name,
            admin_user_status=admin_user.status,
            admin_user_created=admin_user_created,
            membership_id=membership.id,
            membership_status=membership.status,
            membership_role_code=membership.role_code,
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
