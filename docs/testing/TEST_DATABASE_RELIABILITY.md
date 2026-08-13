# Test Database Reliability

Developer/test-infrastructure documentation only — not a product or domain document. Covers `cmp_test` specifically: how the backend test suite uses it destructively, what guarantees the suite now provides after **TEST-001**, and what to do when those guarantees aren't enough.

## `cmp_test` is destructive-test-only

`cmp_test` (via `TEST_DATABASE_URL`) is the only database the backend test suite is ever allowed to mutate destructively — including real Alembic `downgrade`/`upgrade` DDL cycles and real committed rows written outside the per-test savepoint. `cmp` (via `DATABASE_URL`, the development database) must **never** be targeted by any test, fixture, or script. This is enforced in two independent, redundant places:

- `conftest.py`'s `_require_test_database_url()` asserts `TEST_DATABASE_URL != DATABASE_URL` at session start — a configuration-level guard.
- `conftest.py`'s `assert_cmp_test_database(engine)` — used by `apply_test_migrations`, `alembic_head_restore`, and `scripts/reset_test_database.py` — positively verifies the *actual connected database's identity* via `SELECT current_database()` before any destructive operation. This is a connection-identity check, not a configuration check: it catches a stale/misrouted connection that a URL-string comparison alone would miss. It refuses to proceed against anything other than exactly `cmp_test`.

## Migration tests restore dynamic head

Some tests run genuine Alembic `command.downgrade` against `cmp_test` (mostly `test_migrations.py` and the `test_*_downgrade_guard.py` files) to prove a migration's downgrade path and its data-safety guards behave correctly. Before **TEST-001**, several of these did not guarantee `command.upgrade(cfg, "head")` ran if an assertion or guard exception fired between the downgrade and the intended re-upgrade — a single failed test could leave `cmp_test` downgraded (or, worse, at a revision a later test's own downgrade-target assumption didn't expect) for the rest of that pytest session. This is the exact mechanism that produced 25 unrelated-looking failures during AUTHZ-001B2 verification; it was confirmed reproducible by stashing all AUTHZ-001B2 changes back to a clean baseline commit and observing the identical 25 failures recur.

**The fix**: every test that calls `command.downgrade` against `cmp_test` now also depends on the `alembic_head_restore` fixture (`conftest.py`). Its teardown — which pytest runs unconditionally after the test, whether it passed, failed an assertion, or raised unexpectedly — always re-upgrades `cmp_test` to the *dynamically resolved* Alembic head (`resolve_dynamic_alembic_head()`, via `ScriptDirectory.from_config(cfg).get_current_head()` — never a hardcoded revision string) and verifies `alembic_version` matches it. Because this runs during fixture teardown rather than depending on the test body's own `try/finally` placement, it also covers the specific gap several pre-existing tests had: a bare `command.downgrade(...)` call with no wrapping `try` at all, where the downgrade itself failing (not just an assertion after it) could skip cleanup entirely.

This does **not** convert a failing migration test into a passing one. The fixture never catches or swallows anything the test itself raises — restoration is teardown, not error handling. If restoration itself also fails, that is raised separately during teardown and pytest reports it alongside (never instead of) the original test failure. See `test_migration_test_isolation.py` for the regression proofs.

`apply_test_migrations` (session-scoped, autouse) already brings `cmp_test` to head unconditionally at the start of every test session, which for free resolves the common case of a prior session leaving `cmp_test` merely downgraded to an older-but-structurally-valid revision — `alembic upgrade head` just applies whatever's missing. TEST-001 added one thing to this: an explicit post-upgrade verification (`alembic_version == dynamically resolved head`) that fails loudly with a clear, actionable message pointing at this document and the manual recovery script, rather than letting a still-wrong schema state surface later as a confusing, unrelated-looking test failure.

## How committed migration-test fixtures are cleaned

Downgrade-guard tests that need real committed data (so a downgrade guard's own PL/pgSQL check, running in a separate transaction, can see it) do not use the ordinary per-test `db_session` savepoint — they commit through `test_engine` directly, via shared scenario-builder helpers (`tests/_packing_scenario.py`, `tests/_dispatch_scenario.py`, `tests/_recall_scenario.py`, `tests/_storage_scenario.py`, `tests/_traceability_scenario.py`, or a file-local `_cleanup_scenario`/`_cleanup_ledger_migration_scenario` helper in a handful of files). Every one of these already deletes everything it committed, scoped to its own randomly-generated `tenant_id`, from a `finally` block — audited file-by-file as part of TEST-001; no file was found committing scenario data with *no* cleanup attempt at all. `alembic_head_restore` does not replace this — it only guarantees the *schema* ends at head; each test's own scenario helper remains responsible for its own row-level cleanup, which is already the establish pattern and was not the confirmed root cause of the AUTHZ-001B2 incident (a schema-revision mismatch was).

A few tests have a small, pre-existing, low-probability gap: a handful of lines between committing scenario data and that same test's own `try:` block starting are not covered by that test's cleanup `finally`. This was true before TEST-001 and is unchanged by it — closing it would mean restructuring already-working, already-reviewed test bodies for a class of failure (an exception in a few lines of pure setup/teardown-adjacent code with no meaningful side effects) that has never been observed in practice, which is not a proportionate fix. If this ever needs closing, prefer moving the `try:` to wrap the scenario-creation call itself, file by file, over any generic new abstraction.

## Limitation: hard process termination

`alembic_head_restore`'s fixture teardown, and every `try/finally` in these tests, can only run if the pytest process is still running to run it. **None of this can help if the whole process is killed** — a crash, `Ctrl+C` at the wrong instant, or the machine sleeping mid-DDL. In that case `cmp_test` can be left in a genuinely inconsistent, partially-applied schema state that is not simply "at an older revision" — `apply_test_migrations`'s ordinary `alembic upgrade head` call at the next session's start cannot safely repair that class of corruption, and does not attempt to; it fails loudly instead (see above) rather than silently limping forward on a schema it can't positively verify.

This is a deliberate choice, not an oversight: automatically attempting to recover from an arbitrary partially-mutated schema would risk silently masking real corruption as a normal test run. Fail-fast plus a manual, explicit recovery step is safer than a "clever" automatic repair that can't actually verify what state it's recovering from.

## Manual recovery procedure

If a test session reports `apply_test_migrations` failing its post-upgrade verification (or any other symptom suggesting `cmp_test`'s schema is inconsistent — e.g. a downgrade-guard test firing an unexpected guard message, or a wave of unrelated-looking failures reminiscent of the AUTHZ-001B2 incident):

```
cd apps/api
python scripts/reset_test_database.py
```

This positively verifies the target is exactly `cmp_test` (by database identity, not by trusting configuration), drops and recreates its `public` schema (destroying all data — this is only ever safe because `cmp_test` holds nothing but disposable test fixtures), then upgrades it to the dynamically-resolved Alembic head and verifies the result. It refuses to run against `cmp` or anything else, and prints clear, explicit output at every step. It is TEST-ONLY: never imported by production runtime (`app/*`).

`scripts/create_test_db.py` is a different, complementary tool — it only *creates* the `cmp_test` database if it doesn't exist yet (initial one-time setup on a fresh Postgres instance); it does not reset schema/data. Use `reset_test_database.py` for recovery, `create_test_db.py` only for first-time setup.
