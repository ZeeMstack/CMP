"""planning: production requirements and seeding program

PLANNING-OPS-001: the first Planning module tables. GrowCMP needs to answer
"what crop do we need / how much / by when / what are we planning to sow to
cover it / what has actually been sown / what remains uncovered" without
building an ERP/MRP system and without inventing agronomic yield
assumptions. Two new, purely additive tables:

1. `production_requirements` -- a planner's statement of desired FARM
   OUTPUT (crop, optional variety, required-by date, required quantity +
   UOM) for one Farm. Deliberately a MUTABLE row (safe audited updates
   while `status = 'open'`, service-layer enforced) rather than the
   immutable-event shape most of CMP uses -- a Production Requirement has
   no physical-world side effect of its own; nothing here needs
   reversal-plus-new-transaction semantics. `code` is server-generated
   (`PR-{year}-{seq}`, tenant-scoped sequence, mirrors GoodsReceipt's own
   `_next_receipt_code` advisory-lock pattern) and immutable once assigned.

2. `seeding_program_lines` -- one planned sowing intended to cover part of
   a Production Requirement's demand: planned sow date, crop/variety,
   planned seed/plant quantity (its own count UOM), and an expected
   coverage quantity in the SAME UOM as the parent requirement (never a
   silently invented conversion between e.g. seed count and kg -- see
   `docs/product/OPEN_QUESTIONS.md`). A Production Requirement may have many
   plan lines; a plan line may in turn be fulfilled by many actual Sowings
   (never merged into one Crop Batch -- CMP-009's "one Sowing Event per
   Crop Batch, ever" rule is untouched by this ticket).

3. `sowing_events.seeding_program_line_id` -- the smallest additive
   integration into the EXISTING, unmodified Sowing command: an optional,
   nullable, provenance-only link from a real Sowing back to the plan line
   it fulfills. NULL for every unplanned/ad-hoc Sowing (planning is never
   mandatory for execution) and for every event predating this ticket.
   Never read by any Sowing validation/capacity/idempotency logic --
   `sow_batch`/`_sow_batch_core` in `sowing_service.py` are otherwise
   byte-for-byte unchanged.

Both new tables get a `reject_hard_delete` trigger (the same shared
function every other CMP table uses -- see NURSERY-OPS-001's grow-bag
lineage migration for precedent) but deliberately NO `reject_append_only_
mutation`/no-update trigger: unlike Sowing/Harvest/etc., these ARE meant to
be planner-editable before real execution locks them (enforced by
`planning_service`, not the database) -- "no hard delete, cancelled plans
preserved" per the ticket, not "insert-only".

Revision ID: 2c3b8d0bab94
Revises: 5a26ba0dae6c
Create Date: 2026-09-09 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2c3b8d0bab94"
down_revision: str | None = "5a26ba0dae6c"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_REJECT_HARD_DELETE_FUNCTION_NAME = "reject_hard_delete"


def upgrade() -> None:
    # --- 1. production_requirements ---------------------------------------
    op.create_table(
        "production_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("varieties.id"), nullable=True),
        sa.Column("required_by_date", sa.Date(), nullable=False),
        sa.Column("required_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column(
            "quantity_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"), nullable=False
        ),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("update_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("update_request_fingerprint", sa.String(), nullable=True),
        sa.Column("close_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("close_request_fingerprint", sa.String(), nullable=True),
        sa.Column("cancel_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancel_request_fingerprint", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint("status IN ('open', 'closed', 'cancelled')", name="ck_production_requirements_status"),
        sa.CheckConstraint("required_quantity > 0", name="ck_production_requirements_quantity_positive"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_production_requirements_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_production_requirements_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_production_requirements_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_production_requirements_tenant_crop"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_production_requirements_tenant_crop_variety",
        ),
    )
    op.create_index(
        "ux_production_requirements_tenant_code_lower",
        "production_requirements",
        ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )
    op.create_index(
        "ux_production_requirements_tenant_client_command_id",
        "production_requirements",
        ["tenant_id", "client_command_id"],
        unique=True,
    )
    op.create_index(
        "ux_production_requirements_tenant_update_command",
        "production_requirements",
        ["tenant_id", "update_client_command_id"],
        unique=True,
        postgresql_where=sa.text("update_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_production_requirements_tenant_close_command",
        "production_requirements",
        ["tenant_id", "close_client_command_id"],
        unique=True,
        postgresql_where=sa.text("close_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_production_requirements_tenant_cancel_command",
        "production_requirements",
        ["tenant_id", "cancel_client_command_id"],
        unique=True,
        postgresql_where=sa.text("cancel_client_command_id IS NOT NULL"),
    )
    op.execute(
        "CREATE TRIGGER production_requirements_no_delete "
        "BEFORE DELETE ON production_requirements "
        f"FOR EACH ROW EXECUTE FUNCTION {_REJECT_HARD_DELETE_FUNCTION_NAME}();"
    )

    # --- 2. seeding_program_lines -------------------------------------------
    op.create_table(
        "seeding_program_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "production_requirement_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("production_requirements.id"), nullable=False,
        ),
        sa.Column("planned_sow_date", sa.Date(), nullable=False),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("varieties.id"), nullable=True),
        sa.Column("planned_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column(
            "planned_quantity_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"),
            nullable=False,
        ),
        sa.Column("expected_coverage_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column(
            "expected_coverage_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"),
            nullable=False,
        ),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="planned"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("update_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("update_request_fingerprint", sa.String(), nullable=True),
        sa.Column("cancel_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancel_request_fingerprint", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint("status IN ('planned', 'cancelled')", name="ck_seeding_program_lines_status"),
        sa.CheckConstraint("planned_quantity > 0", name="ck_seeding_program_lines_planned_quantity_positive"),
        sa.CheckConstraint(
            "expected_coverage_quantity > 0", name="ck_seeding_program_lines_coverage_quantity_positive"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_seeding_program_lines_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_seeding_program_lines_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_seeding_program_lines_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "production_requirement_id"],
            [
                "production_requirements.tenant_id",
                "production_requirements.farm_id",
                "production_requirements.id",
            ],
            name="fk_seeding_program_lines_tenant_farm_requirement",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_seeding_program_lines_tenant_crop"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_seeding_program_lines_tenant_crop_variety",
        ),
    )
    op.create_index(
        "ux_seeding_program_lines_tenant_client_command_id",
        "seeding_program_lines",
        ["tenant_id", "client_command_id"],
        unique=True,
    )
    op.create_index(
        "ux_seeding_program_lines_tenant_update_command",
        "seeding_program_lines",
        ["tenant_id", "update_client_command_id"],
        unique=True,
        postgresql_where=sa.text("update_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_seeding_program_lines_tenant_cancel_command",
        "seeding_program_lines",
        ["tenant_id", "cancel_client_command_id"],
        unique=True,
        postgresql_where=sa.text("cancel_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ix_seeding_program_lines_tenant_farm_sow_date",
        "seeding_program_lines",
        ["tenant_id", "farm_id", "planned_sow_date"],
    )
    op.create_index(
        "ix_seeding_program_lines_requirement", "seeding_program_lines", ["production_requirement_id"],
    )
    op.execute(
        "CREATE TRIGGER seeding_program_lines_no_delete "
        "BEFORE DELETE ON seeding_program_lines "
        f"FOR EACH ROW EXECUTE FUNCTION {_REJECT_HARD_DELETE_FUNCTION_NAME}();"
    )

    # --- 3. sowing_events: optional provenance link to a plan line ----------
    op.add_column(
        "sowing_events",
        sa.Column("seeding_program_line_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_sowing_events_tenant_farm_seeding_program_line", "sowing_events", "seeding_program_lines",
        ["tenant_id", "farm_id", "seeding_program_line_id"], ["tenant_id", "farm_id", "id"],
    )
    op.create_index(
        "ix_sowing_events_seeding_program_line", "sowing_events", ["seeding_program_line_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()

    linked_sowings = bind.execute(
        sa.text("SELECT count(*) FROM sowing_events WHERE seeding_program_line_id IS NOT NULL")
    ).scalar_one()
    if linked_sowings > 0:
        raise RuntimeError(
            "Cannot downgrade past PLANNING-OPS-001: "
            f"{linked_sowings} existing sowing_events row(s) reference a seeding_program_line and would lose "
            "that provenance."
        )
    line_count = bind.execute(sa.text("SELECT count(*) FROM seeding_program_lines")).scalar_one()
    if line_count > 0:
        raise RuntimeError(
            f"Cannot downgrade past PLANNING-OPS-001: {line_count} existing seeding_program_lines row(s) "
            "would be destroyed."
        )
    requirement_count = bind.execute(sa.text("SELECT count(*) FROM production_requirements")).scalar_one()
    if requirement_count > 0:
        raise RuntimeError(
            f"Cannot downgrade past PLANNING-OPS-001: {requirement_count} existing production_requirements "
            "row(s) would be destroyed."
        )

    op.drop_index("ix_sowing_events_seeding_program_line", table_name="sowing_events")
    op.drop_constraint("fk_sowing_events_tenant_farm_seeding_program_line", "sowing_events", type_="foreignkey")
    op.drop_column("sowing_events", "seeding_program_line_id")

    op.execute("DROP TRIGGER IF EXISTS seeding_program_lines_no_delete ON seeding_program_lines")
    op.drop_index("ix_seeding_program_lines_requirement", table_name="seeding_program_lines")
    op.drop_index("ix_seeding_program_lines_tenant_farm_sow_date", table_name="seeding_program_lines")
    op.drop_index("ux_seeding_program_lines_tenant_cancel_command", table_name="seeding_program_lines")
    op.drop_index("ux_seeding_program_lines_tenant_update_command", table_name="seeding_program_lines")
    op.drop_index("ux_seeding_program_lines_tenant_client_command_id", table_name="seeding_program_lines")
    op.drop_table("seeding_program_lines")

    op.execute("DROP TRIGGER IF EXISTS production_requirements_no_delete ON production_requirements")
    op.drop_index("ux_production_requirements_tenant_cancel_command", table_name="production_requirements")
    op.drop_index("ux_production_requirements_tenant_close_command", table_name="production_requirements")
    op.drop_index("ux_production_requirements_tenant_update_command", table_name="production_requirements")
    op.drop_index("ux_production_requirements_tenant_client_command_id", table_name="production_requirements")
    op.drop_index("ux_production_requirements_tenant_code_lower", table_name="production_requirements")
    op.drop_table("production_requirements")
