"""ALEMBIC-SAFETY-001 (see INCIDENT-001): fail-closed Alembic database URL
resolution.

A caller must always supply `sqlalchemy.url` explicitly before invoking an
online (or offline) Alembic migration -- there is no automatic fallback to
any application setting (`DATABASE_URL`, `TEST_DATABASE_URL`, or any other
default). `migrations/env.py` used to silently fall back to
`settings.database_url` (the development database `cmp`) whenever no URL
was configured, which is exactly the gap that made INCIDENT-001 possible:
a bare, unconfigured `python -m alembic upgrade/downgrade/current`
invocation silently targeted `cmp` instead of failing.

Every existing safe, automated path already sets `sqlalchemy.url`
explicitly before Alembic ever reaches this check --
`scripts/reset_test_database.py`'s `_migrations_cfg()` and
`tests/conftest.py`'s `migrations_alembic_config()` both call
`Config.set_main_option("sqlalchemy.url", ...)` directly -- so they are
unaffected by removing the fallback. Only a bare CLI invocation, which
never sets it, is newly rejected. This is the entire point.

Kept as a small, standalone module (not part of `env.py` itself, and not a
package-relative import, since `migrations/` is not imported as a normal
Python package) so it can be loaded and unit-tested directly without
triggering Alembic's own env.py machinery -- mirroring this same
directory's existing `_produce_lot_ledger_validation.py` convention
(loaded via `importlib.util.spec_from_file_location` from both `env.py`
and test files)."""

PLACEHOLDER_URL = "driver://user:pass@localhost/dbname"


class AlembicUrlNotConfiguredError(RuntimeError):
    """Raised when an Alembic `Config` reaches migration execution without
    an explicitly-supplied, real `sqlalchemy.url` -- see
    `resolve_explicit_alembic_url`."""


def resolve_explicit_alembic_url(config) -> str:
    """Returns the explicitly-configured `sqlalchemy.url` from `config`
    (an `alembic.config.Config`, or anything exposing the same
    `get_main_option(name)` interface).

    Raises `AlembicUrlNotConfiguredError` -- and returns nothing, mutates
    nothing -- if the URL is missing, blank, or still the stock
    `alembic.ini` placeholder. Never falls back to any default: the caller
    must always choose the target database explicitly."""
    url = config.get_main_option("sqlalchemy.url")
    if not url or not url.strip() or url == PLACEHOLDER_URL:
        raise AlembicUrlNotConfiguredError(
            "Alembic database URL must be supplied explicitly; refusing to select a "
            "database automatically. Construct a Config with sqlalchemy.url set explicitly "
            "(see scripts/reset_test_database.py or "
            "tests/conftest.py:migrations_alembic_config) -- never run bare "
            "`alembic upgrade`/`downgrade`/`current` without one."
        )
    return url
