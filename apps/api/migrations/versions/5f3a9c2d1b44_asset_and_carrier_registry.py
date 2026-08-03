"""asset and carrier registry

Revision ID: 5f3a9c2d1b44
Revises: 3cbaeceee9dc
Create Date: 2026-08-02 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '5f3a9c2d1b44'
down_revision: Union[str, None] = '3cbaeceee9dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (code, name, supports_positions) — only germination_trolley supports
# relative shelf/slot positions in CMP-005.
_ASSET_TYPES = (
    ("germination_trolley", "Germination Trolley", True),
    ("transfer_trolley", "Transfer Trolley", False),
    ("seeding_machine", "Seeding Machine", False),
    ("weighing_scale", "Weighing Scale", False),
    ("label_printer", "Label Printer", False),
)

# (code, name)
_CARRIER_TYPES = (
    ("seed_tray", "Seed Tray"),
    ("cultivation_plate", "Cultivation Plate"),
    ("grow_cube", "Grow Cube"),
    ("grow_bag", "Grow Bag"),
    ("harvest_crate", "Harvest Crate"),
)

_STATUS_CHECK = "status IN ('active', 'inactive', 'damaged', 'retired')"
_RETIRED_DATE_CHECK = "status <> 'retired' OR retired_date IS NOT NULL"


def upgrade() -> None:
    op.create_table(
        "asset_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("supports_positions", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    conn = op.get_bind()
    asset_type_ids: dict[str, str] = {}
    for code, name, supports_positions in _ASSET_TYPES:
        result = conn.execute(
            sa.text(
                "INSERT INTO asset_types (id, code, name, supports_positions) "
                "VALUES (gen_random_uuid(), :code, :name, :supports_positions) "
                "RETURNING id"
            ),
            {"code": code, "name": name, "supports_positions": supports_positions},
        )
        asset_type_ids[code] = result.scalar_one()

    op.create_table(
        "carrier_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
    )

    for code, name in _CARRIER_TYPES:
        conn.execute(
            sa.text(
                "INSERT INTO carrier_types (id, code, name) "
                "VALUES (gen_random_uuid(), :code, :name)"
            ),
            {"code": code, "name": name},
        )

    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "asset_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("asset_types.id"), nullable=False
        ),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("commissioned_date", sa.Date(), nullable=True),
        sa.Column("retired_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_assets_status"),
        sa.CheckConstraint(_RETIRED_DATE_CHECK, name="ck_assets_retired_requires_retired_date"),
    )
    op.create_index(
        "ux_assets_tenant_code_lower", "assets", ["tenant_id", sa.text("lower(code)")], unique=True
    )

    op.create_table(
        "carriers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "carrier_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carrier_types.id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("retired_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_carriers_status"),
        sa.CheckConstraint(_RETIRED_DATE_CHECK, name="ck_carriers_retired_requires_retired_date"),
    )
    op.create_index(
        "ux_carriers_tenant_code_lower", "carriers", ["tenant_id", sa.text("lower(code)")], unique=True
    )

    op.create_table(
        "asset_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column(
            "parent_position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_positions.id"),
            nullable=True,
        ),
        sa.Column("position_kind", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("position_kind IN ('shelf', 'slot')", name="ck_asset_positions_kind_allowed"),
        sa.CheckConstraint(
            "(position_kind = 'shelf' AND parent_position_id IS NULL) OR "
            "(position_kind = 'slot' AND parent_position_id IS NOT NULL)",
            name="ck_asset_positions_kind_matches_parent",
        ),
    )
    op.create_index(
        "ux_asset_positions_sibling_code_lower",
        "asset_positions",
        ["parent_position_id", sa.text("lower(code)")],
        unique=True,
        postgresql_where=sa.text("parent_position_id IS NOT NULL"),
    )
    op.create_index(
        "ux_asset_positions_root_code_lower",
        "asset_positions",
        ["asset_id", sa.text("lower(code)")],
        unique=True,
        postgresql_where=sa.text("parent_position_id IS NULL"),
    )

    # Cross-row structural rules that a CHECK constraint cannot express: the
    # owning asset's type must support positions, and a child position's
    # parent must be a shelf belonging to the same asset.
    op.execute(
        """
        CREATE FUNCTION enforce_asset_position_structure() RETURNS trigger AS $$
        DECLARE
            supports BOOLEAN;
            parent_asset_id UUID;
            parent_kind TEXT;
        BEGIN
            SELECT at.supports_positions INTO supports
            FROM assets a JOIN asset_types at ON at.id = a.asset_type_id
            WHERE a.id = NEW.asset_id;
            IF supports IS NOT TRUE THEN
                RAISE EXCEPTION 'asset type does not support relative positions';
            END IF;

            IF NEW.parent_position_id IS NOT NULL THEN
                SELECT asset_id, position_kind INTO parent_asset_id, parent_kind
                FROM asset_positions WHERE id = NEW.parent_position_id;
                IF parent_asset_id IS NULL THEN
                    RAISE EXCEPTION 'parent position not found';
                END IF;
                IF parent_asset_id <> NEW.asset_id THEN
                    RAISE EXCEPTION 'parent position must belong to the same asset';
                END IF;
                IF parent_kind <> 'shelf' THEN
                    RAISE EXCEPTION 'parent position must be a shelf';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER asset_positions_enforce_structure
        BEFORE INSERT OR UPDATE ON asset_positions
        FOR EACH ROW EXECUTE FUNCTION enforce_asset_position_structure();
        """
    )

    # Hard-delete protection: assets, carriers, and asset positions are
    # immutable history once created (CLAUDE.md rule 7) — this ticket has no
    # retirement/delete command, so the only path to removal is direct SQL,
    # which is rejected at the database level.
    op.execute(
        """
        CREATE FUNCTION reject_hard_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% records cannot be hard-deleted', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER assets_no_delete
        BEFORE DELETE ON assets
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )
    op.execute(
        """
        CREATE TRIGGER carriers_no_delete
        BEFORE DELETE ON carriers
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )
    op.execute(
        """
        CREATE TRIGGER asset_positions_no_delete
        BEFORE DELETE ON asset_positions
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS asset_positions_no_delete ON asset_positions")
    op.execute("DROP TRIGGER IF EXISTS carriers_no_delete ON carriers")
    op.execute("DROP TRIGGER IF EXISTS assets_no_delete ON assets")
    op.execute("DROP FUNCTION IF EXISTS reject_hard_delete()")

    op.execute("DROP TRIGGER IF EXISTS asset_positions_enforce_structure ON asset_positions")
    op.execute("DROP FUNCTION IF EXISTS enforce_asset_position_structure()")

    op.drop_index("ux_asset_positions_root_code_lower", table_name="asset_positions")
    op.drop_index("ux_asset_positions_sibling_code_lower", table_name="asset_positions")
    op.drop_table("asset_positions")

    op.drop_index("ux_carriers_tenant_code_lower", table_name="carriers")
    op.drop_table("carriers")

    op.drop_index("ux_assets_tenant_code_lower", table_name="assets")
    op.drop_table("assets")

    op.drop_table("carrier_types")
    op.drop_table("asset_types")
