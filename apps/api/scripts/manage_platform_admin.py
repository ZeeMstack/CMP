"""PILOT-SETUP-001B1: controlled administrative CLI for granting/revoking
CMP platform-admin authority (`app.services.platform_admin_service`).

    python scripts/manage_platform_admin.py grant --oidc-issuer <issuer> --oidc-subject <subject> [--reason "..."] [--granted-by-oidc-issuer <issuer> --granted-by-oidc-subject <subject>]
    python scripts/manage_platform_admin.py revoke --oidc-issuer <issuer> --oidc-subject <subject> [--revoked-by-oidc-issuer <issuer> --revoked-by-oidc-subject <subject>]

This is the smallest safe way to bootstrap CMP's first platform
administrator: there is deliberately no unauthenticated HTTP route that
grants platform authority. This script never creates a User -- an
existing, already-provisioned CMP User (a real OIDC issuer+subject, e.g.
from that person's own prior sign-in) is a hard prerequisite for both
`grant` and `revoke`. Production User provisioning itself remains out of
scope for this ticket (tracked for PILOT-SETUP-001B2) -- if no CMP User
exists yet for the intended platform administrator, this script fails
loudly rather than inventing one.

No credentials/passwords are ever read, stored, or passed -- identity is
always an OIDC issuer+subject pair, resolved against the existing `users`
table exactly as real bearer authentication does.

This file owns ONLY: argument parsing, the database connection, and
human-readable output -- mirrors `scripts/bootstrap_pilot_master_data.py`'s
own separation of concerns. Every domain decision (idempotent grant, soft
revoke, active-uniqueness) lives in `app.services.platform_admin_service`.
`cmd_grant`/`cmd_revoke` take an already-open `Session` and contain the
entire command's logic precisely so tests can exercise them directly
against a real (test) database session -- never a subprocess, and this
script's own `main()`/`_open_connection()` (which target
`settings.database_url`, the real deployment database) are never invoked
by the test suite.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

import app.main  # noqa: E402,F401  forces full model registration before any ORM use
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.settings import settings  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import platform_admin_service, user_service  # noqa: E402


def _fail(message: str) -> None:
    print(f"\nFATAL: {message}", file=sys.stderr)
    raise SystemExit(1)


def _resolve_user(db: Session, *, oidc_issuer: str, oidc_subject: str) -> User:
    user = user_service.get_user_by_issuer_subject(db, oidc_issuer=oidc_issuer, oidc_subject=oidc_subject)
    if user is None:
        _fail(
            f"no CMP User exists for issuer={oidc_issuer!r} subject={oidc_subject!r}. "
            "An existing CMP User is a prerequisite for a platform-admin grant/revoke -- "
            "this script never creates a User."
        )
    return user


def _resolve_optional_actor(
    db: Session, *, oidc_issuer: str | None, oidc_subject: str | None, flag_label: str
) -> User | None:
    if oidc_issuer is None and oidc_subject is None:
        return None
    if oidc_issuer is None or oidc_subject is None:
        _fail(f"--{flag_label}-oidc-issuer and --{flag_label}-oidc-subject must both be supplied, or neither.")
    user = user_service.get_user_by_issuer_subject(db, oidc_issuer=oidc_issuer, oidc_subject=oidc_subject)
    if user is None:
        _fail(f"no CMP User exists for the --{flag_label}-* identity supplied.")
    return user


def cmd_grant(
    db: Session,
    *,
    oidc_issuer: str,
    oidc_subject: str,
    reason: str | None,
    granted_by_oidc_issuer: str | None,
    granted_by_oidc_subject: str | None,
) -> int:
    target = _resolve_user(db, oidc_issuer=oidc_issuer, oidc_subject=oidc_subject)
    granter = _resolve_optional_actor(
        db, oidc_issuer=granted_by_oidc_issuer, oidc_subject=granted_by_oidc_subject, flag_label="granted-by"
    )
    already_active = platform_admin_service.is_platform_admin(db, user_id=target.id)
    grant = platform_admin_service.grant_platform_admin(
        db, user_id=target.id, granted_by_user_id=granter.id if granter else None, reason=reason
    )
    if already_active:
        print(f"{target.email} already holds active platform-admin authority (no-op) -- granted_at={grant.granted_at}")
    else:
        print(f"Granted platform-admin authority to {target.email} (platform_admin_id={grant.id}).")
    return 0


def cmd_revoke(
    db: Session,
    *,
    oidc_issuer: str,
    oidc_subject: str,
    revoked_by_oidc_issuer: str | None,
    revoked_by_oidc_subject: str | None,
) -> int:
    target = _resolve_user(db, oidc_issuer=oidc_issuer, oidc_subject=oidc_subject)
    revoker = _resolve_optional_actor(
        db, oidc_issuer=revoked_by_oidc_issuer, oidc_subject=revoked_by_oidc_subject, flag_label="revoked-by"
    )
    revoked = platform_admin_service.revoke_platform_admin(
        db, user_id=target.id, revoked_by_user_id=revoker.id if revoker else None
    )
    if revoked is None:
        print(f"{target.email} has no active platform-admin authority (no-op).")
    else:
        print(f"Revoked platform-admin authority from {target.email} (platform_admin_id={revoked.id}).")
    return 0


def _database_name(url: str) -> str:
    # Postgres URLs (psycopg dialect) always end in /<dbname>[?params] --
    # this never opens a connection, purely string parsing for the guard
    # below.
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


def _open_connection():
    """Opens a real connection against `settings.database_url` (the actual
    deployment database) -- never invoked by tests, which instead call
    `cmd_grant`/`cmd_revoke` directly with the shared `db_session` test
    fixture. Refuses to run against `cmp_test` by the same identity check
    `scripts/bootstrap_pilot_master_data.py` already established, so a
    misconfigured DATABASE_URL can never silently grant platform authority
    inside the automated test database."""
    engine = create_engine(settings.database_url)
    with engine.connect() as check_conn:
        current_db = check_conn.execute(text("SELECT current_database()")).scalar_one()
    test_db_name = _database_name(settings.test_database_url) if settings.test_database_url else None
    if test_db_name and current_db == test_db_name:
        engine.dispose()
        _fail(
            f"refusing to run against {current_db!r} -- that is this repository's automated-test database. "
            "Point DATABASE_URL at the real target environment's database instead."
        )
    print(f"current_database(): {current_db}")
    return engine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    grant_parser = subparsers.add_parser("grant", help="grant platform-admin authority to an existing CMP User")
    grant_parser.add_argument("--oidc-issuer", required=True)
    grant_parser.add_argument("--oidc-subject", required=True)
    grant_parser.add_argument("--reason", default=None)
    grant_parser.add_argument("--granted-by-oidc-issuer", default=None)
    grant_parser.add_argument("--granted-by-oidc-subject", default=None)

    revoke_parser = subparsers.add_parser("revoke", help="revoke platform-admin authority from a CMP User")
    revoke_parser.add_argument("--oidc-issuer", required=True)
    revoke_parser.add_argument("--oidc-subject", required=True)
    revoke_parser.add_argument("--revoked-by-oidc-issuer", default=None)
    revoke_parser.add_argument("--revoked-by-oidc-subject", default=None)

    args = parser.parse_args()

    engine = _open_connection()
    db = Session(bind=engine)
    try:
        if args.command == "grant":
            return cmd_grant(
                db,
                oidc_issuer=args.oidc_issuer,
                oidc_subject=args.oidc_subject,
                reason=args.reason,
                granted_by_oidc_issuer=args.granted_by_oidc_issuer,
                granted_by_oidc_subject=args.granted_by_oidc_subject,
            )
        return cmd_revoke(
            db,
            oidc_issuer=args.oidc_issuer,
            oidc_subject=args.oidc_subject,
            revoked_by_oidc_issuer=args.revoked_by_oidc_issuer,
            revoked_by_oidc_subject=args.revoked_by_oidc_subject,
        )
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
