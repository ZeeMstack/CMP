"""Idempotently creates the TEST_DATABASE_URL database (e.g. cmp_test) inside
the same PostgreSQL instance as DATABASE_URL. Safe to rerun.

Usage (from apps/api, with the venv active):
    python scripts/create_test_db.py
"""

import sys

import psycopg
from sqlalchemy.engine import make_url

from app.core.settings import settings


def main() -> None:
    if not settings.test_database_url:
        print("TEST_DATABASE_URL is not set.", file=sys.stderr)
        raise SystemExit(1)

    admin_url = make_url(settings.database_url)
    target_db = make_url(settings.test_database_url).database

    conn = psycopg.connect(
        host=admin_url.host,
        port=admin_url.port,
        user=admin_url.username,
        password=admin_url.password,
        dbname=admin_url.database,
        autocommit=True,
    )
    try:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (target_db,)
        ).fetchone()
        if exists:
            print(f"Database {target_db!r} already exists — nothing to do.")
            return
        conn.execute(f'CREATE DATABASE "{target_db}"')
        print(f"Created database {target_db!r}.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
