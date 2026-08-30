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
