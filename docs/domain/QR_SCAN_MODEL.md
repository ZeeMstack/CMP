# QR Identifier and Scan Context Model

Full detail: `CLAUDE.md` rules 2, 7, 10, 11, 12; `docs/adr/006-scan-identity-tokens.md`; the PILOT-SCAN-001 ticket ("QR identities, label printing & scan context"). This document summarizes the approved model; it does not restate the ticket.

## Core rule

**QR identifies context. Scanning never executes a farm operation.** Resolving a token only returns a typed read of current state and prepared navigation links — it never moves plants, completes a Work Item, records Harvest/loss, releases Quality, puts away inventory, records an Observation, or performs any other business transaction. Every destination a scan links to independently re-resolves/validates the ids it was given; QR resolution is never authorization for the downstream command.

## What a QR Identifier is, and is not

A `QrIdentifier` (`qr_identifiers` table) is this ticket's concrete implementation of ADR 006's `scan_identity` concept: it links an opaque, server-generated public `token` to exactly one of eight supported entities. It stores **no mutable operational fact** — never crop, variety, location, status, quantity, current Batch occupant, or Quality state. Those are read fresh from the authoritative live tables every time a token is resolved (`qr_service.resolve_scan_context`).

One typed nullable FK column per supported entity type (`crop_batch_id`, `location_id`, `carrier_id`, `asset_id`, `batch_carrier_assignment_id`, `harvested_produce_lot_id`, `graded_produce_lot_id`, `finished_goods_lot_id`), mirroring `FarmWorkItem`'s own structured-context precedent (PILOT-OPS-001) — real composite FKs, never a bare polymorphic `entity_id` with no referential integrity. `entity_type` is a redundant, CHECK-enforced discriminator naming exactly which one is populated.

A CURRENT-STATE row (ADR-005), like `CropBatch`/`FarmWorkItem`: identity/content fields (tenant/farm, entity_type, every typed entity column, token, `created_by_user_id`/`created_at`) are frozen for life by a DB trigger (`enforce_qr_identifier_mutable_fields`); only `status`/`revoked_at`/`revoked_by_user_id` may ever change. No hard delete is possible.

## Token design

`secrets.token_urlsafe(24)`, server-chosen, opaque, globally unique (`ux_qr_identifiers_token`). The QR payload is `<canonical app origin>/q/<token>`, where the canonical origin is resolved server-side from `APP_BASE_URL` (`lib/server/same-origin.ts::resolveTrustedOrigin`, the same value Auth0's own trusted-redirect logic already uses) — **never** `window.location.origin`. A permanent printed label must point at the one canonical GrowCMP web origin for its whole physical lifetime, regardless of which hostname the operator happened to open (a Render preview URL, a LAN IP, localhost) when they printed it. Because `APP_BASE_URL` is deliberately server-only (never `NEXT_PUBLIC_*`), the label preview route (`app/farms/[farmId]/labels/[entityType]/[entityId]/page.tsx`) is a Server Component that resolves the origin and passes it down as a plain prop to the Client Component that renders the label/QR (`LabelPreviewClient.tsx`); if `APP_BASE_URL` is unset/invalid, the origin resolves to `null` and the label preview refuses to render a QR at all rather than falling back to any request- or browser-derived value. The token is an **identifier, not an authorization grant**: every resolve still goes through the caller's authenticated tenant/permission context; a valid token belonging to an inaccessible tenant returns the identical generic 404 a nonexistent/revoked token does (never an existence oracle).

## Permanent vs. operational identity

- **Permanent** (Carrier, Asset, Location): the QR stays with the physical object/place for its life. The printed label never prominently shows a mutable fact (current Batch/location/status) — the scan page resolves those dynamically.
- **Operational** (Crop Batch, Batch Carrier Assignment/"Placement", Harvested Produce Lot, Graded Produce Lot, Finished Goods Lot): identifies an operational record. May print stable creation-time metadata (crop/variety) on the label; never current stage/status.

**Batch vs. placement** are never merged. A Batch may occupy several Carriers/Locations at once; scanning "the Batch" cannot tell an operator which physical portion they are standing beside. `BatchCarrierAssignment` (CMP-006's own "what crop batch does this carrier contain right now" identity) is the stable, independently-scannable placement identity — its own QR resolves the exact Batch sub-context (crop/variety, current location via its Carrier's own current occupancy), never collapsed into the parent Batch's QR.

**Carrier permanence**: a reusable Carrier's QR (e.g. a Production Cultivation Plate) identifies the physical object, never today's occupant. Scanning it resolves the CURRENT Batch/location dynamically (via `sowing_service.get_carrier_batch_assignment`/`movement_service.get_resolved_location`) — tomorrow the same Carrier may carry a different Batch, and the same QR resolves that new fact automatically.

## Idempotent generation

`qr_service.generate_or_get_qr_identifier` returns the entity's one active identifier, creating it only if none exists. Concurrent callers racing to create the first identity for the same entity never both win: the loser's INSERT hits one of eight partial unique indexes (`ux_qr_identifiers_active_<column>`, `WHERE status = 'active'`, mirroring `Occupancy`'s own XOR-uniqueness pattern), and the service simply re-reads the row the winner just committed. Reprinting reuses this same identity — it never creates a new QR, a new Batch/Lot/Carrier, or a new operational event.

## Scan resolution and authorization

`GET /qr/{token}` returns a compact, discriminated `ScanContext` (one Pydantic model per `entity_type`, never one giant universal object). Authorization here deliberately does not fit this codebase's usual single-static-`Permission`-per-route shape (see `test_authz_read_enforcement_architecture.py`'s own exemption mechanism): a generic resolver's real permission requirement is only known after the token resolves to an `entity_type`. Every QR route (`GET /qr/{token}`, `POST /farms/{farm_id}/qr/{entity_type}/{entity_id}/generate`, `POST /qr/{token}/print`) requires `require_tenant_context` (real authentication + active membership), then enforces the exact per-entity-type `Permission` via `has_permission()` inside the route body before any content is returned or write happens.

`ENTITY_PERMISSIONS` (`app/api/qr.py`) is a FROZEN mapping, verified against the live route table (never a plausible guess) for every one of the eight entity types:

| entity_type | read permission | manage permission | verified against |
|---|---|---|---|
| `crop_batch` | `crop_batch.read` | `crop_batch.manage` | `GET .../crop-batches/{id}` (`app/api/crop_batches.py`) |
| `location` | `location.read` | `location.manage` | `GET .../locations/{id}` (`app/api/locations.py`) |
| `carrier` | `carrier.read` | `carrier.manage` | `GET .../carriers/{id}` (`app/api/carriers.py`) |
| `asset` | `asset.read` | `asset.manage` | `GET .../assets/{id}` (`app/api/assets.py`) |
| `batch_carrier_assignment` | `sowing.read` | `sowing.manage` | `GET .../carriers/{id}/batch-assignment`, `GET .../crop-batches/{id}/carriers` (`app/api/sowings.py`) |
| `harvested_produce_lot` | `harvest.read` | `harvest.manage` | `GET .../harvested-produce-lots/{id}` (`app/api/harvests.py`) |
| `graded_produce_lot` | `grading.read` | `grading.manage` | `GET .../graded-produce-lots/{id}` (`app/api/grading.py`) |
| `finished_goods_lot` | `packing.read` | `packing.manage` | `GET .../finished-goods-lots/{id}` (`app/api/packing.py`) |

Two corrections from this ticket's own first draft, caught at final closure: `batch_carrier_assignment` is gated by `sowing.*`, not `crop_batch.*` — CMP-006's own BatchCarrierAssignment read/write authority already lives under Sowing (`sowing_service.list_batch_carriers`/`get_carrier_batch_assignment`, the exact two functions `qr_service` calls for this entity type, are `sowing.read`-gated). `finished_goods_lot` is gated by `packing.*`, not `finished_goods_storage.*` — `packing_service.get_finished_goods_lot` (the exact function `qr_service` calls) is exposed under `packing.read` in `app/api/packing.py`; `finished_goods_storage.*` governs physical cold-store custody/movement, a different concern this entity type's own identity read never touches.

`tests/test_qr_authz.py` is a single parametrized test proving, for all eight entity types: an authorized same-tenant user resolves it; a role holding every `.read` but no `.manage` permission (`qc_officer`) can never generate/print any of them; a role lacking most `.manage` and five of the eight `.read` permissions (`storekeeper`) is denied both, using the genuine existing role policy (never weakened to make the test pass) — including the honest fact that `location.read`/`carrier.read`/`asset.read` are granted to every current role, so no read-bypass negative exists for those three; a foreign tenant is denied (scoped 404); and a corrupted token never leaks whether the underlying entity exists.

## Print/reprint audit

Tracked via the existing `AuditEvent` infrastructure (`entity_type = 'qr_identifier'`, `action = 'qr_label_print_requested'`) — no separate print-event table. The action name and the response field (`PrintLabelResponse.requested_at`, not `printed_at`) are deliberate: a browser print dialog cannot prove a physical label actually came out of a printer, so the audit trail only claims what is actually known — that a print was requested. "Initial print"/"reprint" mean "first print request"/"subsequent print request for the same active QR identity", adequate for pilot audit, never a physical-output guarantee; the frontend's own confirmation text says "requested", never "printed"/"recorded". `is_reprint` is derived server-side from whether a prior print *request* already exists for that QR identity, never accepted from the caller. A reprint of an operational/lot label (Crop Batch, Batch Carrier Assignment, Harvested/Graded Produce Lot, Finished Goods Lot) requires a non-blank `reason` (`QrReprintReasonRequiredError`, mapped to 400) — a permanent Carrier/Asset/Location label's reprint never requires one.

## Scan ≠ activity

A QR scan is not proof that farm work occurred. No Harvest/Movement/Observation/other business event is ever created merely from resolving a token. "Recent activity"/history for a scanned Batch/Location links to the existing traceability/movement/observation surfaces (via prepared `actions`) rather than duplicating a second generic activity ledger — see `docs/product/OPEN_QUESTIONS.md` for the aggregation gap this leaves open.

## Work Item cross-reference

`farm_work_item_service.list_work_items_for_context` (additive) maps a scanned entity onto `FarmWorkItem`'s own structured context columns (PILOT-OPS-001) — never inferring a relationship those columns don't already express. Scanning does not start/complete a Work Item; opening one still follows PILOT-OPS-001's own rules (Work Item → real operation → authoritative result → completion/link).
