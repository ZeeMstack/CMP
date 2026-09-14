"""farm work item and shift handover

PILOT-OPS-001: introduces the "Today on the Farm" work engine's persisted
domain -- `farm_work_items` (the small operational task/assignment
entity) plus `shift_handovers`/`shift_handover_items` (the pilot shift
handover note).

`farm_work_items` is a CURRENT-STATE row (ADR-005), not a fully immutable
event: identity/content fields (tenant/farm, code, work_type, category,
title, instructions, context references, completion_mode,
created_by_user_id/created_at, and the creation command-idempotency pair)
are frozen for life by `enforce_farm_work_item_mutable_fields` (BEFORE
UPDATE); only the small set of lifecycle/current-state fields (status,
priority, due_at, assigned_to_user_id, blocked_*, completed_*, result_*,
cancelled_*, updated_at, and each command's own idempotency pair) may ever
change, and only through the service-layer commands that own them. No hard
delete is possible on any of the three new tables (`reject_hard_delete`,
already defined by 5f3a9c2d1b44, reused unmodified). Operator-facing
lifecycle HISTORY is not duplicated here -- it reuses the existing
`audit_events` table (`docs/domain/AUDIT_MODEL.md`), read back filtered by
`entity_type = 'farm_work_item'`.

`shift_handovers`/`shift_handover_items` are fully immutable, insert-only
(`reject_append_only_mutation`, already defined by c48f21a6b3d9, reused
unmodified, rejects both UPDATE and DELETE) -- a handover never mutates or
closes the Work Items it references.

Additive only: one new composite anchor constraint on a pre-existing table
(`uq_assets_tenant_farm_id`), mirroring CMP-018's identical
`uq_locations_tenant_farm_id` addition to `locations` -- backs the new
composite foreign key from `farm_work_items.asset_id`. `carriers` already
carries the equivalent `uq_carriers_tenant_farm_id` (added by
d17a4e2f9c86), reused unmodified for `farm_work_items.carrier_id`. No
existing table's columns, indexes, or data are touched otherwise.

Downgrade is destructive by nature (drops three new tables) and is guarded
like every other domain-introducing migration in this codebase: it raises
and makes zero schema change if any Farm Work Item or Shift Handover row
already exists.

Revision ID: 3a278fa65f80
Revises: ba45c84a1210
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "3a278fa65f80"
down_revision: Union[str, None] = "ba45c84a1210"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


WORK_ITEM_CATEGORIES = (
    "nursery", "production", "crop_care", "harvest", "post_harvest",
    "store", "quality", "dispatch", "cleaning", "maintenance",
)
WORK_ITEM_STATUSES = ("open", "in_progress", "blocked", "completed", "cancelled")
WORK_ITEM_PRIORITIES = ("normal", "high", "critical")
WORK_ITEM_COMPLETION_MODES = ("operational_record", "manual_record")
WORK_ITEM_RESULT_ENTITY_TYPES = ("harvest_event", "observation_event")


def upgrade() -> None:
    # --- additive composite anchor on a pre-existing table ---------------
    op.create_unique_constraint(
        "uq_assets_tenant_farm_id", "assets", ["tenant_id", "farm_id", "id"]
    )

    # --- farm_work_items ---------------------------------------------------
    op.create_table(
        "farm_work_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("work_type", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(), nullable=False, server_default="normal"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        # Structured operational context -- real FKs, never packed into an
        # opaque JSON blob (CLAUDE.md rule 3/4; ticket's own "Context Model").
        # Every one is optional: a pump-maintenance task has no batch, a
        # harvest task has crop/batch/source context. QR-compatibility
        # (PILOT-SCAN-001): each is a real, stable entity identifier a
        # future scan can resolve straight into -- never a display string.
        sa.Column("crop_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("carrier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("quantity_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"), nullable=True),
        # Completion mode + shape (ticket: "Completion Modes"). Exactly one
        # of the manual-record or operational-record field groups below is
        # ever populated, enforced by ck_farm_work_items_status_shape.
        sa.Column("completion_mode", sa.String(), nullable=False),
        sa.Column("result_entity_type", sa.String(), nullable=True),
        sa.Column("result_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        # Blocked state (current only -- full block/unblock history lives in
        # audit_events, not duplicated here).
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        # Cancelled state.
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Creation command idempotency (required -- every command has an
        # idempotency key, CLAUDE.md "API and Offline Rules").
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        # Per-command idempotency evidence, one column pair per distinct
        # mutating command -- mirrors `locations`' own update/deactivation/
        # reactivation column-pair precedent (UX-IA-001, 10430de8731e)
        # exactly. `update_*` covers the one combined supervisory command
        # (reassign + change priority/due window); the remaining five cover
        # each lifecycle transition.
        sa.Column("update_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("update_request_fingerprint", sa.String(), nullable=True),
        sa.Column("start_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("start_request_fingerprint", sa.String(), nullable=True),
        sa.Column("block_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("block_request_fingerprint", sa.String(), nullable=True),
        sa.Column("unblock_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("unblock_request_fingerprint", sa.String(), nullable=True),
        sa.Column("complete_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("complete_request_fingerprint", sa.String(), nullable=True),
        sa.Column("cancel_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancel_request_fingerprint", sa.String(), nullable=True),
        sa.Column("link_result_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("link_result_request_fingerprint", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN " + str(WORK_ITEM_STATUSES), name="ck_farm_work_items_status"
        ),
        sa.CheckConstraint(
            "priority IN " + str(WORK_ITEM_PRIORITIES), name="ck_farm_work_items_priority"
        ),
        sa.CheckConstraint(
            "category IN " + str(WORK_ITEM_CATEGORIES), name="ck_farm_work_items_category"
        ),
        sa.CheckConstraint(
            "completion_mode IN " + str(WORK_ITEM_COMPLETION_MODES), name="ck_farm_work_items_completion_mode"
        ),
        sa.CheckConstraint(
            "result_entity_type IS NULL OR result_entity_type IN " + str(WORK_ITEM_RESULT_ENTITY_TYPES),
            name="ck_farm_work_items_result_entity_type",
        ),
        sa.CheckConstraint("length(btrim(work_type)) > 0", name="ck_farm_work_items_work_type_not_blank"),
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_farm_work_items_title_not_blank"),
        sa.CheckConstraint(
            "(quantity IS NULL) = (quantity_uom_id IS NULL)", name="ck_farm_work_items_quantity_uom_pairing"
        ),
        # One comprehensive lifecycle-shape CHECK, mirroring
        # ck_crop_batches_lifecycle_shape's own "one OR-of-ANDs per state"
        # idiom exactly -- CLAUDE.md rule 8 (never hide differences) applied
        # to state, not just quantity: a row's populated fields must always
        # agree with its own status.
        sa.CheckConstraint(
            "("
            "status IN ('open', 'in_progress') AND "
            "blocked_reason IS NULL AND blocked_at IS NULL AND blocked_by_user_id IS NULL AND "
            "completed_at IS NULL AND completed_by_user_id IS NULL AND completion_note IS NULL AND "
            "result_entity_type IS NULL AND result_entity_id IS NULL AND result_recorded_at IS NULL AND "
            "cancelled_at IS NULL AND cancelled_by_user_id IS NULL AND cancel_reason IS NULL"
            ") OR ("
            "status = 'blocked' AND blocked_reason IS NOT NULL AND blocked_at IS NOT NULL AND "
            "completed_at IS NULL AND completed_by_user_id IS NULL AND completion_note IS NULL AND "
            "result_entity_type IS NULL AND result_entity_id IS NULL AND result_recorded_at IS NULL AND "
            "cancelled_at IS NULL AND cancelled_by_user_id IS NULL AND cancel_reason IS NULL"
            ") OR ("
            "status = 'completed' AND completed_at IS NOT NULL AND "
            "blocked_reason IS NULL AND blocked_at IS NULL AND blocked_by_user_id IS NULL AND "
            "cancelled_at IS NULL AND cancelled_by_user_id IS NULL AND cancel_reason IS NULL AND "
            "(("
            "completion_mode = 'manual_record' AND completed_by_user_id IS NOT NULL AND "
            "result_entity_type IS NULL AND result_entity_id IS NULL AND result_recorded_at IS NULL"
            ") OR ("
            "completion_mode = 'operational_record' AND "
            "result_entity_type IS NOT NULL AND result_entity_id IS NOT NULL AND result_recorded_at IS NOT NULL AND "
            "completed_by_user_id IS NULL AND completion_note IS NULL"
            "))"
            ") OR ("
            "status = 'cancelled' AND cancelled_at IS NOT NULL AND cancelled_by_user_id IS NOT NULL AND "
            "blocked_reason IS NULL AND blocked_at IS NULL AND blocked_by_user_id IS NULL AND "
            "completed_at IS NULL AND completed_by_user_id IS NULL AND completion_note IS NULL AND "
            "result_entity_type IS NULL AND result_entity_id IS NULL AND result_recorded_at IS NULL"
            ")",
            name="ck_farm_work_items_status_shape",
        ),
        sa.Index("ux_farm_work_items_tenant_code_lower", "tenant_id", sa.func.lower(sa.column("code")), unique=True),
        sa.Index("ux_farm_work_items_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        sa.Index(
            "ux_farm_work_items_tenant_update_command", "tenant_id", "update_client_command_id",
            unique=True, postgresql_where=sa.text("update_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_farm_work_items_tenant_start_command", "tenant_id", "start_client_command_id",
            unique=True, postgresql_where=sa.text("start_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_farm_work_items_tenant_block_command", "tenant_id", "block_client_command_id",
            unique=True, postgresql_where=sa.text("block_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_farm_work_items_tenant_unblock_command", "tenant_id", "unblock_client_command_id",
            unique=True, postgresql_where=sa.text("unblock_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_farm_work_items_tenant_complete_command", "tenant_id", "complete_client_command_id",
            unique=True, postgresql_where=sa.text("complete_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_farm_work_items_tenant_cancel_command", "tenant_id", "cancel_client_command_id",
            unique=True, postgresql_where=sa.text("cancel_client_command_id IS NOT NULL"),
        ),
        sa.Index(
            "ux_farm_work_items_tenant_link_result_command", "tenant_id", "link_result_client_command_id",
            unique=True, postgresql_where=sa.text("link_result_client_command_id IS NOT NULL"),
        ),
        sa.Index("ix_farm_work_items_farm_status", "tenant_id", "farm_id", "status"),
        sa.Index("ix_farm_work_items_farm_assignee_status", "tenant_id", "farm_id", "assigned_to_user_id", "status"),
        sa.Index("ix_farm_work_items_farm_due_at", "tenant_id", "farm_id", "due_at"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_farm_work_items_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_farm_work_items_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "crop_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_farm_work_items_tenant_farm_crop_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_farm_work_items_tenant_farm_location",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_farm_work_items_tenant_farm_carrier",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "asset_id"],
            ["assets.tenant_id", "assets.farm_id", "assets.id"],
            name="fk_farm_work_items_tenant_farm_asset",
        ),
    )

    # --- shift_handovers / shift_handover_items -----------------------------
    op.create_table(
        "shift_handovers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint("length(btrim(note)) > 0", name="ck_shift_handovers_note_not_blank"),
        sa.Index("ux_shift_handovers_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        sa.Index("ix_shift_handovers_farm_effective_time", "tenant_id", "farm_id", "effective_time"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_shift_handovers_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_shift_handovers_tenant_farm"
        ),
    )

    op.create_table(
        "shift_handover_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("handover_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("work_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.UniqueConstraint("handover_id", "work_item_id", name="uq_shift_handover_items_handover_work_item"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "handover_id"],
            ["shift_handovers.tenant_id", "shift_handovers.farm_id", "shift_handovers.id"],
            name="fk_shift_handover_items_handover",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "work_item_id"],
            ["farm_work_items.tenant_id", "farm_work_items.farm_id", "farm_work_items.id"],
            name="fk_shift_handover_items_work_item",
        ),
    )

    # --- triggers ------------------------------------------------------------
    # farm_work_items: only the current-state lifecycle fields may ever
    # change after creation; every identity/content field is frozen.
    op.execute(
        """
        CREATE FUNCTION enforce_farm_work_item_mutable_fields() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id OR NEW.farm_id <> OLD.farm_id OR NEW.code <> OLD.code
               OR NEW.work_type <> OLD.work_type OR NEW.category <> OLD.category OR NEW.title <> OLD.title
               OR NEW.instructions IS DISTINCT FROM OLD.instructions
               OR NEW.crop_batch_id IS DISTINCT FROM OLD.crop_batch_id
               OR NEW.location_id IS DISTINCT FROM OLD.location_id
               OR NEW.carrier_id IS DISTINCT FROM OLD.carrier_id
               OR NEW.asset_id IS DISTINCT FROM OLD.asset_id
               OR NEW.quantity IS DISTINCT FROM OLD.quantity
               OR NEW.quantity_uom_id IS DISTINCT FROM OLD.quantity_uom_id
               OR NEW.completion_mode <> OLD.completion_mode
               OR NEW.created_by_user_id <> OLD.created_by_user_id OR NEW.created_at <> OLD.created_at
               OR NEW.client_command_id <> OLD.client_command_id
               OR NEW.request_fingerprint <> OLD.request_fingerprint
            THEN
                RAISE EXCEPTION 'farm_work_item identity/content fields are immutable; only lifecycle state may change';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER farm_work_items_enforce_mutable_fields
        BEFORE UPDATE ON farm_work_items
        FOR EACH ROW EXECUTE FUNCTION enforce_farm_work_item_mutable_fields();
        """
    )
    op.execute(
        """
        CREATE TRIGGER farm_work_items_no_delete
        BEFORE DELETE ON farm_work_items
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # shift_handovers / shift_handover_items: fully immutable, insert-only.
    op.execute(
        """
        CREATE TRIGGER shift_handovers_no_update
        BEFORE UPDATE ON shift_handovers
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER shift_handovers_no_delete
        BEFORE DELETE ON shift_handovers
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER shift_handover_items_no_update
        BEFORE UPDATE ON shift_handover_items
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER shift_handover_items_no_delete
        BEFORE DELETE ON shift_handover_items
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    work_item_count = bind.execute(sa.text("SELECT count(*) FROM farm_work_items")).scalar_one()
    handover_count = bind.execute(sa.text("SELECT count(*) FROM shift_handovers")).scalar_one()
    if work_item_count > 0 or handover_count > 0:
        raise RuntimeError(
            "Cannot downgrade past PILOT-OPS-001's Farm Work Item / Shift Handover tables: "
            f"{work_item_count} farm_work_items row(s) and {handover_count} shift_handovers row(s) "
            "already exist. Downgrading would destroy real operational work history."
        )

    op.execute("DROP TRIGGER IF EXISTS shift_handover_items_no_delete ON shift_handover_items")
    op.execute("DROP TRIGGER IF EXISTS shift_handover_items_no_update ON shift_handover_items")
    op.execute("DROP TRIGGER IF EXISTS shift_handovers_no_delete ON shift_handovers")
    op.execute("DROP TRIGGER IF EXISTS shift_handovers_no_update ON shift_handovers")
    op.execute("DROP TRIGGER IF EXISTS farm_work_items_no_delete ON farm_work_items")
    op.execute("DROP TRIGGER IF EXISTS farm_work_items_enforce_mutable_fields ON farm_work_items")
    op.execute("DROP FUNCTION IF EXISTS enforce_farm_work_item_mutable_fields()")

    op.drop_table("shift_handover_items")
    op.drop_table("shift_handovers")
    op.drop_table("farm_work_items")

    op.drop_constraint("uq_assets_tenant_farm_id", "assets", type_="unique")
