# ADR 001: Modular Monolith Architecture

## Context

CMP needs an architecture that supports a single deployable product covering many operational domains (locations, assets, occupancy, movement, transformation, harvest, packing, dispatch) for multiple tenants, while keeping domain boundaries clear and avoiding premature distributed-systems complexity.

## Decision

Use a modular monolith: a Next.js/TypeScript/React PWA frontend and a FastAPI/Python backend (SQLAlchemy, Alembic, Pydantic, Pytest), organized internally by domain module, deployed as a single backend service and a single frontend application. Business rules live in domain/application services, not in routes, UI components, ORM models, or generic helpers.

## Consequences

- Domain boundaries are enforced by code organization and review discipline, not by network boundaries.
- Deployment, transactions, and local development stay simple relative to a distributed system.
- Scaling and team-ownership boundaries must be managed within the monolith (module structure, code ownership) rather than via service extraction.
- Any future move toward microservices, message queues, or container orchestration requires a new ADR justifying the need.

## Rejected alternatives

- **Microservices per domain** — rejected: adds distributed-systems complexity (network calls, eventual consistency, service discovery) not justified by current scale or team size.
- **Kafka / event streaming backbone** — rejected: no current requirement for asynchronous cross-service event propagation; the monolith can enforce atomic command+audit commits directly.
- **Kubernetes / container orchestration** — rejected: no current requirement for multi-service orchestration at this stage.
