# CMP — Crop Management Platform

CMP is a multi-tenant SaaS platform for commercial hydroponic greenhouse farms. It maps the farm and traces inputs, crop batches, carriers, movements, harvest, packing, cold storage, and dispatch, providing complete forward and backward traceability from supplier lot to customer dispatch.

This repository implements CMP's domain model, tenant/platform authentication and authorization, farm/location/carrier setup, and the full production lifecycle (nursery through dispatch) behind a FastAPI backend and a Next.js frontend. Authentication is OIDC-compatible; the implemented production identity provider is Auth0 (`docs/domain/AUTHORIZATION_MODEL.md`). See `docs/acceptance/FIRST_TECHNICAL_PROOF.md` for the original technical proof and `docs/deployment/PILOT_DEPLOYMENT.md` for pilot/production deployment.

## Rules and specifications

- [`CLAUDE.md`](CLAUDE.md) — permanent coding rules and non-negotiable constraints. Read before any implementation work.
- [`docs/CMP_MASTER_SPEC.md`](docs/CMP_MASTER_SPEC.md) — product, domain, architecture, and hydroponic workflow specification.

## Documentation map

- `docs/product/` — product scope, glossary, and open questions.
- `docs/domain/` — domain models: locations, assets/carriers, occupancy/movement, multi-tenancy, audit.
- `docs/acceptance/` — acceptance criteria for the first technical proof.
- `docs/adr/` — architecture decision records.

## Application structure

`apps/api` (FastAPI backend) and `apps/web` (Next.js frontend), per [`docs/adr/001-modular-monolith.md`](docs/adr/001-modular-monolith.md).

## Setup and run

The steps below are **local development only** — `docker compose up -d` starts a local, unauthenticated PostgreSQL container, not a production database, and `ENABLE_DEV_AUTH`/`CMP_DEV_AUTH_BYPASS` (used below) must never be enabled outside development. For pilot/production deployment, see `docs/deployment/PILOT_DEPLOYMENT.md`.

Requires Python 3.12+, Node.js 20.9+, and npm.

### Backend (`apps/api`)

```
cd apps/api
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
copy .env.example .env
.venv\Scripts\uvicorn app.main:app --reload
```

- API: http://localhost:8000, health check: http://localhost:8000/health
- Requires PostgreSQL: `docker compose up -d` from the repo root, then `.venv\Scripts\alembic upgrade head`.
- Tests: `.venv\Scripts\pytest -m "not integration"` runs without a database; `.venv\Scripts\pytest -m integration` requires PostgreSQL and a `cmp_test` database — provision it once via `.venv\Scripts\python scripts\create_test_db.py` (idempotent, safe to rerun).

### Frontend (`apps/web`)

```
cd apps/web
npm install
copy .env.example .env
npm run dev
```

- App: http://localhost:3000
- Checks: `npm run lint`, `npm run typecheck`, `npm run build`
