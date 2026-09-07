"""inventory quality command idempotency

STORE-INV-002A.2 CTO CLOSURE PASS -- corrects a genuine foundation defect
found during review of the initial `.2` implementation: `quality_
disposition_events` (created by `f1a4c8e7b2d5`, already deployed to
production) carries no DB-level uniqueness on `client_command_id` at all.
Locking the target `InventoryQuantityCohort` row before insert made
same-cohort replay safe, but a reused `client_command_id` submitted
concurrently against TWO DIFFERENT cohorts acquires two DIFFERENT row
locks and can slip past that guard entirely -- cohort-row locking cannot
establish tenant-wide command uniqueness on its own.

This migration is purely additive on top of the already-deployed
`f1a4c8e7b2d5` -- that historical migration file is never edited. Mirrors
the one existing precedent in this codebase for "one command header,
idempotent on `(tenant_id, client_command_id)`, fanning out to a variable
number of child event rows": `SeedlingDispositionCommand`/
`SeedlingDispositionEvent` (`b4e8a1f0d6c2`).

One new table, `inventory_quality_commands` -- the logical command header
every `.2` Quality command now writes exactly once, before any
`QualityDispositionEvent` row:

- `operation_kind`: `RECORD` (ordinary whole-cohort disposition, one
  event) | `CORRECT` (whole-cohort correction: one REVERSAL, optionally
  one replacement -- both same command) | `PARTIAL` (ordinary partial-
  quantity disposition via the existing `_split_cohort_core` primitive,
  one child event) | `PARTIAL_CORRECT` (the new "Correct decision for
  part of quantity" command -- also one child event, but bypassing the
  ordinary transition table since it is compensating for a mistaken
  classification, never an ordinary forward transition).
- `target_event_id`: required for `CORRECT`/`PARTIAL_CORRECT` (the
  specific event the operator observed and is now acting on), forbidden
  for `RECORD`/`PARTIAL` -- CHECK-enforced.
- `(tenant_id, client_command_id)` UNIQUE -- the actual fix. Two
  concurrent requests sharing one `client_command_id`, even against
  different cohorts, can never both insert a command row: the loser's
  `db.flush()` raises `IntegrityError` on this exact constraint, caught
  and resolved to either a replay (identical fingerprint) or a conflict
  (different fingerprint) -- never two logical commands.

The automatic, receipt-time `RECEIVED_QUARANTINED` opening event
(written directly by `.1`'s `goods_receipt_service`, no command involved)
is explicitly NOT part of this model -- it is a system/receipt fact, never
an independent human quality command, and must never be distorted to fit
one. `quality_disposition_events.command_id` is therefore NULLABLE: NULL
for the automatic opening fact (the only kind of row that could possibly
already exist in production under this column, satisfying the new CHECK
constraint against every historical row with zero backfill), NOT NULL for
every event any `.2` command has ever written or ever will write again.

A new insert-integrity trigger on `inventory_quality_commands`
(`enforce_inventory_quality_command_insert_integrity`) is defense-in-depth
behind the equivalent service-layer checks -- NOT merely a structural
sanity check. For `CORRECT`/`PARTIAL_CORRECT`, it independently proves, at
INSERT time, every one of: `target_event_id` resolves to a real
`quality_disposition_event`; in this same tenant; on this exact command's
own `inventory_quantity_cohort_id`; is a human decision (never
`RECEIVED_QUARANTINED`, never itself a `REVERSAL`); is not itself already
reversed; and IS THE CURRENT effective, unreversed human decision for that
cohort -- no later, non-`REVERSAL`, not-itself-reversed event may exist,
using the exact same `(effective_time, recorded_time, id)` ordering
`.1`'s own `enforce_quality_disposition_event_insert_integrity` already
established for a REVERSAL's own target-currency check (never a
reinvented or duplicated notion of "current"). The trigger locks the
target `InventoryQuantityCohort` row `FOR UPDATE` FIRST, before evaluating
any of this, so a direct-SQL insert bypassing the service layer entirely
cannot race a concurrent command into an inconsistent current-event view
-- the same serialization guarantee the service's own `_lock_cohort`
already relies on, now also enforced independent of the service layer.
`PARTIAL_CORRECT` writes no REVERSAL row of its own, so `.1`'s existing
trigger (which only fires for `event_kind = 'REVERSAL'`) never covers it;
this new trigger is what closes that gap for `PARTIAL_CORRECT`
specifically, and redundantly re-covers `CORRECT` too (belt and suspenders
with `.1`'s own REVERSAL-target-currency trigger, not a replacement for it).

Downgrade is guarded, never blindly destructive: refuses while any
`inventory_quality_commands` row exists, or any `quality_disposition_
events` row already carries a non-null `command_id` -- mirroring
`b4e8a1f0d6c2`'s own guard idiom exactly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "abcdb6f371f9"
down_revision: str | None = "f1a4c8e7b2d5"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


_COMMAND_INTEGRITY_FUNCTION = """
CREATE OR REPLACE FUNCTION enforce_inventory_quality_command_insert_integrity() RETURNS trigger AS $$
DECLARE
    v_target_tenant_id UUID;
    v_target_cohort_id UUID;
    v_target_kind TEXT;
    v_target_effective_time TIMESTAMPTZ;
    v_target_recorded_time TIMESTAMPTZ;
    v_already_reversed_by UUID;
    v_superseding_event_id UUID;
BEGIN
    IF NEW.operation_kind IN ('CORRECT', 'PARTIAL_CORRECT') THEN
        -- Lock the target cohort FIRST -- the same row/lock the service
        -- layer's own _lock_cohort already holds for the whole
        -- read-validate-write sequence, so a direct-SQL insert bypassing
        -- the service entirely cannot race a concurrent command into an
        -- inconsistent view of "current".
        PERFORM 1 FROM inventory_quantity_cohorts WHERE id = NEW.inventory_quantity_cohort_id FOR UPDATE;

        SELECT tenant_id, inventory_quantity_cohort_id, event_kind, effective_time, recorded_time
        INTO v_target_tenant_id, v_target_cohort_id, v_target_kind, v_target_effective_time, v_target_recorded_time
        FROM quality_disposition_events WHERE id = NEW.target_event_id;

        IF v_target_tenant_id IS NULL THEN
            RAISE EXCEPTION 'target_event_id does not resolve to a quality_disposition_event';
        END IF;
        IF v_target_tenant_id <> NEW.tenant_id THEN
            RAISE EXCEPTION 'target_event_id does not belong to this tenant';
        END IF;
        IF v_target_cohort_id <> NEW.inventory_quantity_cohort_id THEN
            RAISE EXCEPTION 'target_event_id does not belong to this command''s own inventory_quantity_cohort_id';
        END IF;
        IF v_target_kind IN ('RECEIVED_QUARANTINED', 'REVERSAL') THEN
            RAISE EXCEPTION 'target_event_id must be a current human disposition event, never the automatic opening fact or a REVERSAL';
        END IF;

        -- The target must not itself already be reversed.
        SELECT r.id INTO v_already_reversed_by FROM quality_disposition_events r
            WHERE r.reverses_event_id = NEW.target_event_id LIMIT 1;
        IF v_already_reversed_by IS NOT NULL THEN
            RAISE EXCEPTION 'target_event_id has already been corrected -- it is no longer a current decision';
        END IF;

        -- The target must be the CURRENT effective event for this cohort:
        -- no later, non-REVERSAL, not-itself-reversed event may exist.
        -- Same (effective_time, recorded_time, id) ordering and exclusion
        -- rule f1a4c8e7b2d5's own
        -- enforce_quality_disposition_event_insert_integrity already
        -- enforces for a REVERSAL's own reverses_event_id -- never
        -- reinvented here.
        SELECT e2.id INTO v_superseding_event_id FROM quality_disposition_events e2
            WHERE e2.inventory_quantity_cohort_id = v_target_cohort_id
              AND e2.event_kind <> 'REVERSAL'
              AND (e2.effective_time, e2.recorded_time, e2.id) > (v_target_effective_time, v_target_recorded_time, NEW.target_event_id)
              AND NOT EXISTS (SELECT 1 FROM quality_disposition_events r2 WHERE r2.reverses_event_id = e2.id)
            LIMIT 1;
        IF v_superseding_event_id IS NOT NULL THEN
            RAISE EXCEPTION 'target_event_id is not the current disposition event for this cohort -- refresh and retry';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. inventory_quality_commands (target_event_id FK to the ALREADY
    # existing quality_disposition_events -- no circular-reference deferral
    # needed here, unlike the seedling precedent, since that table already
    # exists from f1a4c8e7b2d5) -------------------------------------------
    op.create_table(
        "inventory_quality_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "inventory_quantity_cohort_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_quantity_cohorts.id"), nullable=False,
        ),
        sa.Column("operation_kind", sa.String(), nullable=False),
        sa.Column(
            "target_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quality_disposition_events.id"),
            nullable=True,
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "operation_kind IN ('RECORD', 'CORRECT', 'PARTIAL', 'PARTIAL_CORRECT')",
            name="ck_inventory_quality_commands_operation_kind",
        ),
        sa.CheckConstraint(
            "(operation_kind IN ('RECORD', 'PARTIAL') AND target_event_id IS NULL) OR "
            "(operation_kind IN ('CORRECT', 'PARTIAL_CORRECT') AND target_event_id IS NOT NULL)",
            name="ck_inventory_quality_commands_target_matches_kind",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_quality_commands_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "client_command_id", name="ux_inventory_quality_commands_tenant_client_command_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_quantity_cohort_id"],
            ["inventory_quantity_cohorts.tenant_id", "inventory_quantity_cohorts.id"],
            name="fk_inventory_quality_commands_tenant_cohort",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_event_id"],
            ["quality_disposition_events.tenant_id", "quality_disposition_events.id"],
            name="fk_inventory_quality_commands_tenant_target_event",
        ),
    )

    bind.execute(sa.text(_COMMAND_INTEGRITY_FUNCTION))
    op.execute(
        """
        CREATE TRIGGER inventory_quality_commands_enforce_insert_integrity
        BEFORE INSERT ON inventory_quality_commands
        FOR EACH ROW EXECUTE FUNCTION enforce_inventory_quality_command_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_quality_commands_no_update
        BEFORE UPDATE ON inventory_quality_commands
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_quality_commands_no_delete
        BEFORE DELETE ON inventory_quality_commands
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # --- 2. quality_disposition_events.command_id (additive, nullable,
    # no backfill -- every existing production row is the automatic
    # RECEIVED_QUARANTINED opening fact, which correctly keeps NULL) -------
    op.add_column(
        "quality_disposition_events",
        sa.Column(
            "command_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_quality_commands.id"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_quality_disposition_events_command_id_matches_kind",
        "quality_disposition_events",
        "(event_kind = 'RECEIVED_QUARANTINED' AND command_id IS NULL) OR "
        "(event_kind <> 'RECEIVED_QUARANTINED' AND command_id IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_quality_disposition_events_tenant_command",
        "quality_disposition_events", "inventory_quality_commands",
        ["tenant_id", "command_id"], ["tenant_id", "id"],
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guards: never silently discard command-idempotency
    # evidence or command-linked disposition history --------------------
    existing_commands = bind.execute(sa.text("SELECT count(*) FROM inventory_quality_commands")).scalar_one()
    if existing_commands > 0:
        raise RuntimeError(
            "Cannot downgrade past the inventory quality command idempotency migration: "
            f"{existing_commands} inventory_quality_commands row(s) exist. Downgrading would drop real "
            "Quality command idempotency history. Move/export the affected data out-of-band before "
            "downgrading, or do not downgrade."
        )
    linked_events = bind.execute(
        sa.text("SELECT count(*) FROM quality_disposition_events WHERE command_id IS NOT NULL")
    ).scalar_one()
    if linked_events > 0:
        raise RuntimeError(
            "Cannot downgrade past the inventory quality command idempotency migration: "
            f"{linked_events} quality_disposition_events row(s) already carry a command_id even though no "
            "inventory_quality_commands row exists -- this indicates a partially-committed state that should "
            "not be possible under this migration's own atomicity guarantees. Investigate before downgrading."
        )

    op.drop_constraint(
        "fk_quality_disposition_events_tenant_command", "quality_disposition_events", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_quality_disposition_events_command_id_matches_kind", "quality_disposition_events", type_="check"
    )
    op.drop_column("quality_disposition_events", "command_id")

    op.execute("DROP TRIGGER IF EXISTS inventory_quality_commands_no_delete ON inventory_quality_commands")
    op.execute("DROP TRIGGER IF EXISTS inventory_quality_commands_no_update ON inventory_quality_commands")
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_quality_commands_enforce_insert_integrity "
        "ON inventory_quality_commands"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_quality_command_insert_integrity()")

    op.drop_table("inventory_quality_commands")
