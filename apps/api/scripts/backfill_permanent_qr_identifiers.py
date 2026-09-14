"""PILOT-SCAN-001D: one-time (safe-to-rerun) backfill ensuring every
existing Location, Carrier, and Asset has exactly one active permanent
`QrIdentifier`, for master data created before automatic creation-time QR
provisioning existed (`app.services.qr_provisioning.
ensure_qr_identifier_for_new_entity`, wired into every current Location/
Carrier/Asset creation path). Never touches Batch/lot/placement identities.

    python scripts/backfill_permanent_qr_identifiers.py [--tenant-id UUID] [--dry-run] [--yes]

Idempotent: every entity already holding an active QR is skipped (the
same `qr_service.generate_or_get_qr_identifier` dedup check every other
caller relies on); rerunning after a partial/interrupted run, or after
new master data has since been created (which already gets its QR
automatically), only ever provisions what is still missing.

This script's own `main()`/`_open_connection()` target
`settings.database_url` (the real deployment database, with the same
cmp_test-refusal guard `scripts/manage_platform_admin.py` already
established) and are never invoked by the test suite, which instead
calls `qr_service.backfill_missing_permanent_qr_identifiers` directly
against the shared `db_session`/`committed_connection` test fixtures. All
domain logic (which entities are missing a QR, idempotent provisioning,
per-entity fault isolation) lives in that one service function -- this
file owns only argument parsing, the database connection, the
confirmation prompt, and human-readable output.

DEPLOYMENT: this script is not run automatically by Claude against any
real/production database. Running it against a real deployment's
database is a manual operator action, exactly like
`scripts/manage_platform_admin.py`.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

import app.main  # noqa: E402,F401  forces full model registration before any ORM use
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.settings import settings  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import qr_service  # noqa: E402


def _fail(message: str) -> None:
    print(f"\nFATAL: {message}", file=sys.stderr)
    raise SystemExit(1)


def _database_name(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


def _open_connection():
    """Mirrors `scripts/manage_platform_admin.py::_open_connection` exactly:
    refuses to run against `cmp_test` (this repository's automated-test
    database) even if `DATABASE_URL` is misconfigured to point at it."""
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
    parser.add_argument("--tenant-id", default=None, help="Scope the backfill to one tenant (default: every tenant).")
    parser.add_argument(
        "--actor-user-id", required=True,
        help="An existing CMP User id to record as created_by_user_id on every newly provisioned QrIdentifier "
        "(QrIdentifier.created_by_user_id is NOT NULL -- a real actor is required, exactly as an interactive "
        "'Generate QR' click already requires one).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be provisioned without writing anything (rolls back before exiting).",
    )
    parser.add_argument("--yes", action="store_true", help="Skip the interactive confirmation prompt.")
    args = parser.parse_args()

    try:
        tenant_id = uuid.UUID(args.tenant_id) if args.tenant_id else None
    except ValueError:
        _fail(f"--tenant-id is not a valid UUID: {args.tenant_id!r}")
    try:
        actor_user_id = uuid.UUID(args.actor_user_id)
    except ValueError:
        _fail(f"--actor-user-id is not a valid UUID: {args.actor_user_id!r}")

    engine = _open_connection()
    with Session(engine) as db:
        if db.get(User, actor_user_id) is None:
            _fail(f"no CMP User exists with id {actor_user_id} -- refusing to invent an actor.")

        print(f"\nScope           : {'tenant ' + str(tenant_id) if tenant_id else 'ALL tenants'}")
        print(f"Actor user id   : {actor_user_id}")
        print(f"Mode            : {'DRY RUN (no changes will be written)' if args.dry_run else 'LIVE'}")
        if not args.dry_run and not args.yes:
            answer = input("\nType 'backfill' to continue, anything else to abort: ").strip()
            if answer != "backfill":
                _fail("confirmation not received -- aborting without making any change.")

        result = qr_service.backfill_missing_permanent_qr_identifiers(
            db, actor_user_id=actor_user_id, tenant_id=tenant_id, dry_run=args.dry_run,
        )
        # LIVE mode: every provisioned entity already committed its own
        # transaction inside the service call above. DRY RUN mode: the
        # service call above never writes anything at all -- nothing to
        # roll back here either way.

    label = "would_provision" if args.dry_run else "provisioned"
    print("\nBackfill result:")
    for entity_type in ("location", "carrier", "asset"):
        print(
            f"  {entity_type:8s}: {label}={result['provisioned'][entity_type]:5d}  "
            f"already_had_qr={result['already_had_qr'][entity_type]:5d}"
        )
    if result["errors"]:
        print(f"\n{len(result['errors'])} entities could NOT be provisioned:")
        for entity_type, entity_id, message in result["errors"]:
            print(f"  {entity_type} {entity_id}: {message}")
        return 1
    print("\nNo errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
