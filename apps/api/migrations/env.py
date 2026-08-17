import importlib.util
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from alembic.script import ScriptDirectory
from alembic.script.revision import RangeNotAncestorError
from sqlalchemy import engine_from_config, pool, text

import app.models  # noqa: F401  (registers models on Base.metadata)
from app.core.db import Base
from app.core.settings import settings

config = context.config

# Fixed module name shared with tests/test_alembic_url_safety.py's own
# loader: registering in sys.modules under this exact name means both
# loaders converge on the same module object (and therefore the same
# AlembicUrlNotConfiguredError class identity), whichever side loads it
# first — otherwise two independent importlib loads of the same file
# produce two structurally-identical but distinct classes, and a test's
# `pytest.raises(AlembicUrlNotConfiguredError)` would never match an
# instance raised from this file's own separately-loaded copy.
_ALEMBIC_URL_SAFETY_MODULE_NAME = "cmp_alembic_url_safety"


def _load_alembic_url_safety():
    if _ALEMBIC_URL_SAFETY_MODULE_NAME in sys.modules:
        return sys.modules[_ALEMBIC_URL_SAFETY_MODULE_NAME]
    path = Path(__file__).resolve().parent / "_alembic_url_safety.py"
    spec = importlib.util.spec_from_file_location(_ALEMBIC_URL_SAFETY_MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_ALEMBIC_URL_SAFETY_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


# ALEMBIC-SAFETY-001 (see INCIDENT-001): fail closed. No fallback to
# settings.database_url or any other default — a bare `alembic
# upgrade`/`downgrade`/`current` invocation with no explicit sqlalchemy.url
# must fail here, before fileConfig, before target_metadata is even bound,
# and long before run_migrations_online()'s own engine_from_config(...)
# call below ever executes. It must never silently target any real
# database, development or otherwise.
_load_alembic_url_safety().resolve_explicit_alembic_url(config)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# --- CMP-016A: produce-lot ledger downgrade-guard hardening -----------------
#
# de82132ef837 (CMP-014) is never edited. Its own downgrade() only checks
# for missing/mismatched harvest receipts; it has no check for orphaned or
# duplicated ones. A migration-file-only fix cannot protect a *staged*
# downgrade (head -> CMP-016/CMP-015 in one command, then a later, separate
# command all the way past CMP-014): once the CMP-016A marker revision has
# already been downgraded away in the first command, its own downgrade()
# cannot run again in the second. This guard instead runs unconditionally,
# from env.py, on every Alembic invocation, before context.run_migrations()
# — regardless of which revisions currently exist in the database's
# history. It uses `on_version_apply`-style reasoning is deliberately NOT
# used: that callback fires only *after* a step's own operations have
# already executed, which is too late once de82132ef837.downgrade() has
# already dropped the table.
def _load_produce_lot_ledger_validation():
    path = Path(__file__).resolve().parent / "_produce_lot_ledger_validation.py"
    spec = importlib.util.spec_from_file_location("cmp_produce_lot_ledger_validation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _crossing_revisions(script: ScriptDirectory, upper, lower):
    """Ordered revisions that would be downgraded walking upper -> lower,
    using the Alembic revision graph (never a string/lexical comparison).
    Returns None if `lower` is not reachable by walking down from `upper`
    (an upgrade, an unrelated target, or a no-op some other way)."""
    if upper == lower:
        return []
    try:
        return [s.revision for s in script.iterate_revisions(upper, lower)]
    except RangeNotAncestorError:
        return None


def _guard_produce_lot_ledger_downgrade_online(connection, script: ScriptDirectory) -> None:
    try:
        destination = context.get_revision_argument()
    except Exception:
        # No destination is set for this command (e.g. `alembic current`/
        # `history`, which also execute this env.py but request no
        # migration step) -- nothing to guard.
        return

    plv = _load_produce_lot_ledger_validation()
    mc_heads = context.get_context().get_current_heads()
    script_heads = script.get_heads()

    if len(mc_heads) != 1 or len(script_heads) != 1:
        # Ambiguous lineage: only refuse outright when there is something
        # to protect and this looks like a genuine downgrade request.
        # Unrelated commands (upgrades, revision generation, multi-branch
        # operations unrelated to this lineage) must not be broken by a
        # rarely-exercised multi-head state.
        if destination is not None and plv.table_exists(connection):
            raise RuntimeError(
                "Refusing to evaluate the produce-lot ledger downgrade guard against an "
                "ambiguous Alembic head state (multiple current or script heads). Resolve "
                "to a single head before downgrading."
            )
        return

    path = _crossing_revisions(script, mc_heads[0], destination)
    if path is None or plv.PRODUCE_LOT_LEDGER_REVISION not in path:
        return  # not a downgrade, or one that stays at/above CMP-014

    # Without a lock, another transaction could insert/mutate harvest,
    # produce-lot, or ledger rows after validation reads them but before
    # de82132ef837.downgrade() drops the table. Close that window: lock
    # all three tables this guard (and de82132ef837's own downgrade) reads
    # from, in one deterministic order, before validating, and hold them
    # through context.run_migrations() — both are inside the same
    # transaction opened by run_migrations_online()'s own
    # `with context.begin_transaction():`, so the locks are released
    # exactly once, at that transaction's own commit or rollback.
    existing = {t: plv.table_exists(connection, t) for t in plv.GUARDED_TABLES}
    if not any(existing.values()):
        return  # nothing to protect at all
    if not all(existing.values()):
        missing = [t for t, ok in existing.items() if not ok]
        raise RuntimeError(
            "Cannot safely evaluate the produce-lot ledger downgrade guard: expected table(s) "
            f"{missing} do not exist while at least one sibling table does. This is an "
            "inconsistent schema state; refusing to proceed rather than silently treat it as valid."
        )

    connection.execute(text("SET LOCAL lock_timeout = '5s'"))
    for table_name in plv.GUARDED_TABLES:  # deterministic (alphabetical) order, always
        connection.execute(text(f"LOCK TABLE {table_name} IN ACCESS EXCLUSIVE MODE"))

    violations = plv.run_crossing_validation(connection)
    if violations:
        raise RuntimeError(
            "Cannot downgrade past CMP-014: produce_lot_ledger_entries history is not "
            f"exactly reconstructible ({', '.join(violations)}). Downgrading would silently "
            "discard or misrepresent ledger history. Do not downgrade."
        )


def _guard_produce_lot_ledger_downgrade_offline(script: ScriptDirectory) -> None:
    try:
        destination = context.get_revision_argument()
        starting = context.get_starting_revision_argument()
    except Exception:
        return
    if starting is None or destination is None:
        return
    path = _crossing_revisions(script, starting, destination)
    if path is None:
        return
    plv = _load_produce_lot_ledger_validation()
    if plv.PRODUCE_LOT_LEDGER_REVISION in path:
        raise RuntimeError(
            "Cannot generate offline downgrade SQL past CMP-014: this path cannot be "
            "validated without a live database connection. Perform this downgrade online."
        )


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    script = ScriptDirectory.from_config(config)
    with context.begin_transaction():
        _guard_produce_lot_ledger_downgrade_offline(script)
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        script = ScriptDirectory.from_config(config)
        with context.begin_transaction():
            _guard_produce_lot_ledger_downgrade_online(connection, script)
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
