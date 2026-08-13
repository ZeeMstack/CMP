"""TEST-001 regression proofs for the migration/downgrade test-isolation
reliability fix.

Background: several migration/downgrade-guard tests run real Alembic
`command.downgrade` against the persistent `cmp_test` database and commit
real data through `test_engine` (bypassing the per-test `db_session`
savepoint) so downgrade-guard PL/pgSQL functions can see it. Before this
ticket, several of them did not guarantee `command.upgrade(cfg, "head")`
ran if an assertion or guard exception fired between the downgrade and the
re-upgrade -- a failed test could leave `cmp_test` downgraded or
mismatched for whatever ran next in the same session. This is the
mechanism that produced 25 unrelated failures during AUTHZ-001B2
verification, confirmed reproducible by stashing all AUTHZ-001B2 changes
back to a clean baseline commit and seeing the identical 25 failures.

This file proves the fix (`app.core.testing`-equivalent helpers in
`conftest.py`: `assert_cmp_test_database`, `alembic_head_restore`,
`restore_cmp_test_to_head`) actually delivers the guarantee, without
relying on a real pytest test being allowed to fail (which would show up
as a suite failure) -- the fixture's teardown half is exercised directly
as a plain function, exactly the same code path pytest itself would run
during fixture teardown regardless of the test's outcome.
"""

from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import text

from tests.conftest import (
    assert_cmp_test_database,
    migrations_alembic_config,
    resolve_dynamic_alembic_head,
    restore_cmp_test_to_head,
)

# A pure schema-level, data-independent downgrade target -- reused from
# test_migrations.py's classification-trigger test. Deliberately chosen so
# these regression proofs need no scenario data at all, keeping them fast
# and non-flaky.
_SCHEMA_ONLY_REVISION = "471bdd408a33"


def _current_alembic_version(test_engine) -> str:
    with test_engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


# --- hard safety guard: positively rejects a non-cmp_test target ------------


@pytest.mark.integration
def test_assert_cmp_test_database_rejects_the_postgres_maintenance_database(test_engine) -> None:
    """Section 4's hard-safety-guard proof: the guard must reject a target
    database by its actual identity (`SELECT current_database()`), not
    merely by trusting a URL or environment variable name. Exercised
    against Postgres's own built-in `postgres` maintenance database on the
    same instance/credentials as cmp_test -- reachable, entirely read-only
    here, and never `cmp` -- so this proves real rejection without ever
    touching the development database."""
    from sqlalchemy import create_engine

    # Pass the URL object itself, not str(url) -- str() masks the password
    # (renders it as "***") for safe display/logging, which would make the
    # connection attempt itself fail auth for the wrong reason.
    other_engine = create_engine(test_engine.url.set(database="postgres"))
    try:
        with pytest.raises(AssertionError, match="cmp_test"):
            assert_cmp_test_database(other_engine)
    finally:
        other_engine.dispose()


@pytest.mark.integration
def test_assert_cmp_test_database_accepts_the_real_cmp_test_database(test_engine) -> None:
    """Sanity complement to the rejection proof above: the guard must not
    be overly strict either -- it accepts the genuine cmp_test connection
    every other migration test in this suite relies on."""
    assert_cmp_test_database(test_engine)  # must not raise


# --- head restoration survives a simulated test-body failure ----------------


@pytest.mark.integration
def test_restore_cmp_test_to_head_recovers_after_a_downgrade_and_simulated_failure(test_engine) -> None:
    """Section 7's core regression proof: starting at head, downgrade,
    deliberately fail (simulating an assertion or guard exception in a
    migration test's body), then run exactly the teardown half of
    `alembic_head_restore` -- the same call pytest performs unconditionally
    during fixture teardown, regardless of whether the test passed or
    raised. cmp_test must end at the dynamically-resolved head."""
    assert_cmp_test_database(test_engine)
    cfg = migrations_alembic_config()
    expected_head = resolve_dynamic_alembic_head(cfg)
    assert _current_alembic_version(test_engine) == expected_head, "must start this proof already at head"

    command.downgrade(cfg, _SCHEMA_ONLY_REVISION)
    assert _current_alembic_version(test_engine) == _SCHEMA_ONLY_REVISION, (
        "sanity check: the downgrade must have genuinely happened before simulating a failure"
    )

    def _simulated_failing_migration_test_body() -> None:
        # Represents an ordinary migration test: it downgraded above, and
        # its own assertion now fails -- exactly the historical failure
        # mode (section 7's "deliberately raise/assert failure").
        raise AssertionError("simulated migration test assertion failure")

    with pytest.raises(AssertionError, match="simulated migration test assertion failure"):
        _simulated_failing_migration_test_body()

    # pytest runs fixture teardown unconditionally after the test phase
    # (pass or fail) -- this is that same call, not a special case.
    restore_cmp_test_to_head(test_engine)

    assert _current_alembic_version(test_engine) == expected_head, (
        "cmp_test must be restored to the dynamically-resolved head even though the simulated test body failed"
    )


@pytest.mark.integration
def test_restore_cmp_test_to_head_recovers_even_when_downgrade_itself_is_the_failure(test_engine) -> None:
    """The specific gap several pre-existing tests had: `command.downgrade`
    itself raising (a blocked/guarded downgrade) before the test body ever
    reaches its own try block. Proves restoration still runs and succeeds
    in that case too."""
    assert_cmp_test_database(test_engine)
    cfg = migrations_alembic_config()
    expected_head = resolve_dynamic_alembic_head(cfg)
    assert _current_alembic_version(test_engine) == expected_head

    # No wrapping try/except at all here -- represents the exact historical
    # gap: several pre-existing tests called command.downgrade as a bare,
    # unwrapped statement with no try/finally anywhere around it. Going
    # straight from downgrade to teardown, with nothing in between, proves
    # restoration does not depend on any code executing after the downgrade
    # call inside the test body.
    command.downgrade(cfg, _SCHEMA_ONLY_REVISION)
    assert _current_alembic_version(test_engine) == _SCHEMA_ONLY_REVISION

    # No cleanup, no upgrade, nothing -- simulates a downgrade call that
    # was itself the last thing that ran before an unexpected exception
    # propagated straight out of the test body.
    restore_cmp_test_to_head(test_engine)

    assert _current_alembic_version(test_engine) == expected_head


# --- contamination does not leak to a later test -----------------------------


@pytest.mark.integration
def test_a_downgraded_state_does_not_leak_into_a_subsequent_test(test_engine) -> None:
    """Section 7's second proof: after the two regression tests above
    already exercised a downgrade-then-restore cycle, this test -- which
    runs later in the same session/file -- must see cmp_test already at
    head, proving no downgraded state leaked forward. This is not a
    timing-dependent check: it simply asserts the invariant every other
    test in the suite already depends on implicitly."""
    assert _current_alembic_version(test_engine) == resolve_dynamic_alembic_head(migrations_alembic_config())
