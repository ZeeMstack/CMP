# End-to-End Recall & Traceability Foundation

Full detail: `CMP_MASTER_SPEC.md` §2, §7, §8, §10; `CLAUDE.md` rules 1, 3, 5, 7, 8, 11, 12. This document summarizes the approved model as implemented in CMP-019; it does not restate the spec.

## Scope

CMP-019 is a **read-only traversal layer** over the immutable operational facts CMP-009 through CMP-018 already record. It answers two questions: *what produced this finished-goods lot* (backward trace) and *what might this upstream source have affected* (forward impact). It creates no new table, no lineage ledger, no recall case/status, no customer/order/delivery data, no hold/release command, and no persisted snapshot. Every response reflects current immutable history plus current derived balances/placements, computed fresh on each request.

## Lineage graph (verified from models, not documentation)

`seed_lots → sowing_event_lines` (one line per `batch_carrier_assignment`, UNIQUE). An assignment is opened by exactly one of {sowing event, transplant event, batch-derivation event} — transplant never changes batch identity, only carrier/position. `crop_batches.created_by_batch_derivation_event_id` / `superseded_by_batch_derivation_event_id` point to `batch_derivation_events`; `batch_derivation_sources`/`batch_derivation_outputs` (each with a dedicated `UNIQUE(source_batch_id)` / `UNIQUE(output_batch_id)`) are the authoritative per-event source/output batch sets — split is 1→N, merge is N→1. `harvest_events.batch_id → crop_batches` is direct. `harvested_produce_lots.harvest_event_id` is `UNIQUE` (1:1). `packing_input_lines(packing_event_id, harvested_produce_lot_id)` is genuinely M:N — a produce lot may feed more than one packing event, never collapsed to one. `finished_goods_lots.packing_event_id` is `UNIQUE` (1:1). `dispatch_lines(dispatch_event_id, finished_goods_lot_id)` — one FG lot may appear across many dispatch lines. `finished_goods_storage_movements.finished_goods_lot_id` is 1:N.

**Deferred**: a seed-lot impact endpoint. A batch created by *merge* may legitimately combine assignments from more than one seed lot (split never mixes seed lots, but merge can), so seed-lot attribution is not always provable at batch granularity. This edge is documented, not guessed around.

## Recursive batch lineage

One tenant/farm-constrained `WITH RECURSIVE` CTE per direction (ancestors via `batch_derivation_sources`, descendants via `batch_derivation_outputs`), extending the same idiom `location_service.get_path` already uses, hardened for a genuine DAG: every recursive step re-filters by `tenant_id`/`farm_id`; each branch carries its own `visited` path array. A candidate already in *that branch's own* visited path is a true cycle (a batch reachable from itself) and raises `TraceabilityIntegrityError` — a legitimate re-convergent DAG (the same ancestor reached via two independent branches, e.g. split-then-remerge) is not a cycle and is handled correctly, since the check is per-branch, not across the whole result set. A defensive depth guard (500 generations) exists purely to bound pathological corruption, never as a business limit; hitting it also raises `TraceabilityIntegrityError`, never a silently truncated `trace_complete: false`. Lineage **nodes** are deduplicated by batch ID; lineage **edges** are never deduplicated — a batch reached through two derivations still shows both edges.

## Backward trace: `GET /farms/{farm_id}/traceability/finished-goods-lots/{id}`

Returns typed sections: `subject` (current available/placed/unplaced), `packing_event`, `packing_inputs` (every input line, preserving mixed-source identity), `produce_lots`, `harvest_events`, `lineage` (ancestor batches + edges), `seed_origins` (**every** provable sowing-origin evidence — `seed_lot_id`/code, `sowing_event_id`, `sowing_event_line_id`, `batch_carrier_assignment_id`, `carrier_id`, `originating_batch_id` — a merge-derived batch may legitimately surface more than one), `storage_movements` (full history for this one lot — bounded, and more informative than a current-only snapshot for a single-lot trace), `dispatches`, `quality` (read-only, per contributing batch), and `completeness`.

## Forward impact: `GET /farms/{farm_id}/traceability/crop-batches/{id}/impact` and `GET /farms/{farm_id}/traceability/harvested-produce-lots/{id}/impact`

Descendant-closure traversal from the subject (batch: full descendant set via the recursive CTE; produce lot: the single lot, no ancestry needed) → harvest events → produce lots → **every** packing input line for any packing event touched by an affected produce lot (co-inputs stay visible as context, each flagged `is_affected_source`, never promoted to an additional affected source) → distinct finished-goods lots → current available/placed/unplaced/dispatched per lot → dispatch lines → per-location storage balances (current state, not full movement history — the affected set can span many lots, so a current-balance summary is chosen over a movement log for this endpoint).

**No proportional attribution.** A `potentially_affected_*` quantity is a finished-goods lot's own entire current quantity — never a fraction derived from `source_input / total_input`. `source_input_weight_kg`/`count` records exactly how much of the affected input entered packing; it is never used to scale the output.

**Deduplication.** Every summary total is computed over a *distinct-ID* set (batch, produce lot, finished-goods lot, dispatch line) before any `SUM`. One finished-goods lot reached via two affected inputs counts once; one dispatch line reached via multiple upstream paths counts once. All sums are Decimal-safe.

## Trace completeness and error semantics

`trace_complete: bool` + `limitations: [{code, message}]` + `capability_limitations: [str]`. A legitimately empty branch (a batch never harvested) is a complete, valid result. A missing-but-optional historical relationship (e.g. no provable seed origin) is a `limitation`, not an error. `capability_limitations` always includes `recipient_not_modeled` — dispatch carries no customer/vehicle/invoice field, by design (out of scope until a commercial/logistics ticket). A genuine invariant violation (a resolvable FK pointing at nothing, or a lineage cycle) raises `TraceabilityIntegrityError` → HTTP 500, never a silently truncated 200.

## Read-consistency snapshot

Each of the three service functions opens its own short-lived connection in a PostgreSQL `REPEATABLE READ`, read-only transaction (`traceability_service._snapshot_connection`) and issues **every** query for that trace — including tenant/farm and subject-existence validation — on that one connection. The router's injected `Session` (via `get_db`) is used only to authenticate tenant/user context (`require_dev_tenant_context`); it never touches trace data. This guarantees a response can never be partly-before and partly-after a concurrent dispatch or storage commit — proven by `test_traceability_concurrency.py`. Read-only tests must use the `get_engine` FastAPI dependency override (added to `app/core/db.py`, mirroring `get_db`'s own established override pattern) to point the trace's dedicated connection at `test_engine`; a dedicated connection cannot see another session's uncommitted work, so integration tests build committed scenarios.

## Tenant/farm isolation

Every query — anchor and every recursive step — carries explicit `tenant_id =` / `farm_id =` predicates. Cross-tenant/farm subject IDs resolve to 404 via the same `FarmNotFoundError`/`*NotFoundError` convention used everywhere else.

## Migration

Indexes only: `ix_packing_input_lines_tenant_farm_produce_lot`, `ix_dispatch_lines_tenant_farm_finished_goods_lot`, `ix_finished_goods_storage_movements_tenant_farm_lot` — the three genuinely missing leading-column indexes for the traversal's own reverse-lookup predicates. `harvested_produce_lots.batch_id` was deliberately **not** indexed: the traversal reaches produce lots through the authoritative `harvest_events.batch_id → harvested_produce_lots.harvest_event_id` join, which the existing `harvest_events` composite unique already supports. `batch_derivation_sources.source_batch_id` / `batch_derivation_outputs.output_batch_id` already had dedicated unique indexes (CMP-012) — no gap. No table, trigger, function, or historical migration is touched; no data is denormalized.

## API and audit

Exactly three GET operations. No POST/PUT/PATCH/DELETE, no `/recalls`, no customer search. Zero audit rows for any read.

## Deferred

Seed-lot impact endpoint, recall case/status, customer/order/delivery tracking, notifications, regulatory submission workflow, snapshot/export persistence, proportional quantity attribution, hold/release commands, dispatch recipient/vehicle/invoice data.
