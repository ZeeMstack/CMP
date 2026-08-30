"""DEPLOY-001D: the one approved, explicit, one-shot production/deployment
Alembic migration entrypoint.

TEST-ONLY escape hatch is `--allow-non-production-database` -- everything
else in this file is written for a real DigitalOcean Managed PostgreSQL
pilot target. This script is intentionally narrow: it only ever upgrades
the already-connected database to this repository's own Alembic head. It
never downgrades, never creates/drops/resets a database, and is never
invoked from application startup (`app/main.py` has no migration call of
any kind -- see `tests/test_migrate_database_script.py`).

Usage (production-style, from the deployed `api` image -- see
docs/deployment/PILOT_DEPLOYMENT.md, "Migration"):

    docker compose --env-file /secure/path/production.env -f compose.prod.yaml \\
      run --rm api python scripts/migrate_database.py \\
      --backup-confirmed \\
      --expect-host <managed-postgres-host> \\
      --expect-database <managed-postgres-db> \\
      --yes

Safety model (see root CLAUDE.md and ALEMBIC-SAFETY-001 /
migrations/_alembic_url_safety.py for the underlying fail-closed
invariant this script deliberately never weakens):

  * DATABASE_URL is read directly from the process environment -- never
    from `app.core.settings.settings.database_url`, which carries a
    local-development default that would otherwise become the silent
    migration target the moment DATABASE_URL is merely unset. Never reads
    TEST_DATABASE_URL as a production target either.
  * The target's sanitized identity (host/port/database/sslmode -- never
    username/password) is always printed before anything else happens.
  * An obvious accidental target (a known repository dev/test database
    name, or a local/loopback host) is refused unless the operator passes
    `--allow-non-production-database` -- reserved for this script's own
    automated verification against a disposable `cmp_test` database, never
    for a real deployment.
  * `--expect-host`/`--expect-database`, if supplied, must match exactly or
    the script stops before ever touching the database.
  * A production-style invocation (no `--allow-non-production-database`)
    requires DATABASE_URL to carry a real TLS `sslmode`
    (require/verify-ca/verify-full) and requires `--backup-confirmed`.
    `--backup-confirmed` is an operator acknowledgement that a current,
    recoverable managed-Postgres backup/snapshot already exists -- it is
    NOT itself a backup mechanism, and `--yes` never substitutes for it.
  * A typed confirmation is required unless `--yes` is supplied.
  * Before upgrading, the database's current Alembic revision is read and
    validated: a blank/unversioned database and a database already at any
    known repository revision are both safe to upgrade; an unrecognized or
    ambiguous (multiple current heads) revision state is refused rather
    than guessed at.
  * If the database is already at repository head, the script reports
    success and makes no changes -- it does not call `alembic upgrade`
    at all in that case.
  * The target `sqlalchemy.url` is always passed to Alembic
    programmatically (`Config.set_main_option`, exactly the pattern
    `scripts/reset_test_database.py` and `tests/conftest.py`'s
    `migrations_alembic_config()` already use) -- this file makes no
    change to `migrations/env.py` or `migrations/_alembic_url_safety.py`,
    and a bare `alembic upgrade head` invocation remains exactly as
    fail-closed as before this script existed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Mapping

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

from app.core.settings import settings  # noqa: E402

# Known repository dev/test database names -- never a real pilot/production
# database name. `cmp` is settings.database_url's own local-development
# default database; `cmp_test` is the automated test suite's database
# (scripts/reset_test_database.py, tests/conftest.py).
_KNOWN_DEV_DATABASE_NAMES = {"cmp", "cmp_test"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SAFE_SSLMODES = {"require", "verify-ca", "verify-full"}
_CONFIRMATION_PHRASE = "migrate"


def _fail(message: str) -> None:
    print(f"\nREFUSED: {message}", file=sys.stderr)
    raise SystemExit(1)


def _redact(message: str, database_url: str) -> str:
    """Strips a URL's password (if any) out of an arbitrary error message
    before it is ever printed -- defense in depth on top of the fact that
    this script never interpolates DATABASE_URL itself into any message."""
    try:
        password = make_url(database_url).password
    except Exception:
        password = None
    if password:
        message = message.replace(password, "***")
    return message


def resolve_database_url(env: Mapping[str, str]) -> str:
    """Requires DATABASE_URL to be explicitly present in `env`. Never falls
    back to `app.core.settings.settings.database_url` (that setting's own
    local-development default) and never reads TEST_DATABASE_URL."""
    url = env.get("DATABASE_URL")
    if not url or not url.strip():
        _fail(
            "DATABASE_URL must be set explicitly in the environment. Refusing to select a "
            "database automatically -- there is no fallback to any local/default database."
        )
    return url


def sanitize_target_identity(database_url: str) -> dict:
    """Host/port/database/sslmode only -- never username/password."""
    parsed = make_url(database_url)
    query = dict(parsed.query)
    return {
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
        "sslmode": query.get("sslmode"),
    }


def describe_target(identity: dict) -> str:
    return (
        f"  host      : {identity['host']}\n"
        f"  port      : {identity['port'] if identity['port'] is not None else '(default)'}\n"
        f"  database  : {identity['database']}\n"
        f"  sslmode   : {identity['sslmode'] or '(not set)'}"
    )


def looks_like_non_production_database(identity: dict) -> str | None:
    """Returns a human-readable refusal reason if the target looks like an
    obvious accidental non-production database, else None."""
    host = (identity["host"] or "").lower()
    database = (identity["database"] or "").lower()
    if host in _LOCAL_HOSTS:
        return f"host {identity['host']!r} looks like a local/loopback development host"
    if database in _KNOWN_DEV_DATABASE_NAMES:
        return f"database name {identity['database']!r} is a known repository dev/test database"
    return None


def check_expected_identity(identity: dict, *, expect_host: str | None, expect_database: str | None) -> None:
    """If provided and mismatched: stop before migration -- checked purely
    against the parsed DATABASE_URL, before any connection is opened."""
    if expect_host is not None and (identity["host"] or "") != expect_host:
        _fail(
            f"--expect-host {expect_host!r} does not match target host {identity['host']!r}. "
            "Stopping before migration."
        )
    if expect_database is not None and (identity["database"] or "") != expect_database:
        _fail(
            f"--expect-database {expect_database!r} does not match target database "
            f"{identity['database']!r}. Stopping before migration."
        )


def check_tls_posture(identity: dict, *, allow_non_production: bool) -> None:
    if allow_non_production:
        return
    sslmode = identity["sslmode"]
    if sslmode not in _SAFE_SSLMODES:
        _fail(
            f"a production-style invocation requires DATABASE_URL to include "
            f"sslmode=require|verify-ca|verify-full (found: {sslmode!r}). See "
            "docs/deployment/PILOT_DEPLOYMENT.md, 'Database'."
        )


def check_backup_confirmation(*, backup_confirmed: bool, allow_non_production: bool) -> None:
    """--backup-confirmed is an operator acknowledgement that a current,
    recoverable managed-Postgres backup/snapshot already exists -- it is
    NOT itself a backup mechanism. `--yes` never substitutes for it."""
    if allow_non_production:
        return
    if not backup_confirmed:
        _fail(
            "--backup-confirmed is required for a production-style migration invocation. This "
            "flag only records that the operator has verified a current, recoverable managed-"
            "Postgres backup/snapshot exists -- it is not itself a backup mechanism, and --yes "
            "does not substitute for it."
        )


def confirm_invocation(identity: dict, *, yes: bool, allow_non_production: bool) -> None:
    if yes:
        return
    print("\nAbout to run a database migration against:")
    print(describe_target(identity))
    if not allow_non_production:
        print("This is a PRODUCTION-STYLE invocation.")
    answer = input(f"\nType {_CONFIRMATION_PHRASE!r} to continue, anything else to abort: ").strip()
    if answer != _CONFIRMATION_PHRASE:
        _fail("confirmation not received -- aborting without making any change.")


def build_alembic_config(database_url: str) -> Config:
    """Mirrors `scripts/reset_test_database.py`'s `_migrations_cfg()` and
    `tests/conftest.py`'s `migrations_alembic_config()`: sets
    `sqlalchemy.url` programmatically on the `Config`, exactly the
    established safe pattern -- never a bare CLI invocation, and no change
    to `migrations/env.py`'s own fail-closed check."""
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def resolve_repository_head(cfg: Config) -> str:
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    if len(heads) != 1:
        _fail(
            f"repository migration graph has {len(heads)} heads {heads!r}; expected exactly one. "
            "Refusing to migrate against an ambiguous graph."
        )
    return heads[0]


def read_current_revisions(engine) -> list[str] | None:
    """Returns None for a blank/unversioned database (no alembic_version
    table yet), else the list of `version_num` rows currently stored."""
    with engine.connect() as conn:
        table_exists = conn.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL")).scalar_one()
        if not table_exists:
            return None
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    return list(rows)


def validate_current_revisions(revisions: list[str] | None, known: set[str]) -> str | None:
    """Rejects anything unsafe to upgrade automatically: an empty-but-
    present version table, multiple current heads (ambiguous/branched
    state), or a revision this repository's migration graph doesn't know
    about. Returns None for a blank database, else the single validated
    current revision."""
    if revisions is None:
        return None
    if len(revisions) == 0:
        _fail("alembic_version table exists but is empty; unexpected database state, refusing to upgrade.")
    if len(revisions) > 1:
        _fail(
            f"database reports multiple current Alembic revisions {revisions!r} (ambiguous/branched "
            "state); refusing to upgrade automatically."
        )
    current = revisions[0]
    if current not in known:
        _fail(
            f"current database revision {current!r} is not a known revision in this repository's "
            "migration graph; refusing to upgrade automatically -- this requires manual investigation."
        )
    return current


def run_upgrade(cfg: Config) -> None:
    command.upgrade(cfg, "head")


def verify_post_migration(engine, expected_head: str) -> None:
    with engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    if current != expected_head:
        _fail(
            f"post-migration verification failed: alembic_version is {current!r}, expected head "
            f"{expected_head!r}."
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "DEPLOY-001D: explicit, one-shot Alembic migration to repository head. Never runs from "
            "application startup, never downgrades, never creates/resets/drops a database."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--backup-confirmed",
        action="store_true",
        help=(
            "Operator acknowledgement that a current, recoverable managed-Postgres backup/snapshot "
            "exists. Required for a production-style invocation. NOT itself a backup mechanism."
        ),
    )
    parser.add_argument(
        "--expect-host", default=None, help="Refuse to proceed unless the target host matches exactly."
    )
    parser.add_argument(
        "--expect-database",
        default=None,
        help="Refuse to proceed unless the target database name matches exactly.",
    )
    parser.add_argument("--yes", action="store_true", help="Skip the interactive typed-confirmation prompt.")
    parser.add_argument(
        "--allow-non-production-database",
        action="store_true",
        help=(
            "Explicit override for this script's own automated verification against a disposable "
            "local/test database only. Disables the dev/test-database refusal, the TLS-posture "
            "requirement, and the --backup-confirmed requirement. Never use this against a real "
            "pilot/production target."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    database_url = resolve_database_url(os.environ)
    identity = sanitize_target_identity(database_url)
    print("Target database identity:")
    print(describe_target(identity))

    check_expected_identity(identity, expect_host=args.expect_host, expect_database=args.expect_database)

    if not args.allow_non_production_database:
        reason = looks_like_non_production_database(identity)
        if reason is not None:
            _fail(
                f"target looks like an accidental non-production database ({reason}). Pass "
                "--allow-non-production-database only for this script's own automated verification "
                "against a disposable database -- never against a real deployment target."
            )

    check_tls_posture(identity, allow_non_production=args.allow_non_production_database)
    check_backup_confirmation(
        backup_confirmed=args.backup_confirmed, allow_non_production=args.allow_non_production_database
    )
    confirm_invocation(identity, yes=args.yes, allow_non_production=args.allow_non_production_database)

    cfg = build_alembic_config(database_url)
    head = resolve_repository_head(cfg)
    engine = create_engine(
        database_url, pool_pre_ping=True, connect_args={"connect_timeout": settings.db_connect_timeout_seconds}
    )
    try:
        try:
            script = ScriptDirectory.from_config(cfg)
            known = {rev.revision for rev in script.walk_revisions()}
            revisions = read_current_revisions(engine)
        except SystemExit:
            raise
        except Exception as exc:
            print(f"\nMIGRATION FAILED: {_redact(str(exc), database_url)}", file=sys.stderr)
            return 1

        current = validate_current_revisions(revisions, known)
        print(f"\nCurrent database revision : {current or '(blank/unversioned)'}")
        print(f"Repository target head    : {head}")

        if current == head:
            print("\nDatabase is already at repository head -- already current. No changes made.")
            return 0

        print("\nRunning upgrade to head...")
        try:
            run_upgrade(cfg)
            verify_post_migration(engine, head)
        except SystemExit:
            raise
        except Exception as exc:
            print(f"\nMIGRATION FAILED: {_redact(str(exc), database_url)}", file=sys.stderr)
            return 1

        print(f"\nMigration complete. Database is now at repository head {head}.")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
