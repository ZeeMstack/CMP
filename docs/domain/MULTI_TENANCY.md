# Multi-Tenancy Model

Full detail: `CLAUDE.md` rule 2, "Farm Model"; `docs/adr/003-shared-schema-multitenancy.md`. This document summarizes the approved approach; it does not restate the ADR rationale.

## Isolation strategy

CMP uses a **shared database schema** across tenants (not schema-per-tenant or database-per-tenant). Every tenant-owned record carries `tenant_id`. Isolation is enforced in two layers:

1. **Mandatory application-level tenant scoping** — every backend query and command is filtered and authorized by `tenant_id`. This is the primary, required control. Frontend filtering is never treated as security (`CLAUDE.md` rule 2).
2. **PostgreSQL Row-Level Security (RLS) as defence in depth** — a second, database-enforced layer behind the application-level control, not a replacement for it.

Cross-tenant access must be provably impossible, including in automated cross-tenant tests (`CLAUDE.md` rule 2).

## Authentication

Authentication is **OIDC-compatible**, implemented behind an application adapter so the specific identity provider can be selected or changed independently of the rest of the system. The provider is not yet selected (`docs/product/OPEN_QUESTIONS.md`, technical decisions).

## Administrative hierarchy

`Tenant → Country → City/Region → Farm`. Country and city are administrative/reporting dimensions only; they do not participate in operational occupancy (`LOCATION_MODEL.md`).
