"""harvest forecast and capacity allocation

PILOT-PLAN-001A: the first Harvest Forecast / Capacity Planning tables.
Planning intelligence layered strictly on top of the existing
ProductionRequirement / SeedingProgramLine / CropBatch / Location domain --
no existing table is touched, no new demand/coverage storage duplicates
`planning_service`'s own read-model, and neither new table can create
Occupancy, move a Batch, or mutate agronomic/harvest truth. Full design
writeup: `docs/domain/HARVEST_FORECAST_CAPACITY_MODEL.md`.

Two new, purely additive tables:

1. `batch_harvest_forecasts` -- an insert-only LOW/EXPECTED/HIGH forecast
   revision chain for one Crop Batch (never a mutable single row): revising
   a Batch's forecast inserts a new row and stamps the prior CURRENT row's
   `superseded_at`/`superseded_by_forecast_id`, so every past estimate
   stays permanently inspectable. `ux_batch_harvest_forecasts_current_batch`
   (a partial unique index on `superseded_at IS NULL`) guarantees exactly
   one CURRENT forecast per Batch. `basis` is a small closed enum
   (`grower_estimate`/`planning_assumption`/`protocol_guidance` -- no
   `ai_prediction`, per the ticket's explicit "do not build AI yield
   prediction"). Never referenced by, and never mutates, `harvest_events`/
   `harvested_produce_lots` -- the actual-vs-forecast comparison is a
   read-only service-layer calculation (`harvest_forecast_service`), never
   a stored/derived column here.

2. `production_capacity_allocations` -- a PLANNING reservation of future
   occupant-slot capacity at one `Location` (the existing
   `locations.capacity` DOMAIN-FARM-002 column is the sole authoritative
   capacity source; no new capacity concept is added to `locations`
   itself). A current-state row (mirrors `production_requirements`):
   create/update while `status = 'active'`, cancel to stop consuming
   planned capacity. `planned_start_date`/`planned_end_date` follow a
   `[start, end)` half-open interval (`end > start` enforced, overlap
   computed as `a.start < b.end AND b.start < a.end` in
   `capacity_plan_service`) -- never Occupancy, never a Carrier
   reservation, never a Batch creation.

Entirely additive: no existing column, constraint, or trigger is touched.
Both tables get the shared `reject_hard_delete` trigger, matching
`production_requirements`'/`seeding_program_lines`' own precedent (planner
edits go through `status`/revision transitions, not row deletion).

Downgrade is destructive by nature and is guarded like every other
domain-introducing migration in this codebase: it refuses if either new
table already contains data.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b44ba79079ef"
down_revision: str | None = "b202c013643f"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_REJECT_HARD_DELETE_FUNCTION_NAME = "reject_hard_delete"

FORECAST_BASES = ("grower_estimate", "planning_assumption", "protocol_guidance")
CAPACITY_ALLOCATION_STATUSES = ("active", "cancelled")


def upgrade() -> None:
    # --- 1. batch_harvest_forecasts -----------------------------------------
    op.create_table(
        "batch_harvest_forecasts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_forecast_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("window_start_date", sa.Date(), nullable=False),
        sa.Column("window_end_date", sa.Date(), nullable=False),
        sa.Column("low_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("expected_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column("high_quantity", sa.Numeric(18, 3), nullable=False),
        sa.Column(
            "quantity_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"), nullable=False
        ),
        sa.Column("basis", sa.String(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("revision_reason", sa.String(), nullable=True),
        sa.Column("recorded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint(
            "basis IN ('" + "', '".join(FORECAST_BASES) + "')", name="ck_batch_harvest_forecasts_basis"
        ),
        sa.CheckConstraint(
            "low_quantity >= 0 AND low_quantity <= expected_quantity "
            "AND expected_quantity <= high_quantity AND expected_quantity > 0",
            name="ck_batch_harvest_forecasts_range_shape",
        ),
        sa.CheckConstraint(
            "window_end_date >= window_start_date", name="ck_batch_harvest_forecasts_window_shape"
        ),
        sa.CheckConstraint("revision_number >= 1", name="ck_batch_harvest_forecasts_revision_positive"),
        sa.CheckConstraint(
            "(superseded_at IS NULL) = (superseded_by_forecast_id IS NULL)",
            name="ck_batch_harvest_forecasts_superseded_fields_together",
        ),
        sa.UniqueConstraint(
            "tenant_id", "batch_id", "revision_number", name="uq_batch_harvest_forecasts_batch_revision"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_batch_harvest_forecasts_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_batch_harvest_forecasts_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_batch_harvest_forecasts_tenant_farm_batch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "superseded_by_forecast_id"],
            ["batch_harvest_forecasts.tenant_id", "batch_harvest_forecasts.id"],
            name="fk_batch_harvest_forecasts_tenant_superseded_by",
            # DEFERRABLE: the revision service closes the prior CURRENT row
            # (superseded_by_forecast_id) in the same transaction, before
            # the new row it points at exists -- checked at COMMIT instead.
            deferrable=True, initially="DEFERRED",
        ),
    )
    op.create_index(
        "ux_batch_harvest_forecasts_current_batch",
        "batch_harvest_forecasts",
        ["tenant_id", "farm_id", "batch_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index(
        "ux_batch_harvest_forecasts_tenant_client_command_id",
        "batch_harvest_forecasts",
        ["tenant_id", "client_command_id"],
        unique=True,
    )
    op.create_index(
        "ix_batch_harvest_forecasts_farm_window",
        "batch_harvest_forecasts",
        ["tenant_id", "farm_id", "window_start_date", "window_end_date"],
    )
    op.execute(
        "CREATE TRIGGER batch_harvest_forecasts_no_delete "
        "BEFORE DELETE ON batch_harvest_forecasts "
        f"FOR EACH ROW EXECUTE FUNCTION {_REJECT_HARD_DELETE_FUNCTION_NAME}();"
    )

    # --- 2. production_capacity_allocations ---------------------------------
    op.create_table(
        "production_capacity_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column(
            "production_system_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("production_systems.id"),
            nullable=True,
        ),
        sa.Column("planned_start_date", sa.Date(), nullable=False),
        sa.Column("planned_end_date", sa.Date(), nullable=False),
        sa.Column("planned_capacity_amount", sa.Integer(), nullable=False),
        sa.Column(
            "source_seeding_program_line_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("seeding_program_lines.id"), nullable=True,
        ),
        sa.Column(
            "source_crop_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crop_batches.id"), nullable=True
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("cancelled_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("update_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("update_request_fingerprint", sa.String(), nullable=True),
        sa.Column("cancel_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancel_request_fingerprint", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN ('" + "', '".join(CAPACITY_ALLOCATION_STATUSES) + "')",
            name="ck_production_capacity_allocations_status",
        ),
        sa.CheckConstraint(
            "planned_capacity_amount > 0", name="ck_production_capacity_allocations_amount_positive"
        ),
        sa.CheckConstraint(
            "planned_end_date > planned_start_date", name="ck_production_capacity_allocations_window_shape"
        ),
        sa.CheckConstraint(
            "(status = 'active' AND cancelled_at IS NULL AND cancelled_by_user_id IS NULL) OR "
            "(status = 'cancelled' AND cancelled_at IS NOT NULL AND cancelled_by_user_id IS NOT NULL)",
            name="ck_production_capacity_allocations_status_shape",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"],
            name="fk_production_capacity_allocations_tenant_farm",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_production_capacity_allocations_tenant_farm_location",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "production_system_id"],
            ["production_systems.tenant_id", "production_systems.id"],
            name="fk_production_capacity_allocations_tenant_production_system",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_seeding_program_line_id"],
            ["seeding_program_lines.tenant_id", "seeding_program_lines.farm_id", "seeding_program_lines.id"],
            name="fk_production_capacity_allocations_tenant_farm_seeding_line",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_crop_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_production_capacity_allocations_tenant_farm_batch",
        ),
    )
    op.create_index(
        "ux_production_capacity_allocations_tenant_code_lower",
        "production_capacity_allocations",
        ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )
    op.create_index(
        "ux_production_capacity_allocations_tenant_client_command_id",
        "production_capacity_allocations",
        ["tenant_id", "client_command_id"],
        unique=True,
    )
    op.create_index(
        "ux_production_capacity_allocations_tenant_update_command",
        "production_capacity_allocations",
        ["tenant_id", "update_client_command_id"],
        unique=True,
        postgresql_where=sa.text("update_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_production_capacity_allocations_tenant_cancel_command",
        "production_capacity_allocations",
        ["tenant_id", "cancel_client_command_id"],
        unique=True,
        postgresql_where=sa.text("cancel_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ix_production_capacity_allocations_location_window",
        "production_capacity_allocations",
        ["tenant_id", "farm_id", "location_id", "planned_start_date", "planned_end_date"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_production_capacity_allocations_farm_status",
        "production_capacity_allocations",
        ["tenant_id", "farm_id", "status"],
    )
    op.execute(
        "CREATE TRIGGER production_capacity_allocations_no_delete "
        "BEFORE DELETE ON production_capacity_allocations "
        f"FOR EACH ROW EXECUTE FUNCTION {_REJECT_HARD_DELETE_FUNCTION_NAME}();"
    )


def downgrade() -> None:
    bind = op.get_bind()

    allocation_count = bind.execute(
        sa.text("SELECT count(*) FROM production_capacity_allocations")
    ).scalar_one()
    if allocation_count > 0:
        raise RuntimeError(
            "Cannot downgrade past PILOT-PLAN-001A: "
            f"{allocation_count} existing production_capacity_allocations row(s) would be destroyed."
        )
    forecast_count = bind.execute(sa.text("SELECT count(*) FROM batch_harvest_forecasts")).scalar_one()
    if forecast_count > 0:
        raise RuntimeError(
            f"Cannot downgrade past PILOT-PLAN-001A: {forecast_count} existing batch_harvest_forecasts row(s) "
            "would be destroyed."
        )

    op.execute("DROP TRIGGER IF EXISTS production_capacity_allocations_no_delete ON production_capacity_allocations")
    op.drop_index("ix_production_capacity_allocations_farm_status", table_name="production_capacity_allocations")
    op.drop_index("ix_production_capacity_allocations_location_window", table_name="production_capacity_allocations")
    op.drop_index("ux_production_capacity_allocations_tenant_cancel_command", table_name="production_capacity_allocations")
    op.drop_index("ux_production_capacity_allocations_tenant_update_command", table_name="production_capacity_allocations")
    op.drop_index("ux_production_capacity_allocations_tenant_client_command_id", table_name="production_capacity_allocations")
    op.drop_index("ux_production_capacity_allocations_tenant_code_lower", table_name="production_capacity_allocations")
    op.drop_table("production_capacity_allocations")

    op.execute("DROP TRIGGER IF EXISTS batch_harvest_forecasts_no_delete ON batch_harvest_forecasts")
    op.drop_index("ix_batch_harvest_forecasts_farm_window", table_name="batch_harvest_forecasts")
    op.drop_index("ux_batch_harvest_forecasts_tenant_client_command_id", table_name="batch_harvest_forecasts")
    op.drop_index("ux_batch_harvest_forecasts_current_batch", table_name="batch_harvest_forecasts")
    op.drop_table("batch_harvest_forecasts")
