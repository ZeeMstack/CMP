# CMP — Crop Management Platform

CMP is a multi-tenant SaaS platform for commercial hydroponic greenhouse farms. It maps the farm and traces inputs, crop batches, carriers, movements, harvest, packing, cold storage, and dispatch, providing complete forward and backward traceability from supplier lot to customer dispatch.

This repository currently contains the CMP-001 minimal application scaffold: a FastAPI backend health check and a Next.js placeholder page. No domain models, authentication, or business APIs exist yet — see `docs/acceptance/FIRST_TECHNICAL_PROOF.md` for what's next.

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
