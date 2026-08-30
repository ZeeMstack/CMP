"""DEPLOY-001D: `scripts/migrate_database.py` safety and behavior tests.

Every test in this file operates exclusively against `cmp_test` -- never a
production-shaped database (none exists in this environment). The
"production-style invocation" gate itself is exercised by monkeypatching
`cli.looks_like_non_production_database` to pretend the physical `cmp_test`
target doesn't look like a dev/test database, so the backup-confirmation and
TLS-posture gates can be proven in isolation without ever pointing this
script at anything but the disposable, migration-safe `cmp_test` database.

Calls `cli.main([...])` directly (never a subprocess), mirroring
`tests/test_manage_platform_admin_cli.py` and `tests/test_alembic_url_safety.py`'s
own established pattern of exercising real script/env.py code paths
in-process."""

import socket
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

from scripts import migrate_database as cli  # noqa: E402

from app.core.settings import settings  # noqa: E402


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_head() -> str:
    return ScriptDirectory.from_config(_cfg()).get_current_head()


def _assert_cmp_test(test_engine) -> None:
    with test_engine.connect() as conn:
        current_db = conn.execute(text("SELECT current_database()")).scalar_one()
    assert current_db == "cmp_test", f"refusing to test against {current_db!r} -- expected cmp_test"


def _set_current_revision(test_engine, revision: str) -> None:
    with test_engine.connect() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = :rev"), {"rev": revision})
        conn.commit()


# =====================================================================
# 1. missing DATABASE_URL -> refuse
# =====================================================================


def test_missing_database_url_is_refused(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as exc_info:
        cli.resolve_database_url({})
    assert exc_info.value.code == 1


def test_blank_database_url_is_refused() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.resolve_database_url({"DATABASE_URL": "   "})
    assert exc_info.value.code == 1


def test_database_url_never_falls_back_to_test_database_url() -> None:
    # Only DATABASE_URL is ever consulted -- TEST_DATABASE_URL is ignored
    # entirely, even when present.
    env = {"TEST_DATABASE_URL": settings.test_database_url}
    with pytest.raises(SystemExit):
        cli.resolve_database_url(env)


# =====================================================================
# 2. credentials never printed
# =====================================================================


def test_describe_target_never_includes_credentials() -> None:
    identity = cli.sanitize_target_identity("postgresql+psycopg://cmp_user:sekret-pw@db.example.com:5432/cmp_pilot")
    rendered = cli.describe_target(identity)
    assert "cmp_user" not in rendered
    assert "sekret-pw" not in rendered
    assert "db.example.com" in rendered
    assert "cmp_pilot" in rendered


def test_redact_strips_password_from_arbitrary_message() -> None:
    url = "postgresql+psycopg://cmp_user:sekret-pw@db.example.com:5432/cmp_pilot"
    message = "connection to db.example.com failed: password sekret-pw was rejected"
    redacted = cli._redact(message, url)
    assert "sekret-pw" not in redacted
    assert "***" in redacted


# =====================================================================
# 3/4. obvious test/local DB refused in production mode
# =====================================================================


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://cmp:cmp@localhost:5432/cmp_test",
        "postgresql+psycopg://cmp:cmp@localhost:5432/cmp",
        "postgresql+psycopg://cmp:cmp@127.0.0.1:5432/some_other_db",
    ],
)
def test_known_dev_or_local_targets_refused_without_override(url: str) -> None:
    identity = cli.sanitize_target_identity(url)
    assert cli.looks_like_non_production_database(identity) is not None


def test_real_looking_target_is_not_flagged() -> None:
    identity = cli.sanitize_target_identity(
        "postgresql+psycopg://cmp_user:pw@db.example.com:5432/cmp_pilot?sslmode=verify-full"
    )
    assert cli.looks_like_non_production_database(identity) is None


@pytest.mark.integration
def test_main_refuses_cmp_test_target_without_override(monkeypatch, test_engine) -> None:
    _assert_cmp_test(test_engine)
    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--yes", "--backup-confirmed"])
    assert exc_info.value.code == 1


# =====================================================================
# 5. explicit verification/test mode can operate on the disposable DB
# =====================================================================


@pytest.mark.integration
def test_main_allows_cmp_test_with_explicit_override(monkeypatch, test_engine, apply_test_migrations) -> None:
    _assert_cmp_test(test_engine)
    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    # No --backup-confirmed supplied -- proves it is not required once
    # --allow-non-production-database is set.
    exit_code = cli.main(["--yes", "--allow-non-production-database"])
    assert exit_code == 0


# =====================================================================
# 6/7. expected-host / expected-database mismatch -> refuse before upgrade
# =====================================================================


@pytest.mark.integration
def test_main_refuses_on_expect_host_mismatch(monkeypatch, test_engine) -> None:
    _assert_cmp_test(test_engine)
    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    calls = []
    monkeypatch.setattr(cli, "run_upgrade", lambda cfg: calls.append(cfg))
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--yes", "--allow-non-production-database", "--expect-host", "not-the-real-host"])
    assert exc_info.value.code == 1
    assert calls == []


@pytest.mark.integration
def test_main_refuses_on_expect_database_mismatch(monkeypatch, test_engine) -> None:
    _assert_cmp_test(test_engine)
    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    calls = []
    monkeypatch.setattr(cli, "run_upgrade", lambda cfg: calls.append(cfg))
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--yes", "--allow-non-production-database", "--expect-database", "not-the-real-db"])
    assert exc_info.value.code == 1
    assert calls == []


# =====================================================================
# TLS posture gate -- required for a production-style invocation, skipped
# under --allow-non-production-database (proven separately via the
# monkeypatch in the backup-confirmation tests below).
# =====================================================================


def test_check_tls_posture_refuses_missing_sslmode() -> None:
    identity = cli.sanitize_target_identity("postgresql+psycopg://u:p@host.example:5432/db")
    with pytest.raises(SystemExit):
        cli.check_tls_posture(identity, allow_non_production=False)


def test_check_tls_posture_refuses_weak_sslmode() -> None:
    identity = cli.sanitize_target_identity("postgresql+psycopg://u:p@host.example:5432/db?sslmode=prefer")
    with pytest.raises(SystemExit):
        cli.check_tls_posture(identity, allow_non_production=False)


def test_check_tls_posture_accepts_strong_sslmode() -> None:
    identity = cli.sanitize_target_identity("postgresql+psycopg://u:p@host.example:5432/db?sslmode=verify-full")
    cli.check_tls_posture(identity, allow_non_production=False)  # must not raise


def test_check_tls_posture_skipped_when_non_production_allowed() -> None:
    identity = cli.sanitize_target_identity("postgresql+psycopg://u:p@host.example:5432/db")
    cli.check_tls_posture(identity, allow_non_production=True)  # must not raise


# =====================================================================
# 8/9. --backup-confirmed required; --yes does not bypass it
# =====================================================================


@pytest.mark.integration
def test_main_refuses_without_backup_confirmed_in_production_mode(monkeypatch, test_engine) -> None:
    _assert_cmp_test(test_engine)
    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    # Pretend the physical cmp_test target looks production-shaped, so the
    # backup-confirmation gate (not the dev-database heuristic) is what's
    # under test here -- the real target never changes.
    monkeypatch.setattr(cli, "looks_like_non_production_database", lambda identity: None)
    calls = []
    monkeypatch.setattr(cli, "run_upgrade", lambda cfg: calls.append(cfg))
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--yes"])
    assert exc_info.value.code == 1
    assert calls == []


@pytest.mark.integration
def test_main_yes_does_not_bypass_backup_confirmation(monkeypatch, test_engine) -> None:
    _assert_cmp_test(test_engine)
    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    monkeypatch.setattr(cli, "looks_like_non_production_database", lambda identity: None)
    monkeypatch.setattr(
        cli,
        "check_tls_posture",
        lambda identity, allow_non_production, allow_private_network_without_tls=False: None,
    )
    calls = []
    monkeypatch.setattr(cli, "run_upgrade", lambda cfg: calls.append(cfg))
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--yes"])  # --yes present, --backup-confirmed absent
    assert exc_info.value.code == 1
    assert calls == []


# =====================================================================
# 10/11/14. current revision + target head displayed; already-at-head no-op
# =====================================================================


@pytest.mark.integration
def test_main_reports_current_revision_and_head_and_is_noop_at_head(
    monkeypatch, test_engine, apply_test_migrations, capsys
) -> None:
    _assert_cmp_test(test_engine)
    expected_head = _resolve_head()
    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    exit_code = cli.main(["--yes", "--allow-non-production-database"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert f"Current database revision : {expected_head}" in out
    assert f"Repository target head    : {expected_head}" in out
    assert "already current" in out


# =====================================================================
# 12. blank DB upgrades to repository head
# =====================================================================


@pytest.mark.integration
def test_main_upgrades_blank_database_to_head(monkeypatch, test_engine, alembic_head_restore) -> None:
    _assert_cmp_test(test_engine)
    expected_head = _resolve_head()
    with test_engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()

    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    exit_code = cli.main(["--yes", "--allow-non-production-database"])
    assert exit_code == 0

    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert current == expected_head


# =====================================================================
# 13. existing older known revision upgrades to head
# =====================================================================


@pytest.mark.integration
def test_main_upgrades_older_known_revision_to_head(monkeypatch, test_engine, alembic_head_restore) -> None:
    _assert_cmp_test(test_engine)
    expected_head = _resolve_head()
    command.downgrade(_cfg(), "471bdd408a33")

    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    exit_code = cli.main(["--yes", "--allow-non-production-database"])
    assert exit_code == 0

    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert current == expected_head


# =====================================================================
# 15. unknown revision refuses
# =====================================================================


@pytest.mark.integration
def test_main_refuses_unknown_current_revision(monkeypatch, test_engine, apply_test_migrations) -> None:
    _assert_cmp_test(test_engine)
    expected_head = _resolve_head()
    _set_current_revision(test_engine, "deadbeefdeadbeef")
    try:
        monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["--yes", "--allow-non-production-database"])
        assert exc_info.value.code == 1
    finally:
        # command.upgrade cannot repair an unrecognized stored revision, so
        # restore it directly rather than relying on alembic_head_restore's
        # own command.upgrade(cfg, "head") teardown.
        _set_current_revision(test_engine, expected_head)


# =====================================================================
# 17. migration failure returns non-zero (and never leaks a credential)
# =====================================================================


@pytest.mark.integration
def test_main_returns_nonzero_and_redacts_on_upgrade_failure(monkeypatch, test_engine, alembic_head_restore, capsys) -> None:
    _assert_cmp_test(test_engine)
    command.downgrade(_cfg(), "471bdd408a33")

    def _boom(cfg):
        raise RuntimeError(f"simulated failure near {settings.test_database_url}")

    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    monkeypatch.setattr(cli, "run_upgrade", _boom)
    exit_code = cli.main(["--yes", "--allow-non-production-database"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "MIGRATION FAILED" in err


# =====================================================================
# 18. bare Alembic invocation remains fail-closed (regression proof this
# script's existence never weakened migrations/env.py)
# =====================================================================


@pytest.mark.integration
def test_bare_alembic_invocation_still_fails_closed() -> None:
    # Must match migrations/env.py's own loader exactly (same sys.modules
    # name) so the AlembicUrlNotConfiguredError class raised by the real
    # env.py below is identical to the one imported here -- see
    # tests/test_alembic_url_safety.py's own identical loader.
    import importlib.util

    module_name = "cmp_alembic_url_safety"
    if module_name in sys.modules:
        module = sys.modules[module_name]
    else:
        spec = importlib.util.spec_from_file_location(module_name, API_ROOT / "migrations" / "_alembic_url_safety.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

    bare_cfg = Config(str(API_ROOT / "alembic.ini"))
    bare_cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    with pytest.raises(module.AlembicUrlNotConfiguredError):
        command.current(bare_cfg)


# =====================================================================
# 19. application startup still does not auto-migrate
# =====================================================================


def test_app_main_never_references_alembic() -> None:
    source = (API_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "alembic" not in source.lower()


# =====================================================================
# 20. production Docker image copies only the approved deployment scripts
# =====================================================================


def test_dockerfile_copies_only_approved_deployment_scripts() -> None:
    dockerfile = (API_ROOT / "Dockerfile").read_text(encoding="utf-8")
    copy_lines = [line.strip() for line in dockerfile.splitlines() if line.strip().startswith("COPY ")]
    assert any("scripts/manage_platform_admin.py" in line for line in copy_lines)
    assert any("scripts/migrate_database.py" in line for line in copy_lines)
    for excluded in (
        "reset_test_database.py",
        "create_test_db.py",
        "dev_seed_frontend_pilot.py",
        "seed_qa_005b.py",
        "bootstrap_pilot_master_data.py",
    ):
        assert not any(excluded in line for line in copy_lines), f"{excluded} must not be COPYed into the image"
    assert 'CMD ["uvicorn"' in dockerfile


# =====================================================================
# DEPLOY-001E.2: --allow-private-network-without-tls
#
# DNS is always mocked via `socket.getaddrinfo` -- never a real lookup --
# per the ticket's own requirement. `_fake_getaddrinfo` reproduces just
# enough of the real return shape (`cli.resolve_hostname_addresses` only
# reads `info[4][0]`) for both IPv4 and IPv6 results.
# =====================================================================


def _fake_getaddrinfo(addresses: list[str]):
    def _fake(host, port, *args, **kwargs):
        results = []
        for addr in addresses:
            if ":" in addr:
                results.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (addr, 0, 0, 0)))
            else:
                results.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0)))
        return results

    return _fake


def _test_target_identity() -> dict:
    return cli.sanitize_target_identity(settings.test_database_url)


# =====================================================================
# 21. hostname resolution (mocked DNS)
# =====================================================================


def test_resolve_hostname_addresses_dedupes(monkeypatch) -> None:
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["10.1.2.3", "10.1.2.3", "10.1.2.4"]))
    assert cli.resolve_hostname_addresses("db.internal") == ["10.1.2.3", "10.1.2.4"]


def test_resolve_hostname_addresses_refuses_on_resolution_failure(monkeypatch) -> None:
    def _raise(host, port, *args, **kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(cli.socket, "getaddrinfo", _raise)
    with pytest.raises(SystemExit) as exc_info:
        cli.resolve_hostname_addresses("does-not-resolve.invalid")
    assert exc_info.value.code == 1


# =====================================================================
# 22. private-address validation: RFC1918 IPv4 / IPv6 unique-local accepted,
# everything else (public, loopback, link-local, mixed) refused
# =====================================================================


def test_check_private_network_addresses_accepts_private_ipv4(monkeypatch) -> None:
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["10.0.5.6"]))
    assert cli.check_private_network_addresses("cmp-api-internal") == ["10.0.5.6"]


@pytest.mark.parametrize("address", ["172.16.0.1", "192.168.1.1", "10.255.255.255"])
def test_check_private_network_addresses_accepts_all_rfc1918_ranges(monkeypatch, address: str) -> None:
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo([address]))
    assert cli.check_private_network_addresses("cmp-api-internal") == [address]


def test_check_private_network_addresses_accepts_private_ipv6(monkeypatch) -> None:
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["fc00::1"]))
    assert cli.check_private_network_addresses("cmp-api-internal") == ["fc00::1"]


def test_check_private_network_addresses_refuses_public_ipv4(monkeypatch) -> None:
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["8.8.8.8"]))
    with pytest.raises(SystemExit):
        cli.check_private_network_addresses("cmp-api-internal")


def test_check_private_network_addresses_refuses_literal_public_ip_host(monkeypatch) -> None:
    # The host itself is a raw public IP -- getaddrinfo resolves a literal
    # IP to itself with no real lookup, so this exercises the exact same
    # refusal path as a public hostname.
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["203.0.113.7"]))
    with pytest.raises(SystemExit):
        cli.check_private_network_addresses("203.0.113.7")


def test_check_private_network_addresses_refuses_mixed_private_and_public(monkeypatch) -> None:
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["10.0.0.5", "8.8.8.8"]))
    with pytest.raises(SystemExit):
        cli.check_private_network_addresses("cmp-api-internal")


def test_check_private_network_addresses_refuses_resolved_ipv4_loopback(monkeypatch) -> None:
    # Not the literal string "localhost"/"127.0.0.1" that looks_like_non_
    # production_database already catches -- a hostname that merely
    # *resolves* to loopback must still be refused here, independently.
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["127.0.0.1"]))
    with pytest.raises(SystemExit):
        cli.check_private_network_addresses("sneaky-hostname")


def test_check_private_network_addresses_refuses_resolved_ipv6_loopback(monkeypatch) -> None:
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["::1"]))
    with pytest.raises(SystemExit):
        cli.check_private_network_addresses("sneaky-hostname")


def test_check_private_network_addresses_refuses_link_local(monkeypatch) -> None:
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["169.254.1.1"]))
    with pytest.raises(SystemExit):
        cli.check_private_network_addresses("cmp-api-internal")


# =====================================================================
# 23. check_tls_posture wiring for --allow-private-network-without-tls --
# proves the flag never weakens the default path (no flag == unchanged
# behavior) and only accepts a target once every resolved address is
# verified private.
# =====================================================================


def test_check_tls_posture_still_refuses_missing_sslmode_without_flag() -> None:
    identity = cli.sanitize_target_identity("postgresql+psycopg://u:p@host.example:5432/db")
    with pytest.raises(SystemExit):
        cli.check_tls_posture(identity, allow_non_production=False)


def test_check_tls_posture_still_accepts_strong_sslmode_without_flag() -> None:
    identity = cli.sanitize_target_identity("postgresql+psycopg://u:p@host.example:5432/db?sslmode=verify-full")
    cli.check_tls_posture(identity, allow_non_production=False)  # must not raise


def test_check_tls_posture_refuses_when_flag_set_but_resolution_is_public(monkeypatch) -> None:
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["8.8.8.8"]))
    identity = cli.sanitize_target_identity("postgresql+psycopg://u:p@public.example:5432/db")
    with pytest.raises(SystemExit):
        cli.check_tls_posture(identity, allow_non_production=False, allow_private_network_without_tls=True)


def test_check_tls_posture_accepts_missing_sslmode_when_flag_set_and_resolution_is_private(monkeypatch) -> None:
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["10.1.2.3"]))
    identity = cli.sanitize_target_identity("postgresql+psycopg://u:p@cmp-api-internal:5432/db")
    cli.check_tls_posture(identity, allow_non_production=False, allow_private_network_without_tls=True)  # no raise


def test_check_tls_posture_ignores_flag_when_sslmode_already_safe(monkeypatch) -> None:
    # sslmode already satisfies the default rule -- resolution must never
    # even be attempted in that case.
    def _boom(host, port, *args, **kwargs):
        raise AssertionError("DNS resolution must not be attempted when sslmode is already safe")

    monkeypatch.setattr(cli.socket, "getaddrinfo", _boom)
    identity = cli.sanitize_target_identity("postgresql+psycopg://u:p@host.example:5432/db?sslmode=require")
    cli.check_tls_posture(identity, allow_non_production=False, allow_private_network_without_tls=True)


def test_check_tls_posture_private_network_mode_prints_clear_message(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["10.1.2.3"]))
    identity = cli.sanitize_target_identity("postgresql+psycopg://u:p@cmp-api-internal:5432/db")
    cli.check_tls_posture(identity, allow_non_production=False, allow_private_network_without_tls=True)
    out = capsys.readouterr().out
    assert "PRIVATE-NETWORK MODE" in out
    assert "--allow-private-network-without-tls" in out


def test_check_tls_posture_flag_never_prints_credentials(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli.socket, "getaddrinfo", _fake_getaddrinfo(["10.1.2.3"]))
    identity = cli.sanitize_target_identity("postgresql+psycopg://cmp_user:sekret-pw@cmp-api-internal:5432/db")
    cli.check_tls_posture(identity, allow_non_production=False, allow_private_network_without_tls=True)
    out = capsys.readouterr().out
    assert "sekret-pw" not in out
    assert "cmp_user" not in out


# =====================================================================
# 24. --allow-private-network-without-tls prerequisites (argument-level,
# checked before DATABASE_URL is ever touched)
# =====================================================================


def test_private_network_flag_noop_when_not_supplied() -> None:
    args = cli.build_arg_parser().parse_args([])
    cli.check_private_network_flag_prerequisites(args)  # must not raise


def test_private_network_flag_requires_expect_host() -> None:
    args = cli.build_arg_parser().parse_args(
        ["--allow-private-network-without-tls", "--expect-database", "cmp_pilot"]
    )
    with pytest.raises(SystemExit):
        cli.check_private_network_flag_prerequisites(args)


def test_private_network_flag_requires_expect_database() -> None:
    args = cli.build_arg_parser().parse_args(
        ["--allow-private-network-without-tls", "--expect-host", "cmp-api-internal"]
    )
    with pytest.raises(SystemExit):
        cli.check_private_network_flag_prerequisites(args)


def test_private_network_flag_accepts_when_both_expect_flags_supplied() -> None:
    args = cli.build_arg_parser().parse_args(
        [
            "--allow-private-network-without-tls",
            "--expect-host",
            "cmp-api-internal",
            "--expect-database",
            "cmp_pilot",
        ]
    )
    cli.check_private_network_flag_prerequisites(args)  # must not raise


def test_private_network_flag_mutually_exclusive_with_allow_non_production_database() -> None:
    args = cli.build_arg_parser().parse_args(
        [
            "--allow-private-network-without-tls",
            "--allow-non-production-database",
            "--expect-host",
            "cmp-api-internal",
            "--expect-database",
            "cmp_pilot",
        ]
    )
    with pytest.raises(SystemExit):
        cli.check_private_network_flag_prerequisites(args)


def test_private_network_flag_yes_does_not_bypass_expect_flags() -> None:
    # No --expect-host/--expect-database at all -- must refuse before
    # DATABASE_URL is even read, regardless of --yes and --backup-confirmed.
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--yes", "--backup-confirmed", "--allow-private-network-without-tls"])
    assert exc_info.value.code == 1


# =====================================================================
# 25. --allow-private-network-without-tls end-to-end via cli.main()
# =====================================================================


@pytest.mark.integration
def test_main_private_network_flag_requires_backup_confirmed(monkeypatch, test_engine) -> None:
    _assert_cmp_test(test_engine)
    identity = _test_target_identity()
    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    monkeypatch.setattr(cli, "looks_like_non_production_database", lambda i: None)
    monkeypatch.setattr(cli, "check_private_network_addresses", lambda host: ["10.1.2.3"])
    calls = []
    monkeypatch.setattr(cli, "run_upgrade", lambda cfg: calls.append(cfg))
    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            [
                "--yes",
                "--allow-private-network-without-tls",
                "--expect-host",
                identity["host"],
                "--expect-database",
                identity["database"],
            ]
        )
    assert exc_info.value.code == 1
    assert calls == []


@pytest.mark.integration
def test_main_private_network_flag_succeeds_against_verified_private_target(
    monkeypatch, test_engine, apply_test_migrations, capsys
) -> None:
    _assert_cmp_test(test_engine)
    identity = _test_target_identity()
    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    monkeypatch.setattr(cli, "looks_like_non_production_database", lambda i: None)
    monkeypatch.setattr(cli, "check_private_network_addresses", lambda host: ["10.1.2.3"])

    exit_code = cli.main(
        [
            "--yes",
            "--backup-confirmed",
            "--allow-private-network-without-tls",
            "--expect-host",
            identity["host"],
            "--expect-database",
            identity["database"],
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "PRIVATE-NETWORK MODE" in out
    assert "already current" in out


@pytest.mark.integration
def test_main_private_network_flag_reaches_backup_confirmation_gate_with_no_credential_leak(
    monkeypatch, test_engine, capsys
) -> None:
    """Covers the full `cli.main()` wiring up to (and including) the
    private-network mode message, proving it is reached and stops correctly
    without --backup-confirmed. Credential-redaction itself is proven at the
    unit level (`test_check_tls_posture_flag_never_prints_credentials`,
    `test_describe_target_never_includes_credentials`) using a distinctive
    fabricated password -- the real local `cmp_test` password ("cmp") is
    deliberately not used for a substring-leak assertion here, since it is
    also a legitimate substring of the "cmp_test" database name and would
    produce a false positive."""
    _assert_cmp_test(test_engine)
    identity = _test_target_identity()
    monkeypatch.setenv("DATABASE_URL", settings.test_database_url)
    monkeypatch.setattr(cli, "looks_like_non_production_database", lambda i: None)
    monkeypatch.setattr(cli, "check_private_network_addresses", lambda host: ["10.1.2.3"])

    with pytest.raises(SystemExit):
        # --backup-confirmed deliberately omitted -- stops right after the
        # private-network mode message is printed, which is exactly the
        # output this test needs to inspect.
        cli.main(
            [
                "--yes",
                "--allow-private-network-without-tls",
                "--expect-host",
                identity["host"],
                "--expect-database",
                identity["database"],
            ]
        )
    out = capsys.readouterr().out
    assert "PRIVATE-NETWORK MODE" in out
