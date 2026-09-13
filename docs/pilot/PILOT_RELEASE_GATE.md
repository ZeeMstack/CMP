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

**Dev-auth hermeticity (PILOT-BLOCKER-008 CTO-review closure):** deployed
production always keeps `ENABLE_DEV_AUTH=false` — that is a security
invariant, never operator-configurable (`app/core/dev_auth.py::check_dev_
auth_startup_invariant`). The release-gate tests below are self-contained
and do not depend on ambient dev-auth enablement: `tests/test_authz_farm_
proof.py` (file-scoped autouse fixture) and `tests/test_quality_hold.py::
test_quality_hold_api_smoke` (its own opt-in fixture) each force `settings.
enable_dev_auth` on for exactly their own duration via `monkeypatch`,
mirroring the same technique `test_carrier_specification.py`'s own `_dev_
auth_enabled` fixture and `test_dev_auth.py`'s negative-case already use —
so both pass whether the ambient `.env` says `true` or `false`, confirmed
by running each explicitly under `ENABLE_DEV_AUTH=false`. `tests/test_
authz_read_enforcement_architecture.py`/`tests/test_authz_mutation_
enforcement_architecture.py` are independently hermetic the same way (B1),
building their own `create_app(Settings(enable_dev_auth=...))` instances
rather than depending on the ambient `app.main.app` singleton.

This does **not** claim the broader, pre-existing ~35-file ambient-
`ENABLE_DEV_AUTH` dependency (documented in-code in `test_carrier_
specification.py`'s own fixture comment) has been fixed — only these two
files plus the two architecture files are now proven hermetic. The
remaining ~35 files' non-hermetic dev-auth-header dependency on the
test-runner's ambient `.env` value remains a known, separately-tracked,
non-gate technical-debt item; a release-gate pass that happens to also
exercise one of THOSE files should still expect it to require `ENABLE_
DEV_AUTH=true` in the shell running `pytest` until that broader item is
addressed.

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

**Quality safety tests** — the full focused Quality contract, not
chronology/hold alone (PILOT-BLOCKER-008 B3 correction): ordinary/partial/
correction commands, HTTP behavior, command idempotency/replay,
concurrency, chronology (F04–F08), and the separate batch/stage-level
Quality Hold feature:

```
pytest tests/test_pilot_blocker_005_f07_quality_chronology.py \
       tests/test_store_inv_002a2_quality.py \
       tests/test_store_inv_002a2_quality_http.py \
       tests/test_store_inv_002a2_command_idempotency_migration.py \
       tests/test_store_inv_002a2_quality_concurrency.py \
       tests/test_quality_hold.py \
       tests/test_quality_hold_stage_blocking.py \
       -q
```

**Inventory existence custody-conflict tests** — the physical-custody
floor invariant and its HTTP mapping (PILOT-BLOCKER-008 A9):

```
pytest tests/test_store_inv_002b_custody.py -q
```

**Migration head check** — confirms `cmp_test` reaches the single,
dynamically-resolved Alembic head cleanly, using only the existing
approved fixtures (never a bare `alembic` command):

```
pytest tests/test_migrations.py::test_alembic_script_graph_resolves_single_unambiguous_head \
       tests/test_migrations.py::test_migration_upgrade_head_matches_dynamically_resolved_alembic_head \
       -q
```

**Migration/downgrade-guard tests — PILOT-BLOCKER-008 B3 correction: `test_migrations.py`
is NOT a superset of the standalone `*_downgrade_guard.py`/`*_migration.py`
files.** Direct inspection (`grep def test_ tests/test_migrations.py`)
confirms `test_migrations.py` contains its own inline CMP-009..019/
capacity/germination round-trip tests only — it never collects the 23
separate `tests/test_*_downgrade_guard.py` files (each proves ONE
feature's own downgrade guard against a different revision). Never claim
one covers the other "indirectly." Name every file a release-gate pass
actually ran, explicitly, in the release record:

- `pytest tests/test_migrations.py -q` — the CMP-009..019/capacity/
  germination round-trip suite. This is the slowest group in this gate (a
  full downgrade/upgrade cycle per test) — run it for a release, not
  per-ticket.
- `pytest tests/test_batch_derivation_downgrade_guard.py -q` — CMP-012
  split/merge derivation guard.
- `pytest tests/test_nursery_ops_downgrade_guard.py -q` — Nursery Ops guard.
- `pytest tests/test_recall_downgrade_guard.py -q` — recall traceability
  guard.
- Any other `tests/test_<feature>_downgrade_guard.py`/`tests/test_<feature>
  _migration.py` file whose feature THIS release actually touched — name it
  explicitly for that release; never imply it by omission.

Run each of the above as a **separate** `pytest` invocation (do not combine
them into one command) — the release record captures each file's own
pass/fail independently.

**Known operational hazard confirmed during PILOT-BLOCKER-008**: these
downgrade-guard tests build their own scenario data directly against
`cmp_test` and are sensitive to rows already committed by an EARLIER,
unrelated test file run against the same `cmp_test` in the same session —
observed concretely when `test_store_inv_002b_custody.py`'s committed
putaway rows caused `test_batch_derivation_downgrade_guard.py`'s CMP-012
guard to be masked by a later, unrelated guard (STORE-INV-002B's) firing
first. Reset `cmp_test` (`python scripts/reset_test_database.py`)
immediately before running this migration/guard group specifically, even
if other groups ran first in the same release-gate pass.

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
configuration for test purposes only, via `CMP_TEST_AUTH_BYPASS` — a
mechanism distinct from the backend's `ENABLE_DEV_AUTH`/frontend's
`CMP_DEV_AUTH_BYPASS`; see that file's own comments). Run it deliberately
for a release, not as part of the fast day-to-day loop.

**Required/optional classification (PILOT-BLOCKER-008 B3 correction —
resolves prior ambiguity):** the pilot E2E scope (exactly which specs —
see B5's table below) is **REQUIRED** for a release gate whenever the
Playwright browser/test environment is already provisioned in the
environment running the gate. If it is not already available, do **not**
spend the release window provisioning it from scratch — record it as
**NOT RUN** with the reason, and treat real deployed acceptance testing
(after the Production section below) as the mandatory substitute for that
pass. "Not run" must always be a recorded, deliberate decision, never a
silent skip.

## Exact release test scope (PILOT-BLOCKER-008 B5)

Every required or optional check, named exactly — no vague "run relevant
tests." `Evidence` is what to record in the release notes/ticket for that
pass.

| Check | Exact command | Purpose | Required/Optional | Evidence |
|---|---|---|---|---|
| F01 tenant isolation | `pytest tests/test_inventory_storage_tenant_isolation.py -q` | Cross-tenant data isolation | Required | pass/fail + count |
| Authorization/policy | `pytest tests/test_permissions.py tests/test_authz_architecture.py tests/test_authz_mutation_enforcement_architecture.py tests/test_authz_read_enforcement_architecture.py tests/test_authz_farm_proof.py -q` | Role/permission catalog, mutation/read enforcement architecture (includes PILOT-BLOCKER-008 B1's hermetic dev-bootstrap proof) | Required | pass/fail + count |
| F02 accounting | `pytest tests/test_pilot_blocker_004_f02_inventory_accounting.py tests/test_inventory_category_db_integrity.py tests/test_inventory_item_db_integrity.py -q` | Cohort accounting reconciliation, incl. the raw-PG-trigger proof | Required | pass/fail + count |
| Quality safety | `pytest tests/test_pilot_blocker_005_f07_quality_chronology.py tests/test_store_inv_002a2_quality.py tests/test_store_inv_002a2_quality_http.py tests/test_store_inv_002a2_command_idempotency_migration.py tests/test_store_inv_002a2_quality_concurrency.py tests/test_quality_hold.py tests/test_quality_hold_stage_blocking.py -q` | Full Quality command contract + chronology + hold | Required | pass/fail + count |
| Custody-conflict | `pytest tests/test_store_inv_002b_custody.py -q` | Physical-custody floor invariant + HTTP mapping | Required | pass/fail + count |
| Migration head check | `pytest tests/test_migrations.py::test_alembic_script_graph_resolves_single_unambiguous_head tests/test_migrations.py::test_migration_upgrade_head_matches_dynamically_resolved_alembic_head -q` | Single unambiguous Alembic head | Required | pass/fail |
| Migration/downgrade-guards | Each file separately — see "Backend" above for the exact named list | Full downgrade/upgrade/backfill + per-feature guards | Required (full `test_migrations.py` + the named guard files) | pass/fail per file |
| Frontend typecheck | `npm run typecheck` | Type safety | Required | pass/fail |
| Frontend lint | `npm run lint` | Lint policy (or changed-file scope) | Required | pass/fail |
| Frontend unit/component | `npm test` | Vitest suite | Required | pass/fail + count |
| Frontend build | `npm run build` | Production build succeeds | Required | pass/fail |
| Playwright E2E | `npm run e2e` | Pilot browser acceptance scope | Required IF environment already provisioned; otherwise NOT RUN (recorded) | pass/fail + count, or "NOT RUN — reason" |

## Production

Deployment mechanics live in `docs/deployment/PILOT_DEPLOYMENT.md` and
`docs/deployment/RENDER_PILOT_DEPLOYMENT.md` — this section is only the
release-gate checklist of what to capture/confirm, in order. **If this
release changes the database schema, follow `RENDER_PILOT_DEPLOYMENT.md`'s
"Schema-changing release procedure" (PILOT-BLOCKER-008 B4) instead of the
plain order below** — `/ready` proves DB connectivity only, never
schema-match, so a schema-changing release needs the stricter
maintenance-window sequence documented there.

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
8. **Backup/restore evidence** — for DigitalOcean, per `docs/deployment/PILOT_DEPLOYMENT.md` "Backup and recovery"; for Render, per `docs/deployment/RENDER_PILOT_DEPLOYMENT.md`'s "Backup and recovery" (PILOT-BLOCKER-008 B3). `--backup-confirmed` in step 5 is an operator acknowledgement, not itself a backup mechanism, on either path. Do not skip verifying a real recoverable snapshot/recovery point exists before a migrating release.

## Result

A release is gate-clear when every Backend and Frontend command above
passes and every Production step is completed/recorded. Record known,
accepted exceptions (e.g. a pre-existing, separately-tracked failure
unrelated to the release) explicitly rather than silently — see
`docs/product/OPEN_QUESTIONS.md` for the place to log one.
