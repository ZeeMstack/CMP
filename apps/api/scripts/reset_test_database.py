"""Manually resets cmp_test to a known-good, empty-schema-then-head state.

TEST-ONLY. Never imported by production runtime (`app/*`). This is the
documented manual recovery procedure for the one failure class the test
suite's own automatic recovery (`alembic_head_restore` fixture,
`apply_test_migrations` session fixture) cannot cover: the whole pytest
process being killed (crash, Ctrl+C, machine sleep) mid-migration, which
can leave cmp_test with a genuinely corrupted/partially-applied schema —
not merely "downgraded to an older revision" (which `apply_test_migrations`
already self-heals for free on the next normal test run).

Positively verifies the target is exactly `cmp_test` by database identity
(`SELECT current_database()`), never by trusting TEST_DATABASE_URL's name
or the environment alone. Refuses to run against anything else, including
the development database `cmp`.

Usage (from apps/api, with the venv active):
    python scripts/reset_test_database.py
"""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.core.settings import settings

API_ROOT = Path(__file__).resolve().parent.parent


def _migrations_cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def main() -> None:
    if not settings.test_database_url:
        print("TEST_DATABASE_URL is not set.", file=sys.stderr)
        raise SystemExit(1)
    if settings.test_database_url == settings.database_url:
        print("TEST_DATABASE_URL must not equal DATABASE_URL -- refusing to proceed.", file=sys.stderr)
        raise SystemExit(1)

    engine = create_engine(settings.test_database_url)
    try:
        with engine.connect() as conn:
            current_db = conn.execute(text("SELECT current_database()")).scalar_one()
            if current_db != "cmp_test":
                print(
                    f"Refusing destructive reset: connected database is {current_db!r}, expected exactly "
                    "'cmp_test'. Nothing was changed.",
                    file=sys.stderr,
                )
                raise SystemExit(1)
            print(f"Verified target database: {current_db!r}. Proceeding with reset.")

            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.commit()
            print("cmp_test public schema dropped and recreated (blank).")

        cfg = _migrations_cfg()
        expected_head = ScriptDirectory.from_config(cfg).get_current_head()
        command.upgrade(cfg, "head")

        with engine.connect() as conn:
            current_db = conn.execute(text("SELECT current_database()")).scalar_one()
            current_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if current_db != "cmp_test" or current_rev != expected_head:
            print(
                f"Reset did not verify cleanly: database={current_db!r}, alembic_version={current_rev!r}, "
                f"expected head={expected_head!r}.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(f"cmp_test rebuilt and verified at Alembic head {current_rev!r}.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
