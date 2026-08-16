"""seedling biological dispositions and current living quantity

NURSERY-OPS-003B -- adds biological quantity-reducing facts recorded AFTER
NURSERY-OPS-003A's `SeedlingEntry` anchor. See
`docs/domain/OBSERVATION_QUALITY_MODEL.md`'s NURSERY-OPS-003B addendum for
the full model writeup; this docstring summarizes only what the migration
itself does.

Three new tables:

1. `seedling_disposition_reasons` -- a global (no `tenant_id`), platform-
   defined, immutable catalog, seeded here with exactly the eight approved
   Seedling-stage reasons (WEAK_SEEDLING, DISEASE, PEST_DAMAGE,
   PHYSICAL_DAMAGE, MORTALITY, QC_REJECTION, SAMPLE, OTHER) --
   NON_GERMINATION and TRANSPLANT_DAMAGE are deliberately never seeded here
   (frozen product decision, section 0.3). `code` is the primary key (a
   deliberate, evidence-based departure from `location_types`/
   `carrier_types`'s own UUID-PK-plus-separate-code shape): it is
   referenced as a natural-key FK from `seedling_disposition_events.
   reason_code`, which is what lets "OTHER requires a note" be a same-row
   CHECK on the event table itself rather than needing a cross-table
   trigger.

2. `seedling_disposition_commands` -- the logical operator-command header.
   A RECORD command always produces exactly one child event (REDUCTION); a
   CORRECT command always produces exactly one REVERSAL and, optionally,
   one replacement REDUCTION -- both committed in the same transaction as
   the command header. This mirrors the same header-plus-variable-child-
   lines shape already established by `SowingEvent`/`TransplantEvent`/the
   modern Germination outcome's own `ObservationEvent` pairing.
   `target_event_id` is added via a deferred ALTER TABLE (step 4 below)
   since it forward-references `seedling_disposition_events`, which does
   not exist yet at this point in the migration -- a genuine circular
   reference (events.command_id -> commands.id, commands.target_event_id
   -> events.id) resolved by creating both tables first, then adding the
   second FK.

3. `seedling_disposition_events` -- immutable, insert-only. REDUCTION rows
   (`quantity_delta < 0`) record seedlings that stopped continuing in the
   living population; REVERSAL rows (`quantity_delta > 0`) are the exact
   negation of one specific, named prior REDUCTION (`reverses_event_id`) --
   accounting correction, never biological resurrection -- enforced by the
   insert-integrity trigger, not merely convention. A replacement REDUCTION
   created by the same correction command references what it replaces via
   `corrects_event_id` (provenance only; every event of either kind
   contributes its own signed `quantity_delta` identically to the balance
   arithmetic). `current_living_seedling_count` is never persisted --
   always `SeedlingEntry.starting_living_seedling_count +
   SUM(quantity_delta)`, and the insert-integrity trigger proves, on every
   insert, that this running balance never dips below zero or exceeds the
   frozen starting quantity at ANY effective-time point in chronological
   order (grouped by `effective_time`, not by insertion/recorded_at/UUID
   order -- section 24) -- not merely in the final aggregate.

Direct-write DB integrity (two trigger functions, both defense-in-depth
behind the equivalent service-layer checks in `seedling_disposition_
service.py`): tenant/farm/batch/seedling-entry/command/assignment
consistency; the "assignment must still be currently active" MVP safeguard
(section 0.E/29/43) applied to BOTH command and event inserts; temporal
bounds against the SeedlingEntry's own effective_time and the assignment's
`assigned_effective_time`; reversal integrity (target is a REDUCTION,
belongs to the same tenant/farm/seedling-entry, is not already reversed --
backstopped by a partial unique index -- exact delta/reason/effective_time
match, cannot self-reference, must belong to the CORRECT command that
targets it); replacement-correction linkage (must be a REDUCTION, must be
accompanied by a sibling REVERSAL of the same target within the same
command); the chronological balance walk. Append-only (no UPDATE/DELETE) on
both new mutable-looking tables, reusing the existing
`reject_append_only_mutation()` function (defined by `c48f21a6b3d9`, not
redefined here).

No changes to `movement_service`/Movement semantics, no changes to
`SeedlingEntry`'s own schema or trigger, no changes to `transplant_service`.
`BIOLOGICAL_DISPOSITION_MANAGE` (the new permission granting write access to
this domain) is NOT migration-backed -- CMP's permission catalog is a pure
Python enum + role-mapping dict (`app/core/permissions.py`), never
persisted to the database -- so no migration action is needed or included
for it.

Revision ID: b4e8a1f0d6c2
Revises: a3f7c9d2e0b1
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b4e8a1f0d6c2'
down_revision: Union[str, None] = 'a3f7c9d2e0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_APPROVED_REASONS = [
    ("WEAK_SEEDLING", "Weak seedling removed from continuation"),
    ("DISEASE", "Disease"),
    ("PEST_DAMAGE", "Pest damage"),
    ("PHYSICAL_DAMAGE", "Physical damage"),
    ("MORTALITY", "Confirmed mortality"),
    ("QC_REJECTION", "QC rejection (stops progressing)"),
    ("SAMPLE", "Destructive sample"),
    ("OTHER", "Other (note required)"),
]

_CHRONOLOGICAL_BALANCE_MARKER = "CMP-DOMAIN-SEEDLING-003B chronological balance violated"

_COMMAND_INTEGRITY_FUNCTION = """
    CREATE FUNCTION enforce_seedling_disposition_command_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_entry_tenant_id UUID;
        v_entry_farm_id UUID;
        v_entry_batch_id UUID;
        v_entry_assignment_id UUID;
        v_assignment_released TIMESTAMPTZ;
        v_target_seedling_entry_id UUID;
        v_target_tenant_id UUID;
        v_target_farm_id UUID;
    BEGIN
        SELECT tenant_id, farm_id, batch_id, batch_carrier_assignment_id
        INTO v_entry_tenant_id, v_entry_farm_id, v_entry_batch_id, v_entry_assignment_id
        FROM seedling_entries WHERE id = NEW.seedling_entry_id;
        IF v_entry_tenant_id IS NULL THEN
            RAISE EXCEPTION 'seedling entry not found';
        END IF;
        IF v_entry_tenant_id <> NEW.tenant_id OR v_entry_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'seedling entry does not belong to this tenant/farm';
        END IF;
        IF v_entry_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'seedling entry does not belong to this batch';
        END IF;

        -- Section 29/43: a NEW command may only be created while the source
        -- assignment is still currently active/unreleased -- deliberate,
        -- temporary MVP safeguard (see module docstring).
        SELECT released_effective_time INTO v_assignment_released
        FROM batch_carrier_assignments WHERE id = v_entry_assignment_id;
        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'assignment has already been released; no new Seedling disposition command may be created';
        END IF;

        IF NEW.operation_kind = 'CORRECT' THEN
            SELECT seedling_entry_id, tenant_id, farm_id
            INTO v_target_seedling_entry_id, v_target_tenant_id, v_target_farm_id
            FROM seedling_disposition_events WHERE id = NEW.target_event_id;
            IF v_target_seedling_entry_id IS NULL THEN
                RAISE EXCEPTION 'target event not found';
            END IF;
            IF v_target_tenant_id <> NEW.tenant_id OR v_target_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'target event does not belong to this tenant/farm';
            END IF;
            IF v_target_seedling_entry_id <> NEW.seedling_entry_id THEN
                RAISE EXCEPTION 'target event does not belong to this seedling entry';
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_EVENT_INTEGRITY_FUNCTION = """
    CREATE FUNCTION enforce_seedling_disposition_event_insert_integrity() RETURNS trigger AS $$
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

        -- Section 24/26/82: chronological balance -- group ALL deltas
        -- (existing rows for this seedling_entry_id + NEW's own) by
        -- effective_time, walk forward in chronological order, and prove
        -- the running balance never dips below zero or exceeds the frozen
        -- starting quantity at ANY point -- never decided by insertion/
        -- recorded_at/UUID order within one effective-time group.
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


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. seedling_disposition_reasons (global, immutable catalog) --------
    op.create_table(
        "seedling_disposition_reasons",
        sa.Column("code", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
    )
    for code, name in _APPROVED_REASONS:
        bind.execute(
            sa.text("INSERT INTO seedling_disposition_reasons (code, name) VALUES (:code, :name)"),
            {"code": code, "name": name},
        )

    # --- 2. seedling_disposition_commands (target_event_id FK deferred) -----
    op.create_table(
        "seedling_disposition_commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "seedling_entry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seedling_entries.id"), nullable=False
        ),
        sa.Column("operation_kind", sa.String(), nullable=False),
        sa.Column("target_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "operation_kind IN ('RECORD', 'CORRECT')", name="ck_seedling_disposition_commands_operation_kind"
        ),
        sa.CheckConstraint(
            "(operation_kind = 'RECORD' AND target_event_id IS NULL) OR "
            "(operation_kind = 'CORRECT' AND target_event_id IS NOT NULL)",
            name="ck_seedling_disposition_commands_target_matches_kind",
        ),
        sa.UniqueConstraint(
            "tenant_id", "client_command_id", name="ux_seedling_disposition_commands_tenant_client_command_id"
        ),
        sa.UniqueConstraint(
            "tenant_id", "farm_id", "id", name="uq_seedling_disposition_commands_tenant_farm_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_seedling_disposition_commands_tenant_farm_batch",
        ),
    )

    # --- 3. seedling_disposition_events (immutable) --------------------------
    op.create_table(
        "seedling_disposition_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "command_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seedling_disposition_commands.id"),
            nullable=False,
        ),
        sa.Column(
            "seedling_entry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seedling_entries.id"), nullable=False
        ),
        sa.Column("event_kind", sa.String(), nullable=False),
        sa.Column(
            "reason_code", sa.String(), sa.ForeignKey("seedling_disposition_reasons.code"), nullable=False
        ),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column(
            "reverses_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seedling_disposition_events.id"),
            nullable=True,
        ),
        sa.Column(
            "corrects_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seedling_disposition_events.id"),
            nullable=True,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("event_kind IN ('REDUCTION', 'REVERSAL')", name="ck_seedling_disposition_events_kind"),
        sa.CheckConstraint("quantity_delta <> 0", name="ck_seedling_disposition_events_delta_nonzero"),
        sa.CheckConstraint(
            "(event_kind = 'REDUCTION' AND quantity_delta < 0 AND reverses_event_id IS NULL) OR "
            "(event_kind = 'REVERSAL' AND quantity_delta > 0 AND reverses_event_id IS NOT NULL)",
            name="ck_seedling_disposition_events_kind_sign_consistency",
        ),
        sa.CheckConstraint(
            "corrects_event_id IS NULL OR event_kind = 'REDUCTION'",
            name="ck_seedling_disposition_events_corrects_only_on_reduction",
        ),
        sa.CheckConstraint(
            "reason_code <> 'OTHER' OR (note IS NOT NULL AND btrim(note) <> '')",
            name="ck_seedling_disposition_events_other_requires_note",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "command_id"],
            [
                "seedling_disposition_commands.tenant_id",
                "seedling_disposition_commands.farm_id",
                "seedling_disposition_commands.id",
            ],
            name="fk_seedling_disposition_events_tenant_farm_command",
        ),
    )
    op.create_index(
        "ux_seedling_disposition_events_reverses_once", "seedling_disposition_events", ["reverses_event_id"],
        unique=True, postgresql_where=sa.text("reverses_event_id IS NOT NULL"),
    )
    op.create_index(
        "ix_seedling_disposition_events_entry_effective", "seedling_disposition_events",
        ["seedling_entry_id", "effective_time"],
    )

    # --- 4. deferred circular FK: commands.target_event_id -> events.id -----
    op.create_foreign_key(
        "fk_seedling_disposition_commands_target_event", "seedling_disposition_commands",
        "seedling_disposition_events", ["target_event_id"], ["id"],
    )

    # --- 5. direct-write integrity -------------------------------------------
    bind.execute(sa.text(_COMMAND_INTEGRITY_FUNCTION))
    op.execute(
        """
        CREATE TRIGGER seedling_disposition_commands_enforce_insert_integrity
        BEFORE INSERT ON seedling_disposition_commands
        FOR EACH ROW EXECUTE FUNCTION enforce_seedling_disposition_command_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER seedling_disposition_commands_no_update
        BEFORE UPDATE ON seedling_disposition_commands
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER seedling_disposition_commands_no_delete
        BEFORE DELETE ON seedling_disposition_commands
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )

    bind.execute(sa.text(_EVENT_INTEGRITY_FUNCTION))
    op.execute(
        """
        CREATE TRIGGER seedling_disposition_events_enforce_insert_integrity
        BEFORE INSERT ON seedling_disposition_events
        FOR EACH ROW EXECUTE FUNCTION enforce_seedling_disposition_event_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER seedling_disposition_events_no_update
        BEFORE UPDATE ON seedling_disposition_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER seedling_disposition_events_no_delete
        BEFORE DELETE ON seedling_disposition_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guards: never silently discard biological history --------
    existing_events = bind.execute(sa.text("SELECT count(*) FROM seedling_disposition_events")).scalar_one()
    if existing_events > 0:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-003B: "
            f"{existing_events} seedling_disposition_events row(s) exist. Downgrading would drop real "
            "Seedling biological disposition history. Move/export the affected data out-of-band before "
            "downgrading, or do not downgrade."
        )
    existing_commands = bind.execute(sa.text("SELECT count(*) FROM seedling_disposition_commands")).scalar_one()
    if existing_commands > 0:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-003B: "
            f"{existing_commands} seedling_disposition_commands row(s) exist even though no events do -- "
            "this indicates a partially-committed state that should not be possible under this migration's "
            "own atomicity guarantees. Investigate before downgrading."
        )

    op.execute("DROP TRIGGER IF EXISTS seedling_disposition_events_no_delete ON seedling_disposition_events")
    op.execute("DROP TRIGGER IF EXISTS seedling_disposition_events_no_update ON seedling_disposition_events")
    op.execute(
        "DROP TRIGGER IF EXISTS seedling_disposition_events_enforce_insert_integrity "
        "ON seedling_disposition_events"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_seedling_disposition_event_insert_integrity()")

    op.execute("DROP TRIGGER IF EXISTS seedling_disposition_commands_no_delete ON seedling_disposition_commands")
    op.execute("DROP TRIGGER IF EXISTS seedling_disposition_commands_no_update ON seedling_disposition_commands")
    op.execute(
        "DROP TRIGGER IF EXISTS seedling_disposition_commands_enforce_insert_integrity "
        "ON seedling_disposition_commands"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_seedling_disposition_command_insert_integrity()")

    op.drop_constraint(
        "fk_seedling_disposition_commands_target_event", "seedling_disposition_commands", type_="foreignkey"
    )

    op.drop_index("ix_seedling_disposition_events_entry_effective", table_name="seedling_disposition_events")
    op.drop_index("ux_seedling_disposition_events_reverses_once", table_name="seedling_disposition_events")
    op.drop_table("seedling_disposition_events")
    op.drop_table("seedling_disposition_commands")
    op.drop_table("seedling_disposition_reasons")
