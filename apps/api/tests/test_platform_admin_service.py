import uuid

import pytest
from sqlalchemy import select

from app.models.audit_event import AuditEvent
from app.models.platform_admin import PlatformAdmin
from app.services import platform_admin_service, user_service


def _make_user(db_session, *, subject: str | None = None):
    subject = subject or f"platform-admin-subject-{uuid.uuid4().hex[:12]}"
    return user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=subject,
        email=f"{subject}@example.com",
        display_name="Platform Admin Candidate",
    )


@pytest.mark.integration
def test_grant_creates_active_assignment(db_session) -> None:
    user = _make_user(db_session)
    grant = platform_admin_service.grant_platform_admin(
        db_session, user_id=user.id, granted_by_user_id=None, reason="Initial platform administrator"
    )
    assert grant.user_id == user.id
    assert grant.revoked_at is None
    assert grant.revoked_by_user_id is None
    assert grant.reason == "Initial platform administrator"
    assert platform_admin_service.is_platform_admin(db_session, user_id=user.id) is True


@pytest.mark.integration
def test_repeated_grant_is_idempotent_no_duplicate_row(db_session) -> None:
    user = _make_user(db_session)
    first = platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)
    second = platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)
    assert first.id == second.id

    rows = db_session.execute(select(PlatformAdmin).where(PlatformAdmin.user_id == user.id)).scalars().all()
    assert len(rows) == 1


@pytest.mark.integration
def test_revoke_clears_active_authority_without_deleting_row(db_session) -> None:
    user = _make_user(db_session)
    grant = platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)
    revoker = _make_user(db_session)

    revoked = platform_admin_service.revoke_platform_admin(db_session, user_id=user.id, revoked_by_user_id=revoker.id)
    assert revoked is not None
    assert revoked.id == grant.id
    assert revoked.revoked_at is not None
    assert revoked.revoked_by_user_id == revoker.id
    assert platform_admin_service.is_platform_admin(db_session, user_id=user.id) is False

    # No hard delete -- the row still exists as permanent history.
    row = db_session.get(PlatformAdmin, grant.id)
    assert row is not None


@pytest.mark.integration
def test_repeated_revoke_is_a_safe_no_op(db_session) -> None:
    user = _make_user(db_session)
    platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)
    platform_admin_service.revoke_platform_admin(db_session, user_id=user.id, revoked_by_user_id=None)

    second_revoke = platform_admin_service.revoke_platform_admin(db_session, user_id=user.id, revoked_by_user_id=None)
    assert second_revoke is None


@pytest.mark.integration
def test_revoke_of_never_granted_user_is_a_safe_no_op(db_session) -> None:
    user = _make_user(db_session)
    result = platform_admin_service.revoke_platform_admin(db_session, user_id=user.id, revoked_by_user_id=None)
    assert result is None
    assert platform_admin_service.is_platform_admin(db_session, user_id=user.id) is False


@pytest.mark.integration
def test_grant_after_revoke_creates_a_new_row_preserving_history(db_session) -> None:
    user = _make_user(db_session)
    first_grant = platform_admin_service.grant_platform_admin(
        db_session, user_id=user.id, granted_by_user_id=None, reason="first cycle"
    )
    platform_admin_service.revoke_platform_admin(db_session, user_id=user.id, revoked_by_user_id=None)

    second_grant = platform_admin_service.grant_platform_admin(
        db_session, user_id=user.id, granted_by_user_id=None, reason="second cycle"
    )
    assert second_grant.id != first_grant.id
    assert platform_admin_service.is_platform_admin(db_session, user_id=user.id) is True

    rows = db_session.execute(select(PlatformAdmin).where(PlatformAdmin.user_id == user.id)).scalars().all()
    assert len(rows) == 2
    # The first cycle's own facts are untouched by the second grant.
    first_row = next(r for r in rows if r.id == first_grant.id)
    assert first_row.revoked_at is not None
    assert first_row.reason == "first cycle"


@pytest.mark.integration
def test_active_assignment_uniqueness_enforced_at_database_level(db_session) -> None:
    user = _make_user(db_session)
    platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)

    # Bypasses the idempotent service function to prove the DB-level
    # partial unique index itself rejects a second concurrently-active row,
    # not merely the service's own existing-row check.
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(PlatformAdmin(user_id=user.id))
            db_session.flush()


@pytest.mark.integration
def test_grant_and_revoke_do_not_write_a_tenant_scoped_audit_event(db_session) -> None:
    """Platform-admin grant/revoke are genuinely tenant-less actions --
    AuditEvent.tenant_id is NOT NULL, and there is no tenant to attribute a
    platform-level action to. This mirrors user_service.create_user's own,
    already-established precedent for the same structural situation (see
    that function's docstring comment). The PlatformAdmin row's own
    granted_at/granted_by_user_id/revoked_at/revoked_by_user_id/reason
    fields are this action's permanent record instead."""
    user = _make_user(db_session)
    before = db_session.execute(select(AuditEvent)).scalars().all()

    platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)
    platform_admin_service.revoke_platform_admin(db_session, user_id=user.id, revoked_by_user_id=None)

    after = db_session.execute(select(AuditEvent)).scalars().all()
    assert len(after) == len(before)
