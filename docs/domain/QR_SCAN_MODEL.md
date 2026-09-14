# QR Identifier and Scan Context Model

Full detail: `CLAUDE.md` rules 2, 7, 10, 11, 12; `docs/adr/006-scan-identity-tokens.md`; the PILOT-SCAN-001 ticket ("QR identities, label printing & scan context"). This document summarizes the approved model; it does not restate the ticket.

## Core rule

**QR identifies context. Scanning never executes a farm operation.** Resolving a token only returns a typed read of current state and prepared navigation links — it never moves plants, completes a Work Item, records Harvest/loss, releases Quality, puts away inventory, records an Observation, or performs any other business transaction. Every destination a scan links to independently re-resolves/validates the ids it was given; QR resolution is never authorization for the downstream command.

## What a QR Identifier is, and is not

A `QrIdentifier` (`qr_identifiers` table) is this ticket's concrete implementation of ADR 006's `scan_identity` concept: it links an opaque, server-generated public `token` to exactly one of eight supported entities. It stores **no mutable operational fact** — never crop, variety, location, status, quantity, current Batch occupant, or Quality state. Those are read fresh from the authoritative live tables every time a token is resolved (`qr_service.resolve_scan_context`).

One typed nullable FK column per supported entity type (`crop_batch_id`, `location_id`, `carrier_id`, `asset_id`, `batch_carrier_assignment_id`, `harvested_produce_lot_id`, `graded_produce_lot_id`, `finished_goods_lot_id`), mirroring `FarmWorkItem`'s own structured-context precedent (PILOT-OPS-001) — real composite FKs, never a bare polymorphic `entity_id` with no referential integrity. `entity_type` is a redundant, CHECK-enforced discriminator naming exactly which one is populated.

A CURRENT-STATE row (ADR-005), like `CropBatch`/`FarmWorkItem`: identity/content fields (tenant/farm, entity_type, every typed entity column, token, `created_by_user_id`/`created_at`) are frozen for life by a DB trigger (`enforce_qr_identifier_mutable_fields`); only `status`/`revoked_at`/`revoked_by_user_id` may ever change. No hard delete is possible.

## Token design

`secrets.token_urlsafe(24)`, server-chosen, opaque, globally unique (`ux_qr_identifiers_token`). The QR payload is `<window.location.origin>/q/<token>` — built from the browser's own authoritative origin at render time rather than a new, separately-maintained base-URL config or a hardcoded domain (no such config exists yet in this codebase). The token is an **identifier, not an authorization grant**: every resolve still goes through the caller's authenticated tenant/permission context; a valid token belonging to an inaccessible tenant returns the identical generic 404 a nonexistent/revoked token does (never an existence oracle).

## Permanent vs. operational identity

- **Permanent** (Carrier, Asset, Location): the QR stays with the physical object/place for its life. The printed label never prominently shows a mutable fact (current Batch/location/status) — the scan page resolves those dynamically.
- **Operational** (Crop Batch, Batch Carrier Assignment/"Placement", Harvested Produce Lot, Graded Produce Lot, Finished Goods Lot): identifies an operational record. May print stable creation-time metadata (crop/variety) on the label; never current stage/status.

**Batch vs. placement** are never merged. A Batch may occupy several Carriers/Locations at once; scanning "the Batch" cannot tell an operator which physical portion they are standing beside. `BatchCarrierAssignment` (CMP-006's own "what crop batch does this carrier contain right now" identity) is the stable, independently-scannable placement identity — its own QR resolves the exact Batch sub-context (crop/variety, current location via its Carrier's own current occupancy), never collapsed into the parent Batch's QR.

**Carrier permanence**: a reusable Carrier's QR (e.g. a Production Cultivation Plate) identifies the physical object, never today's occupant. Scanning it resolves the CURRENT Batch/location dynamically (via `sowing_service.get_carrier_batch_assignment`/`movement_service.get_resolved_location`) — tomorrow the same Carrier may carry a different Batch, and the same QR resolves that new fact automatically.

## Idempotent generation

`qr_service.generate_or_get_qr_identifier` returns the entity's one active identifier, creating it only if none exists. Concurrent callers racing to create the first identity for the same entity never both win: the loser's INSERT hits one of eight partial unique indexes (`ux_qr_identifiers_active_<column>`, `WHERE status = 'active'`, mirroring `Occupancy`'s own XOR-uniqueness pattern), and the service simply re-reads the row the winner just committed. Reprinting reuses this same identity — it never creates a new QR, a new Batch/Lot/Carrier, or a new operational event.

## Scan resolution and authorization

`GET /qr/{token}` returns a compact, discriminated `ScanContext` (one Pydantic model per `entity_type`, never one giant universal object). Authorization here deliberately does not fit this codebase's usual single-static-`Permission`-per-route shape (see `test_authz_read_enforcement_architecture.py`'s own exemption mechanism): a generic resolver's real permission requirement is only known after the token resolves to an `entity_type`. Every QR route (`GET /qr/{token}`, `POST /farms/{farm_id}/qr/{entity_type}/{entity_id}/generate`, `POST /qr/{token}/print`) requires `require_tenant_context` (real authentication + active membership), then enforces the exact per-entity-type `Permission` (`app/api/qr.py::ENTITY_PERMISSIONS`) via `has_permission()` inside the route body before any content is returned or write happens. See `docs/product/OPEN_QUESTIONS.md` for the flagged architectural gap this pattern surfaces, and `tests/test_qr_authz.py` for the behavioral proof it holds.

## Print/reprint audit

Tracked via the existing `AuditEvent` infrastructure (`entity_type = 'qr_identifier'`, `action = 'qr_label_printed'`) — no separate print-event table. `is_reprint` is derived server-side from whether a prior print event already exists for that QR identity, never accepted from the caller. A reprint reason is accepted but not required at the schema level (floor policy on when a reason is mandatory is a UX/process decision left to the calling screen, not enforced in this ticket's backend).

## Scan ≠ activity

A QR scan is not proof that farm work occurred. No Harvest/Movement/Observation/other business event is ever created merely from resolving a token. "Recent activity"/history for a scanned Batch/Location links to the existing traceability/movement/observation surfaces (via prepared `actions`) rather than duplicating a second generic activity ledger — see `docs/product/OPEN_QUESTIONS.md` for the aggregation gap this leaves open.

## Work Item cross-reference

`farm_work_item_service.list_work_items_for_context` (additive) maps a scanned entity onto `FarmWorkItem`'s own structured context columns (PILOT-OPS-001) — never inferring a relationship those columns don't already express. Scanning does not start/complete a Work Item; opening one still follows PILOT-OPS-001's own rules (Work Item → real operation → authoritative result → completion/link).
