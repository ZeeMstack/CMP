# ADR 002: PostgreSQL as the Database

## Context

CMP requires a database that supports strict relational integrity for a generic, deep parent-child location tree; transactional, lockable commits for occupancy/movement/transformation commands; UUID primary keys; and per-tenant row isolation strong enough to serve as a defence-in-depth layer alongside application-level tenant scoping.

## Decision

Use PostgreSQL as the sole database, with UUIDs, constraints, transactions/row locking, and Row-Level Security (RLS) where useful for tenant isolation.

## Consequences

- Strong relational integrity and transactional guarantees are available natively for atomic command+audit commits.
- RLS can be layered on top of application-level tenant scoping for defence in depth (`docs/domain/MULTI_TENANCY.md`).
- A single relational engine must be operated and scaled; no polyglot persistence.
- Any future addition of another database technology requires a new ADR justifying the need.

## Rejected alternatives

- **MySQL** — rejected: weaker native support for the constraint/locking guarantees and RLS-style row security CMP relies on for tenant isolation.
- **SQLite** — rejected: not designed for concurrent multi-tenant write workloads or server-side row-level security.
- **Document database (e.g. MongoDB)** — rejected: the domain model is relational by nature (generic parent-child location trees, referential occupancy/movement records, reconciliation constraints); a document store would push referential integrity into application code with weaker guarantees.
