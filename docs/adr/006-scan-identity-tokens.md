# ADR 006: Opaque Scan-Identity Tokens for QR Codes

## Context

CMP relies on QR scanning for floor operations (locating trays, trolleys, carriers). QR payloads, once printed, are effectively immutable and can persist in the field long after the underlying record changes (location, batch, status). Encoding mutable data directly in the QR would let stale labels present incorrect information.

## Decision

QR codes encode an **opaque public token**, resolved through a `scan_identity` record that links the token to the entity it identifies. No mutable crop, asset, batch, or location data is encoded in the QR payload itself — a scan always triggers a server-side lookup that returns current data.

## Consequences

- A scanned label always reflects live system state, never stale embedded data.
- Every scan requires a lookup call; offline scanning must handle lookup failure/queuing explicitly (`CLAUDE.md` "API and Offline Rules").
- Token generation, `scan_identity` uniqueness, and print/reprint/replacement auditing (`docs/domain/AUDIT_MODEL.md`) become a required subsystem before any QR-based flow ships.

## Rejected alternatives

- **Embedding location/batch/status data directly in the QR payload** — rejected: creates stale-label risk, since printed data cannot be updated after the fact, and conflicts with the immutable-history and current-state requirements in `docs/domain/OCCUPANCY_MOVEMENT_MODEL.md`.
