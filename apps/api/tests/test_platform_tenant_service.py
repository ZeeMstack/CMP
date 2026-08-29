"""PILOT-SETUP-001B2: `platform_tenant_service.onboard_tenant` orchestration
tests. Deliberately does NOT use the shared `db_session`/`client` fixtures
for the atomicity-proof tests (7/8/9 below) -- `onboard_tenant` owns its own
`Connection`/outer transaction end-to-end (mirrors
`app.services.traceability_service`'s own precedent), so proving it actually
committed or rolled back for real requires querying from a wholly separate
connection afterward, exactly as `tests/test_pilot_bootstrap_service.py::
test_dry_run_writes_nothing` already established for the identical
transaction pattern."""

import uuid

import pytest
from sqlalchemy import text

from app.services import platform_tenant_service, user_service
from app.services.errors import AdminIdentityEmailMismatchError, DuplicateTenantCodeError
from tests._platform_tenant_scenario import cleanup_onboarded_tenant


def _onboard_kwargs(**overrides) -> dict:
    unique = uuid.uuid4().hex[:10]
    kwargs = dict(
        tenant_code=f"onb-{unique}",
        tenant_name="Onboarding Tenant",
        admin_oidc_issuer="https://issuer.example",
        admin_oidc_subject=f"onb-admin-{unique}",
        admin_email=f"{unique}@example.com",
        admin_display_name="Onboarding Admin",
    )
    kwargs.update(overrides)
    return kwargs


# --- 1. new Tenant + new User + tenant_admin Membership succeeds -----------


@pytest.mark.integration
def test_new_tenant_new_user_creates_full_onboarding(test_engine) -> None:
    kwargs = _onboard_kwargs()
    result = platform_tenant_service.onboard_tenant(test_engine, **kwargs)
    try:
        assert result.tenant_code == kwargs["tenant_code"]
        assert result.admin_user_created is True
        assert result.admin_user_oidc_issuer == kwargs["admin_oidc_issuer"]
        assert result.admin_user_oidc_subject == kwargs["admin_oidc_subject"]
        assert result.membership_role_code == "tenant_admin"
        assert result.membership_status == "active"

        with test_engine.connect() as conn:
            tenant_row = conn.execute(
                text("SELECT id FROM tenants WHERE id = :id"), {"id": str(result.tenant_id)}
            ).scalar_one_or_none()
            user_row = conn.execute(
                text("SELECT id FROM users WHERE id = :id"), {"id": str(result.admin_user_id)}
            ).scalar_one_or_none()
            membership_row = conn.execute(
                text("SELECT id FROM tenant_memberships WHERE id = :id"), {"id": str(result.membership_id)}
            ).scalar_one_or_none()
        assert tenant_row is not None
        assert user_row is not None
        assert membership_row is not None
    finally:
        cleanup_onboarded_tenant(test_engine, result.tenant_id, result.admin_user_id)


# --- 2. new Tenant + existing User succeeds ---------------------------------


@pytest.mark.integration
def test_new_tenant_existing_user_reuses_user(test_engine) -> None:
    unique = uuid.uuid4().hex[:10]
    with test_engine.connect() as conn:
        outer = conn.begin()
        from sqlalchemy.orm import Session

        db = Session(bind=conn, join_transaction_mode="create_savepoint")
        existing_user = user_service.create_user(
            db, oidc_issuer="https://issuer.example", oidc_subject=f"pre-{unique}",
            email=f"pre-{unique}@example.com", display_name="Pre-existing Admin",
        )
        existing_user_id = existing_user.id
        db.close()
        outer.commit()

    kwargs = _onboard_kwargs(
        admin_oidc_subject=f"pre-{unique}", admin_email=f"pre-{unique}@example.com",
    )
    result = platform_tenant_service.onboard_tenant(test_engine, **kwargs)
    try:
        assert result.admin_user_created is False
        assert result.admin_user_id == existing_user_id
    finally:
        cleanup_onboarded_tenant(test_engine, result.tenant_id, result.admin_user_id)


# --- resolved User email mismatch is a conflict, never silently applied ----


@pytest.mark.integration
def test_resolved_user_email_mismatch_is_rejected(test_engine) -> None:
    unique = uuid.uuid4().hex[:10]
    with test_engine.connect() as conn:
        outer = conn.begin()
        from sqlalchemy.orm import Session

        db = Session(bind=conn, join_transaction_mode="create_savepoint")
        existing_user = user_service.create_user(
            db, oidc_issuer="https://issuer.example", oidc_subject=f"mismatch-{unique}",
            email=f"original-{unique}@example.com", display_name="Original Admin",
        )
        existing_user_id = existing_user.id
        db.close()
        outer.commit()

    kwargs = _onboard_kwargs(
        admin_oidc_subject=f"mismatch-{unique}", admin_email=f"different-{unique}@example.com",
    )
    with pytest.raises(AdminIdentityEmailMismatchError):
        platform_tenant_service.onboard_tenant(test_engine, **kwargs)

    # The existing user's own email is untouched.
    with test_engine.connect() as conn:
        email = conn.execute(
            text("SELECT email FROM users WHERE id = :id"), {"id": str(existing_user_id)}
        ).scalar_one()
    assert email == f"original-{unique}@example.com"
    cleanup_onboarded_tenant(test_engine, None, existing_user_id)


# --- 3. Platform Admin does not become Tenant member implicitly ------------
# (see tests/test_platform_tenants_http.py::
#  test_platform_admin_caller_receives_no_membership_only_initial_admin_does
#  -- `onboard_tenant`'s signature takes no "calling actor" parameter at
#  all, only `tenant_code`/`tenant_name`/`admin_*`, so there is structurally
#  no way for a caller's own identity to receive a Membership through this
#  function; the meaningful proof is at the HTTP boundary, where a real
#  Platform Admin principal exists to assert about.)


# --- 4. duplicate Tenant code conflicts -------------------------------------


@pytest.mark.integration
def test_duplicate_tenant_code_conflicts(test_engine) -> None:
    kwargs = _onboard_kwargs()
    first = platform_tenant_service.onboard_tenant(test_engine, **kwargs)
    try:
        retry_kwargs = _onboard_kwargs(tenant_code=kwargs["tenant_code"])
        with pytest.raises(DuplicateTenantCodeError):
            platform_tenant_service.onboard_tenant(test_engine, **retry_kwargs)

        # Retry's own new admin identity was never persisted -- the whole
        # command failed before that user could be created.
        with test_engine.connect() as conn:
            row = conn.execute(
                text("SELECT id FROM users WHERE oidc_subject = :s"),
                {"s": retry_kwargs["admin_oidc_subject"]},
            ).scalar_one_or_none()
        assert row is None
    finally:
        cleanup_onboarded_tenant(test_engine, first.tenant_id, first.admin_user_id)


# --- 5. duplicate OIDC User not created (race simulation) -------------------


@pytest.mark.integration
def test_existing_identity_never_produces_a_second_user_row(test_engine) -> None:
    kwargs = _onboard_kwargs()
    first = platform_tenant_service.onboard_tenant(test_engine, **kwargs)
    try:
        second_kwargs = _onboard_kwargs(
            admin_oidc_subject=kwargs["admin_oidc_subject"], admin_email=kwargs["admin_email"],
        )
        second = platform_tenant_service.onboard_tenant(test_engine, **second_kwargs)
        try:
            assert second.admin_user_created is False
            assert second.admin_user_id == first.admin_user_id
            with test_engine.connect() as conn:
                count = conn.execute(
                    text("SELECT count(*) FROM users WHERE oidc_subject = :s"),
                    {"s": kwargs["admin_oidc_subject"]},
                ).scalar_one()
            assert count == 1
        finally:
            cleanup_onboarded_tenant(test_engine, second.tenant_id, None)
    finally:
        cleanup_onboarded_tenant(test_engine, first.tenant_id, first.admin_user_id)


# --- 6. existing active Membership not duplicated ---------------------------


@pytest.mark.integration
def test_reusing_same_admin_for_a_second_tenant_creates_a_second_membership_not_a_duplicate(test_engine) -> None:
    """The same admin identity onboarding a SECOND, different Tenant is
    legitimate (one User, two active Memberships, one per tenant) -- this is
    the realistic shape of 'existing active Membership not duplicated':
    onboarding never creates two active Memberships for the same
    (tenant, user) pair, proven per-tenant here since a brand-new Tenant can
    never already have a Membership row for anyone."""
    kwargs = _onboard_kwargs()
    first = platform_tenant_service.onboard_tenant(test_engine, **kwargs)
    try:
        second_kwargs = _onboard_kwargs(
            admin_oidc_subject=kwargs["admin_oidc_subject"], admin_email=kwargs["admin_email"],
        )
        second = platform_tenant_service.onboard_tenant(test_engine, **second_kwargs)
        try:
            assert second.admin_user_id == first.admin_user_id
            assert second.membership_id != first.membership_id
            with test_engine.connect() as conn:
                count = conn.execute(
                    text(
                        "SELECT count(*) FROM tenant_memberships WHERE user_id = :uid AND status = 'active'"
                    ),
                    {"uid": str(first.admin_user_id)},
                ).scalar_one()
            assert count == 2
        finally:
            cleanup_onboarded_tenant(test_engine, second.tenant_id, None)
    finally:
        cleanup_onboarded_tenant(test_engine, first.tenant_id, first.admin_user_id)


# --- 7/8/9. Membership-step failure rolls back Tenant AND newly-created ----
# --- User -- no partial state after orchestration failure ------------------


@pytest.mark.integration
def test_membership_step_failure_rolls_back_tenant_and_new_user(test_engine, monkeypatch) -> None:
    """Forces the membership step to fail with a generic exception (not a
    realistic domain condition -- the point of this test is proving the
    transaction wrapper itself rolls back on ANY failure at that step, not
    re-testing a specific domain rule). Verified from a wholly separate
    connection afterward -- the same discipline `test_pilot_bootstrap_
    service.py::test_dry_run_writes_nothing` already established -- so a
    same-session illusion of visibility (rolled-back-but-still-in-the-
    Session's-identity-map) can never masquerade as a real proof."""

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated membership-step failure")

    monkeypatch.setattr(platform_tenant_service.membership_service, "add_membership", _boom)

    kwargs = _onboard_kwargs()
    with pytest.raises(RuntimeError, match="simulated membership-step failure"):
        platform_tenant_service.onboard_tenant(test_engine, **kwargs)

    with test_engine.connect() as conn:
        tenant_count = conn.execute(
            text("SELECT count(*) FROM tenants WHERE code = :code"), {"code": kwargs["tenant_code"]}
        ).scalar_one()
        user_count = conn.execute(
            text("SELECT count(*) FROM users WHERE oidc_subject = :s"), {"s": kwargs["admin_oidc_subject"]}
        ).scalar_one()
        membership_count = conn.execute(
            text(
                "SELECT count(*) FROM tenant_memberships m JOIN tenants t ON t.id = m.tenant_id "
                "WHERE t.code = :code"
            ),
            {"code": kwargs["tenant_code"]},
        ).scalar_one()
    assert tenant_count == 0, "the new Tenant must not survive a membership-step failure"
    assert user_count == 0, "the newly-created admin User must not survive a membership-step failure"
    assert membership_count == 0
