# STORE-INV-002A — Common Build Procedure

**This document is procedural only. It is not a source of domain truth.** The canonical domain model for this ticket family is `docs/domain/STORE_INVENTORY_MODEL.md` (as amended by the `STORE-INV-002A` discovery). If anything in this document, or in `STORE_INV_002A1_RECEIPT_LOT_QUANTITY_BUILD_PLAN.md` / `STORE_INV_002A2_QUALITY_OPERATIONAL_UX_BUILD_PLAN.md`, conflicts with the canonical domain model, **the canonical domain model wins** and this document must be corrected, not the other way round.

Referenced by both `STORE-INV-002A.1` and `STORE-INV-002A.2` build plans — read this once, then read the phase-specific plan for that phase's exact scope, steps, and acceptance criteria.

---

## 1. Claude execution rules (both phases)

Before coding each substantial step within a phase:

1. Inspect the actual current files relevant to that step (models, services, schemas, tests, migrations) — never assume shape from memory or from an earlier round of discovery.
2. State the intended files to change before changing them.
3. State the invariant(s) being implemented (reference the exact `STORE_INVENTORY_MODEL.md` section).
4. Implement narrowly — the smallest change that satisfies the step; no speculative abstraction, no unrelated refactor.
5. Run the smallest relevant focused test(s) for that step only.
6. Fix only failures attributable to the current change.
7. Re-run the smallest relevant tests.
8. Proceed to the next step.

**Do not run full backend/frontend suites during ordinary implementation.** Use focused, affected tests only (`pytest apps/api/tests/test_<area>.py -k <case>`, targeted `npm test`/`vitest` file runs). A single broader regression gate may be authorized later, explicitly, by the CTO before a PR is opened — it is not part of ordinary step-by-step implementation and must not be run repeatedly or unprompted.

Never invent a second idempotency framework, a second audit mechanism, or a second migration-target-resolution mechanism — reuse the exact conventions this codebase already has (client_command_id + request fingerprint; `append_audit_event`; `migrations_alembic_config()`/`scripts/reset_test_database.py`).

## 2. Git / PR procedure (per phase)

Windows PowerShell, this repo's primary shell.

1. Confirm a clean working tree and the current branch before starting:
   ```powershell
   git status
   git branch --show-current
   ```
2. Confirm `main` is up to date and the branch is cut from a verified, merged commit on `main` (not from a stale local `main`):
   ```powershell
   git fetch origin
   git log origin/main -1
   ```
3. Discovery/docs land first where a ticket requires it (already true for `STORE-INV-002A` — this build-plan pass itself). Implementation commits are kept logically separated where useful (e.g. migration + models in one commit, service layer in another, API routes in another, frontend in another) rather than one undifferentiated commit per phase.
4. Before every commit, inspect the exact staged boundary — never a blind `git add -A`:
   ```powershell
   git status
   git diff --cached
   git diff --cached --check
   ```
   Confirm nothing unstaged remains unexpectedly (`git status` again after staging).
5. Push the feature branch only after CTO review of the relevant step/phase.
6. **The PR is created manually by the user in GitHub — Claude does not create or merge the PR.**
7. Merge is performed manually by the user.
8. After merge:
   ```powershell
   git checkout main
   git pull origin main
   git log -1
   ```
   Confirm the expected merge commit is present.
9. **Do not delete the feature branch until production deployment for that phase is verified** (§3 below). Clean up the local and remote branch only after successful, confirmed completion.

## 3. Production deployment procedure (per phase, when that phase ships a migration)

Do not perform any of this during a documentation or discovery pass — it is captured here for the phase that actually deploys. Follows the existing `docs/deployment/PILOT_DEPLOYMENT.md` architecture (DigitalOcean VPS, Managed PostgreSQL, Docker Compose, Caddy, manual controlled deployment) — nothing here supersedes that document.

1. Verify the target branch is `main`, merged, at the expected commit.
2. Verify the current production baseline (API/Web commit, DB Alembic revision) before touching anything.
3. Confirm a fresh/recent recovery point exists per the current deployment decision (managed-Postgres backup/snapshot policy already in place — this ticket does not change backup policy).
4. Deploy the API image built from merged `main`.
5. Run **only** the guarded migration path already established for this codebase — never a bare `alembic upgrade`/`downgrade`/`current` invocation (`CLAUDE.md`, "Development Database Safety"; the same discipline applies to production, with the production-specific tooling this repo's deployment already uses, never test-only helpers like `scripts/reset_test_database.py`).
6. Confirm the database identity being targeted is actually the intended production database before migrating (never rely on an implicit/default target).
7. Confirm the current Alembic revision before migrating.
8. Migrate to the exact expected new head — no further, no partial.
9. Verify `/health`.
10. Verify `/ready`.
11. Deploy the Web image.
12. Run a non-destructive UI smoke check (login, navigate to the newly-shipped screens if this is the `.2` phase, confirm no 500s).
13. Only after all of the above pass, proceed to feature-branch cleanup (§2.9).

Never auto-run migrations on service boot or as a pre-deploy hook — this codebase's `migrations/env.py` deliberately fails closed on an implicit target, and that design is not superseded by this ticket. Never expose secrets (DB URLs, Auth0 credentials) in any build-plan document, commit message, or PR description.

## 4. Acceptance-checklist categories (used by both phase plans)

Every phase's acceptance checklist distinguishes these categories explicitly. **"Code written" is never equivalent to "ticket complete."** A phase is not complete until every applicable category below is checked:

- `DOMAIN COMPLETE` — behavior matches `STORE_INVENTORY_MODEL.md` exactly, no undocumented deviation.
- `DATABASE COMPLETE` — models, constraints, triggers match the design; migration applies cleanly.
- `API COMPLETE` — endpoints match the designed shape; OpenAPI/client generation (this repo's existing "generate the frontend client from OpenAPI where practical" convention) run where applicable.
- `PERMISSIONS COMPLETE` — new `Permission` values defined, wired to the correct routes, role grants applied per the design, verified against the existing architecture-walk test convention (`tests/test_authz_mutation_enforcement_architecture.py`-style).
- `AUDIT/IDEMPOTENCY COMPLETE` — every command has its `client_command_id`/fingerprint pair and its audit event; replay and conflict behavior proven.
- `CONCURRENCY COMPLETE` — lock targets and lock order proven under a real concurrent test (matching this codebase's `threading.Barrier`-based precedent), not merely asserted.
- `UI COMPLETE` — only applicable to `.2`; screens exist, are wired to real endpoints, and match the frozen workflow-first navigation.
- `FOCUSED TESTS COMPLETE` — every test named in the phase's test-gate list passes.
- `MIGRATION VERIFIED` — upgrade and downgrade both proven; downgrade-blocking behavior proven once operational rows exist.
- `PR MERGED` — merged by the user, not Claude.
- `PRODUCTION DEPLOYED` — per §3, when the phase includes a migration/deploy.
- `PRODUCTION SMOKED` — post-deploy smoke check passed.
- `BRANCH CLEANED` — only after the above.
