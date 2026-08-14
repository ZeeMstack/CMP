# CMP — Claude Code Rules

## Read First

Read this file before every task. Read `docs/CMP_MASTER_SPEC.md` only for product, domain, architecture, or hydroponic workflow work. Read only task-relevant files.

If requirements conflict or a decision is missing, stop and report it. Do not invent agronomic, quality, security, or architectural rules.

## Product Boundary

CMP is a multi-tenant SaaS platform for commercial hydroponic greenhouse farms. It maps the farm and traces inputs, crop batches, carriers, movements, harvest, packing, cold storage, and dispatch.

Included: nursery, leafy-green and vine greenhouses; input store; production; quality; harvest; packing; finished-goods cold store; dispatch; recall.

Excluded unless approved: open fields, livestock, orchards, GIS/satellite features, machinery telematics, payroll, accounting, invoicing, general ledger, and retail POS.

## Non-Negotiable Rules

1. **Crop-agnostic:** Never branch on a literal crop, variety, stage, greenhouse, growing system, or customer name. New crops and workflows must be configuration, not new code paths or crop-specific tables.
2. **Tenant isolation:** Every tenant-owned record has `tenant_id`. Enforce isolation in backend queries, authorization, database constraints/RLS where appropriate, and cross-tenant tests. Frontend filtering is not security.
3. **Generic locations:** Use UUID-based parent-child locations; never assume a fixed depth or repeat greenhouse/zone/span/table/gutter columns across operational tables.
4. **Separate concepts:** Fixed locations, mobile assets, crop carriers, and equipment are distinct. Structures such as tables/gutters may have linked asset and location records.
5. **Occupancy:** A batch may occupy several carriers and locations. Use active occupancy plus history; do not rely only on `current_location_id`.
6. **Movement vs transformation:** Movement changes location of the same entity. Transformation converts inputs into outputs.
7. **Immutable history:** Never hard-delete or rewrite production, inventory, quality, movement, transformation, harvest, pack, cold-store, dispatch, label, or audit history. Correct through reversal/void plus a new transaction.
8. **Quantity reconciliation:** `input = output + loss + rejection + sample + remainder`. Never hide differences.
9. **Versioning:** Crop workflows, recipes, quality rules, and customer specifications are versioned. Existing batches retain their assigned versions.
10. **Command operations:** Critical changes use domain commands, not unrestricted CRUD. Validate tenant, source, destination, capacity, status, workflow, approval, and idempotency; commit state and audit records atomically.
11. **Security:** Enforce permissions in the backend. Never expose secrets, production credentials, or unrestricted production database access.
12. **Usability:** Minimize floor typing and scans. Scan flows require clear sequence, duplicate protection, visible offline/sync status, and practical recovery.

## Farm Model

Administrative: `Tenant → Country → City/Region → Farm`.

Operational locations use a configurable tree beginning at Farm. Standard templates are defined in `docs/CMP_MASTER_SPEC.md` for:

- Nursery: seeding, germination chamber/positions, seedling tables, InterVines, InterSalads. Does not use zone/span.
- Leafy greens: zone → span → grow table (mandatory chain, no shortcuts). The grow table is the leaf; the Production Cultivation Plate is a carrier occupying it, not a further location level.
- Vines: zone → span → grow gutter → grow-bag position (mandatory chain, no shortcuts). Grow Gutter Side (left/right) is not a location — it is plant canopy/branch training only.

## Architecture

Use a modular monolith.

- Frontend: Next.js, TypeScript, React PWA, TanStack Query, React Hook Form, Zod, IndexedDB outbox.
- Backend: FastAPI, Python, SQLAlchemy, Alembic, Pydantic, Pytest.
- Database: PostgreSQL, UUIDs, constraints, transactions/locking, RLS where useful.

Do not add microservices, Kafka, Kubernetes, Redis, or major libraries without an approved need and ADR.

Keep business rules in domain/application services, not routes, UI components, ORM models, or generic helpers. Generate the frontend client from OpenAPI where practical.

## API and Offline Rules

Use commands such as `/movements`, `/transformations`, `/stock-issues`, `/quality-holds`, `/harvest-events`, and `/reversals`. Do not move a carrier through a generic `PATCH`.

Every offline command has an idempotency key. UI states: `queued`, `synchronized`, `rejected`, `needs attention`. Never show queued work as server-confirmed.

## Development Database Safety

Never run bare `python -m alembic upgrade`, `downgrade`, or `current` (or any other Alembic command that can execute a migration) for verification or migration work. `migrations/env.py` fails closed: it refuses to resolve a database target automatically, so a bare invocation with no explicit URL fails loudly before connecting — but always construct the target explicitly anyway; do not rely on the failure as the workflow.

Alembic database targets must always be supplied explicitly, via an approved helper or a `Config` with `sqlalchemy.url` set directly — e.g. `scripts/reset_test_database.py`, or `tests/conftest.py`'s `migrations_alembic_config()`. For test/migration work, use this existing `cmp_test`-safe tooling; never hand-construct a bare CLI invocation. The development database must never be targeted implicitly.

## Working Method

For each non-trivial task:

1. Read this file, the ticket, and only relevant docs/code.
2. Plan briefly: scope, assumptions, affected files, migration/API/UI/security/audit impacts, edge cases, tests, and exclusions.
3. Implement the smallest approved change. Do not refactor unrelated code or add speculative features.
4. Add migrations, tests, and docs where required.
5. Verify with focused tests, lint/type checks, migration checks, and relevant build/E2E evidence.
6. Report facts and remaining risks; do not claim success without evidence.

A feature is done only when applicable domain validation, authorization, tenant isolation, audit events, error states, duplicate protection, tests, documentation, and builds pass.

## Authority and Stop Conditions

Claude may inspect, plan, implement approved scope, test, and review. Claude may not independently decide product scope, agronomic policy, quality release, traceability granularity, major architecture, infrastructure, destructive migrations, production access, or batch/seed-lot merge policy.

Record unresolved decisions in `docs/product/OPEN-QUESTIONS.md` and stop when:

- requirements conflict;
- a material rule is missing;
- a value would be invented;
- tenant isolation or reconciliation cannot be proven;
- a destructive change is proposed;
- scanning is operationally impractical;
- production access is required;
- scope exceeds the ticket.

## Source Precedence

1. Current explicit user-approved decision
2. This file
3. Approved ADRs/specifications/acceptance criteria
4. Original process documents
5. Existing code
6. Claude inference

Existing code is not automatically correct. Never silently resolve conflicts.

## Current Build Order

1. Control documents and ADRs
2. Tenant/auth/farm/permissions/audit
3. Generic location builder and greenhouse templates
4. Assets, carriers, codes, and labels
5. Occupancy, movement, scanning, reversal, history
6. Transformations and reconciliation
7. Crop/workflow configuration and batches
8. Store, production execution, quality, harvest, packing, cold store, dispatch, integrations

Do not build planning dashboards before the location-and-movement proof in `docs/CMP_MASTER_SPEC.md` passes.
