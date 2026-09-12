# Pilot Release Gate

**PILOT-BLOCKER-006 (F09 release assurance).** The one canonical checklist/
command sequence for a pilot release verification. This is a deliberate
pre-pilot/release operation — run before cutting a release or deploying —
**not** the everyday per-ticket development test loop. Do not run this on
every commit, and do not run the full backend suite or the full Playwright
suite as a substitute for it; that is explicitly out of scope for this gate
(see "What this gate is not," below).

Every command below targets `cmp_test` (backend) or the local repo
(frontend) — never the development or production database directly. Backend
migration/database commands must always go through the approved tooling
(`tests/conftest.py`'s `migrations_alembic_config()`/fixtures or
`scripts/reset_test_database.py`) — never a bare `alembic` invocation (see
root `CLAUDE.md`, "Development Database Safety").

## What this gate is not

- Not a replacement for focused tests during normal ticket work.
- Not a mandate to run the full ~2,000+ backend test suite or the full
  Playwright E2E suite on every release — the targeted groups below are
  the ones that have historically caught real pilot-blocking regressions
  (authorization/policy drift, inventory/quality reconciliation, migration
  fixture rot). Broaden it only when a specific release has a reason to
  (e.g. a change that touches an area with no targeted group below).
- Not a CI pipeline. There is no CI in this repository today; this
  document is the canonical procedure until CI automation is separately
  scoped and approved.

## Backend

Run from `apps/api`, with `cmp_test` reachable and `TEST_DATABASE_URL` set
(see `.env.example`). If `cmp_test` is in a known-bad state (a prior
interrupted migration test, a stale row blocking a downgrade guard), reset
it first with the approved recovery script — never by hand:

```
python scripts/reset_test_database.py
```

**Targeted security/policy tests** — authorization catalog, role-policy
pin, and the structural mutation/read-enforcement architecture proofs:

```
pytest tests/test_permissions.py \
       tests/test_authz_architecture.py \
       tests/test_authz_mutation_enforcement_architecture.py \
       tests/test_authz_read_enforcement_architecture.py \
       tests/test_authz_farm_proof.py \
       tests/test_inventory_storage_tenant_isolation.py \
       -q
```

**Targeted inventory integrity tests** — quantity reconciliation and
cohort/lot accounting (F02):

```
pytest tests/test_pilot_blocker_004_f02_inventory_accounting.py \
       tests/test_inventory_category_db_integrity.py \
       tests/test_inventory_item_db_integrity.py \
       -q
```

**Quality safety tests** — disposition/command recovery and hold
chronology (F04–F08):

```
pytest tests/test_pilot_blocker_005_f07_quality_chronology.py \
       tests/test_quality_hold.py \
       tests/test_quality_hold_stage_blocking.py \
       -q
```

**Migration head check** — confirms `cmp_test` reaches the single,
dynamically-resolved Alembic head cleanly, using only the existing
approved fixtures (never a bare `alembic` command):

```
pytest tests/test_migrations.py::test_alembic_script_graph_resolves_single_unambiguous_head \
       tests/test_migrations.py::test_migration_upgrade_head_matches_dynamically_resolved_alembic_head \
       -q
```

**Migration-focused tests** — the full downgrade/upgrade/backfill
round-trip proof suite (`test_migrations.py` and the per-feature
`*_downgrade_guard.py`/`*_migration.py` files). This is the slowest group
in this gate (a full downgrade/upgrade cycle per test) — run it for a
release, not per-ticket:

```
pytest tests/test_migrations.py -q
```

If a release specifically touched one feature's migration, the narrower,
single-file forms (`tests/test_<feature>_migration.py`,
`tests/test_<feature>_downgrade_guard.py`) are sufficient and much faster.

**Known exception**: do not run `tests/test_nursery_ops_downgrade_guard.py`
as a whole file — one of its tests
(`test_migration_downgrade_blocked_when_seeding_provenance_exists`)
self-deadlocks against `cmp_test` (see `docs/product/OPEN_QUESTIONS.md`,
"Migration graph decisions"). The rest of that file's tests are safe to
run individually by node ID.

## Frontend

Run from `apps/web`.

**Typecheck:**

```
npm run typecheck
```

**ESLint** — full project, or scope to touched files for a smaller change:

```
npm run lint
```

**Component/page tests (Vitest)** — unit/component/page tests only. Vitest
must never collect `e2e/*.spec.ts` (Playwright owns those — see
`vitest.config.ts`'s `include`/`exclude` and `playwright.config.ts`'s own
`testDir: "./e2e"`); confirm this stayed true if `vitest.config.ts` or the
`e2e/` directory structure changes:

```
npm test
```

**Playwright (E2E) — separate and explicit, never folded into `npm test`:**

```
npm run e2e
```

Playwright requires a built, running app (`playwright.config.ts`'s
`webServer` runs `next start` against a stubbed/bypassed auth
configuration for test purposes only — see that file's own comments). Run
it deliberately for a release, not as part of the fast day-to-day loop.

## Production

Deployment mechanics live in `docs/deployment/PILOT_DEPLOYMENT.md` and
`docs/deployment/RENDER_PILOT_DEPLOYMENT.md` — this section is only the
release-gate checklist of what to capture/confirm, in order:

1. **Merged main SHA recorded** — the exact commit deployed (`git rev-parse HEAD` on `main` after merge).
2. **API deploy** — new `cmp-api` image/revision live.
3. **`/health`** — liveness, no DB dependency (`app/api/health.py`); confirm `200`.
4. **`/ready`** — readiness, checks DB connectivity (`app/api/ready.py`); confirm `200` (a `503` here means investigate before declaring the release good, even if `/health` is green).
5. **Migration — only when this release actually includes one.** Run
   `scripts/migrate_database.py --backup-confirmed` (plus whatever
   `--expect-host`/`--expect-database`/TLS flags the target requires — see
   that script's own `--help` and `docs/deployment/PILOT_DEPLOYMENT.md`
   "Migration"). Never a bare `alembic` command against production. Skip
   this step entirely when the release has no migration.
6. **Web deploy** — only when the release includes a frontend change; confirm the `web` health check (`/login`, per `RENDER_PILOT_DEPLOYMENT.md`) is green.
7. **DB revision recorded** — the resulting `alembic_version` value, captured after step 5 (or reconfirmed unchanged if step 5 was skipped).
8. **Backup/restore evidence** — handled separately per `docs/deployment/PILOT_DEPLOYMENT.md` "Backup and recovery"; `--backup-confirmed` in step 5 is an operator acknowledgement, not itself a backup mechanism. Do not skip verifying a real recoverable snapshot exists before a migrating release.

## Result

A release is gate-clear when every Backend and Frontend command above
passes and every Production step is completed/recorded. Record known,
accepted exceptions (e.g. a pre-existing, separately-tracked failure
unrelated to the release) explicitly rather than silently — see
`docs/product/OPEN_QUESTIONS.md` for the place to log one.
