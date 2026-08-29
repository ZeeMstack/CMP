"""PILOT-SETUP-001A: thin CLI over `app.services.pilot_bootstrap_service`.

    python scripts/bootstrap_pilot_master_data.py --config <path> --dry-run
    python scripts/bootstrap_pilot_master_data.py --config <path> --apply
    python scripts/bootstrap_pilot_master_data.py --config <path> --readiness

This file owns ONLY: argument parsing, YAML loading, the database
connection/transaction, and human-readable output. Every domain decision
(what to create, in what order, what counts as a conflict) lives in
`app.services.pilot_bootstrap_service`, which is unit-testable on its own
without this script.

Transaction handling mirrors `tests/conftest.py`'s own `db_session` fixture
exactly: a Session is bound to an explicit outer Connection transaction with
`join_transaction_mode="create_savepoint"`, so every internal `db.commit()`
the service layer performs only releases a SAVEPOINT -- the real outer
transaction is committed (APPLY, on success) or rolled back (DRY RUN,
always; APPLY, on any failure) by this script alone, once, at the very end.
--readiness never opens a transaction with intent to write at all, but is
still wrapped the same way defensively (and always rolled back) since it
calls no mutating service.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

import app.main  # noqa: E402,F401  forces full model registration before any ORM use
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.settings import settings  # noqa: E402
from app.services.pilot_bootstrap_service import (  # noqa: E402
    PilotBootstrapAbortedError,
    PilotConfig,
    PilotTargetNotResolvedError,
    find_placeholders,
    run_bootstrap,
    run_readiness_check,
)
from pydantic import ValidationError  # noqa: E402


def _fail(message: str) -> None:
    print(f"\nFATAL: {message}", file=sys.stderr)
    raise SystemExit(1)


def _load_config(path: Path) -> PilotConfig:
    if not path.exists():
        _fail(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    try:
        return PilotConfig.model_validate(raw)
    except ValidationError as exc:
        _fail(f"config file failed validation:\n{exc}")


def _database_name(url: str) -> str:
    # Postgres URLs (psycopg dialect) always end in /<dbname>[?params] --
    # this never opens a connection, purely string parsing for the guard
    # below.
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


def _open_connection():
    engine = create_engine(settings.database_url)

    # The database-identity check runs on its OWN connection, opened and
    # closed here -- a Core Connection auto-begins an implicit transaction
    # on first `execute()`, so reusing this same connection for the caller's
    # own explicit `conn.begin()` below would raise InvalidRequestError.
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

    conn = engine.connect()
    return engine, conn


def _print_steps(steps) -> None:
    if not steps:
        print("  (no master-data steps were attempted)")
        return
    width = max(len(f"{s.kind}:{s.code}") for s in steps)
    for s in steps:
        label = f"{s.kind}:{s.code}".ljust(width)
        line = f"  [{s.status:<9}] {label}"
        if s.detail:
            line += f"  -- {s.detail}"
        print(line)


def cmd_dry_run_or_apply(config_path: Path, *, apply: bool) -> int:
    config = _load_config(config_path)
    placeholders = find_placeholders(config)

    if apply and placeholders:
        print("FATAL: config still contains template placeholders -- refusing to --apply:", file=sys.stderr)
        for p in placeholders:
            print(f"  - {p}", file=sys.stderr)
        return 1

    engine, conn = _open_connection()
    outer_trans = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        try:
            result = run_bootstrap(db, config=config, dry_run=not apply)
        except PilotTargetNotResolvedError as exc:
            outer_trans.rollback()
            print(f"\nFATAL: target could not be resolved -- {exc}", file=sys.stderr)
            return 1
        except PilotBootstrapAbortedError as exc:
            outer_trans.rollback()
            print(f"\n{'APPLY' if apply else 'DRY RUN'} aborted on first CONFLICT/BLOCKED step:")
            _print_steps(exc.result.steps)
            print(f"\nFATAL: {exc}", file=sys.stderr)
            print("Nothing was written -- the whole run was rolled back atomically.")
            return 1

        mode = "APPLY" if apply else "DRY RUN"
        print(f"\n{mode} summary (tenant_id={result.tenant_id}, farm_id={result.farm_id}):")
        _print_steps(result.steps)

        if result.placeholders:
            print(f"\n{len(result.placeholders)} unresolved template placeholder(s) (would block --apply):")
            for p in result.placeholders:
                print(f"  - {p}")

        print(
            f"\nOperational-table integrity check: "
            f"{'PASS -- 0 operational rows created by this run' if result.operational_integrity_ok else 'FAILED -- an operational table changed, this must never happen'}"
        )

        if apply:
            if not result.operational_integrity_ok:
                outer_trans.rollback()
                _fail("refusing to commit: an operational table changed during this run.")
            outer_trans.commit()
            print("\nCommitted.")
        else:
            outer_trans.rollback()
            print("\nDRY RUN -- nothing was written (transaction rolled back).")

        return 1 if (result.has_conflicts or result.has_blocked or (not apply and result.placeholders)) else 0
    finally:
        db.close()
        conn.close()
        engine.dispose()


def cmd_readiness(config_path: Path) -> int:
    config = _load_config(config_path)
    engine, conn = _open_connection()
    outer_trans = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        items = run_readiness_check(db, config=config)
    finally:
        outer_trans.rollback()  # readiness never writes; rolled back defensively regardless
        db.close()
        conn.close()
        engine.dispose()

    print("\nPilot readiness for the first legitimate Iceberg Sowing:")
    width = max(len(i.name) for i in items) if items else 0
    blocking = False
    for i in items:
        line = f"  [{i.status:<9}] {i.name.ljust(width)}"
        if i.detail:
            line += f"  -- {i.detail}"
        print(line)
        if i.status in ("MISSING", "CONFLICT") and not i.informational:
            blocking = True
    print("\nREADY" if not blocking else "\nNOT READY")
    return 1 if blocking else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, type=Path, help="path to a pilot config YAML file")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="validate and report; write nothing")
    mode.add_argument("--apply", action="store_true", help="create missing master/config data")
    mode.add_argument("--readiness", action="store_true", help="read-only check: is this environment Sowing-ready?")
    args = parser.parse_args()

    if args.readiness:
        return cmd_readiness(args.config)
    return cmd_dry_run_or_apply(args.config, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
