"""location types and locations

Revision ID: 3cbaeceee9dc
Revises: 471bdd408a33
Create Date: 2026-08-02 12:50:35.892912

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '3cbaeceee9dc'
down_revision: Union[str, None] = '471bdd408a33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (code, name, default_occupiable) — occupiable defaults mark position-level
# types that directly hold crop/product; container/structural types default
# to false. Individual locations may still override this at creation time.
_LOCATION_TYPES = (
    ("greenhouse", "Greenhouse", False),
    ("area", "Area", False),
    ("zone", "Zone", False),
    ("span", "Span", False),
    ("seeding_station", "Seeding Station", False),
    ("germination_chamber", "Germination Chamber", False),
    ("chamber_position", "Chamber Position", True),
    ("grow_table", "Grow Table", False),
    ("table_position", "Table Position", True),
    ("grow_gutter", "Grow Gutter", False),
    ("gutter_side", "Gutter Side", False),
    ("grow_bag_position", "Grow-Bag Position", True),
    ("store", "Store", False),
    ("store_bin", "Store Bin", True),
    ("packing_hall", "Packing Hall", False),
    ("cold_store", "Cold Store", False),
    ("cold_store_position", "Cold-Store Position", True),
    ("dispatch_area", "Dispatch Area", True),
)

# (parent_code | None, child_code) — None means the child may be a farm root.
_HIERARCHY_RULES = (
    (None, "greenhouse"),
    (None, "store"),
    (None, "packing_hall"),
    (None, "cold_store"),
    (None, "dispatch_area"),
    ("greenhouse", "area"),
    ("greenhouse", "zone"),
    ("greenhouse", "span"),
    ("area", "seeding_station"),
    ("area", "germination_chamber"),
    ("area", "grow_table"),
    ("area", "zone"),
    ("area", "span"),
    ("zone", "span"),
    ("zone", "grow_table"),
    ("zone", "grow_gutter"),
    ("span", "grow_table"),
    ("span", "grow_gutter"),
    ("germination_chamber", "chamber_position"),
    ("grow_table", "table_position"),
    ("grow_gutter", "gutter_side"),
    ("grow_gutter", "grow_bag_position"),
    ("gutter_side", "grow_bag_position"),
    ("store", "store_bin"),
    ("cold_store", "cold_store_position"),
)


def upgrade() -> None:
    op.create_table(
        "location_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("default_occupiable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    conn = op.get_bind()
    type_ids: dict[str, str] = {}
    for code, name, default_occupiable in _LOCATION_TYPES:
        result = conn.execute(
            sa.text(
                "INSERT INTO location_types (id, code, name, default_occupiable) "
                "VALUES (gen_random_uuid(), :code, :name, :default_occupiable) "
                "RETURNING id"
            ),
            {"code": code, "name": name, "default_occupiable": default_occupiable},
        )
        type_ids[code] = result.scalar_one()

    op.create_table(
        "location_type_hierarchy_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "parent_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("location_types.id"), nullable=True
        ),
        sa.Column(
            "child_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("location_types.id"), nullable=False
        ),
    )
    op.create_index(
        "ux_location_type_hierarchy_parent_child",
        "location_type_hierarchy_rules",
        ["parent_type_id", "child_type_id"],
        unique=True,
        postgresql_where=sa.text("parent_type_id IS NOT NULL"),
    )
    op.create_index(
        "ux_location_type_hierarchy_root_child",
        "location_type_hierarchy_rules",
        ["child_type_id"],
        unique=True,
        postgresql_where=sa.text("parent_type_id IS NULL"),
    )

    for parent_code, child_code in _HIERARCHY_RULES:
        conn.execute(
            sa.text(
                "INSERT INTO location_type_hierarchy_rules (id, parent_type_id, child_type_id) "
                "VALUES (gen_random_uuid(), :parent_id, :child_id)"
            ),
            {"parent_id": type_ids[parent_code] if parent_code else None, "child_id": type_ids[child_code]},
        )

    op.create_table(
        "locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "parent_location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id"), nullable=True
        ),
        sa.Column(
            "location_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("location_types.id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("greenhouse_classification", sa.String(), nullable=True),
        sa.Column("occupiable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_locations_status"),
        sa.CheckConstraint(
            "greenhouse_classification IS NULL OR greenhouse_classification IN "
            "('nursery', 'leafy_greens', 'vines', 'mixed', 'other')",
            name="ck_locations_greenhouse_classification_allowed",
        ),
    )
    op.create_index(
        "ux_locations_sibling_code_lower",
        "locations",
        ["parent_location_id", sa.text("lower(code)")],
        unique=True,
        postgresql_where=sa.text("parent_location_id IS NOT NULL"),
    )
    op.create_index(
        "ux_locations_root_code_lower",
        "locations",
        ["farm_id", sa.text("lower(code)")],
        unique=True,
        postgresql_where=sa.text("parent_location_id IS NULL"),
    )

    # Whether greenhouse_classification is required or forbidden depends on
    # the row's location_type (via a join to location_types), which a plain
    # CHECK constraint cannot express — enforced here at the DB level as a
    # backstop to schema/service validation.
    op.execute(
        """
        CREATE FUNCTION enforce_location_greenhouse_classification() RETURNS trigger AS $$
        DECLARE
            type_code TEXT;
        BEGIN
            SELECT code INTO type_code FROM location_types WHERE id = NEW.location_type_id;
            IF type_code = 'greenhouse' THEN
                IF NEW.greenhouse_classification IS NULL THEN
                    RAISE EXCEPTION 'greenhouse locations require a greenhouse_classification';
                END IF;
            ELSE
                IF NEW.greenhouse_classification IS NOT NULL THEN
                    RAISE EXCEPTION 'only greenhouse locations may have a greenhouse_classification';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER locations_enforce_greenhouse_classification
        BEFORE INSERT OR UPDATE ON locations
        FOR EACH ROW EXECUTE FUNCTION enforce_location_greenhouse_classification();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS locations_enforce_greenhouse_classification ON locations")
    op.execute("DROP FUNCTION IF EXISTS enforce_location_greenhouse_classification()")

    op.drop_index("ux_locations_root_code_lower", table_name="locations")
    op.drop_index("ux_locations_sibling_code_lower", table_name="locations")
    op.drop_table("locations")

    op.drop_index("ux_location_type_hierarchy_root_child", table_name="location_type_hierarchy_rules")
    op.drop_index("ux_location_type_hierarchy_parent_child", table_name="location_type_hierarchy_rules")
    op.drop_table("location_type_hierarchy_rules")

    op.drop_table("location_types")
