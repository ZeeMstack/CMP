# Crop Batch and Stage Execution Model

Full detail: `CMP_MASTER_SPEC.md` §2, §8; `CLAUDE.md` rules 5, 7, 9, 10. This document summarizes the approved model as implemented in CMP-008; it does not restate the spec.

## Four distinct layers

- **Workflow configuration** (`CROP_WORKFLOW_MODEL.md`) — the reusable, crop-agnostic *definition* of stages and transitions. Tenant-owned, never itself executed.
- **Immutable workflow version** — one published, frozen snapshot of that definition. Never changes once published; retirement never rewrites history.
- **Crop-batch execution** (this document) — one real production run, permanently bound to the workflow version that was published when it was created. This is where "what actually happened" lives.
- **Physical carrier occupancy** (`OCCUPANCY_MOVEMENT_MODEL.md`) — where a batch's physical material sits (carrier, location). CMP-008 does not touch this layer at all; a crop batch has no carrier, location, or quantity yet.

## Crop batch

A `crop_batch` is tenant- and farm-owned, with a normalized, tenant-wide unique `code` (same scope as farms/assets/crops/workflows — safer for labels and search than farm-scoped codes, though `farm_id` itself remains immutable in this ticket; cross-farm transfer is not supported). It stores only `workflow_id` and `workflow_version_id` — never crop/variety/production-system fields, which are always derived through `workflow_version → workflow → crop/variety/production_system`. There is also no `current_stage_id`: the current stage is always the one `batch_stage_run` row with no exit time.

At creation, the server resolves the workflow's *currently published* version and stores it permanently — a later publish can never retroactively change which version governs an existing batch. Creation requires: the workflow is active; exactly one published version exists; its crop, optional variety, and production system are all active; and it has exactly one start stage. `created_by_user_id` is required — there are no anonymous batches.

## Stage runs and transitions

Every stage occupied by a batch, past or present, is one `batch_stage_run` row. Runs are opened only by an immutable `batch_stage_transition` record and closed only by another. A batch has exactly one active (unclosed) run at a time — enforced by a partial unique index — and a closed run can never reopen. **Closing the batch does not close its terminal run**: the terminal stage remains the batch's permanent "current stage" for history purposes.

`batch_stage_transitions` covers both a batch's initial entry (`command_kind = 'initial_entry'`, no source stage, no configured transition) and normal progression (`command_kind = 'stage_transition'`, both required) in one immutable, insert-only table — inventing a fake configured transition for entry would be worse than the nullable pair. Normal progression always derives source and destination from a server-validated, tenant- and version-scoped configured `workflow_transition`; clients never submit stage IDs directly.

## Idempotency and concurrency

Both batch creation and stage progression accept a client-generated command ID, checked *before* any workflow/batch-state validation — so a legitimate retry succeeds even after a newer workflow version has published, the referenced configuration has gone inactive, or the batch has already progressed or closed. Creation uses `(tenant_id, client_command_id)` on `crop_batches`; progression uses `(tenant_id, command_kind, client_command_id)` on `batch_stage_transitions`, letting the same UUID be reused across the two command categories without conflict. Concurrent commands serialize on `SELECT ... FOR UPDATE` (the workflow row for creation, the batch row then its active stage run for progression); a losing `IntegrityError` triggers an explicit rollback, a re-fetch by command ID, and a fingerprint comparison — never a blind retry of the write.

## Database protection

Composite foreign keys (mirroring CMP-007's `(tenant_id, ...) → parent(tenant_id, id)` style) prove tenant/farm/version consistency structurally. Cross-row rules a `CHECK` cannot express are triggers: a batch's identity and creation fields are immutable, its lifecycle moves only `active → closed`, and closing requires the active run to already be on a terminal stage with a matching effective time; stage runs may only be inserted active and closed exactly once, each linked to a transition whose own batch/stage actually match; `batch_stage_transitions` are fully append-only.

## Deferred

Seed lots, sowing, seed counts, germination observations, batch-to-carrier assignment, grow locations, occupancy/movement commands, quality, approvals/holds, transformations, harvest, packing, QR identities, labels, frontend, RLS, role-specific authorization.

Split/merge (batch identity derivation) is implemented — see `docs/domain/BATCH_DERIVATION_MODEL.md` (CMP-012), which adds a third lifecycle state (`superseded`) and a third `batch_stage_transitions` command kind (`derivation_entry`) on top of the model described here.
