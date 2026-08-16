"""seedling entry and seed_tray -> seedling_table compatibility

NURSERY-OPS-003A -- Seedling Entry & Placement. FROZEN authoritative physical
model: Seed Tray Carrier occupies a Seedling Table Location directly (no
`seedling_table_position`, no Zone/Span in Nursery). A Germination biological
handoff cannot wait for a later, separate ticket: when a Tray genuinely
enters Seedling operations, CMP must freeze exactly which completed
`GerminationOutcomeSnapshot` supplied the starting biological quantity --
otherwise a later, even historically truthful, Germination reassessment
could silently change a quantity Seedling operations has already built
history on top of. See `docs/domain/OBSERVATION_QUALITY_MODEL.md`'s
NURSERY-OPS-003A addendum for the full model writeup.

Two changes:

1. Adds exactly one `occupancy_compatibility_rules` row:
   `carrier:seed_tray -> location:seedling_table`. This is the only new
   compatibility row this ticket adds -- deliberately NOT
   `seed_tray -> seedling_area` (a Tray never occupies the structural Area
   node itself) and NOT a `seedling_table_position` row (none exists; the
   Table is the leaf, matching the already-established
   `cultivation_plate -> grow_table` direct-occupancy precedent from
   `9ca4ac801827`). `seed_tray`'s only prior rule
   (`carrier:seed_tray -> position:slot`, for the Germination Trolley slot)
   is untouched.

2. Creates `seedling_entries`: one immutable, insert-only row per
   `BatchCarrierAssignment`, ever (`ux_seedling_entries_assignment`).
   References the exact `GerminationOutcomeSnapshot` that was historically
   valid at the entry's own `effective_time` (resolved server-side by
   `seedling_entry_service._resolve_source_snapshot` -- never the caller,
   never simply "latest completed now") and the physical `Movement` that
   carried the Tray onto the selected Seedling Table in the SAME
   transaction/commit as this row (`seedling_entry_service.
   record_seedling_entry`). `starting_living_seedling_count` is a
   deliberate, DB-verified freeze of that snapshot's own
   `normal_seedling_count + abnormal_seedling_count` -- a later Germination
   correction, however historically valid on the Germination side, never
   rewrites it.

   Direct-write DB integrity (a trigger, since these are all cross-row
   truths a CHECK constraint cannot express): assignment/batch consistency,
   seed_tray carrier type, temporal assignment validity
   (`[assigned_effective_time, released_effective_time)`, mirroring 002B's
   own pattern), the source snapshot's tenant/farm/assignment consistency,
   `assessment_complete = true`, the source snapshot's own effective_time
   at or before the entry's effective_time, the frozen quantity actually
   equaling the source snapshot's normal + abnormal, and the referenced
   Movement's own tenant/farm/occupant/destination-type/effective_time
   consistency. Append-only (no UPDATE/DELETE), reusing the existing
   `reject_append_only_mutation()` function (defined by `c48f21a6b3d9`, not
   redefined here).

   `movement_service.execute_movement` gains NO Germination/Seedling
   awareness from this ticket -- see `app/services/movement_service.py`'s
   own new `_execute_movement_core` split (extracted so
   `seedling_entry_service` can commit the Movement and this table's row in
   one transaction; every existing Movement caller's behavior is otherwise
   unchanged, proven by the full pre-existing Movement test suite staying
   green).

Revision ID: a3f7c9d2e0b1
Revises: 7bddca3261cc
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a3f7c9d2e0b1'
down_revision: Union[str, None] = '7bddca3261cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. carrier:seed_tray -> location:seedling_table compatibility -----
    seed_tray_type_id = bind.execute(
        sa.text("SELECT id FROM carrier_types WHERE code = 'seed_tray'")
    ).scalar_one()
    seedling_table_type_id = bind.execute(
        sa.text("SELECT id FROM location_types WHERE code = 'seedling_table'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO occupancy_compatibility_rules "
            "(id, occupant_carrier_type_id, target_location_type_id) "
            "VALUES (gen_random_uuid(), :occupant_id, :target_id)"
        ),
        {"occupant_id": seed_tray_type_id, "target_id": seedling_table_type_id},
    )

    # --- 2. seedling_entries (immutable) -------------------------------------
    op.create_table(
        "seedling_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column(
            "batch_carrier_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_carrier_assignments.id"),
            nullable=False,
        ),
        sa.Column(
            "source_germination_outcome_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("germination_outcome_snapshots.id"),
            nullable=False,
        ),
        sa.Column("movement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("movements.id"), nullable=False),
        sa.Column("starting_living_seedling_count", sa.Integer(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "starting_living_seedling_count >= 0", name="ck_seedling_entries_starting_count_non_negative"
        ),
        sa.UniqueConstraint("batch_carrier_assignment_id", name="ux_seedling_entries_assignment"),
        sa.UniqueConstraint(
            "tenant_id", "client_command_id", name="ux_seedling_entries_tenant_client_command_id"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_seedling_entries_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_carrier_assignment_id"],
            [
                "batch_carrier_assignments.tenant_id",
                "batch_carrier_assignments.farm_id",
                "batch_carrier_assignments.id",
            ],
            name="fk_seedling_entries_tenant_farm_assignment",
        ),
    )
    op.create_index("ix_seedling_entries_batch", "seedling_entries", ["batch_id"])

    # --- 3. direct-write integrity -------------------------------------------
    op.execute(
        """
        CREATE FUNCTION enforce_seedling_entry_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_assignment_batch_id UUID;
            v_assignment_carrier_id UUID;
            v_assignment_assigned TIMESTAMPTZ;
            v_assignment_released TIMESTAMPTZ;
            v_carrier_type_code TEXT;
            v_snapshot_tenant_id UUID;
            v_snapshot_farm_id UUID;
            v_snapshot_assignment_id UUID;
            v_snapshot_complete BOOLEAN;
            v_snapshot_normal INTEGER;
            v_snapshot_abnormal INTEGER;
            v_snapshot_effective TIMESTAMPTZ;
            v_movement_tenant_id UUID;
            v_movement_farm_id UUID;
            v_movement_occupant_carrier_id UUID;
            v_movement_destination_location_id UUID;
            v_movement_effective TIMESTAMPTZ;
            v_destination_location_type_code TEXT;
        BEGIN
            -- Assignment / batch consistency and temporal validity (mirrors
            -- 002B's own [assigned_effective_time, released_effective_time)
            -- pattern -- a historical entry must remain valid if
            -- effective_time occurred while the assignment was actually
            -- active, even if it has SINCE been released).
            SELECT batch_id, carrier_id, assigned_effective_time, released_effective_time
            INTO v_assignment_batch_id, v_assignment_carrier_id, v_assignment_assigned, v_assignment_released
            FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;
            IF v_assignment_batch_id IS NULL THEN
                RAISE EXCEPTION 'assignment not found';
            END IF;
            IF v_assignment_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'assignment does not belong to this batch';
            END IF;
            IF NEW.effective_time < v_assignment_assigned THEN
                RAISE EXCEPTION 'seedling entry effective_time precedes assignment assigned_effective_time';
            END IF;
            IF v_assignment_released IS NOT NULL AND NEW.effective_time >= v_assignment_released THEN
                RAISE EXCEPTION 'seedling entry effective_time is at or after the assignment''s release; the assignment was not active at that time';
            END IF;

            SELECT ct.code INTO v_carrier_type_code
            FROM carriers c JOIN carrier_types ct ON ct.id = c.carrier_type_id
            WHERE c.id = v_assignment_carrier_id;
            IF v_carrier_type_code IS DISTINCT FROM 'seed_tray' THEN
                RAISE EXCEPTION 'seedling entry assignment must be a seed_tray carrier';
            END IF;

            -- Source Germination outcome snapshot: must belong to this exact
            -- tenant/farm/assignment, be a COMPLETED assessment, have its own
            -- effective_time at/before this entry's effective_time, and the
            -- frozen quantity must equal what it actually reported --
            -- section 11: never a caller-supplied starting quantity.
            SELECT gos.tenant_id, gos.farm_id, gos.batch_carrier_assignment_id, gos.assessment_complete,
                   gos.normal_seedling_count, gos.abnormal_seedling_count, oe.effective_time
            INTO v_snapshot_tenant_id, v_snapshot_farm_id, v_snapshot_assignment_id, v_snapshot_complete,
                 v_snapshot_normal, v_snapshot_abnormal, v_snapshot_effective
            FROM germination_outcome_snapshots gos
            JOIN observation_events oe ON oe.id = gos.observation_event_id
            WHERE gos.id = NEW.source_germination_outcome_snapshot_id;
            IF v_snapshot_assignment_id IS NULL THEN
                RAISE EXCEPTION 'source germination outcome snapshot not found';
            END IF;
            IF v_snapshot_tenant_id <> NEW.tenant_id OR v_snapshot_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'source germination outcome snapshot does not belong to this tenant/farm';
            END IF;
            IF v_snapshot_assignment_id <> NEW.batch_carrier_assignment_id THEN
                RAISE EXCEPTION 'source germination outcome snapshot does not belong to this assignment';
            END IF;
            IF NOT v_snapshot_complete THEN
                RAISE EXCEPTION 'source germination outcome snapshot must be a completed assessment';
            END IF;
            IF v_snapshot_effective > NEW.effective_time THEN
                RAISE EXCEPTION 'source germination outcome snapshot effective_time is after the seedling entry effective_time';
            END IF;
            IF NEW.starting_living_seedling_count <> v_snapshot_normal + v_snapshot_abnormal THEN
                RAISE EXCEPTION 'starting_living_seedling_count must equal the source snapshot''s normal + abnormal seedling counts';
            END IF;

            -- Referenced Movement: same tenant/farm, moves this exact
            -- assignment's Seed Tray carrier, destination is a
            -- seedling_table location, and its effective_time matches this
            -- entry's effective_time exactly (section 9: one command, one
            -- handoff time, used consistently for both facts).
            SELECT m.tenant_id, m.farm_id, m.occupant_carrier_id, m.destination_location_id, m.effective_time
            INTO v_movement_tenant_id, v_movement_farm_id, v_movement_occupant_carrier_id,
                 v_movement_destination_location_id, v_movement_effective
            FROM movements m WHERE m.id = NEW.movement_id;
            IF v_movement_effective IS NULL THEN
                RAISE EXCEPTION 'referenced movement not found';
            END IF;
            IF v_movement_tenant_id <> NEW.tenant_id OR v_movement_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'referenced movement does not belong to this tenant/farm';
            END IF;
            IF v_movement_occupant_carrier_id IS DISTINCT FROM v_assignment_carrier_id THEN
                RAISE EXCEPTION 'referenced movement does not move this assignment''s Seed Tray carrier';
            END IF;
            IF v_movement_effective <> NEW.effective_time THEN
                RAISE EXCEPTION 'referenced movement effective_time must match the seedling entry effective_time';
            END IF;

            SELECT lt.code INTO v_destination_location_type_code
            FROM locations l JOIN location_types lt ON lt.id = l.location_type_id
            WHERE l.id = v_movement_destination_location_id;
            IF v_destination_location_type_code IS DISTINCT FROM 'seedling_table' THEN
                RAISE EXCEPTION 'referenced movement destination must be a seedling_table location';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER seedling_entries_enforce_insert_integrity
        BEFORE INSERT ON seedling_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_seedling_entry_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER seedling_entries_no_update
        BEFORE UPDATE ON seedling_entries
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER seedling_entries_no_delete
        BEFORE DELETE ON seedling_entries
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard 1: never silently discard biological handoff history
    existing = bind.execute(sa.text("SELECT count(*) FROM seedling_entries")).scalar_one()
    if existing > 0:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-003A: "
            f"{existing} seedling_entries row(s) exist. Downgrading would drop real Seedling biological "
            "handoff history. Move/export the affected data out-of-band before downgrading, or do not "
            "downgrade."
        )

    # --- downgrade guard 2: never leave live physical data the old model
    # cannot explain -- if any Seed Tray currently occupies a Seedling
    # Table, removing the compatibility rule would make that live state
    # impossible to reproduce under the reverted schema. Do not
    # auto-move Trays off Tables to force the downgrade through.
    live_occupancy = bind.execute(
        sa.text(
            "SELECT count(*) FROM occupancies o "
            "JOIN carriers c ON c.id = o.occupant_carrier_id "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = 'seed_tray' "
            "JOIN locations l ON l.id = o.target_location_id "
            "JOIN location_types lt ON lt.id = l.location_type_id AND lt.code = 'seedling_table' "
            "WHERE o.end_time IS NULL"
        )
    ).scalar_one()
    if live_occupancy > 0:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-003A: "
            f"{live_occupancy} Seed Tray(s) currently occupy a Seedling Table. Removing the "
            "seed_tray -> seedling_table compatibility rule would leave this live physical state "
            "unreproducible under the reverted schema. Move the affected Tray(s) off Seedling Tables "
            "out-of-band before downgrading, or do not downgrade."
        )

    op.execute("DROP TRIGGER IF EXISTS seedling_entries_no_delete ON seedling_entries")
    op.execute("DROP TRIGGER IF EXISTS seedling_entries_no_update ON seedling_entries")
    op.execute("DROP TRIGGER IF EXISTS seedling_entries_enforce_insert_integrity ON seedling_entries")
    op.execute("DROP FUNCTION IF EXISTS enforce_seedling_entry_insert_integrity()")

    op.drop_index("ix_seedling_entries_batch", table_name="seedling_entries")
    op.drop_table("seedling_entries")

    seed_tray_type_id = bind.execute(
        sa.text("SELECT id FROM carrier_types WHERE code = 'seed_tray'")
    ).scalar_one()
    seedling_table_type_id = bind.execute(
        sa.text("SELECT id FROM location_types WHERE code = 'seedling_table'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "DELETE FROM occupancy_compatibility_rules "
            "WHERE occupant_carrier_type_id = :occupant_id AND target_location_type_id = :target_id"
        ),
        {"occupant_id": seed_tray_type_id, "target_id": seedling_table_type_id},
    )
