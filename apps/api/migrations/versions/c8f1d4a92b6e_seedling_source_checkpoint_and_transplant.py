"""seedling source checkpoint and transplant checkpoint evolution

NURSERY-OPS-004A -- introduces the authoritative source-accounting boundary
needed for PARTIAL TRANSPLANT of a modern (SeedlingEntry-anchored) Seed Tray.
See `docs/domain/OBSERVATION_QUALITY_MODEL.md`'s NURSERY-OPS-004A addendum
for the full model writeup; this docstring summarizes only what the
migration itself does.

One new table:

`seedling_source_checkpoints` -- immutable, insert-only boundary marker, one
row per modern `TransplantSourceLine`. Each checkpoint closes the currently-
open biological balance window and opens a new one: `remainder_after`
becomes the new anchor value, `effective_time` the new anchor time, for
every `SeedlingDispositionEvent` recorded from that point forward against
the same `seedling_entry_id`. Chained via `previous_checkpoint_id` to the
actual latest prior checkpoint for the same Tray (or NULL for the first).
Deliberately minimal -- no `checkpoint_id` column is added to
`seedling_disposition_events` (window membership is resolved purely
temporally, against `effective_time`, never a second insert-time pointer);
actor/note stay owned by `TransplantEvent`; the categorized loss facts stay
owned by `TransplantSourceLine`; the successful-transfer quantity stays
derived from `TransplantAllocation`, never independently stored.

`transplant_source_lines` evolution (existing CMP-011 table):

- Four new categorized loss columns (`transplant_damage_count`,
  `qc_rejection_count`, `sample_count`, `other_loss_count` +
  `other_loss_note`) -- `discarded_plant_count` is PRESERVED as their
  DB-enforced aggregate (same-row CHECK), never repurposed or dropped.
- `source_plant_count` changes MEANING (not type): it is no longer a
  caller-supplied fact -- it becomes the server-derived, DB-verified
  authoritative `source_available_before` at the transplant's own
  `effective_time`, resolved from SeedlingEntry + SeedlingDispositionEvents
  + SeedlingSourceCheckpoints (never `sown_site_count`, never `seed_count`).
- `ux_transplant_source_lines_assignment` (an assignment may appear as a
  source in at most ONE transplant event, ever) is replaced with
  `ux_transplant_source_lines_event_assignment` (unique per-event, not
  lifetime) -- the same source Tray may now appear across SEQUENTIAL
  transplant events (partial transplant), but never twice within one.

Guard: this migration REFUSES to run if any `transplant_source_lines` rows
already exist (the semantic upgrade to server-derived `source_plant_count`
cannot be safely backfilled from `sown_site_count`/`seed_count`/assumptions
for pre-existing rows -- fails loudly rather than fabricating history).

Three existing trigger functions are updated via `CREATE OR REPLACE` (their
own CREATE TRIGGER statements, defined in earlier, untouched historical
migrations, keep firing against the new function bodies unchanged) --
mirrors the exact precedent already established by `7bddca3261cc`'s own
germination-check integrity fix:

1. `enforce_seedling_disposition_event_insert_integrity` (originally
   `b4e8a1f0d6c2`) -- now checkpoint-aware: resolves the currently-open
   balance window's anchor (latest checkpoint's `remainder_after`/
   `effective_time`, or the SeedlingEntry's own starting quantity/
   effective_time if none exists), rejects any new event at or before that
   anchor's own time, and walks the chronological balance ONLY over deltas
   strictly after it -- never against the original SeedlingEntry start once
   a checkpoint exists.
2. `enforce_transplant_source_line_insert_integrity` (originally
   `f3a8c2e1b975`) -- no longer bounds `source_plant_count` against
   `sown_site_count` (which is why modern Nursery Seed Trays, whose
   `sown_site_count` is deliberately NULL per NURSERY-OPS-001.1, could never
   transplant at all); now requires a SeedlingEntry to exist for the source
   assignment and verifies `source_plant_count` against the SAME
   checkpoint-aware server-derivation the service layer uses.
3. `enforce_transplant_reconciliation` (originally `f3a8c2e1b975`, deferred/
   constraint trigger) -- the per-source and event-level equations now
   include each source's own checkpoint `remainder_after`; release of a
   source assignment is now CONDITIONAL (iff its own checkpoint's
   `remainder_after = 0`), never unconditional.
4. `enforce_batch_carrier_assignment_closure_only_v2` (originally
   `a4d92f7c1e6b`) -- its release-validation branch looked up the ONE
   `transplant_source_line` for an assignment with an unordered, unfiltered
   `SELECT ... INTO`; NURSERY-OPS-004A's own `ux_transplant_source_lines_
   event_assignment` change (see below) means an assignment can now have
   MULTIPLE source lines across sequential transplant events, making that
   lookup ambiguous. Fixed by filtering directly on the releasing event.

One new trigger function, `enforce_seedling_source_checkpoint_insert_integrity`
(BEFORE INSERT on `seedling_source_checkpoints`) plus append-only triggers,
reusing the existing `reject_append_only_mutation()` function (not
redefined here).

No changes to `movement_service`/Movement semantics, no new Nursery
transplant UI, no InterSalads/InterVines carrier/location work (NURSERY-
OPS-004B/004C), no transplant correction mechanism (explicitly deferred).

Revision ID: c8f1d4a92b6e
Revises: b4e8a1f0d6c2
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c8f1d4a92b6e'
down_revision: Union[str, None] = 'b4e8a1f0d6c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CHRONOLOGICAL_BALANCE_MARKER = "CMP-DOMAIN-SEEDLING-003B chronological balance violated"

# =====================================================================
# enforce_seedling_disposition_event_insert_integrity -- original (b4e8a1f0d6c2)
# and checkpoint-aware (this migration) versions.
# =====================================================================

_ORIGINAL_EVENT_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_seedling_disposition_event_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_cmd_tenant_id UUID;
        v_cmd_farm_id UUID;
        v_cmd_seedling_entry_id UUID;
        v_cmd_operation_kind TEXT;
        v_cmd_target_event_id UUID;
        v_entry_effective TIMESTAMPTZ;
        v_entry_starting INTEGER;
        v_assignment_id UUID;
        v_assignment_assigned TIMESTAMPTZ;
        v_assignment_released TIMESTAMPTZ;
        v_target_kind TEXT;
        v_target_tenant_id UUID;
        v_target_farm_id UUID;
        v_target_seedling_entry_id UUID;
        v_target_reason TEXT;
        v_target_delta INTEGER;
        v_target_effective TIMESTAMPTZ;
        v_running INTEGER;
        rec RECORD;
    BEGIN
        SELECT tenant_id, farm_id, seedling_entry_id, operation_kind, target_event_id
        INTO v_cmd_tenant_id, v_cmd_farm_id, v_cmd_seedling_entry_id, v_cmd_operation_kind, v_cmd_target_event_id
        FROM seedling_disposition_commands WHERE id = NEW.command_id;
        IF v_cmd_tenant_id IS NULL THEN
            RAISE EXCEPTION 'command not found';
        END IF;
        IF v_cmd_tenant_id <> NEW.tenant_id OR v_cmd_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'command does not belong to this tenant/farm';
        END IF;
        IF v_cmd_seedling_entry_id <> NEW.seedling_entry_id THEN
            RAISE EXCEPTION 'event does not belong to the same seedling entry as its command';
        END IF;

        SELECT effective_time, starting_living_seedling_count, batch_carrier_assignment_id
        INTO v_entry_effective, v_entry_starting, v_assignment_id
        FROM seedling_entries WHERE id = NEW.seedling_entry_id FOR UPDATE;

        SELECT assigned_effective_time, released_effective_time
        INTO v_assignment_assigned, v_assignment_released
        FROM batch_carrier_assignments WHERE id = v_assignment_id;

        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'assignment has already been released; no new Seedling disposition event may be created';
        END IF;

        IF NEW.effective_time < v_entry_effective THEN
            RAISE EXCEPTION 'event effective_time precedes the SeedlingEntry''s own effective_time';
        END IF;
        IF NEW.effective_time < v_assignment_assigned THEN
            RAISE EXCEPTION 'event effective_time precedes the assignment''s assigned_effective_time';
        END IF;

        IF NEW.event_kind = 'REVERSAL' THEN
            SELECT tenant_id, farm_id, seedling_entry_id, event_kind, reason_code, quantity_delta, effective_time
            INTO v_target_tenant_id, v_target_farm_id, v_target_seedling_entry_id, v_target_kind,
                 v_target_reason, v_target_delta, v_target_effective
            FROM seedling_disposition_events WHERE id = NEW.reverses_event_id;
            IF v_target_tenant_id IS NULL THEN
                RAISE EXCEPTION 'reversal target event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id OR v_target_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'reversal target does not belong to this tenant/farm';
            END IF;
            IF v_target_seedling_entry_id <> NEW.seedling_entry_id THEN
                RAISE EXCEPTION 'reversal target does not belong to this seedling entry';
            END IF;
            IF v_target_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'only a REDUCTION event may be reversed';
            END IF;
            IF NEW.id = NEW.reverses_event_id THEN
                RAISE EXCEPTION 'a reversal cannot reference itself';
            END IF;
            IF NEW.quantity_delta <> -v_target_delta THEN
                RAISE EXCEPTION 'reversal quantity_delta must be the exact negation of the target event''s own delta';
            END IF;
            IF NEW.reason_code <> v_target_reason THEN
                RAISE EXCEPTION 'reversal reason_code must match the target event''s own reason_code';
            END IF;
            IF NEW.effective_time <> v_target_effective THEN
                RAISE EXCEPTION 'reversal effective_time must match the target event''s own effective_time';
            END IF;
            IF v_cmd_operation_kind <> 'CORRECT' OR v_cmd_target_event_id <> NEW.reverses_event_id THEN
                RAISE EXCEPTION 'reversal must belong to a CORRECT command targeting the same event';
            END IF;
        END IF;

        IF NEW.corrects_event_id IS NOT NULL THEN
            SELECT tenant_id, farm_id, seedling_entry_id, event_kind
            INTO v_target_tenant_id, v_target_farm_id, v_target_seedling_entry_id, v_target_kind
            FROM seedling_disposition_events WHERE id = NEW.corrects_event_id;
            IF v_target_tenant_id IS NULL THEN
                RAISE EXCEPTION 'correction target event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id OR v_target_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'correction target does not belong to this tenant/farm';
            END IF;
            IF v_target_seedling_entry_id <> NEW.seedling_entry_id THEN
                RAISE EXCEPTION 'correction target does not belong to this seedling entry';
            END IF;
            IF v_target_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'only a REDUCTION event may be corrected';
            END IF;
            IF v_cmd_operation_kind <> 'CORRECT' OR v_cmd_target_event_id <> NEW.corrects_event_id THEN
                RAISE EXCEPTION 'replacement must belong to a CORRECT command targeting the same event';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM seedling_disposition_events
                WHERE command_id = NEW.command_id AND event_kind = 'REVERSAL' AND reverses_event_id = NEW.corrects_event_id
            ) THEN
                RAISE EXCEPTION 'replacement must be accompanied by a reversal of the corrected event within the same command';
            END IF;
        END IF;

        v_running := v_entry_starting;
        FOR rec IN
            SELECT et, SUM(qd) AS net FROM (
                SELECT effective_time AS et, quantity_delta AS qd
                FROM seedling_disposition_events WHERE seedling_entry_id = NEW.seedling_entry_id
                UNION ALL
                SELECT NEW.effective_time, NEW.quantity_delta
            ) combined
            GROUP BY et
            ORDER BY et
        LOOP
            v_running := v_running + rec.net;
            IF v_running < 0 OR v_running > v_entry_starting THEN
                RAISE EXCEPTION '{marker} for seedling_entry %', NEW.seedling_entry_id
                    USING ERRCODE = 'check_violation';
            END IF;
        END LOOP;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """.replace("{marker}", _CHRONOLOGICAL_BALANCE_MARKER)

_CHECKPOINT_AWARE_EVENT_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_seedling_disposition_event_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_cmd_tenant_id UUID;
        v_cmd_farm_id UUID;
        v_cmd_seedling_entry_id UUID;
        v_cmd_operation_kind TEXT;
        v_cmd_target_event_id UUID;
        v_entry_effective TIMESTAMPTZ;
        v_entry_starting INTEGER;
        v_assignment_id UUID;
        v_assignment_assigned TIMESTAMPTZ;
        v_assignment_released TIMESTAMPTZ;
        v_target_kind TEXT;
        v_target_tenant_id UUID;
        v_target_farm_id UUID;
        v_target_seedling_entry_id UUID;
        v_target_reason TEXT;
        v_target_delta INTEGER;
        v_target_effective TIMESTAMPTZ;
        v_running INTEGER;
        v_anchor_value INTEGER;
        v_anchor_time TIMESTAMPTZ;
        rec RECORD;
    BEGIN
        SELECT tenant_id, farm_id, seedling_entry_id, operation_kind, target_event_id
        INTO v_cmd_tenant_id, v_cmd_farm_id, v_cmd_seedling_entry_id, v_cmd_operation_kind, v_cmd_target_event_id
        FROM seedling_disposition_commands WHERE id = NEW.command_id;
        IF v_cmd_tenant_id IS NULL THEN
            RAISE EXCEPTION 'command not found';
        END IF;
        IF v_cmd_tenant_id <> NEW.tenant_id OR v_cmd_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'command does not belong to this tenant/farm';
        END IF;
        IF v_cmd_seedling_entry_id <> NEW.seedling_entry_id THEN
            RAISE EXCEPTION 'event does not belong to the same seedling entry as its command';
        END IF;

        -- Lock the SeedlingEntry anchor -- serializes concurrent event
        -- inserts for the same Tray (defense-in-depth behind the service's
        -- own CropBatch-first lock; section 34/41).
        SELECT effective_time, starting_living_seedling_count, batch_carrier_assignment_id
        INTO v_entry_effective, v_entry_starting, v_assignment_id
        FROM seedling_entries WHERE id = NEW.seedling_entry_id FOR UPDATE;

        SELECT assigned_effective_time, released_effective_time
        INTO v_assignment_assigned, v_assignment_released
        FROM batch_carrier_assignments WHERE id = v_assignment_id;

        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'assignment has already been released; no new Seedling disposition event may be created';
        END IF;

        IF NEW.effective_time < v_entry_effective THEN
            RAISE EXCEPTION 'event effective_time precedes the SeedlingEntry''s own effective_time';
        END IF;
        IF NEW.effective_time < v_assignment_assigned THEN
            RAISE EXCEPTION 'event effective_time precedes the assignment''s assigned_effective_time';
        END IF;

        -- NURSERY-OPS-004A section 8/24/41: resolve the currently-open
        -- balance window's anchor -- the latest SeedlingSourceCheckpoint's
        -- own remainder_after/effective_time (locked, same serialization
        -- discipline as the SeedlingEntry lock above), or the
        -- SeedlingEntry's own starting quantity if no checkpoint exists
        -- yet. A checkpoint is a hard temporal floor: no new event may
        -- land at or before it (section 24) -- the checkpoint has already
        -- frozen everything through its own time into an immutable
        -- downstream transplant handoff.
        SELECT remainder_after, effective_time INTO v_anchor_value, v_anchor_time
        FROM seedling_source_checkpoints WHERE seedling_entry_id = NEW.seedling_entry_id
        ORDER BY effective_time DESC, recorded_at DESC, id DESC LIMIT 1 FOR UPDATE;

        IF v_anchor_time IS NOT NULL AND NEW.effective_time <= v_anchor_time THEN
            RAISE EXCEPTION 'event effective_time is at or before the latest transplant checkpoint''s own effective_time -- this balance window is closed';
        END IF;
        IF v_anchor_value IS NULL THEN
            v_anchor_value := v_entry_starting;
        END IF;

        IF NEW.event_kind = 'REVERSAL' THEN
            SELECT tenant_id, farm_id, seedling_entry_id, event_kind, reason_code, quantity_delta, effective_time
            INTO v_target_tenant_id, v_target_farm_id, v_target_seedling_entry_id, v_target_kind,
                 v_target_reason, v_target_delta, v_target_effective
            FROM seedling_disposition_events WHERE id = NEW.reverses_event_id;
            IF v_target_tenant_id IS NULL THEN
                RAISE EXCEPTION 'reversal target event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id OR v_target_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'reversal target does not belong to this tenant/farm';
            END IF;
            IF v_target_seedling_entry_id <> NEW.seedling_entry_id THEN
                RAISE EXCEPTION 'reversal target does not belong to this seedling entry';
            END IF;
            IF v_target_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'only a REDUCTION event may be reversed';
            END IF;
            IF NEW.id = NEW.reverses_event_id THEN
                RAISE EXCEPTION 'a reversal cannot reference itself';
            END IF;
            IF NEW.quantity_delta <> -v_target_delta THEN
                RAISE EXCEPTION 'reversal quantity_delta must be the exact negation of the target event''s own delta';
            END IF;
            IF NEW.reason_code <> v_target_reason THEN
                RAISE EXCEPTION 'reversal reason_code must match the target event''s own reason_code';
            END IF;
            IF NEW.effective_time <> v_target_effective THEN
                RAISE EXCEPTION 'reversal effective_time must match the target event''s own effective_time';
            END IF;
            IF v_cmd_operation_kind <> 'CORRECT' OR v_cmd_target_event_id <> NEW.reverses_event_id THEN
                RAISE EXCEPTION 'reversal must belong to a CORRECT command targeting the same event';
            END IF;
        END IF;

        IF NEW.corrects_event_id IS NOT NULL THEN
            SELECT tenant_id, farm_id, seedling_entry_id, event_kind
            INTO v_target_tenant_id, v_target_farm_id, v_target_seedling_entry_id, v_target_kind
            FROM seedling_disposition_events WHERE id = NEW.corrects_event_id;
            IF v_target_tenant_id IS NULL THEN
                RAISE EXCEPTION 'correction target event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id OR v_target_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'correction target does not belong to this tenant/farm';
            END IF;
            IF v_target_seedling_entry_id <> NEW.seedling_entry_id THEN
                RAISE EXCEPTION 'correction target does not belong to this seedling entry';
            END IF;
            IF v_target_kind <> 'REDUCTION' THEN
                RAISE EXCEPTION 'only a REDUCTION event may be corrected';
            END IF;
            IF v_cmd_operation_kind <> 'CORRECT' OR v_cmd_target_event_id <> NEW.corrects_event_id THEN
                RAISE EXCEPTION 'replacement must belong to a CORRECT command targeting the same event';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM seedling_disposition_events
                WHERE command_id = NEW.command_id AND event_kind = 'REVERSAL' AND reverses_event_id = NEW.corrects_event_id
            ) THEN
                RAISE EXCEPTION 'replacement must be accompanied by a reversal of the corrected event within the same command';
            END IF;
        END IF;

        -- Section 24/26/82, extended by NURSERY-OPS-004A section 7/8/41:
        -- chronological balance -- group deltas STRICTLY AFTER v_anchor_time
        -- (all existing rows if no checkpoint exists yet, matching
        -- unmodified 003B behavior) by effective_time, walk forward, prove
        -- the running balance never dips below zero or exceeds
        -- v_anchor_value -- never against the original SeedlingEntry start
        -- once a checkpoint exists.
        v_running := v_anchor_value;
        FOR rec IN
            SELECT et, SUM(qd) AS net FROM (
                SELECT effective_time AS et, quantity_delta AS qd
                FROM seedling_disposition_events
                WHERE seedling_entry_id = NEW.seedling_entry_id
                  AND (v_anchor_time IS NULL OR effective_time > v_anchor_time)
                UNION ALL
                SELECT NEW.effective_time, NEW.quantity_delta
            ) combined
            GROUP BY et
            ORDER BY et
        LOOP
            v_running := v_running + rec.net;
            IF v_running < 0 OR v_running > v_anchor_value THEN
                RAISE EXCEPTION '{marker} for seedling_entry %', NEW.seedling_entry_id
                    USING ERRCODE = 'check_violation';
            END IF;
        END LOOP;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """.replace("{marker}", _CHRONOLOGICAL_BALANCE_MARKER)

# =====================================================================
# enforce_transplant_source_line_insert_integrity -- original (f3a8c2e1b975)
# and modern, SeedlingEntry-anchored (this migration) versions.
# =====================================================================

_ORIGINAL_TRANSPLANT_SOURCE_LINE_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_transplant_source_line_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_event_batch_id UUID;
        v_assignment_batch_id UUID;
        v_assignment_carrier UUID;
        v_assignment_released TIMESTAMPTZ;
        v_assignment_sowing_event UUID;
        v_sown_count INTEGER;
    BEGIN
        SELECT batch_id INTO v_event_batch_id FROM transplant_events WHERE id = NEW.transplant_event_id;

        SELECT batch_id, carrier_id, released_effective_time, opening_sowing_event_id
        INTO v_assignment_batch_id, v_assignment_carrier, v_assignment_released, v_assignment_sowing_event
        FROM batch_carrier_assignments WHERE id = NEW.source_batch_carrier_assignment_id;
        IF v_assignment_batch_id IS NULL THEN
            RAISE EXCEPTION 'source assignment not found';
        END IF;
        IF v_assignment_batch_id <> v_event_batch_id THEN
            RAISE EXCEPTION 'source assignment does not belong to this transplant event''s batch';
        END IF;
        IF v_assignment_carrier <> NEW.source_carrier_id THEN
            RAISE EXCEPTION 'source carrier does not match assignment carrier';
        END IF;
        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'source assignment is already released';
        END IF;
        IF v_assignment_sowing_event IS NULL THEN
            RAISE EXCEPTION 'source assignment did not originate from sowing';
        END IF;

        SELECT sown_site_count INTO v_sown_count FROM sowing_event_lines
        WHERE batch_carrier_assignment_id = NEW.source_batch_carrier_assignment_id;
        IF v_sown_count IS NULL THEN
            RAISE EXCEPTION 'no sowing line found for source assignment';
        END IF;
        IF NEW.source_plant_count > v_sown_count THEN
            RAISE EXCEPTION 'source_plant_count cannot exceed the assignment''s original sown_site_count';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_MODERN_TRANSPLANT_SOURCE_LINE_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_transplant_source_line_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_event_batch_id UUID;
        v_event_effective TIMESTAMPTZ;
        v_assignment_batch_id UUID;
        v_assignment_carrier UUID;
        v_assignment_released TIMESTAMPTZ;
        v_entry_id UUID;
        v_entry_starting INTEGER;
        v_entry_effective TIMESTAMPTZ;
        v_anchor_value INTEGER;
        v_anchor_time TIMESTAMPTZ;
        v_has_checkpoint BOOLEAN;
        v_latest_disposition TIMESTAMPTZ;
        v_delta_sum INTEGER;
        v_available_before INTEGER;
    BEGIN
        SELECT batch_id, effective_time INTO v_event_batch_id, v_event_effective
        FROM transplant_events WHERE id = NEW.transplant_event_id;

        SELECT batch_id, carrier_id, released_effective_time
        INTO v_assignment_batch_id, v_assignment_carrier, v_assignment_released
        FROM batch_carrier_assignments WHERE id = NEW.source_batch_carrier_assignment_id;
        IF v_assignment_batch_id IS NULL THEN
            RAISE EXCEPTION 'source assignment not found';
        END IF;
        IF v_assignment_batch_id <> v_event_batch_id THEN
            RAISE EXCEPTION 'source assignment does not belong to this transplant event''s batch';
        END IF;
        IF v_assignment_carrier <> NEW.source_carrier_id THEN
            RAISE EXCEPTION 'source carrier does not match assignment carrier';
        END IF;
        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'source assignment is already released';
        END IF;

        -- NURSERY-OPS-004A section 5/21: modern source authority is
        -- SeedlingEntry-anchored -- never sown_site_count, never
        -- substituted with seed_count. A source assignment with no
        -- SeedlingEntry at all has no authoritative source quantity this
        -- migration can derive.
        SELECT id, starting_living_seedling_count, effective_time
        INTO v_entry_id, v_entry_starting, v_entry_effective
        FROM seedling_entries WHERE batch_carrier_assignment_id = NEW.source_batch_carrier_assignment_id;
        IF v_entry_id IS NULL THEN
            RAISE EXCEPTION 'source assignment has no Seedling biological entry; modern transplant requires a SeedlingEntry-anchored source';
        END IF;

        SELECT remainder_after, effective_time INTO v_anchor_value, v_anchor_time
        FROM seedling_source_checkpoints WHERE seedling_entry_id = v_entry_id
        ORDER BY effective_time DESC, recorded_at DESC, id DESC LIMIT 1;
        v_has_checkpoint := v_anchor_value IS NOT NULL;
        IF NOT v_has_checkpoint THEN
            v_anchor_value := v_entry_starting;
            v_anchor_time := v_entry_effective;
        END IF;

        -- Section 22/23: append-forward -- strictly greater than a PRIOR
        -- CHECKPOINT specifically (no equal checkpoint timestamps ever);
        -- at/after the SeedlingEntry's own effective_time when no
        -- checkpoint exists yet; and never earlier than a disposition
        -- already recorded inside the currently-open window.
        IF v_has_checkpoint THEN
            IF v_event_effective <= v_anchor_time THEN
                RAISE EXCEPTION 'transplant effective_time must be strictly greater than the previous checkpoint''s own effective_time';
            END IF;
        ELSE
            IF v_event_effective < v_anchor_time THEN
                RAISE EXCEPTION 'transplant effective_time precedes the SeedlingEntry''s own effective_time';
            END IF;
        END IF;

        SELECT MAX(effective_time) INTO v_latest_disposition
        FROM seedling_disposition_events
        WHERE seedling_entry_id = v_entry_id AND effective_time > v_anchor_time;
        IF v_latest_disposition IS NOT NULL AND v_event_effective < v_latest_disposition THEN
            RAISE EXCEPTION 'transplant effective_time precedes a disposition already recorded in the currently-open balance window';
        END IF;

        -- Section 6/7/12: source_plant_count must equal the SAME
        -- server-derived source_available_before formula the service layer
        -- uses -- anchor_value + SUM(disposition deltas strictly inside
        -- the open window, up to and including this transplant's own time).
        SELECT COALESCE(SUM(quantity_delta), 0) INTO v_delta_sum
        FROM seedling_disposition_events
        WHERE seedling_entry_id = v_entry_id
          AND effective_time > v_anchor_time AND effective_time <= v_event_effective;
        v_available_before := v_anchor_value + v_delta_sum;

        IF NEW.source_plant_count <> v_available_before THEN
            RAISE EXCEPTION 'source_plant_count does not match the authoritative server-derived source availability';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# enforce_transplant_reconciliation -- original (f3a8c2e1b975) and
# checkpoint-aware (this migration) versions.
# =====================================================================

_ORIGINAL_TRANSPLANT_RECONCILIATION_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_transplant_reconciliation() RETURNS trigger AS $$
    DECLARE
        v_event_id UUID;
        v_source_line_count INTEGER;
        v_destination_line_count INTEGER;
        v_allocation_count INTEGER;
        v_bad_source_count INTEGER;
        v_bad_destination_count INTEGER;
        v_total_source INTEGER;
        v_total_destination INTEGER;
        v_total_discarded INTEGER;
        v_unreleased_source_count INTEGER;
        v_unopened_destination_count INTEGER;
        v_extra_release_count INTEGER;
        v_extra_open_count INTEGER;
        v_event_effective TIMESTAMPTZ;
    BEGIN
        IF TG_TABLE_NAME = 'transplant_events' THEN
            v_event_id := NEW.id;
        ELSIF TG_TABLE_NAME = 'transplant_source_lines' THEN
            v_event_id := NEW.transplant_event_id;
        ELSIF TG_TABLE_NAME = 'transplant_destination_lines' THEN
            v_event_id := NEW.transplant_event_id;
        ELSIF TG_TABLE_NAME = 'transplant_allocations' THEN
            v_event_id := NEW.transplant_event_id;
        ELSIF TG_TABLE_NAME = 'batch_carrier_assignments' THEN
            IF TG_OP = 'INSERT' THEN
                v_event_id := NEW.opening_transplant_event_id;
            ELSE
                v_event_id := NEW.released_by_transplant_event_id;
            END IF;
        END IF;

        IF v_event_id IS NULL THEN
            RETURN NEW;
        END IF;

        SELECT effective_time INTO v_event_effective FROM transplant_events WHERE id = v_event_id;

        SELECT count(*) INTO v_source_line_count FROM transplant_source_lines WHERE transplant_event_id = v_event_id;
        SELECT count(*) INTO v_destination_line_count FROM transplant_destination_lines WHERE transplant_event_id = v_event_id;
        SELECT count(*) INTO v_allocation_count FROM transplant_allocations WHERE transplant_event_id = v_event_id;

        IF v_source_line_count = 0 THEN
            RAISE EXCEPTION 'transplant event % has no source lines', v_event_id;
        END IF;
        IF v_destination_line_count = 0 THEN
            RAISE EXCEPTION 'transplant event % has no destination lines', v_event_id;
        END IF;
        IF v_allocation_count = 0 THEN
            RAISE EXCEPTION 'transplant event % has no allocations', v_event_id;
        END IF;

        SELECT count(*) INTO v_bad_source_count
        FROM transplant_source_lines sl
        WHERE sl.transplant_event_id = v_event_id
          AND sl.discarded_plant_count + COALESCE(
              (SELECT sum(a.allocated_plant_count) FROM transplant_allocations a WHERE a.source_line_id = sl.id), 0
          ) <> sl.source_plant_count;
        IF v_bad_source_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has unreconciled source lines', v_event_id;
        END IF;

        SELECT count(*) INTO v_bad_destination_count
        FROM transplant_destination_lines dl
        WHERE dl.transplant_event_id = v_event_id
          AND COALESCE(
              (SELECT sum(a.allocated_plant_count) FROM transplant_allocations a WHERE a.destination_line_id = dl.id), 0
          ) <> dl.assigned_plant_count;
        IF v_bad_destination_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has unreconciled destination lines', v_event_id;
        END IF;

        SELECT sum(source_plant_count), sum(discarded_plant_count) INTO v_total_source, v_total_discarded
        FROM transplant_source_lines WHERE transplant_event_id = v_event_id;
        SELECT sum(assigned_plant_count) INTO v_total_destination
        FROM transplant_destination_lines WHERE transplant_event_id = v_event_id;
        IF v_total_source IS DISTINCT FROM (COALESCE(v_total_destination, 0) + COALESCE(v_total_discarded, 0)) THEN
            RAISE EXCEPTION 'transplant event % totals do not reconcile', v_event_id;
        END IF;

        SELECT count(*) INTO v_unreleased_source_count
        FROM transplant_source_lines sl
        JOIN batch_carrier_assignments a ON a.id = sl.source_batch_carrier_assignment_id
        WHERE sl.transplant_event_id = v_event_id
          AND (a.released_by_transplant_event_id IS DISTINCT FROM v_event_id
               OR a.released_effective_time IS DISTINCT FROM v_event_effective);
        IF v_unreleased_source_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has a source line whose assignment was not released by this event', v_event_id;
        END IF;

        SELECT count(*) INTO v_unopened_destination_count
        FROM transplant_destination_lines dl
        JOIN batch_carrier_assignments a ON a.id = dl.destination_batch_carrier_assignment_id
        WHERE dl.transplant_event_id = v_event_id
          AND (a.opening_transplant_event_id IS DISTINCT FROM v_event_id
               OR a.assigned_effective_time IS DISTINCT FROM v_event_effective);
        IF v_unopened_destination_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has a destination line whose assignment was not opened by this event', v_event_id;
        END IF;

        SELECT count(*) INTO v_extra_release_count
        FROM batch_carrier_assignments a
        WHERE a.released_by_transplant_event_id = v_event_id
          AND NOT EXISTS (
              SELECT 1 FROM transplant_source_lines sl
              WHERE sl.source_batch_carrier_assignment_id = a.id AND sl.transplant_event_id = v_event_id
          );
        IF v_extra_release_count > 0 THEN
            RAISE EXCEPTION 'transplant event % released an assignment without a matching source line', v_event_id;
        END IF;

        SELECT count(*) INTO v_extra_open_count
        FROM batch_carrier_assignments a
        WHERE a.opening_transplant_event_id = v_event_id
          AND NOT EXISTS (
              SELECT 1 FROM transplant_destination_lines dl
              WHERE dl.destination_batch_carrier_assignment_id = a.id AND dl.transplant_event_id = v_event_id
          );
        IF v_extra_open_count > 0 THEN
            RAISE EXCEPTION 'transplant event % opened an assignment without a matching destination line', v_event_id;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_CHECKPOINT_AWARE_TRANSPLANT_RECONCILIATION_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_transplant_reconciliation() RETURNS trigger AS $$
    DECLARE
        v_event_id UUID;
        v_source_line_count INTEGER;
        v_destination_line_count INTEGER;
        v_allocation_count INTEGER;
        v_checkpoint_count INTEGER;
        v_bad_source_count INTEGER;
        v_bad_destination_count INTEGER;
        v_total_source INTEGER;
        v_total_destination INTEGER;
        v_total_discarded INTEGER;
        v_total_remainder INTEGER;
        v_unreleased_source_count INTEGER;
        v_unopened_destination_count INTEGER;
        v_extra_release_count INTEGER;
        v_remainder_release_count INTEGER;
        v_extra_open_count INTEGER;
        v_event_effective TIMESTAMPTZ;
    BEGIN
        IF TG_TABLE_NAME = 'transplant_events' THEN
            v_event_id := NEW.id;
        ELSIF TG_TABLE_NAME = 'transplant_source_lines' THEN
            v_event_id := NEW.transplant_event_id;
        ELSIF TG_TABLE_NAME = 'transplant_destination_lines' THEN
            v_event_id := NEW.transplant_event_id;
        ELSIF TG_TABLE_NAME = 'transplant_allocations' THEN
            v_event_id := NEW.transplant_event_id;
        ELSIF TG_TABLE_NAME = 'seedling_source_checkpoints' THEN
            SELECT transplant_event_id INTO v_event_id FROM transplant_source_lines WHERE id = NEW.transplant_source_line_id;
        ELSIF TG_TABLE_NAME = 'batch_carrier_assignments' THEN
            IF TG_OP = 'INSERT' THEN
                v_event_id := NEW.opening_transplant_event_id;
            ELSE
                v_event_id := NEW.released_by_transplant_event_id;
            END IF;
        END IF;

        IF v_event_id IS NULL THEN
            RETURN NEW;
        END IF;

        SELECT effective_time INTO v_event_effective FROM transplant_events WHERE id = v_event_id;

        SELECT count(*) INTO v_source_line_count FROM transplant_source_lines WHERE transplant_event_id = v_event_id;
        SELECT count(*) INTO v_destination_line_count FROM transplant_destination_lines WHERE transplant_event_id = v_event_id;
        SELECT count(*) INTO v_allocation_count FROM transplant_allocations WHERE transplant_event_id = v_event_id;
        SELECT count(*) INTO v_checkpoint_count
        FROM seedling_source_checkpoints sc
        JOIN transplant_source_lines sl ON sl.id = sc.transplant_source_line_id
        WHERE sl.transplant_event_id = v_event_id;

        IF v_source_line_count = 0 THEN
            RAISE EXCEPTION 'transplant event % has no source lines', v_event_id;
        END IF;
        IF v_destination_line_count = 0 THEN
            RAISE EXCEPTION 'transplant event % has no destination lines', v_event_id;
        END IF;
        IF v_allocation_count = 0 THEN
            RAISE EXCEPTION 'transplant event % has no allocations', v_event_id;
        END IF;
        IF v_checkpoint_count <> v_source_line_count THEN
            RAISE EXCEPTION 'transplant event % does not have exactly one checkpoint per source line', v_event_id;
        END IF;

        -- NURSERY-OPS-004A section 16: per-source reconciliation now
        -- includes the source's own checkpoint remainder_after.
        SELECT count(*) INTO v_bad_source_count
        FROM transplant_source_lines sl
        JOIN seedling_source_checkpoints sc ON sc.transplant_source_line_id = sl.id
        WHERE sl.transplant_event_id = v_event_id
          AND sl.discarded_plant_count + sc.remainder_after + COALESCE(
              (SELECT sum(a.allocated_plant_count) FROM transplant_allocations a WHERE a.source_line_id = sl.id), 0
          ) <> sl.source_plant_count;
        IF v_bad_source_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has unreconciled source lines', v_event_id;
        END IF;

        SELECT count(*) INTO v_bad_destination_count
        FROM transplant_destination_lines dl
        WHERE dl.transplant_event_id = v_event_id
          AND COALESCE(
              (SELECT sum(a.allocated_plant_count) FROM transplant_allocations a WHERE a.destination_line_id = dl.id), 0
          ) <> dl.assigned_plant_count;
        IF v_bad_destination_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has unreconciled destination lines', v_event_id;
        END IF;

        -- Section 19: event-level reconciliation includes total remainder.
        SELECT sum(sl.source_plant_count), sum(sl.discarded_plant_count)
        INTO v_total_source, v_total_discarded
        FROM transplant_source_lines sl WHERE sl.transplant_event_id = v_event_id;
        SELECT sum(dl.assigned_plant_count) INTO v_total_destination
        FROM transplant_destination_lines dl WHERE dl.transplant_event_id = v_event_id;
        SELECT sum(sc.remainder_after) INTO v_total_remainder
        FROM seedling_source_checkpoints sc
        JOIN transplant_source_lines sl ON sl.id = sc.transplant_source_line_id
        WHERE sl.transplant_event_id = v_event_id;
        IF v_total_source IS DISTINCT FROM (
            COALESCE(v_total_destination, 0) + COALESCE(v_total_discarded, 0) + COALESCE(v_total_remainder, 0)
        ) THEN
            RAISE EXCEPTION 'transplant event % totals do not reconcile', v_event_id;
        END IF;

        -- Section 29/30/45: CONDITIONAL release -- iff this specific
        -- source line's own checkpoint remainder reached zero. One source
        -- reaching zero must never release another source that still has
        -- remainder (checked independently, per assignment).
        SELECT count(*) INTO v_unreleased_source_count
        FROM transplant_source_lines sl
        JOIN seedling_source_checkpoints sc ON sc.transplant_source_line_id = sl.id
        JOIN batch_carrier_assignments a ON a.id = sl.source_batch_carrier_assignment_id
        WHERE sl.transplant_event_id = v_event_id
          AND sc.remainder_after = 0
          AND (a.released_by_transplant_event_id IS DISTINCT FROM v_event_id
               OR a.released_effective_time IS DISTINCT FROM v_event_effective);
        IF v_unreleased_source_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has a fully-consumed source line whose assignment was not released by this event', v_event_id;
        END IF;

        SELECT count(*) INTO v_remainder_release_count
        FROM transplant_source_lines sl
        JOIN seedling_source_checkpoints sc ON sc.transplant_source_line_id = sl.id
        JOIN batch_carrier_assignments a ON a.id = sl.source_batch_carrier_assignment_id
        WHERE sl.transplant_event_id = v_event_id
          AND sc.remainder_after > 0
          AND a.released_by_transplant_event_id = v_event_id;
        IF v_remainder_release_count > 0 THEN
            RAISE EXCEPTION 'transplant event % released a source assignment that still has remainder', v_event_id;
        END IF;

        SELECT count(*) INTO v_extra_release_count
        FROM batch_carrier_assignments a
        WHERE a.released_by_transplant_event_id = v_event_id
          AND NOT EXISTS (
              SELECT 1 FROM transplant_source_lines sl
              WHERE sl.source_batch_carrier_assignment_id = a.id AND sl.transplant_event_id = v_event_id
          );
        IF v_extra_release_count > 0 THEN
            RAISE EXCEPTION 'transplant event % released an assignment without a matching source line', v_event_id;
        END IF;

        SELECT count(*) INTO v_unopened_destination_count
        FROM transplant_destination_lines dl
        JOIN batch_carrier_assignments a ON a.id = dl.destination_batch_carrier_assignment_id
        WHERE dl.transplant_event_id = v_event_id
          AND (a.opening_transplant_event_id IS DISTINCT FROM v_event_id
               OR a.assigned_effective_time IS DISTINCT FROM v_event_effective);
        IF v_unopened_destination_count > 0 THEN
            RAISE EXCEPTION 'transplant event % has a destination line whose assignment was not opened by this event', v_event_id;
        END IF;

        SELECT count(*) INTO v_extra_open_count
        FROM batch_carrier_assignments a
        WHERE a.opening_transplant_event_id = v_event_id
          AND NOT EXISTS (
              SELECT 1 FROM transplant_destination_lines dl
              WHERE dl.destination_batch_carrier_assignment_id = a.id AND dl.transplant_event_id = v_event_id
          );
        IF v_extra_open_count > 0 THEN
            RAISE EXCEPTION 'transplant event % opened an assignment without a matching destination line', v_event_id;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# seedling_source_checkpoints insert integrity (new)
# =====================================================================

_CHECKPOINT_INTEGRITY_FUNCTION = """
    CREATE FUNCTION enforce_seedling_source_checkpoint_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_line_tenant_id UUID;
        v_line_farm_id UUID;
        v_line_event_id UUID;
        v_line_assignment_id UUID;
        v_line_available INTEGER;
        v_line_discarded INTEGER;
        v_event_effective TIMESTAMPTZ;
        v_event_batch_id UUID;
        v_entry_batch_id UUID;
        v_entry_tenant_id UUID;
        v_entry_farm_id UUID;
        v_assignment_released TIMESTAMPTZ;
        v_prev_actual UUID;
        v_prev_effective TIMESTAMPTZ;
        v_allocated_sum INTEGER;
        v_expected_remainder INTEGER;
    BEGIN
        SELECT tenant_id, farm_id, transplant_event_id, source_batch_carrier_assignment_id,
               source_plant_count, discarded_plant_count
        INTO v_line_tenant_id, v_line_farm_id, v_line_event_id, v_line_assignment_id,
             v_line_available, v_line_discarded
        FROM transplant_source_lines WHERE id = NEW.transplant_source_line_id;
        IF v_line_tenant_id IS NULL THEN
            RAISE EXCEPTION 'transplant source line not found';
        END IF;
        IF v_line_tenant_id <> NEW.tenant_id OR v_line_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'checkpoint does not belong to this tenant/farm';
        END IF;
        IF v_line_assignment_id <> NEW.source_batch_carrier_assignment_id THEN
            RAISE EXCEPTION 'checkpoint source assignment does not match its own transplant source line';
        END IF;

        SELECT effective_time, batch_id INTO v_event_effective, v_event_batch_id
        FROM transplant_events WHERE id = v_line_event_id;
        IF v_event_effective <> NEW.effective_time THEN
            RAISE EXCEPTION 'checkpoint effective_time must equal its transplant event''s own effective_time';
        END IF;
        IF v_event_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'checkpoint batch_id does not match its transplant event''s batch';
        END IF;

        SELECT tenant_id, farm_id, batch_id INTO v_entry_tenant_id, v_entry_farm_id, v_entry_batch_id
        FROM seedling_entries WHERE id = NEW.seedling_entry_id;
        IF v_entry_tenant_id IS NULL THEN
            RAISE EXCEPTION 'seedling entry not found';
        END IF;
        IF v_entry_tenant_id <> NEW.tenant_id OR v_entry_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'checkpoint seedling entry does not belong to this tenant/farm';
        END IF;
        IF v_entry_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'checkpoint seedling entry does not belong to this batch';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM seedling_entries
            WHERE id = NEW.seedling_entry_id AND batch_carrier_assignment_id = NEW.source_batch_carrier_assignment_id
        ) THEN
            RAISE EXCEPTION 'checkpoint seedling entry does not belong to the checkpoint''s own source assignment';
        END IF;

        SELECT released_effective_time INTO v_assignment_released
        FROM batch_carrier_assignments WHERE id = NEW.source_batch_carrier_assignment_id;
        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'source assignment has already been released; no new checkpoint may be created';
        END IF;

        -- Section 22: previous_checkpoint_id must be the ACTUAL latest
        -- prior checkpoint for this seedling_entry_id (or NULL if none) --
        -- no skipping, no branching -- and strictly monotonic effective_time.
        SELECT id, effective_time INTO v_prev_actual, v_prev_effective
        FROM seedling_source_checkpoints WHERE seedling_entry_id = NEW.seedling_entry_id
        ORDER BY effective_time DESC, recorded_at DESC, id DESC LIMIT 1;
        IF NEW.previous_checkpoint_id IS DISTINCT FROM v_prev_actual THEN
            RAISE EXCEPTION 'previous_checkpoint_id does not reference the actual latest prior checkpoint for this seedling entry';
        END IF;
        IF v_prev_effective IS NOT NULL AND NEW.effective_time <= v_prev_effective THEN
            RAISE EXCEPTION 'checkpoint effective_time must be strictly greater than the previous checkpoint''s own effective_time';
        END IF;

        -- Section 17: remainder_after arithmetic -- exact, server-derived,
        -- checked against real allocation sums (checkpoints are inserted
        -- LAST, after allocations, so this is always safely computable).
        SELECT COALESCE(SUM(allocated_plant_count), 0) INTO v_allocated_sum
        FROM transplant_allocations WHERE source_line_id = NEW.transplant_source_line_id;
        v_expected_remainder := v_line_available - v_allocated_sum - v_line_discarded;
        IF NEW.remainder_after <> v_expected_remainder THEN
            RAISE EXCEPTION 'remainder_after does not match source_available_before - successful_transfer - discarded_plant_count';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

# =====================================================================
# enforce_batch_carrier_assignment_closure_only_v2 -- original (a4d92f7c1e6b)
# and multi-line-aware (this migration) versions.
#
# NURSERY-OPS-004A section 39 replaced `ux_transplant_source_lines_assignment`
# (lifetime-once per assignment) with `ux_transplant_source_lines_event_
# assignment` (unique per-event, not lifetime) specifically so the SAME
# source assignment can appear across SEQUENTIAL transplant events
# (partial/sequential transplant of one Tray). The original closure-only
# trigger's own release-validation branch was never taught about this: its
# `SELECT transplant_event_id, source_carrier_id INTO ... FROM
# transplant_source_lines WHERE source_batch_carrier_assignment_id = NEW.id`
# has no ORDER BY/LIMIT and no filter on WHICH event -- against a table that
# can now hold multiple rows per assignment, Postgres is free to return any
# one of them, so it can non-deterministically compare the WRONG event's
# source line against `NEW.released_by_transplant_event_id` and reject a
# perfectly legitimate release. Fixed by filtering the lookup to the exact
# (assignment, releasing event) pair the release itself names -- unambiguous
# regardless of how many other events also touched this assignment earlier.
# =====================================================================

_ORIGINAL_CLOSURE_ONLY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_batch_carrier_assignment_closure_only_v2() RETURNS trigger AS $$
    DECLARE
        v_source_line_event UUID;
        v_source_line_carrier UUID;
        v_transplant_batch_id UUID;
        v_transplant_effective TIMESTAMPTZ;
        v_derivation_effective TIMESTAMPTZ;
    BEGIN
        IF OLD.released_effective_time IS NOT NULL THEN
            RAISE EXCEPTION 'batch_carrier_assignment is already released and cannot be modified';
        END IF;

        IF NEW.tenant_id <> OLD.tenant_id
           OR NEW.farm_id <> OLD.farm_id
           OR NEW.batch_id <> OLD.batch_id
           OR NEW.carrier_id <> OLD.carrier_id
           OR NEW.batch_stage_run_id <> OLD.batch_stage_run_id
           OR NEW.assigned_effective_time <> OLD.assigned_effective_time
           OR NEW.opening_sowing_event_id IS DISTINCT FROM OLD.opening_sowing_event_id
           OR NEW.opening_transplant_event_id IS DISTINCT FROM OLD.opening_transplant_event_id
           OR NEW.opening_batch_derivation_event_id IS DISTINCT FROM OLD.opening_batch_derivation_event_id
           OR NEW.actor_user_id <> OLD.actor_user_id
        THEN
            RAISE EXCEPTION 'only released_effective_time, released_by_transplant_event_id, and released_by_batch_derivation_event_id may change when releasing a batch_carrier_assignment';
        END IF;

        IF NEW.released_effective_time IS NULL
           OR (NEW.released_by_transplant_event_id IS NULL AND NEW.released_by_batch_derivation_event_id IS NULL)
        THEN
            RAISE EXCEPTION 'releasing a batch_carrier_assignment requires released_effective_time and exactly one typed releaser';
        END IF;

        IF NEW.released_by_transplant_event_id IS NOT NULL THEN
            IF NEW.opening_sowing_event_id IS NULL THEN
                RAISE EXCEPTION 'only sowing-origin assignments may be released by transplantation';
            END IF;

            SELECT batch_id, effective_time INTO v_transplant_batch_id, v_transplant_effective
            FROM transplant_events WHERE id = NEW.released_by_transplant_event_id;
            IF v_transplant_batch_id IS NULL THEN
                RAISE EXCEPTION 'releasing transplant event not found';
            END IF;
            IF v_transplant_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'releasing transplant event batch mismatch';
            END IF;
            IF v_transplant_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing transplant event''s effective time';
            END IF;

            SELECT transplant_event_id, source_carrier_id INTO v_source_line_event, v_source_line_carrier
            FROM transplant_source_lines WHERE source_batch_carrier_assignment_id = NEW.id;
            IF v_source_line_event IS NULL THEN
                RAISE EXCEPTION 'no transplant source line found for this assignment';
            END IF;
            IF v_source_line_event <> NEW.released_by_transplant_event_id THEN
                RAISE EXCEPTION 'source line event does not match released_by_transplant_event_id';
            END IF;
            IF v_source_line_carrier <> NEW.carrier_id THEN
                RAISE EXCEPTION 'source line carrier does not match assignment carrier';
            END IF;
        ELSE
            -- Unlike the transplant-release branch above, the matching
            -- batch_assignment_transfers row cannot be required to exist
            -- yet: the destination assignment (and therefore the
            -- transfer row, which references it) can only be inserted
            -- for this carrier *after* this same release frees the
            -- carrier's "one active assignment" slot. Full cross-table
            -- linkage (transfer exists, carrier/batch match, quantities
            -- reconcile) is proven by the deferred reconciliation
            -- trigger at commit instead.
            SELECT effective_time INTO v_derivation_effective
            FROM batch_derivation_events WHERE id = NEW.released_by_batch_derivation_event_id;
            IF v_derivation_effective IS NULL THEN
                RAISE EXCEPTION 'releasing batch derivation event not found';
            END IF;
            IF v_derivation_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing derivation event''s effective time';
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_MULTI_LINE_AWARE_CLOSURE_ONLY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_batch_carrier_assignment_closure_only_v2() RETURNS trigger AS $$
    DECLARE
        v_source_line_carrier UUID;
        v_transplant_batch_id UUID;
        v_transplant_effective TIMESTAMPTZ;
        v_derivation_effective TIMESTAMPTZ;
    BEGIN
        IF OLD.released_effective_time IS NOT NULL THEN
            RAISE EXCEPTION 'batch_carrier_assignment is already released and cannot be modified';
        END IF;

        IF NEW.tenant_id <> OLD.tenant_id
           OR NEW.farm_id <> OLD.farm_id
           OR NEW.batch_id <> OLD.batch_id
           OR NEW.carrier_id <> OLD.carrier_id
           OR NEW.batch_stage_run_id <> OLD.batch_stage_run_id
           OR NEW.assigned_effective_time <> OLD.assigned_effective_time
           OR NEW.opening_sowing_event_id IS DISTINCT FROM OLD.opening_sowing_event_id
           OR NEW.opening_transplant_event_id IS DISTINCT FROM OLD.opening_transplant_event_id
           OR NEW.opening_batch_derivation_event_id IS DISTINCT FROM OLD.opening_batch_derivation_event_id
           OR NEW.actor_user_id <> OLD.actor_user_id
        THEN
            RAISE EXCEPTION 'only released_effective_time, released_by_transplant_event_id, and released_by_batch_derivation_event_id may change when releasing a batch_carrier_assignment';
        END IF;

        IF NEW.released_effective_time IS NULL
           OR (NEW.released_by_transplant_event_id IS NULL AND NEW.released_by_batch_derivation_event_id IS NULL)
        THEN
            RAISE EXCEPTION 'releasing a batch_carrier_assignment requires released_effective_time and exactly one typed releaser';
        END IF;

        IF NEW.released_by_transplant_event_id IS NOT NULL THEN
            IF NEW.opening_sowing_event_id IS NULL THEN
                RAISE EXCEPTION 'only sowing-origin assignments may be released by transplantation';
            END IF;

            SELECT batch_id, effective_time INTO v_transplant_batch_id, v_transplant_effective
            FROM transplant_events WHERE id = NEW.released_by_transplant_event_id;
            IF v_transplant_batch_id IS NULL THEN
                RAISE EXCEPTION 'releasing transplant event not found';
            END IF;
            IF v_transplant_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'releasing transplant event batch mismatch';
            END IF;
            IF v_transplant_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing transplant event''s effective time';
            END IF;

            -- NURSERY-OPS-004A: a modern source assignment may have MULTIPLE
            -- transplant_source_lines across sequential events (partial
            -- transplant) -- filter directly on the releasing event itself
            -- rather than an unordered, ambiguous SELECT over all of them.
            SELECT source_carrier_id INTO v_source_line_carrier
            FROM transplant_source_lines
            WHERE source_batch_carrier_assignment_id = NEW.id
              AND transplant_event_id = NEW.released_by_transplant_event_id;
            IF v_source_line_carrier IS NULL THEN
                RAISE EXCEPTION 'no transplant source line found for this assignment and its releasing transplant event';
            END IF;
            IF v_source_line_carrier <> NEW.carrier_id THEN
                RAISE EXCEPTION 'source line carrier does not match assignment carrier';
            END IF;
        ELSE
            -- Unlike the transplant-release branch above, the matching
            -- batch_assignment_transfers row cannot be required to exist
            -- yet: the destination assignment (and therefore the
            -- transfer row, which references it) can only be inserted
            -- for this carrier *after* this same release frees the
            -- carrier's "one active assignment" slot. Full cross-table
            -- linkage (transfer exists, carrier/batch match, quantities
            -- reconcile) is proven by the deferred reconciliation
            -- trigger at commit instead.
            SELECT effective_time INTO v_derivation_effective
            FROM batch_derivation_events WHERE id = NEW.released_by_batch_derivation_event_id;
            IF v_derivation_effective IS NULL THEN
                RAISE EXCEPTION 'releasing batch derivation event not found';
            END IF;
            IF v_derivation_effective <> NEW.released_effective_time THEN
                RAISE EXCEPTION 'released_effective_time must match the releasing derivation event''s effective time';
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    bind = op.get_bind()

    # --- section 37: guard -- refuse to semantically upgrade source_plant_count
    # for pre-existing rows; never fabricate authoritative history. -----------------
    existing_count = bind.execute(sa.text("SELECT count(*) FROM transplant_source_lines")).scalar_one()
    if existing_count > 0:
        raise RuntimeError(
            "Cannot apply NURSERY-OPS-004A: "
            f"{existing_count} transplant_source_lines row(s) already exist. source_plant_count is "
            "changing meaning to a server-derived authoritative quantity, and this migration will not "
            "fabricate that history from sown_site_count, seed_count, or any other assumption. "
            "Move/export the affected data out-of-band before upgrading, or do not upgrade."
        )

    # --- 1. seedling_entries: composite unique needed as a checkpoint FK target ----
    op.create_unique_constraint(
        "uq_seedling_entries_tenant_farm_id", "seedling_entries", ["tenant_id", "farm_id", "id"]
    )

    # --- 2. transplant_source_lines evolution ---------------------------------------
    op.add_column(
        "transplant_source_lines",
        sa.Column("transplant_damage_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "transplant_source_lines",
        sa.Column("qc_rejection_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "transplant_source_lines", sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "transplant_source_lines", sa.Column("other_loss_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("transplant_source_lines", sa.Column("other_loss_note", sa.String(), nullable=True))
    op.alter_column("transplant_source_lines", "transplant_damage_count", server_default=None)
    op.alter_column("transplant_source_lines", "qc_rejection_count", server_default=None)
    op.alter_column("transplant_source_lines", "sample_count", server_default=None)
    op.alter_column("transplant_source_lines", "other_loss_count", server_default=None)

    op.create_check_constraint(
        "ck_transplant_source_lines_damage_non_negative", "transplant_source_lines", "transplant_damage_count >= 0"
    )
    op.create_check_constraint(
        "ck_transplant_source_lines_rejection_non_negative", "transplant_source_lines", "qc_rejection_count >= 0"
    )
    op.create_check_constraint(
        "ck_transplant_source_lines_sample_non_negative", "transplant_source_lines", "sample_count >= 0"
    )
    op.create_check_constraint(
        "ck_transplant_source_lines_other_loss_non_negative", "transplant_source_lines", "other_loss_count >= 0"
    )
    op.create_check_constraint(
        "ck_transplant_source_lines_discarded_matches_categories",
        "transplant_source_lines",
        "discarded_plant_count = transplant_damage_count + qc_rejection_count + sample_count + other_loss_count",
    )
    op.create_check_constraint(
        "ck_transplant_source_lines_other_loss_requires_note",
        "transplant_source_lines",
        "other_loss_count = 0 OR (other_loss_note IS NOT NULL AND btrim(other_loss_note) <> '')",
    )

    op.drop_constraint("ux_transplant_source_lines_assignment", "transplant_source_lines", type_="unique")
    op.create_unique_constraint(
        "ux_transplant_source_lines_event_assignment",
        "transplant_source_lines",
        ["transplant_event_id", "source_batch_carrier_assignment_id"],
    )
    op.create_unique_constraint(
        "uq_transplant_source_lines_tenant_farm_id", "transplant_source_lines", ["tenant_id", "farm_id", "id"]
    )

    # --- 3. seedling_source_checkpoints (new) ---------------------------------------
    op.create_table(
        "seedling_source_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "seedling_entry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seedling_entries.id"),
            nullable=False,
        ),
        sa.Column(
            "source_batch_carrier_assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"), nullable=False,
        ),
        sa.Column(
            "transplant_source_line_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transplant_source_lines.id"), nullable=False,
        ),
        sa.Column(
            "previous_checkpoint_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seedling_source_checkpoints.id"),
            nullable=True,
        ),
        sa.Column("remainder_after", sa.Integer(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("remainder_after >= 0", name="ck_seedling_source_checkpoints_remainder_non_negative"),
        sa.UniqueConstraint("transplant_source_line_id", name="ux_seedling_source_checkpoints_source_line"),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_seedling_source_checkpoints_tenant_farm_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_seedling_source_checkpoints_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "seedling_entry_id"],
            ["seedling_entries.tenant_id", "seedling_entries.farm_id", "seedling_entries.id"],
            name="fk_seedling_source_checkpoints_tenant_farm_entry",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "transplant_source_line_id"],
            [
                "transplant_source_lines.tenant_id", "transplant_source_lines.farm_id",
                "transplant_source_lines.id",
            ],
            name="fk_seedling_source_checkpoints_tenant_farm_source_line",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id", "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_seedling_source_checkpoints_tenant_farm_assignment",
        ),
    )
    op.create_index(
        "ux_seedling_source_checkpoints_previous_once",
        "seedling_source_checkpoints", ["previous_checkpoint_id"], unique=True,
    )
    op.create_index(
        "ix_seedling_source_checkpoints_entry_effective",
        "seedling_source_checkpoints", ["seedling_entry_id", "effective_time"],
    )

    op.execute(_CHECKPOINT_INTEGRITY_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER seedling_source_checkpoints_enforce_insert_integrity
        BEFORE INSERT ON seedling_source_checkpoints
        FOR EACH ROW EXECUTE FUNCTION enforce_seedling_source_checkpoint_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER seedling_source_checkpoints_no_update
        BEFORE UPDATE ON seedling_source_checkpoints
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER seedling_source_checkpoints_no_delete
        BEFORE DELETE ON seedling_source_checkpoints
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER seedling_source_checkpoints_enforce_reconciliation
        AFTER INSERT ON seedling_source_checkpoints
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_transplant_reconciliation();
        """
    )

    # --- 4. CREATE OR REPLACE the four checkpoint/multi-line-aware trigger functions
    bind.execute(sa.text(_CHECKPOINT_AWARE_EVENT_INTEGRITY_FUNCTION))
    bind.execute(sa.text(_MODERN_TRANSPLANT_SOURCE_LINE_INTEGRITY_FUNCTION))
    bind.execute(sa.text(_CHECKPOINT_AWARE_TRANSPLANT_RECONCILIATION_FUNCTION))
    bind.execute(sa.text(_MULTI_LINE_AWARE_CLOSURE_ONLY_FUNCTION))


def downgrade() -> None:
    bind = op.get_bind()

    # --- section 38: downgrade guard -- never discard checkpoint history -----------
    checkpoint_count = bind.execute(sa.text("SELECT count(*) FROM seedling_source_checkpoints")).scalar_one()
    if checkpoint_count > 0:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-004A: "
            f"{checkpoint_count} seedling_source_checkpoints row(s) exist. Downgrading would drop real "
            "transplant source-accounting history. Move/export the affected data out-of-band before "
            "downgrading, or do not downgrade."
        )

    # --- section 39: downgrade guard -- old lifetime-once uniqueness cannot be
    # restored if modern partial-transplant history already violates it -----------
    dup = bind.execute(
        sa.text(
            "SELECT source_batch_carrier_assignment_id, count(*) AS c FROM transplant_source_lines "
            "GROUP BY source_batch_carrier_assignment_id HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if dup is not None:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-004A: source assignment "
            f"{dup[0]} appears in {dup[1]} transplant events. The old lifetime-once "
            "UNIQUE(source_batch_carrier_assignment_id) constraint cannot represent this modern "
            "partial-transplant history. Move/export the affected data out-of-band before downgrading, "
            "or do not downgrade."
        )

    bind.execute(sa.text(_ORIGINAL_CLOSURE_ONLY_FUNCTION))
    bind.execute(sa.text(_ORIGINAL_TRANSPLANT_RECONCILIATION_FUNCTION))
    bind.execute(sa.text(_ORIGINAL_TRANSPLANT_SOURCE_LINE_INTEGRITY_FUNCTION))
    bind.execute(sa.text(_ORIGINAL_EVENT_INTEGRITY_FUNCTION))

    op.execute(
        "DROP TRIGGER IF EXISTS seedling_source_checkpoints_enforce_reconciliation ON seedling_source_checkpoints"
    )
    op.execute("DROP TRIGGER IF EXISTS seedling_source_checkpoints_no_delete ON seedling_source_checkpoints")
    op.execute("DROP TRIGGER IF EXISTS seedling_source_checkpoints_no_update ON seedling_source_checkpoints")
    op.execute(
        "DROP TRIGGER IF EXISTS seedling_source_checkpoints_enforce_insert_integrity "
        "ON seedling_source_checkpoints"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_seedling_source_checkpoint_insert_integrity()")
    op.drop_index("ix_seedling_source_checkpoints_entry_effective", table_name="seedling_source_checkpoints")
    op.drop_index("ux_seedling_source_checkpoints_previous_once", table_name="seedling_source_checkpoints")
    op.drop_table("seedling_source_checkpoints")

    op.drop_constraint("uq_transplant_source_lines_tenant_farm_id", "transplant_source_lines", type_="unique")
    op.drop_constraint("ux_transplant_source_lines_event_assignment", "transplant_source_lines", type_="unique")
    op.create_unique_constraint(
        "ux_transplant_source_lines_assignment", "transplant_source_lines", ["source_batch_carrier_assignment_id"]
    )

    op.drop_constraint("ck_transplant_source_lines_other_loss_requires_note", "transplant_source_lines", type_="check")
    op.drop_constraint(
        "ck_transplant_source_lines_discarded_matches_categories", "transplant_source_lines", type_="check"
    )
    op.drop_constraint("ck_transplant_source_lines_other_loss_non_negative", "transplant_source_lines", type_="check")
    op.drop_constraint("ck_transplant_source_lines_sample_non_negative", "transplant_source_lines", type_="check")
    op.drop_constraint("ck_transplant_source_lines_rejection_non_negative", "transplant_source_lines", type_="check")
    op.drop_constraint("ck_transplant_source_lines_damage_non_negative", "transplant_source_lines", type_="check")

    op.drop_column("transplant_source_lines", "other_loss_note")
    op.drop_column("transplant_source_lines", "other_loss_count")
    op.drop_column("transplant_source_lines", "sample_count")
    op.drop_column("transplant_source_lines", "qc_rejection_count")
    op.drop_column("transplant_source_lines", "transplant_damage_count")

    op.drop_constraint("uq_seedling_entries_tenant_farm_id", "seedling_entries", type_="unique")
