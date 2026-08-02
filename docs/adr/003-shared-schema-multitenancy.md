# ADR 003: Shared-Schema Multi-Tenancy

## Context

CMP is a multi-tenant SaaS platform. Every tenant-owned record must be provably isolated from other tenants, in a way that supports many tenants without operational overhead scaling linearly per tenant.

## Decision

Use a single shared database schema across all tenants. Every tenant-owned record carries a `tenant_id`. Isolation is enforced through mandatory application-level tenant scoping on every query and command, with PostgreSQL Row-Level Security (RLS) as an additional, database-enforced layer of defence in depth. Frontend filtering is never treated as a security control.

## Consequences

- Onboarding a new tenant requires no schema or database provisioning — only a new `Tenant` row.
- Every backend query and command must consistently include tenant scoping; this is a discipline enforced by code review, cross-tenant tests, and RLS as a backstop.
- A bug in application-level scoping is mitigated, not fully covered, by RLS — both layers are required.
- Detailed RLS policy definitions (per-table policies, role setup) are not yet specified (`docs/product/OPEN_QUESTIONS.md`).

## Rejected alternatives

- **Schema-per-tenant** — rejected: multiplies migration and operational complexity per tenant with no corresponding isolation benefit once RLS and application-level scoping are in place.
- **Database-per-tenant** — rejected: far higher operational overhead (provisioning, connection management, cross-tenant reporting) not justified at this stage.
