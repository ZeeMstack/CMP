"""germination outcome snapshot (modern, individual-seedling-based)

NURSERY-OPS-002B -- FROZEN product decision: the modern Imperial Germination
outcome is INDIVIDUAL-SEEDLING-based, not site/cell-based. Operators count
individual emerged seedlings/plants; both "normal" and "abnormal" seedlings
are LIVING and are NOT a loss at Germination. The legacy `germination_checks`
table (CMP-010) remains completely untouched in meaning -- it stays a
site/cell-based historical observation, valid only when a Sowing line's
`sown_site_count` was actually recorded. Neither table is redefined in terms
of the other; no historical row of either is rewritten, reinterpreted, or
migrated into the other's shape.

Three changes:

1. Corrects a real semantic defect in `enforce_germination_check_insert_integrity`
   (CMP-010, `e29b5c1a7d43`): a `SELECT ... INTO` cannot distinguish "no
   SowingEventLine row exists" from "the row exists but `sown_site_count` is
   NULL" -- both produced the exact same ("no sowing line found") exception.
   Since the NURSERY-OPS-001 operator Sowing command always leaves
   `sown_site_count = NULL` (NURSERY-OPS-001.1, `a7e4f2c9b381`), this bug
   meant a Tray sown through the modern operator flow could NEVER record a
   legacy site-based GerminationCheck, with a misleading error message.
   Fixed via `CREATE OR REPLACE FUNCTION` (same precedent as
   `enforce_sowing_event_line_insert_integrity`'s own prior replacement in
   `a7e4f2c9b381`) -- the historical migration file that created this
   function is NOT edited. The corrected function now raises a distinct,
   accurate message for the "row exists, no site count recorded" case, and
   still requires a genuinely-recorded `sown_site_count` before accepting a
   site-based check -- it does NOT fall back to `seed_count` and does NOT
   make legacy GerminationCheck silently writable for modern-sown Trays.

2. Creates `germination_outcome_snapshots`, reusing the EXISTING
   `observation_events` table as its immutable header (same tenant/farm/
   batch scope, actor, effective_time, client_command_id, request
   fingerprint, and idempotency/audit machinery already proven by CMP-010 --
   no second event-header framework). One row per (event, assignment); an
   assignment may have many snapshot rows across many events over time
   (point-in-time snapshots, never additive -- see `observation_service.py`).

3. Adds direct-write DB integrity for the new table: tenant/farm/batch
   consistency, seed_tray carrier type, real Sowing provenance
   (`SowingEventLine.seed_count`, never `sown_site_count`), non-negative
   counts, `normal + abnormal <= seed_count` (never required to equal it --
   the gap is deliberately left uncategorized, see `SEED_SOWING_MODEL.md`),
   temporal assignment validity (effective_time within
   `[assigned_effective_time, released_effective_time)`, not merely "is the
   assignment currently unreleased" -- a historical entry must remain valid
   even after the Tray has since been released), and the "no newer
   provisional snapshot after an established completed handoff" invariant
   from section 12 of the ticket. Append-only (no UPDATE/DELETE), matching
   every other CMP-010 table.

4. NURSERY-OPS-002B.1: corrects `enforce_observation_event_insert_integrity`
   (CMP-010, `e29b5c1a7d43`) -- the historical migration file is NOT edited.
   The original function required `active_batch_stage_run_id` to reference
   the batch's CURRENTLY-open (non-exited) stage run unconditionally, which
   silently defeats a genuinely historical Germination outcome: once the
   batch has progressed past the stage that was truthfully active at the
   outcome's own `effective_time`, no reference to that (now-exited, but
   historically correct) run could ever pass this trigger, even though
   `observation_service.record_observation`'s own service-layer resolution
   (see below) correctly identifies it. The corrected function instead
   requires the referenced run's own `[entered_effective_time,
   exited_effective_time)` window to cover `NEW.effective_time` -- a strict
   generalization, not a loosening: for a "now" `effective_time` this is
   identical to the original rule (only the currently-open run's window
   ever covers "now"), and it additionally permits a genuinely historical
   event to reference the run that was truthfully active back then. Every
   existing caller (`values`/legacy `germination_checks`, via
   `observation_service.record_observation`'s own unchanged, still-current-
   run-only resolution for those paths) never presents an exited run to
   this trigger regardless of what it now permits, so this is a dormant,
   defense-in-depth widening for them -- observably unchanged behavior --
   and the trigger the modern Germination outcome's own historical
   resolution genuinely depends on to function at all. Isolating this
   entirely inside `germination_outcome_snapshots`'s own trigger is not
   possible: `active_batch_stage_run_id` lives on `observation_events`
   itself, inserted before any snapshot row, so only `ObservationEvent`'s
   own trigger can gate it.

Revision ID: 7bddca3261cc
Revises: c2d6f8a4b153
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '7bddca3261cc'
down_revision: Union[str, None] = 'c2d6f8a4b153'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ORIGINAL_GERMINATION_CHECK_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_germination_check_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_event_batch_id UUID;
        v_event_effective TIMESTAMPTZ;
        v_assignment_batch_id UUID;
        v_assignment_assigned TIMESTAMPTZ;
        v_sown_site_count INTEGER;
    BEGIN
        SELECT batch_id, effective_time INTO v_event_batch_id, v_event_effective
        FROM observation_events WHERE id = NEW.observation_event_id;

        SELECT batch_id, assigned_effective_time INTO v_assignment_batch_id, v_assignment_assigned
        FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;
        IF v_assignment_batch_id IS NULL THEN
            RAISE EXCEPTION 'assignment not found';
        END IF;
        IF v_assignment_batch_id <> v_event_batch_id THEN
            RAISE EXCEPTION 'assignment does not belong to this observation event''s batch';
        END IF;
        IF v_event_effective < v_assignment_assigned THEN
            RAISE EXCEPTION 'observation effective time precedes assignment assigned_effective_time';
        END IF;

        SELECT sown_site_count INTO v_sown_site_count
        FROM sowing_event_lines WHERE batch_carrier_assignment_id = NEW.batch_carrier_assignment_id;
        IF v_sown_site_count IS NULL THEN
            RAISE EXCEPTION 'no sowing line found for this assignment';
        END IF;
        IF NEW.inspected_site_count > v_sown_site_count THEN
            RAISE EXCEPTION 'inspected_site_count cannot exceed the assignment''s original sown_site_count';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_CORRECTED_GERMINATION_CHECK_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_germination_check_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_event_batch_id UUID;
        v_event_effective TIMESTAMPTZ;
        v_assignment_batch_id UUID;
        v_assignment_assigned TIMESTAMPTZ;
        v_sown_site_count INTEGER;
    BEGIN
        SELECT batch_id, effective_time INTO v_event_batch_id, v_event_effective
        FROM observation_events WHERE id = NEW.observation_event_id;

        SELECT batch_id, assigned_effective_time INTO v_assignment_batch_id, v_assignment_assigned
        FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;
        IF v_assignment_batch_id IS NULL THEN
            RAISE EXCEPTION 'assignment not found';
        END IF;
        IF v_assignment_batch_id <> v_event_batch_id THEN
            RAISE EXCEPTION 'assignment does not belong to this observation event''s batch';
        END IF;
        IF v_event_effective < v_assignment_assigned THEN
            RAISE EXCEPTION 'observation effective time precedes assignment assigned_effective_time';
        END IF;

        -- NURSERY-OPS-002B: distinguish "no SowingEventLine row at all" from
        -- "the row exists but sown_site_count was never recorded" -- these
        -- are different facts and must not share one message. Postgres's
        -- implicit FOUND is set by the SELECT INTO immediately above.
        SELECT sown_site_count INTO v_sown_site_count
        FROM sowing_event_lines WHERE batch_carrier_assignment_id = NEW.batch_carrier_assignment_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'no sowing line found for this assignment';
        END IF;
        IF v_sown_site_count IS NULL THEN
            RAISE EXCEPTION 'Site-based GerminationCheck requires a recorded sown_site_count; this assignment''s Sowing line has none on record.';
        END IF;
        IF NEW.inspected_site_count > v_sown_site_count THEN
            RAISE EXCEPTION 'inspected_site_count cannot exceed the assignment''s original sown_site_count';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_ORIGINAL_OBSERVATION_EVENT_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_observation_event_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_run_batch_id UUID;
        v_run_exited TIMESTAMPTZ;
        v_batch_state TEXT;
    BEGIN
        SELECT batch_id, exited_effective_time INTO v_run_batch_id, v_run_exited
        FROM batch_stage_runs WHERE id = NEW.active_batch_stage_run_id;
        IF v_run_batch_id IS NULL THEN
            RAISE EXCEPTION 'active stage run not found';
        END IF;
        IF v_run_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'stage run does not belong to this batch';
        END IF;
        IF v_run_exited IS NOT NULL THEN
            RAISE EXCEPTION 'observation requires the batch''s currently active stage run';
        END IF;

        SELECT state INTO v_batch_state FROM crop_batches WHERE id = NEW.batch_id;
        IF v_batch_state IS DISTINCT FROM 'active' THEN
            RAISE EXCEPTION 'crop batch is not active';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_CORRECTED_OBSERVATION_EVENT_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_observation_event_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_run_batch_id UUID;
        v_run_entered TIMESTAMPTZ;
        v_run_exited TIMESTAMPTZ;
        v_batch_state TEXT;
    BEGIN
        SELECT batch_id, entered_effective_time, exited_effective_time
        INTO v_run_batch_id, v_run_entered, v_run_exited
        FROM batch_stage_runs WHERE id = NEW.active_batch_stage_run_id;
        IF v_run_batch_id IS NULL THEN
            RAISE EXCEPTION 'active stage run not found';
        END IF;
        IF v_run_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'stage run does not belong to this batch';
        END IF;

        -- NURSERY-OPS-002B.1: a stage run is valid context for an event
        -- whose effective_time falls within the run's own historical
        -- window -- not merely a run that still happens to be open today.
        -- Strictly generalizes the original "must be currently active"
        -- rule: for a "now" effective_time this is identical (only the
        -- currently-open run's window ever covers "now"); it additionally
        -- permits a genuinely historical event to reference a since-exited
        -- run that was truthfully active at that time.
        IF NEW.effective_time < v_run_entered THEN
            RAISE EXCEPTION 'observation effective_time precedes the referenced stage run''s entry time';
        END IF;
        IF v_run_exited IS NOT NULL AND NEW.effective_time >= v_run_exited THEN
            RAISE EXCEPTION 'observation effective_time is at or after the referenced stage run''s exit time';
        END IF;

        SELECT state INTO v_batch_state FROM crop_batches WHERE id = NEW.batch_id;
        IF v_batch_state IS DISTINCT FROM 'active' THEN
            RAISE EXCEPTION 'crop batch is not active';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. correct the legacy GerminationCheck NULL-vs-missing-row defect --
    bind.execute(sa.text(_CORRECTED_GERMINATION_CHECK_INTEGRITY_FUNCTION))

    # --- 1b. correct ObservationEvent's stage-run window check (002B.1) -----
    bind.execute(sa.text(_CORRECTED_OBSERVATION_EVENT_INTEGRITY_FUNCTION))

    # --- 2. germination_outcome_snapshots (immutable) -----------------------
    op.create_table(
        "germination_outcome_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "observation_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("observation_events.id"),
            nullable=False,
        ),
        sa.Column(
            "batch_carrier_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"),
            nullable=False,
        ),
        sa.Column("normal_seedling_count", sa.Integer(), nullable=False),
        sa.Column("abnormal_seedling_count", sa.Integer(), nullable=False),
        sa.Column("assessment_complete", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "normal_seedling_count >= 0", name="ck_germination_outcome_snapshots_normal_non_negative"
        ),
        sa.CheckConstraint(
            "abnormal_seedling_count >= 0", name="ck_germination_outcome_snapshots_abnormal_non_negative"
        ),
        sa.UniqueConstraint(
            "observation_event_id", "batch_carrier_assignment_id",
            name="ux_germination_outcome_snapshots_event_assignment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "observation_event_id"],
            ["observation_events.tenant_id", "observation_events.farm_id", "observation_events.id"],
            name="fk_germination_outcome_snapshots_tenant_farm_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_germination_outcome_snapshots_tenant_farm_assignment",
        ),
    )
    op.create_index(
        "ix_germination_outcome_snapshots_assignment",
        "germination_outcome_snapshots",
        ["batch_carrier_assignment_id"],
    )

    # --- 3. direct-write integrity -------------------------------------------
    op.execute(
        """
        CREATE FUNCTION enforce_germination_outcome_snapshot_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_event_batch_id UUID;
            v_event_effective TIMESTAMPTZ;
            v_assignment_batch_id UUID;
            v_assignment_assigned TIMESTAMPTZ;
            v_assignment_released TIMESTAMPTZ;
            v_assignment_carrier_id UUID;
            v_carrier_type_code TEXT;
            v_seed_count INTEGER;
            v_latest_completed_effective TIMESTAMPTZ;
            v_latest_provisional_effective TIMESTAMPTZ;
        BEGIN
            SELECT batch_id, effective_time INTO v_event_batch_id, v_event_effective
            FROM observation_events WHERE id = NEW.observation_event_id;

            SELECT batch_id, assigned_effective_time, released_effective_time, carrier_id
            INTO v_assignment_batch_id, v_assignment_assigned, v_assignment_released, v_assignment_carrier_id
            FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;
            IF v_assignment_batch_id IS NULL THEN
                RAISE EXCEPTION 'assignment not found';
            END IF;
            IF v_assignment_batch_id <> v_event_batch_id THEN
                RAISE EXCEPTION 'assignment does not belong to this observation event''s batch';
            END IF;

            -- Temporal truth, not current-state truth (section 17): a
            -- historical entry must remain valid if effective_time occurred
            -- while the assignment was actually active, even if the
            -- assignment has SINCE been released.
            IF v_event_effective < v_assignment_assigned THEN
                RAISE EXCEPTION 'outcome effective time precedes assignment assigned_effective_time';
            END IF;
            IF v_assignment_released IS NOT NULL AND v_event_effective >= v_assignment_released THEN
                RAISE EXCEPTION 'outcome effective time is at or after the assignment''s release; the assignment was not active at that time';
            END IF;

            SELECT ct.code INTO v_carrier_type_code
            FROM carriers c JOIN carrier_types ct ON ct.id = c.carrier_type_id
            WHERE c.id = v_assignment_carrier_id;
            IF v_carrier_type_code IS DISTINCT FROM 'seed_tray' THEN
                RAISE EXCEPTION 'germination outcome assignment must be a seed_tray carrier';
            END IF;

            -- Modern outcome anchors to seed_count, never sown_site_count.
            SELECT seed_count INTO v_seed_count
            FROM sowing_event_lines WHERE batch_carrier_assignment_id = NEW.batch_carrier_assignment_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'no sowing line found for this assignment';
            END IF;
            IF NEW.normal_seedling_count + NEW.abnormal_seedling_count > v_seed_count THEN
                RAISE EXCEPTION 'normal and abnormal seedling counts cannot exceed the assignment''s authoritative seed_count';
            END IF;

            -- Section 12/23.E: once a completed handoff exists, a newer
            -- provisional snapshot cannot reopen it -- enforced in BOTH
            -- directions so the invariant holds even when two concurrent
            -- commands race and arrive in an order that disagrees with
            -- their own effective_time values (the batch-row lock in
            -- `observation_service.record_observation` serializes the two
            -- transactions, but which one acquires the lock FIRST is
            -- independent of which effective_time is chronologically
            -- earlier -- only a symmetric check makes the final state
            -- correct regardless of arrival order). A historical backfill
            -- provisional (effective_time <= the latest completion) remains
            -- allowed; multiple completed snapshots over time remain
            -- allowed as long as no already-committed provisional is newer.
            IF NOT NEW.assessment_complete THEN
                SELECT max(oe.effective_time) INTO v_latest_completed_effective
                FROM germination_outcome_snapshots gos
                JOIN observation_events oe ON oe.id = gos.observation_event_id
                WHERE gos.batch_carrier_assignment_id = NEW.batch_carrier_assignment_id
                AND gos.assessment_complete = true;
                IF v_latest_completed_effective IS NOT NULL AND v_event_effective > v_latest_completed_effective THEN
                    RAISE EXCEPTION 'assignment already has a completed Germination outcome at or after this effective time; a new provisional snapshot cannot be recorded after an established handoff';
                END IF;
            ELSE
                SELECT max(oe.effective_time) INTO v_latest_provisional_effective
                FROM germination_outcome_snapshots gos
                JOIN observation_events oe ON oe.id = gos.observation_event_id
                WHERE gos.batch_carrier_assignment_id = NEW.batch_carrier_assignment_id
                AND gos.assessment_complete = false;
                IF v_latest_provisional_effective IS NOT NULL AND v_latest_provisional_effective > v_event_effective THEN
                    RAISE EXCEPTION 'a provisional Germination outcome with a later effective time already exists for this assignment; record a new provisional correction or use a later effective time for this completed outcome';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER germination_outcome_snapshots_enforce_insert_integrity
        BEFORE INSERT ON germination_outcome_snapshots
        FOR EACH ROW EXECUTE FUNCTION enforce_germination_outcome_snapshot_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER germination_outcome_snapshots_no_update
        BEFORE UPDATE ON germination_outcome_snapshots
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER germination_outcome_snapshots_no_delete
        BEFORE DELETE ON germination_outcome_snapshots
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: never silently discard modern biological history -
    existing = bind.execute(sa.text("SELECT count(*) FROM germination_outcome_snapshots")).scalar_one()
    if existing > 0:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-002B: "
            f"{existing} germination_outcome_snapshots row(s) exist. Downgrading would drop real "
            "modern Germination outcome history. Move/export the affected data out-of-band before "
            "downgrading, or do not downgrade."
        )

    op.execute("DROP TRIGGER IF EXISTS germination_outcome_snapshots_no_delete ON germination_outcome_snapshots")
    op.execute("DROP TRIGGER IF EXISTS germination_outcome_snapshots_no_update ON germination_outcome_snapshots")
    op.execute(
        "DROP TRIGGER IF EXISTS germination_outcome_snapshots_enforce_insert_integrity "
        "ON germination_outcome_snapshots"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_germination_outcome_snapshot_insert_integrity()")

    op.drop_index("ix_germination_outcome_snapshots_assignment", table_name="germination_outcome_snapshots")
    op.drop_table("germination_outcome_snapshots")

    # --- revert 1: restore the legacy GerminationCheck function exactly -----
    # Pure function-body swap, touches no table row -- always safe regardless
    # of legacy GerminationCheck data present.
    bind.execute(sa.text(_ORIGINAL_GERMINATION_CHECK_INTEGRITY_FUNCTION))

    # --- revert 1b: restore ObservationEvent's original stricter check -----
    # Also a pure function-body swap -- no existing observation_events row
    # is re-validated when a trigger is replaced, so no row is touched. Safe
    # unconditionally: the germination_outcome_snapshots guard above already
    # refuses this downgrade whenever any modern outcome (the only feature
    # that could ever cause an event to reference an exited stage run) has
    # been recorded, so by this point none can exist.
    bind.execute(sa.text(_ORIGINAL_OBSERVATION_EVENT_INTEGRITY_FUNCTION))
