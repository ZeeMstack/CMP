"""PILOT-SETUP-001B1: `scripts/manage_platform_admin.py` command-logic
tests. Calls `cmd_grant`/`cmd_revoke` directly against the shared
`db_session` test fixture (bound to cmp_test) -- never a subprocess, and
this module never imports or calls `main()`/`_open_connection()`, which
target `settings.database_url` (the real deployment database)."""

import sys
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

from scripts import manage_platform_admin as cli  # noqa: E402

from app.services import platform_admin_service, user_service  # noqa: E402
from tests._platform_admin_bootstrap_scenario import cleanup_bootstrapped_admin  # noqa: E402


def _make_user(db_session, *, subject: str | None = None):
    subject = subject or f"cli-subject-{uuid.uuid4().hex[:12]}"
    return user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=subject,
        email=f"{subject}@example.com",
        display_name="CLI Test User",
    )


@pytest.mark.integration
def test_grant_existing_user(db_session, capsys) -> None:
    user = _make_user(db_session, subject="cli-grant-target")
    exit_code = cli.cmd_grant(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject="cli-grant-target",
        reason="Initial platform administrator",
        granted_by_oidc_issuer=None,
        granted_by_oidc_subject=None,
    )
    assert exit_code == 0
    assert platform_admin_service.is_platform_admin(db_session, user_id=user.id) is True
    assert "Granted platform-admin authority" in capsys.readouterr().out


@pytest.mark.integration
def test_grant_unknown_user_is_rejected(db_session) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_grant(
            db_session,
            oidc_issuer="https://issuer.example",
            oidc_subject="does-not-exist",
            reason=None,
            granted_by_oidc_issuer=None,
            granted_by_oidc_subject=None,
        )
    assert exc_info.value.code == 1


@pytest.mark.integration
def test_grant_unknown_granted_by_actor_is_rejected(db_session) -> None:
    _make_user(db_session, subject="cli-grant-target-2")
    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_grant(
            db_session,
            oidc_issuer="https://issuer.example",
            oidc_subject="cli-grant-target-2",
            reason=None,
            granted_by_oidc_issuer="https://issuer.example",
            granted_by_oidc_subject="does-not-exist-either",
        )
    assert exc_info.value.code == 1


@pytest.mark.integration
def test_revoke_existing_grant(db_session, capsys) -> None:
    user = _make_user(db_session, subject="cli-revoke-target")
    platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)

    exit_code = cli.cmd_revoke(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject="cli-revoke-target",
        revoked_by_oidc_issuer=None,
        revoked_by_oidc_subject=None,
    )
    assert exit_code == 0
    assert platform_admin_service.is_platform_admin(db_session, user_id=user.id) is False
    assert "Revoked platform-admin authority" in capsys.readouterr().out


@pytest.mark.integration
def test_revoke_unknown_user_is_rejected(db_session) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_revoke(
            db_session,
            oidc_issuer="https://issuer.example",
            oidc_subject="does-not-exist-revoke",
            revoked_by_oidc_issuer=None,
            revoked_by_oidc_subject=None,
        )
    assert exc_info.value.code == 1


@pytest.mark.integration
def test_grant_then_grant_again_is_idempotent(db_session, capsys) -> None:
    user = _make_user(db_session, subject="cli-rerun-target")
    cli.cmd_grant(
        db_session, oidc_issuer="https://issuer.example", oidc_subject="cli-rerun-target",
        reason=None, granted_by_oidc_issuer=None, granted_by_oidc_subject=None,
    )
    capsys.readouterr()
    exit_code = cli.cmd_grant(
        db_session, oidc_issuer="https://issuer.example", oidc_subject="cli-rerun-target",
        reason=None, granted_by_oidc_issuer=None, granted_by_oidc_subject=None,
    )
    assert exit_code == 0
    assert "already holds active platform-admin authority" in capsys.readouterr().out
    assert platform_admin_service.is_platform_admin(db_session, user_id=user.id) is True


@pytest.mark.integration
def test_revoke_then_revoke_again_is_safe(db_session, capsys) -> None:
    user = _make_user(db_session, subject="cli-rerun-revoke-target")
    platform_admin_service.grant_platform_admin(db_session, user_id=user.id, granted_by_user_id=None)
    cli.cmd_revoke(
        db_session, oidc_issuer="https://issuer.example", oidc_subject="cli-rerun-revoke-target",
        revoked_by_oidc_issuer=None, revoked_by_oidc_subject=None,
    )
    capsys.readouterr()
    exit_code = cli.cmd_revoke(
        db_session, oidc_issuer="https://issuer.example", oidc_subject="cli-rerun-revoke-target",
        revoked_by_oidc_issuer=None, revoked_by_oidc_subject=None,
    )
    assert exit_code == 0
    assert "no active platform-admin authority" in capsys.readouterr().out


# --- DEPLOY-001A: cmd_bootstrap_first_admin ---------------------------------
#
# Takes an Engine (not a Session) -- mirrors platform_tenant_service.
# onboard_tenant's own Engine-based testability -- so these tests use the
# shared `test_engine` fixture and clean up committed rows themselves,
# exactly like tests/test_platform_tenant_service.py.


def _bootstrap_kwargs(**overrides) -> dict:
    unique = uuid.uuid4().hex[:10]
    kwargs = dict(
        oidc_issuer="https://issuer.example",
        oidc_subject=f"cli-bootstrap-{unique}",
        email=f"cli-bootstrap-{unique}@example.com",
        display_name="CLI Bootstrap Admin",
        reason="DEPLOY-001A pilot bootstrap",
    )
    kwargs.update(overrides)
    return kwargs


@pytest.mark.integration
def test_cmd_bootstrap_first_admin_creates_user_and_grants(test_engine, capsys) -> None:
    kwargs = _bootstrap_kwargs()
    exit_code = cli.cmd_bootstrap_first_admin(test_engine, **kwargs)
    out = capsys.readouterr().out
    try:
        assert exit_code == 0
        assert "Created User" in out
        assert kwargs["email"] in out

        user = user_service.get_user_by_issuer_subject(
            _bound_session(test_engine), oidc_issuer=kwargs["oidc_issuer"], oidc_subject=kwargs["oidc_subject"]
        )
        assert user is not None
        assert platform_admin_service.is_platform_admin(_bound_session(test_engine), user_id=user.id) is True
    finally:
        user = user_service.get_user_by_issuer_subject(
            _bound_session(test_engine), oidc_issuer=kwargs["oidc_issuer"], oidc_subject=kwargs["oidc_subject"]
        )
        cleanup_bootstrapped_admin(test_engine, user.id if user else None)


def _bound_session(engine):
    """A short-lived, autocommit-off Session for read-only lookups against
    already-committed rows in this test module -- never used to write, so
    no savepoint/outer-transaction machinery is needed here."""
    from sqlalchemy.orm import Session

    return Session(bind=engine)


@pytest.mark.integration
def test_cmd_bootstrap_first_admin_already_active_is_idempotent(test_engine, capsys) -> None:
    kwargs = _bootstrap_kwargs()
    cli.cmd_bootstrap_first_admin(test_engine, **kwargs)
    capsys.readouterr()
    user = user_service.get_user_by_issuer_subject(
        _bound_session(test_engine), oidc_issuer=kwargs["oidc_issuer"], oidc_subject=kwargs["oidc_subject"]
    )
    try:
        exit_code = cli.cmd_bootstrap_first_admin(test_engine, **kwargs)
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "already holds active platform-admin authority" in out
    finally:
        cleanup_bootstrapped_admin(test_engine, user.id if user else None)


@pytest.mark.integration
def test_cmd_bootstrap_first_admin_email_conflict_is_rejected(test_engine) -> None:
    kwargs = _bootstrap_kwargs()
    cli.cmd_bootstrap_first_admin(test_engine, **kwargs)
    user = user_service.get_user_by_issuer_subject(
        _bound_session(test_engine), oidc_issuer=kwargs["oidc_issuer"], oidc_subject=kwargs["oidc_subject"]
    )
    try:
        with pytest.raises(SystemExit) as exc_info:
            cli.cmd_bootstrap_first_admin(test_engine, **{**kwargs, "email": "someone-else@example.com"})
        assert exc_info.value.code == 1
    finally:
        cleanup_bootstrapped_admin(test_engine, user.id if user else None)


@pytest.mark.integration
def test_confirm_bootstrap_first_admin_yes_skips_prompt_and_prints_no_secrets(test_engine, capsys, monkeypatch) -> None:
    def _unexpected_input(*args, **kwargs):
        raise AssertionError("input() must not be called when yes=True")

    monkeypatch.setattr("builtins.input", _unexpected_input)
    cli._confirm_bootstrap_first_admin(
        test_engine,
        oidc_issuer="https://issuer.example",
        oidc_subject="preview-subject",
        email="preview@example.com",
        display_name="Preview Admin",
        reason=None,
        yes=True,
    )
    out = capsys.readouterr().out
    assert "preview-subject" in out
    assert "preview@example.com" in out
    for secret_marker in ("DATABASE_URL", "postgresql://", "postgresql+psycopg://", "password"):
        assert secret_marker not in out


@pytest.mark.integration
def test_confirm_bootstrap_first_admin_aborts_without_exact_phrase(test_engine, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "yes")
    with pytest.raises(SystemExit) as exc_info:
        cli._confirm_bootstrap_first_admin(
            test_engine,
            oidc_issuer="https://issuer.example",
            oidc_subject="abort-subject",
            email="abort@example.com",
            display_name="Abort Admin",
            reason=None,
            yes=False,
        )
    assert exc_info.value.code == 1

    user = user_service.get_user_by_issuer_subject(
        _bound_session(test_engine), oidc_issuer="https://issuer.example", oidc_subject="abort-subject"
    )
    assert user is None, "an aborted confirmation must never create a User"
