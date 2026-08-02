# Audit Model

Full detail: `CMP_MASTER_SPEC.md` §4, §7; `CLAUDE.md` rules 7–8, 10. This document summarizes the approved approach; it does not restate the spec.

## Immutable history

Production, inventory, quality, movement, transformation, harvest, pack, cold-store, dispatch, label, and audit history are never hard-deleted or rewritten. Corrections are made through reversal/void plus a new transaction (`CLAUDE.md` rule 7).

## Atomic commit

Command execution, resulting state changes (e.g. occupancy), and the corresponding audit event commit atomically — never as separate, individually-failable steps (`CLAUDE.md` rule 10).

## What is audited

- Every domain command execution (movement, transformation, stock issue, quality hold, harvest event, reversal, etc.), with actor, device, effective time, recorded time, and idempotency key.
- Every QR/label print, reprint, and replacement, with actor, time, and reason (spec §4).
- Reconciliation of transformations: `input = output + loss + rejection + sample + remainder` — differences are never hidden (`CLAUDE.md` rule 8).

## Identity and labels

Every important record has a UUID, tenant ownership, human-readable code, status, and audit metadata. Codes are display/label identifiers, not relational keys. QR payload contents and scan lookup are defined in `docs/adr/006-scan-identity-tokens.md`.
