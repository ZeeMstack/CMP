"""location maintenance lifecycle idempotency

UX-IA-001: adds the three new command idempotency column-pairs (update/
deactivate/reactivate) to `locations`, plus their tenant-scoped partial
unique indexes -- mirroring InventoryItem/InventoryCategory's own
per-command shape exactly (see a1c4e8f2b6d3). This is the first idempotency
support `locations` has had for any command; `create_location`/
`bulk_generate_children` remain deliberately non-idempotent (acknowledged,
pre-existing technical debt, explicitly out of scope for this ticket --
see docs/domain/LOCATION_MODEL.md, "Location maintenance lifecycle").

No structural change: `status` (active/inactive) already exists (CMP-004)
and is completely untouched here -- only the command-idempotency evidence
columns are new. All six new columns are nullable; no backfill, no data
touched.

Downgrade is guarded, never blindly destructive: it refuses while any
Location row carries command-history/idempotency evidence in any of the
three new column pairs (i.e. update/deactivate/reactivate has ever actually
been used on any Location) -- mirroring a1c4e8f2b6d3's own guard idiom.

Revision ID: 10430de8731e
Revises: a1c4e8f2b6d3
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '10430de8731e'
down_revision: Union[str, None] = 'a1c4e8f2b6d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "locations", sa.Column("update_client_command_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("locations", sa.Column("update_request_fingerprint", sa.String(), nullable=True))
    op.add_column(
        "locations", sa.Column("deactivation_client_command_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("locations", sa.Column("deactivation_request_fingerprint", sa.String(), nullable=True))
    op.add_column(
        "locations", sa.Column("reactivation_client_command_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("locations", sa.Column("reactivation_request_fingerprint", sa.String(), nullable=True))

    op.create_index(
        "ux_locations_tenant_update_command",
        "locations", ["tenant_id", "update_client_command_id"], unique=True,
        postgresql_where=sa.text("update_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_locations_tenant_deactivation_command",
        "locations", ["tenant_id", "deactivation_client_command_id"], unique=True,
        postgresql_where=sa.text("deactivation_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_locations_tenant_reactivation_command",
        "locations", ["tenant_id", "reactivation_client_command_id"], unique=True,
        postgresql_where=sa.text("reactivation_client_command_id IS NOT NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- guard: never blindly destroy command-idempotency evidence -------
    used_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM locations WHERE "
            "update_client_command_id IS NOT NULL OR "
            "deactivation_client_command_id IS NOT NULL OR "
            "reactivation_client_command_id IS NOT NULL"
        )
    ).scalar_one()
    if used_count > 0:
        raise RuntimeError(
            "Cannot downgrade past UX-IA-001's Location maintenance idempotency columns: "
            f"{used_count} locations row(s) already carry update/deactivate/reactivate command "
            "history. Downgrading would silently destroy real idempotency evidence for those "
            "commands. Do not downgrade past this point once any Location has been renamed, "
            "deactivated, or reactivated."
        )

    # --- only now: drop purely-additive, never-used infrastructure -------
    op.drop_index("ux_locations_tenant_reactivation_command", table_name="locations")
    op.drop_index("ux_locations_tenant_deactivation_command", table_name="locations")
    op.drop_index("ux_locations_tenant_update_command", table_name="locations")

    op.drop_column("locations", "reactivation_request_fingerprint")
    op.drop_column("locations", "reactivation_client_command_id")
    op.drop_column("locations", "deactivation_request_fingerprint")
    op.drop_column("locations", "deactivation_client_command_id")
    op.drop_column("locations", "update_request_fingerprint")
    op.drop_column("locations", "update_client_command_id")
