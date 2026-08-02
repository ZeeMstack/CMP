# ADR 007: Client-Generated Idempotency Keys

## Context

CMP is an online-first PWA with an offline command outbox (`CLAUDE.md` "API and Offline Rules"). Commands (movements, transformations, stock issues, etc.) may be queued offline and retried on reconnect, risking duplicate execution if the same command is submitted more than once.

## Decision

Every command carries a client-generated UUID idempotency key. The server enforces uniqueness of this key **per tenant and per command type**: a resubmission with the same key for the same tenant/command type does not re-execute the command a second time.

## Consequences

- Clients (including the offline outbox) must generate and persist a stable idempotency key at the time a command is created, before it is ever transmitted.
- The server must store and check idempotency keys as part of the same atomic transaction as the command's state change and audit event (`docs/domain/AUDIT_MODEL.md`).
- Retry-safe offline sync becomes possible: a queued command can be resent after a dropped connection without risk of double-applying it.

## Rejected alternatives

- **Server-generated keys only, no idempotency enforcement** — rejected: cannot protect against duplicate submission from a retried offline command, since the server would have no way to recognize a resend as the same logical command.
