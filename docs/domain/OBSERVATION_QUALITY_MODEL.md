# Observation, Germination Check, and Quality Hold Model

Full detail: `CMP_MASTER_SPEC.md` §2, §8; `CLAUDE.md` rules 1, 3, 5, 7, 10, 12. This document summarizes the approved model as implemented in CMP-010; it does not restate the spec.

## Two measurement shapes, on purpose

Independent, tenant-defined metrics (temperature, humidity, EC, pH, plant height, visual notes) go through the generic `observation_definitions` / `observation_events` / `observation_values` system: one typed value per definition per target, bounded only by that definition's own static min/max. Germination is different — its integrity rules (`germinated ≤ observed`, category counts within the inspected population) compare *sibling counts from the same inspection*, which a per-value CHECK on separate EAV rows cannot express. Rather than build a cross-row trigger keyed to specific definition codes (a rule engine CMP-010 deliberately avoids), germination gets its own narrow, immutable `germination_checks` table: one row per assignment per event, with real columns, so ordinary same-row `CHECK` constraints enforce every rule directly. Both shapes attach to the same `observation_event` and are included in one fingerprint and one audit event — an event may carry generic values, germination checks, or both.

## Observations never rewrite sowing quantities

`germination_checks.inspected_site_count` is validated against — never written into — the CMP-009 `sowing_event_lines.sown_site_count` for the same assignment (a trigger join, since the two tables are otherwise unrelated). `germination_percentage` is derived at read time from `(normal + abnormal) / inspected * 100` using `Decimal` arithmetic throughout the read path — it is never a stored column, so there is nothing to keep in sync.

## Targets and assignment timing

Each observation definition declares a `target_scope`: `crop_batch` (no assignment), `carrier_assignment` (assignment required), or `either`. A referenced assignment must belong to the same batch as the observation event but is **not** required to belong to the batch's *current* stage run — a carrier assigned during seeding can still be observed during germination. What is enforced is temporal: an observation's effective time can never precede the assignment's own `assigned_effective_time`. Assignment "active" here means CMP-009's existing `released_effective_time IS NULL` — CMP-010 adds no release mechanism of its own.

## Quality holds block progression, releases don't mutate them

A `quality_hold` is immutable and batch-level; multiple simultaneous open holds are permitted (the alternative — capping one open hold at a time — adds dedup complexity for no real benefit, since "any open hold blocks" already generalizes cleanly). Open vs. released is never a stored status: it is derived from whether a `quality_hold_releases` row exists for that hold, mirroring CMP-009's own release-by-absence convention on `batch_carrier_assignments`. A hold's optional `source_observation_event_id` must reference an observation on the same batch with an effective time no later than the hold's own.

## Stage-progression blocking is enforced twice

`crop_batch_service.transition_stage` (CMP-008) checks for an open hold immediately after its existing post-lock idempotency recheck and before any other validation — so an exact replay of an already-successful transition still returns its original result even if a hold was placed afterward, but any *genuinely new* transition attempt is rejected outright. As defense in depth against direct SQL or a future bypass of that service function, a trigger on the **existing** `batch_stage_transitions` table (`batch_stage_transitions_enforce_no_open_hold`) rejects any `INSERT ... command_kind = 'stage_transition'` row while an open hold exists for that batch — the trigger's `WHEN` clause means it never fires for `command_kind = 'initial_entry'`, so batch creation is untouched. Both checks share one locking discipline: hold placement, hold release, and stage transition all serialize on the same `crop_batches` row lock CMP-008 already established, so no new concurrency primitive was introduced.

## Database protection

Composite foreign keys prove tenant/farm/batch consistency structurally, reusing CMP-008/009's existing `(tenant_id, farm_id, ...)` composite constraints wherever they already covered what CMP-010 needed — no additive constraint was required on any pre-existing table (verified against the live schema before writing the migration). Triggers are reserved for genuinely cross-row rules: an observation value's typed column matching its definition's `value_type` and numeric/percentage bounds (requires reading `observation_definitions`), a germination check's `inspected_site_count` against the sown count (requires reading `sowing_event_lines`), and the two stage-progression trigger described above. Observation-definition rows are immutable except `status` — a dedicated trigger permits only that one field (plus `updated_at`) to change, matching the same pattern CMP-007 established for workflow lifecycle fields.

## Hold-blocking scope across tickets

Quality holds are not a global lock — each later ticket that gates on them extends the net deliberately, not automatically: CMP-010 holds block stage progression (`transition_stage`, above). CMP-012 holds also block batch split/merge (identity derivation) — a genuinely new derivation command creating a real hold-blocked scenario, checked with the same replay-before-mutable-state discipline. CMP-013 holds also block harvested-produce-lot creation — reusing `quality_hold_service.has_open_quality_hold` at the service layer, plus (a first for this net) a DB-level `SELECT ... FOR UPDATE`-locked check inside the harvest-event insert-integrity trigger, so a direct-SQL insert genuinely serializes against hold placement rather than relying on an unlocked read. CMP-011 transplantation remains **unaffected** — it is a same-stage transformation the hold net was never extended to, and this document's own scope does not implicitly widen to cover it.

## Deferred

Carrier release/reassignment, transplanting, transformations, automatic stage progression, automatic pass/fail rules, scoring/formula engines, approval workflows, role-specific hold authority, correction/void of observations or holds, seed inventory deduction, laboratory integrations, sensors/IoT ingestion, occupancy/movement changes, packing, QR identities, labels, frontend, RLS.

Split/merge (CMP-012) and harvest (CMP-013) are implemented — see `docs/domain/BATCH_DERIVATION_MODEL.md` and `docs/domain/HARVEST_MODEL.md`; both extend the hold-blocking net described above without altering the stage-progression behavior documented here.
