"""occupancy and movement

Revision ID: 8a2c6f1e9d33
Revises: 5f3a9c2d1b44
Create Date: 2026-08-03 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '8a2c6f1e9d33'
down_revision: Union[str, None] = '5f3a9c2d1b44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (occupant_kind, occupant_type_code, target_kind, target_type_code)
_COMPATIBILITY_RULES = (
    ("asset", "germination_trolley", "location", "chamber_position"),
    ("carrier", "seed_tray", "position", "slot"),
    ("carrier", "cultivation_plate", "location", "table_position"),
    ("carrier", "grow_cube", "location", "table_position"),
    ("carrier", "grow_bag", "location", "grow_bag_position"),
)


def upgrade() -> None:
    conn = op.get_bind()

    # --- occupancy_compatibility_rules -----------------------------------
    op.create_table(
        "occupancy_compatibility_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "occupant_asset_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_types.id"),
            nullable=True,
        ),
        sa.Column(
            "occupant_carrier_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carrier_types.id"),
            nullable=True,
        ),
        sa.Column(
            "target_location_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("location_types.id"),
            nullable=True,
        ),
        sa.Column("target_position_kind", sa.String(), nullable=True),
        sa.CheckConstraint(
            "(occupant_asset_type_id IS NOT NULL)::int + (occupant_carrier_type_id IS NOT NULL)::int = 1",
            name="ck_occ_compat_rules_occupant_xor",
        ),
        sa.CheckConstraint(
            "(target_location_type_id IS NOT NULL)::int + (target_position_kind IS NOT NULL)::int = 1",
            name="ck_occ_compat_rules_target_xor",
        ),
        sa.CheckConstraint(
            "target_position_kind IS NULL OR target_position_kind IN ('shelf', 'slot')",
            name="ck_occ_compat_rules_position_kind_allowed",
        ),
    )
    op.create_index(
        "ux_occ_compat_asset_location",
        "occupancy_compatibility_rules",
        ["occupant_asset_type_id", "target_location_type_id"],
        unique=True,
        postgresql_where=sa.text(
            "occupant_asset_type_id IS NOT NULL AND target_location_type_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ux_occ_compat_asset_position",
        "occupancy_compatibility_rules",
        ["occupant_asset_type_id", "target_position_kind"],
        unique=True,
        postgresql_where=sa.text(
            "occupant_asset_type_id IS NOT NULL AND target_position_kind IS NOT NULL"
        ),
    )
    op.create_index(
        "ux_occ_compat_carrier_location",
        "occupancy_compatibility_rules",
        ["occupant_carrier_type_id", "target_location_type_id"],
        unique=True,
        postgresql_where=sa.text(
            "occupant_carrier_type_id IS NOT NULL AND target_location_type_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ux_occ_compat_carrier_position",
        "occupancy_compatibility_rules",
        ["occupant_carrier_type_id", "target_position_kind"],
        unique=True,
        postgresql_where=sa.text(
            "occupant_carrier_type_id IS NOT NULL AND target_position_kind IS NOT NULL"
        ),
    )

    for occupant_kind, occupant_code, target_kind, target_code in _COMPATIBILITY_RULES:
        if occupant_kind == "asset":
            occupant_asset_type_id = conn.execute(
                sa.text("SELECT id FROM asset_types WHERE code = :code"), {"code": occupant_code}
            ).scalar_one()
            occupant_carrier_type_id = None
        else:
            occupant_asset_type_id = None
            occupant_carrier_type_id = conn.execute(
                sa.text("SELECT id FROM carrier_types WHERE code = :code"), {"code": occupant_code}
            ).scalar_one()

        if target_kind == "location":
            target_location_type_id = conn.execute(
                sa.text("SELECT id FROM location_types WHERE code = :code"), {"code": target_code}
            ).scalar_one()
            target_position_kind = None
        else:
            target_location_type_id = None
            target_position_kind = target_code

        conn.execute(
            sa.text(
                "INSERT INTO occupancy_compatibility_rules "
                "(id, occupant_asset_type_id, occupant_carrier_type_id, target_location_type_id, target_position_kind) "
                "VALUES (gen_random_uuid(), :oat, :oct, :tlt, :tpk)"
            ),
            {
                "oat": occupant_asset_type_id,
                "oct": occupant_carrier_type_id,
                "tlt": target_location_type_id,
                "tpk": target_position_kind,
            },
        )

    # --- movements --------------------------------------------------------
    op.create_table(
        "movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("occupant_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("occupant_carrier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carriers.id"), nullable=True),
        sa.Column("source_location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id"), nullable=True),
        sa.Column(
            "source_asset_position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_positions.id"),
            nullable=True,
        ),
        sa.Column(
            "destination_location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id"), nullable=True
        ),
        sa.Column(
            "destination_asset_position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_positions.id"),
            nullable=True,
        ),
        sa.Column("command_type", sa.String(), nullable=False, server_default="movement"),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.CheckConstraint(
            "(occupant_asset_id IS NOT NULL)::int + (occupant_carrier_id IS NOT NULL)::int = 1",
            name="ck_movements_occupant_xor",
        ),
        sa.CheckConstraint(
            "NOT (source_location_id IS NOT NULL AND source_asset_position_id IS NOT NULL)",
            name="ck_movements_source_at_most_one",
        ),
        sa.CheckConstraint(
            "NOT (destination_location_id IS NOT NULL AND destination_asset_position_id IS NOT NULL)",
            name="ck_movements_destination_at_most_one",
        ),
        sa.CheckConstraint(
            "source_location_id IS NOT NULL OR source_asset_position_id IS NOT NULL "
            "OR destination_location_id IS NOT NULL OR destination_asset_position_id IS NOT NULL",
            name="ck_movements_source_or_destination_present",
        ),
        sa.CheckConstraint(
            "NOT (source_location_id IS NOT NULL AND source_location_id = destination_location_id)",
            name="ck_movements_source_destination_location_distinct",
        ),
        sa.CheckConstraint(
            "NOT (source_asset_position_id IS NOT NULL AND source_asset_position_id = destination_asset_position_id)",
            name="ck_movements_source_destination_position_distinct",
        ),
        sa.CheckConstraint("command_type IN ('movement')", name="ck_movements_command_type_allowed"),
    )
    op.create_index(
        "ux_movements_tenant_command_client_id",
        "movements",
        ["tenant_id", "command_type", "client_command_id"],
        unique=True,
    )

    op.execute(
        """
        CREATE FUNCTION reject_movement_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'movements is append-only: % not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER movements_no_update
        BEFORE UPDATE ON movements
        FOR EACH ROW EXECUTE FUNCTION reject_movement_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER movements_no_delete
        BEFORE DELETE ON movements
        FOR EACH ROW EXECUTE FUNCTION reject_movement_mutation();
        """
    )

    # --- occupancies --------------------------------------------------------
    op.create_table(
        "occupancies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("occupant_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("occupant_carrier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carriers.id"), nullable=True),
        sa.Column("target_location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id"), nullable=True),
        sa.Column(
            "target_asset_position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("asset_positions.id"),
            nullable=True,
        ),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "opened_by_movement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("movements.id"), nullable=False
        ),
        sa.Column(
            "closed_by_movement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("movements.id"), nullable=True
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(occupant_asset_id IS NOT NULL)::int + (occupant_carrier_id IS NOT NULL)::int = 1",
            name="ck_occupancies_occupant_xor",
        ),
        sa.CheckConstraint(
            "(target_location_id IS NOT NULL)::int + (target_asset_position_id IS NOT NULL)::int = 1",
            name="ck_occupancies_target_xor",
        ),
        sa.CheckConstraint(
            "end_time IS NULL OR end_time >= effective_time", name="ck_occupancies_end_after_effective"
        ),
        sa.CheckConstraint(
            "(end_time IS NULL) = (closed_by_movement_id IS NULL)",
            name="ck_occupancies_closure_fields_together",
        ),
    )
    op.create_index(
        "ux_occupancies_active_occupant_asset",
        "occupancies",
        ["occupant_asset_id"],
        unique=True,
        postgresql_where=sa.text("end_time IS NULL AND occupant_asset_id IS NOT NULL"),
    )
    op.create_index(
        "ux_occupancies_active_occupant_carrier",
        "occupancies",
        ["occupant_carrier_id"],
        unique=True,
        postgresql_where=sa.text("end_time IS NULL AND occupant_carrier_id IS NOT NULL"),
    )
    op.create_index(
        "ux_occupancies_active_target_location",
        "occupancies",
        ["target_location_id"],
        unique=True,
        postgresql_where=sa.text("end_time IS NULL AND target_location_id IS NOT NULL"),
    )
    op.create_index(
        "ux_occupancies_active_target_position",
        "occupancies",
        ["target_asset_position_id"],
        unique=True,
        postgresql_where=sa.text("end_time IS NULL AND target_asset_position_id IS NOT NULL"),
    )

    # Cross-row integrity a CHECK constraint cannot express: occupant/target
    # existence, tenant/farm match, active status, occupiability, self-
    # position, compatibility-rule membership, and opening-movement match.
    op.execute(
        """
        CREATE FUNCTION enforce_occupancy_insert_integrity() RETURNS trigger AS $$
        DECLARE
            occ_tenant UUID;
            occ_farm UUID;
            occ_status TEXT;
            occ_asset_type_id UUID;
            occ_carrier_type_id UUID;
            tgt_tenant UUID;
            tgt_farm UUID;
            tgt_status TEXT;
            tgt_occupiable BOOLEAN;
            tgt_location_type_id UUID;
            pos_asset_id UUID;
            pos_kind TEXT;
            rule_found INT;
            mv_tenant UUID;
            mv_farm UUID;
            mv_occ_asset UUID;
            mv_occ_carrier UUID;
            mv_dest_loc UUID;
            mv_dest_pos UUID;
            mv_effective TIMESTAMPTZ;
        BEGIN
            IF NEW.end_time IS NOT NULL OR NEW.closed_by_movement_id IS NOT NULL THEN
                RAISE EXCEPTION 'occupancy must be inserted as active';
            END IF;

            IF NEW.occupant_asset_id IS NOT NULL THEN
                SELECT tenant_id, farm_id, status, asset_type_id INTO occ_tenant, occ_farm, occ_status, occ_asset_type_id
                FROM assets WHERE id = NEW.occupant_asset_id;
            ELSE
                SELECT tenant_id, farm_id, status, carrier_type_id INTO occ_tenant, occ_farm, occ_status, occ_carrier_type_id
                FROM carriers WHERE id = NEW.occupant_carrier_id;
            END IF;
            IF occ_tenant IS NULL THEN
                RAISE EXCEPTION 'occupant not found';
            END IF;
            IF occ_tenant <> NEW.tenant_id OR occ_farm <> NEW.farm_id THEN
                RAISE EXCEPTION 'occupant tenant/farm mismatch';
            END IF;
            IF occ_status <> 'active' THEN
                RAISE EXCEPTION 'occupant is not active';
            END IF;

            IF NEW.target_location_id IS NOT NULL THEN
                SELECT tenant_id, farm_id, status, occupiable, location_type_id
                INTO tgt_tenant, tgt_farm, tgt_status, tgt_occupiable, tgt_location_type_id
                FROM locations WHERE id = NEW.target_location_id;
                IF tgt_tenant IS NULL THEN
                    RAISE EXCEPTION 'target location not found';
                END IF;
                IF tgt_tenant <> NEW.tenant_id OR tgt_farm <> NEW.farm_id THEN
                    RAISE EXCEPTION 'target location tenant/farm mismatch';
                END IF;
                IF tgt_status <> 'active' THEN
                    RAISE EXCEPTION 'target location is not active';
                END IF;
                IF NOT tgt_occupiable THEN
                    RAISE EXCEPTION 'target location is not occupiable';
                END IF;
            ELSE
                SELECT asset_id, position_kind INTO pos_asset_id, pos_kind
                FROM asset_positions WHERE id = NEW.target_asset_position_id;
                IF pos_asset_id IS NULL THEN
                    RAISE EXCEPTION 'target asset position not found';
                END IF;
                IF NEW.occupant_asset_id IS NOT NULL AND NEW.occupant_asset_id = pos_asset_id THEN
                    RAISE EXCEPTION 'an asset cannot occupy its own position';
                END IF;
                SELECT tenant_id, farm_id, status INTO tgt_tenant, tgt_farm, tgt_status
                FROM assets WHERE id = pos_asset_id;
                IF tgt_tenant <> NEW.tenant_id OR tgt_farm <> NEW.farm_id THEN
                    RAISE EXCEPTION 'containing asset tenant/farm mismatch';
                END IF;
                IF tgt_status <> 'active' THEN
                    RAISE EXCEPTION 'containing asset is not active';
                END IF;
            END IF;

            IF NEW.target_location_id IS NOT NULL THEN
                IF NEW.occupant_asset_id IS NOT NULL THEN
                    SELECT 1 INTO rule_found FROM occupancy_compatibility_rules
                    WHERE occupant_asset_type_id = occ_asset_type_id AND target_location_type_id = tgt_location_type_id;
                ELSE
                    SELECT 1 INTO rule_found FROM occupancy_compatibility_rules
                    WHERE occupant_carrier_type_id = occ_carrier_type_id AND target_location_type_id = tgt_location_type_id;
                END IF;
            ELSE
                IF NEW.occupant_asset_id IS NOT NULL THEN
                    SELECT 1 INTO rule_found FROM occupancy_compatibility_rules
                    WHERE occupant_asset_type_id = occ_asset_type_id AND target_position_kind = pos_kind;
                ELSE
                    SELECT 1 INTO rule_found FROM occupancy_compatibility_rules
                    WHERE occupant_carrier_type_id = occ_carrier_type_id AND target_position_kind = pos_kind;
                END IF;
            END IF;
            IF rule_found IS NULL THEN
                RAISE EXCEPTION 'occupant type is not compatible with target type';
            END IF;

            SELECT tenant_id, farm_id, occupant_asset_id, occupant_carrier_id,
                   destination_location_id, destination_asset_position_id, effective_time
            INTO mv_tenant, mv_farm, mv_occ_asset, mv_occ_carrier, mv_dest_loc, mv_dest_pos, mv_effective
            FROM movements WHERE id = NEW.opened_by_movement_id;
            IF mv_tenant IS NULL THEN
                RAISE EXCEPTION 'opening movement not found';
            END IF;
            IF mv_tenant <> NEW.tenant_id OR mv_farm <> NEW.farm_id THEN
                RAISE EXCEPTION 'opening movement tenant/farm mismatch';
            END IF;
            IF NOT (mv_occ_asset IS NOT DISTINCT FROM NEW.occupant_asset_id
                    AND mv_occ_carrier IS NOT DISTINCT FROM NEW.occupant_carrier_id) THEN
                RAISE EXCEPTION 'opening movement occupant mismatch';
            END IF;
            IF NOT (mv_dest_loc IS NOT DISTINCT FROM NEW.target_location_id
                    AND mv_dest_pos IS NOT DISTINCT FROM NEW.target_asset_position_id) THEN
                RAISE EXCEPTION 'opening movement destination mismatch';
            END IF;
            IF mv_effective <> NEW.effective_time THEN
                RAISE EXCEPTION 'opening movement effective_time mismatch';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER occupancies_enforce_insert_integrity
        BEFORE INSERT ON occupancies
        FOR EACH ROW EXECUTE FUNCTION enforce_occupancy_insert_integrity();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_occupancy_closure_only() RETURNS trigger AS $$
        DECLARE
            mv_tenant UUID;
            mv_farm UUID;
            mv_occ_asset UUID;
            mv_occ_carrier UUID;
            mv_src_loc UUID;
            mv_src_pos UUID;
            mv_effective TIMESTAMPTZ;
        BEGIN
            IF OLD.end_time IS NOT NULL THEN
                RAISE EXCEPTION 'occupancy is already closed and cannot be modified';
            END IF;

            IF NEW.tenant_id <> OLD.tenant_id
               OR NEW.farm_id <> OLD.farm_id
               OR NOT (NEW.occupant_asset_id IS NOT DISTINCT FROM OLD.occupant_asset_id)
               OR NOT (NEW.occupant_carrier_id IS NOT DISTINCT FROM OLD.occupant_carrier_id)
               OR NOT (NEW.target_location_id IS NOT DISTINCT FROM OLD.target_location_id)
               OR NOT (NEW.target_asset_position_id IS NOT DISTINCT FROM OLD.target_asset_position_id)
               OR NEW.effective_time <> OLD.effective_time
               OR NEW.opened_by_movement_id <> OLD.opened_by_movement_id
               OR NOT (NEW.actor_user_id IS NOT DISTINCT FROM OLD.actor_user_id)
            THEN
                RAISE EXCEPTION 'only end_time and closed_by_movement_id may change when closing an occupancy';
            END IF;

            IF NEW.end_time IS NULL OR NEW.closed_by_movement_id IS NULL THEN
                RAISE EXCEPTION 'closing an occupancy requires both end_time and closed_by_movement_id';
            END IF;
            IF NEW.end_time < NEW.effective_time THEN
                RAISE EXCEPTION 'end_time cannot precede effective_time';
            END IF;

            SELECT tenant_id, farm_id, occupant_asset_id, occupant_carrier_id,
                   source_location_id, source_asset_position_id, effective_time
            INTO mv_tenant, mv_farm, mv_occ_asset, mv_occ_carrier, mv_src_loc, mv_src_pos, mv_effective
            FROM movements WHERE id = NEW.closed_by_movement_id;
            IF mv_tenant IS NULL THEN
                RAISE EXCEPTION 'closing movement not found';
            END IF;
            IF mv_tenant <> NEW.tenant_id OR mv_farm <> NEW.farm_id THEN
                RAISE EXCEPTION 'closing movement tenant/farm mismatch';
            END IF;
            IF NOT (mv_occ_asset IS NOT DISTINCT FROM NEW.occupant_asset_id
                    AND mv_occ_carrier IS NOT DISTINCT FROM NEW.occupant_carrier_id) THEN
                RAISE EXCEPTION 'closing movement occupant mismatch';
            END IF;
            IF NOT (mv_src_loc IS NOT DISTINCT FROM NEW.target_location_id
                    AND mv_src_pos IS NOT DISTINCT FROM NEW.target_asset_position_id) THEN
                RAISE EXCEPTION 'closing movement source must match occupancy target';
            END IF;
            IF mv_effective <> NEW.end_time THEN
                RAISE EXCEPTION 'closing movement effective_time must match occupancy end_time';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER occupancies_enforce_closure_only
        BEFORE UPDATE ON occupancies
        FOR EACH ROW EXECUTE FUNCTION enforce_occupancy_closure_only();
        """
    )

    # Reuses the delete-rejection function created by CMP-005 (5f3a9c2d1b44).
    op.execute(
        """
        CREATE TRIGGER occupancies_no_delete
        BEFORE DELETE ON occupancies
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS occupancies_no_delete ON occupancies")
    op.execute("DROP TRIGGER IF EXISTS occupancies_enforce_closure_only ON occupancies")
    op.execute("DROP FUNCTION IF EXISTS enforce_occupancy_closure_only()")
    op.execute("DROP TRIGGER IF EXISTS occupancies_enforce_insert_integrity ON occupancies")
    op.execute("DROP FUNCTION IF EXISTS enforce_occupancy_insert_integrity()")

    op.drop_index("ux_occupancies_active_target_position", table_name="occupancies")
    op.drop_index("ux_occupancies_active_target_location", table_name="occupancies")
    op.drop_index("ux_occupancies_active_occupant_carrier", table_name="occupancies")
    op.drop_index("ux_occupancies_active_occupant_asset", table_name="occupancies")
    op.drop_table("occupancies")

    op.execute("DROP TRIGGER IF EXISTS movements_no_delete ON movements")
    op.execute("DROP TRIGGER IF EXISTS movements_no_update ON movements")
    op.execute("DROP FUNCTION IF EXISTS reject_movement_mutation()")
    op.drop_index("ux_movements_tenant_command_client_id", table_name="movements")
    op.drop_table("movements")

    op.drop_index("ux_occ_compat_carrier_position", table_name="occupancy_compatibility_rules")
    op.drop_index("ux_occ_compat_carrier_location", table_name="occupancy_compatibility_rules")
    op.drop_index("ux_occ_compat_asset_position", table_name="occupancy_compatibility_rules")
    op.drop_index("ux_occ_compat_asset_location", table_name="occupancy_compatibility_rules")
    op.drop_table("occupancy_compatibility_rules")
