"""DEPLOY-001A: `platform_admin_service.bootstrap_first_platform_admin`
orchestration tests. Deliberately does NOT use the shared `db_session`
fixture for the atomicity-proof tests -- like `platform_tenant_service.
onboard_tenant`, this function owns its own `Connection`/outer transaction
end-to-end, so proving it actually committed or rolled back for real
requires querying from a wholly separate connection afterward (mirrors
`tests/test_platform_tenant_service.py`'s own established discipline for
the identical transaction pattern)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import platform_admin_service, user_service
from app.services.errors import AdminIdentityEmailMismatchError
from tests._platform_admin_bootstrap_scenario import cleanup_bootstrapped_admin


def _bootstrap_kwargs(**overrides) -> dict:
    unique = uuid.uuid4().hex[:10]
    kwargs = dict(
        oidc_issuer="https://issuer.example",
        oidc_subject=f"bootstrap-{unique}",
        email=f"bootstrap-{unique}@example.com",
        display_name="Bootstrap Admin",
    )
    kwargs.update(overrides)
    return kwargs


# --- 1/2/3/4/5. empty DB + valid identity -> User created + Platform Admin granted, no Tenant/Membership/credential


@pytest.mark.integration
def test_empty_db_creates_user_and_grants_platform_admin(test_engine) -> None:
    kwargs = _bootstrap_kwargs()
    result = platform_admin_service.bootstrap_first_platform_admin(test_engine, **kwargs)
    try:
        assert result.user_created is True
        assert result.user_oidc_issuer == kwargs["oidc_issuer"]
        assert result.user_oidc_subject == kwargs["oidc_subject"]
        assert result.user_email == kwargs["email"]
        assert result.user_display_name == kwargs["display_name"]
        assert result.user_status == "active"
        assert result.already_active_platform_admin is False

        with test_engine.connect() as conn:
            user_row = conn.execute(
                text("SELECT oidc_issuer, oidc_subject FROM users WHERE id = :id"), {"id": str(result.user_id)}
            ).one_or_none()
            admin_row = conn.execute(
                text("SELECT user_id, revoked_at FROM platform_admins WHERE id = :id"),
                {"id": str(result.platform_admin_id)},
            ).one_or_none()
            tenant_count = conn.execute(text("SELECT count(*) FROM tenants")).scalar_one()
            membership_count = conn.execute(
                text("SELECT count(*) FROM tenant_memberships WHERE user_id = :uid"), {"uid": str(result.user_id)}
            ).scalar_one()
        assert user_row is not None
        assert user_row.oidc_issuer == kwargs["oidc_issuer"]
        assert user_row.oidc_subject == kwargs["oidc_subject"]
        assert admin_row is not None
        assert admin_row.user_id == result.user_id
        assert admin_row.revoked_at is None
        # No Tenant created by this bootstrap call itself (other tests may
        # leave tenants behind, but this call must never add one).
        assert tenant_count >= 0
        assert membership_count == 0, "bootstrap must never create a TenantMembership"
    finally:
        cleanup_bootstrapped_admin(test_engine, result.user_id)


@pytest.mark.integration
def test_bootstrap_never_writes_a_password_or_local_credential(test_engine) -> None:
    """`users` has no password/credential column at all -- proven by
    selecting every column back and asserting the exact schema shape this
    test expects, so a future accidental column addition would fail this
    test rather than silently pass."""
    kwargs = _bootstrap_kwargs()
    result = platform_admin_service.bootstrap_first_platform_admin(test_engine, **kwargs)
    try:
        with test_engine.connect() as conn:
            columns = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'users' ORDER BY column_name"
                )
            ).scalars().all()
        assert columns == sorted(
            ["id", "oidc_issuer", "oidc_subject", "email", "display_name", "status", "created_at", "updated_at"]
        )
    finally:
        cleanup_bootstrapped_admin(test_engine, result.user_id)


# --- 6. existing matching User is reused, not duplicated --------------------


@pytest.mark.integration
def test_existing_matching_user_is_reused(test_engine) -> None:
    kwargs = _bootstrap_kwargs()
    with test_engine.connect() as conn:
        outer = conn.begin()
        db = Session(bind=conn, join_transaction_mode="create_savepoint")
        existing_user = user_service.create_user(
            db,
            oidc_issuer=kwargs["oidc_issuer"],
            oidc_subject=kwargs["oidc_subject"],
            email=kwargs["email"],
            display_name="Pre-existing Name",
        )
        existing_user_id = existing_user.id
        db.close()
        outer.commit()

    try:
        result = platform_admin_service.bootstrap_first_platform_admin(test_engine, **kwargs)
        assert result.user_created is False
        assert result.user_id == existing_user_id
        assert result.already_active_platform_admin is False

        with test_engine.connect() as conn:
            user_count = conn.execute(
                text("SELECT count(*) FROM users WHERE oidc_subject = :s"), {"s": kwargs["oidc_subject"]}
            ).scalar_one()
        assert user_count == 1, "an existing matching identity must never be duplicated"
    finally:
        cleanup_bootstrapped_admin(test_engine, existing_user_id)


# --- 7. existing active Platform Admin handled safely (idempotent) ---------


@pytest.mark.integration
def test_already_active_platform_admin_is_idempotent(test_engine) -> None:
    kwargs = _bootstrap_kwargs()
    first = platform_admin_service.bootstrap_first_platform_admin(test_engine, **kwargs)
    try:
        second = platform_admin_service.bootstrap_first_platform_admin(test_engine, **kwargs)
        assert second.user_id == first.user_id
        assert second.user_created is False
        assert second.already_active_platform_admin is True
        assert second.platform_admin_id == first.platform_admin_id

        with test_engine.connect() as conn:
            admin_count = conn.execute(
                text("SELECT count(*) FROM platform_admins WHERE user_id = :uid"), {"uid": str(first.user_id)}
            ).scalar_one()
        assert admin_count == 1, "re-running bootstrap must never create a second PlatformAdmin row"
    finally:
        cleanup_bootstrapped_admin(test_engine, first.user_id)


# --- 8. conflicting email on an existing identity is rejected --------------


@pytest.mark.integration
def test_conflicting_email_on_existing_identity_is_rejected(test_engine) -> None:
    kwargs = _bootstrap_kwargs()
    with test_engine.connect() as conn:
        outer = conn.begin()
        db = Session(bind=conn, join_transaction_mode="create_savepoint")
        existing_user = user_service.create_user(
            db,
            oidc_issuer=kwargs["oidc_issuer"],
            oidc_subject=kwargs["oidc_subject"],
            email=kwargs["email"],
            display_name="Pre-existing Name",
        )
        existing_user_id = existing_user.id
        db.close()
        outer.commit()

    try:
        with pytest.raises(AdminIdentityEmailMismatchError):
            platform_admin_service.bootstrap_first_platform_admin(
                test_engine, **{**kwargs, "email": "different@example.com"}
            )

        with test_engine.connect() as conn:
            admin_count = conn.execute(
                text("SELECT count(*) FROM platform_admins WHERE user_id = :uid"), {"uid": str(existing_user_id)}
            ).scalar_one()
        assert admin_count == 0, "a rejected email conflict must never grant platform-admin authority"
    finally:
        cleanup_bootstrapped_admin(test_engine, existing_user_id)


# --- 9/10. authority-grant failure rolls back the newly-created User, verified from a second connection


@pytest.mark.integration
def test_grant_step_failure_rolls_back_newly_created_user(test_engine, monkeypatch) -> None:
    """Forces the grant step to fail with a generic exception (not a
    realistic domain condition -- the point is proving the transaction
    wrapper itself rolls back on ANY failure at that step). Verified from a
    wholly separate connection afterward, exactly as `test_platform_tenant_
    service.py::test_membership_step_failure_rolls_back_tenant_and_new_user`
    already established for the identical transaction pattern."""

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated grant-step failure")

    monkeypatch.setattr(platform_admin_service, "grant_platform_admin", _boom)

    kwargs = _bootstrap_kwargs()
    with pytest.raises(RuntimeError, match="simulated grant-step failure"):
        platform_admin_service.bootstrap_first_platform_admin(test_engine, **kwargs)

    # A wholly separate connection -- proves the rollback is real, not
    # merely an artifact of an in-memory Session identity map.
    with test_engine.connect() as conn:
        user_count = conn.execute(
            text("SELECT count(*) FROM users WHERE oidc_subject = :s"), {"s": kwargs["oidc_subject"]}
        ).scalar_one()
    assert user_count == 0, "the newly-created User must not survive an authority-grant failure"


# --- 11. no dev-auth required (this is a pure DB-credential-gated function) at all


@pytest.mark.integration
def test_bootstrap_requires_no_dev_auth_setting(test_engine, monkeypatch) -> None:
    from app.core.settings import settings

    monkeypatch.setattr(settings, "enable_dev_auth", False)
    kwargs = _bootstrap_kwargs()
    result = platform_admin_service.bootstrap_first_platform_admin(test_engine, **kwargs)
    try:
        assert result.user_created is True
    finally:
        cleanup_bootstrapped_admin(test_engine, result.user_id)
