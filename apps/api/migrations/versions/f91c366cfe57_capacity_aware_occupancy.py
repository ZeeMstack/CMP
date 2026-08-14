"""capacity-aware occupancy

DOMAIN-FARM-002: locations and asset_positions gain a nullable `capacity`
column (NULL/1 -> effective capacity 1, exclusive, backward-compatible; >1
permits that many simultaneous identified occupants). The universal
target-side unique indexes (`ux_occupancies_active_target_location`,
`ux_occupancies_active_target_position`) are replaced by row-locking,
concurrency-safe capacity enforcement inside the existing
`enforce_occupancy_insert_integrity` trigger (originally created by
8a2c6f1e9d33). Occupant-side exclusivity
(`ux_occupancies_active_occupant_asset`/`_carrier`) is untouched. Does NOT
add Carrier-as-occupancy-target (`target_carrier_id`) -- occupancy target
shape remains Location XOR AssetPosition only.

Revision ID: f91c366cfe57
Revises: 9ca4ac801827
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f91c366cfe57'
down_revision: Union[str, None] = '9ca4ac801827'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CAPACITY_EXCEEDED_MARKER = "CMP-DOMAIN-FARM-002 target capacity exceeded"
_CAPACITY_REDUCTION_MARKER = "CMP-DOMAIN-FARM-002 capacity reduction would violate active occupancy count"

# The exact pre-DOMAIN-FARM-002 function body (8a2c6f1e9d33), reproduced here
# so downgrade() can restore it verbatim -- migrations are immutable, so this
# file (not 8a2c6f1e9d33) owns the capacity-aware replacement and its own
# precise reversal.
_ORIGINAL_INSERT_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_occupancy_insert_integrity() RETURNS trigger AS $$
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

# DOMAIN-FARM-002: same function, with the target SELECTs upgraded to
# `FOR UPDATE` (locking the target row so concurrent inserters targeting the
# same row serialize here -- the authoritative, concurrency-safe backstop
# required even for direct-SQL/ORM writes that bypass movement_service) and
# a capacity check immediately after each target's existing validity checks.
# COALESCE(capacity, 1) preserves exact pre-existing exclusive behavior for
# every row with capacity left NULL.
_CAPACITY_AWARE_INSERT_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_occupancy_insert_integrity() RETURNS trigger AS $$
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
        tgt_capacity INT;
        active_count INT;
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
            SELECT tenant_id, farm_id, status, occupiable, location_type_id, capacity
            INTO tgt_tenant, tgt_farm, tgt_status, tgt_occupiable, tgt_location_type_id, tgt_capacity
            FROM locations WHERE id = NEW.target_location_id
            FOR UPDATE;
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

            SELECT COUNT(*) INTO active_count FROM occupancies
            WHERE target_location_id = NEW.target_location_id AND end_time IS NULL;
            IF active_count >= COALESCE(tgt_capacity, 1) THEN
                RAISE EXCEPTION '{marker} for location %', NEW.target_location_id
                    USING ERRCODE = 'check_violation';
            END IF;
        ELSE
            SELECT asset_id, position_kind, capacity INTO pos_asset_id, pos_kind, tgt_capacity
            FROM asset_positions WHERE id = NEW.target_asset_position_id
            FOR UPDATE;
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

            SELECT COUNT(*) INTO active_count FROM occupancies
            WHERE target_asset_position_id = NEW.target_asset_position_id AND end_time IS NULL;
            IF active_count >= COALESCE(tgt_capacity, 1) THEN
                RAISE EXCEPTION '{marker} for asset position %', NEW.target_asset_position_id
                    USING ERRCODE = 'check_violation';
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
""".replace("{marker}", _CAPACITY_EXCEEDED_MARKER)


def upgrade() -> None:
    conn = op.get_bind()

    # --- 1. capacity columns + positive-capacity CHECKs --------------------
    op.add_column("locations", sa.Column("capacity", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_locations_capacity_positive", "locations", "capacity IS NULL OR capacity >= 1"
    )
    op.add_column("asset_positions", sa.Column("capacity", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_asset_positions_capacity_positive", "asset_positions", "capacity IS NULL OR capacity >= 1"
    )

    # --- 2. Deliberate, auditable pre-check ---------------------------------
    # The old target-side unique indexes (about to be dropped) already
    # guarantee this, but verify explicitly rather than assume it.
    bad_location = conn.execute(
        sa.text(
            """
            SELECT target_location_id, COUNT(*) FROM occupancies
            WHERE end_time IS NULL AND target_location_id IS NOT NULL
            GROUP BY target_location_id HAVING COUNT(*) > 1 LIMIT 1
            """
        )
    ).first()
    if bad_location is not None:
        raise RuntimeError(
            "DOMAIN-FARM-002 cannot activate capacity enforcement: location "
            f"{bad_location[0]} already has {bad_location[1]} active occupancies, which the "
            "pre-existing target-side unique index should have made impossible. Refusing to "
            "proceed with existing occupancy data this migration cannot trust."
        )
    bad_position = conn.execute(
        sa.text(
            """
            SELECT target_asset_position_id, COUNT(*) FROM occupancies
            WHERE end_time IS NULL AND target_asset_position_id IS NOT NULL
            GROUP BY target_asset_position_id HAVING COUNT(*) > 1 LIMIT 1
            """
        )
    ).first()
    if bad_position is not None:
        raise RuntimeError(
            "DOMAIN-FARM-002 cannot activate capacity enforcement: asset position "
            f"{bad_position[0]} already has {bad_position[1]} active occupancies, which the "
            "pre-existing target-side unique index should have made impossible. Refusing to "
            "proceed with existing occupancy data this migration cannot trust."
        )

    # --- 3. Replace universal target-side exclusivity with capacity --------
    op.drop_index("ux_occupancies_active_target_location", table_name="occupancies")
    op.drop_index("ux_occupancies_active_target_position", table_name="occupancies")

    # --- 4. Row-locking, concurrency-safe capacity enforcement -------------
    op.execute(_CAPACITY_AWARE_INSERT_INTEGRITY_FUNCTION)

    # --- 5. DOMAIN-FARM-002.1: capacity CANNOT be reduced below the current
    # active occupancy count. A plain CHECK can't reference the occupancies
    # table; a trigger is required. Fires only when `capacity` actually
    # changes (the WHEN clause), so unrelated updates to a location/asset
    # position never pay this cost. Concurrency safety needs no explicit
    # `SELECT ... FOR UPDATE` here: an UPDATE statement already holds a row
    # lock on the row it is modifying from the moment it is matched, before
    # any BEFORE-trigger runs -- the identical row `enforce_occupancy_
    # insert_integrity` locks via its own `SELECT ... FOR UPDATE` before
    # counting. Both paths therefore serialize on the SAME target row
    # regardless of which started first: whichever acquires the lock first
    # forces the other to wait, re-read, and see the first's already-
    # committed effect, making the invalid combination (capacity below the
    # committed active count) unreachable either way.
    op.execute(
        f"""
        CREATE FUNCTION enforce_location_capacity_reduction() RETURNS trigger AS $$
        DECLARE
            active_count INT;
        BEGIN
            SELECT COUNT(*) INTO active_count FROM occupancies
            WHERE target_location_id = NEW.id AND end_time IS NULL;
            IF active_count > COALESCE(NEW.capacity, 1) THEN
                RAISE EXCEPTION '{_CAPACITY_REDUCTION_MARKER} for location %', NEW.id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER locations_enforce_capacity_reduction
        BEFORE UPDATE ON locations
        FOR EACH ROW
        WHEN (NEW.capacity IS DISTINCT FROM OLD.capacity)
        EXECUTE FUNCTION enforce_location_capacity_reduction();
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION enforce_asset_position_capacity_reduction() RETURNS trigger AS $$
        DECLARE
            active_count INT;
        BEGIN
            SELECT COUNT(*) INTO active_count FROM occupancies
            WHERE target_asset_position_id = NEW.id AND end_time IS NULL;
            IF active_count > COALESCE(NEW.capacity, 1) THEN
                RAISE EXCEPTION '{_CAPACITY_REDUCTION_MARKER} for asset position %', NEW.id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER asset_positions_enforce_capacity_reduction
        BEFORE UPDATE ON asset_positions
        FOR EACH ROW
        WHEN (NEW.capacity IS DISTINCT FROM OLD.capacity)
        EXECUTE FUNCTION enforce_asset_position_capacity_reduction();
        """
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Refuse to silently destroy configured capacity or collapse multi-
    # occupant targets. Diagnostics only -- never delete/collapse/reset.
    expanded_locations = conn.execute(
        sa.text("SELECT id, code, capacity FROM locations WHERE capacity IS NOT NULL AND capacity > 1 LIMIT 20")
    ).mappings().all()
    expanded_positions = conn.execute(
        sa.text(
            "SELECT id, code, capacity FROM asset_positions WHERE capacity IS NOT NULL AND capacity > 1 LIMIT 20"
        )
    ).mappings().all()
    multi_occupied_locations = conn.execute(
        sa.text(
            """
            SELECT target_location_id, COUNT(*) AS active_count FROM occupancies
            WHERE end_time IS NULL AND target_location_id IS NOT NULL
            GROUP BY target_location_id HAVING COUNT(*) > 1 LIMIT 20
            """
        )
    ).mappings().all()
    multi_occupied_positions = conn.execute(
        sa.text(
            """
            SELECT target_asset_position_id, COUNT(*) AS active_count FROM occupancies
            WHERE end_time IS NULL AND target_asset_position_id IS NOT NULL
            GROUP BY target_asset_position_id HAVING COUNT(*) > 1 LIMIT 20
            """
        )
    ).mappings().all()

    if expanded_locations or expanded_positions or multi_occupied_locations or multi_occupied_positions:
        lines = [
            "DOMAIN-FARM-002 downgrade refused: capacity-aware occupancy is in active use. "
            "Downgrading would restore universal target-side exclusivity and remove capacity "
            "configuration, which cannot be done without destroying business data. Offending rows:"
        ]
        if expanded_locations:
            lines.append(f"  locations with capacity > 1 ({len(expanded_locations)}+ shown, max 20):")
            lines.extend(f"    id={r['id']} code={r['code']} capacity={r['capacity']}" for r in expanded_locations)
        if expanded_positions:
            lines.append(f"  asset_positions with capacity > 1 ({len(expanded_positions)}+ shown, max 20):")
            lines.extend(f"    id={r['id']} code={r['code']} capacity={r['capacity']}" for r in expanded_positions)
        if multi_occupied_locations:
            lines.append(f"  locations with >1 active occupancy ({len(multi_occupied_locations)}+ shown, max 20):")
            lines.extend(
                f"    target_location_id={r['target_location_id']} active_count={r['active_count']}"
                for r in multi_occupied_locations
            )
        if multi_occupied_positions:
            lines.append(
                f"  asset_positions with >1 active occupancy ({len(multi_occupied_positions)}+ shown, max 20):"
            )
            lines.extend(
                f"    target_asset_position_id={r['target_asset_position_id']} active_count={r['active_count']}"
                for r in multi_occupied_positions
            )
        raise RuntimeError("\n".join(lines))

    # Safe: no expanded capacity configured, no target has more than one
    # active occupant. Drop the capacity-reduction guard triggers first --
    # their WHEN clauses depend on the `capacity` column, which is dropped
    # below, and Postgres refuses DROP COLUMN while a trigger still
    # references it.
    op.execute("DROP TRIGGER IF EXISTS asset_positions_enforce_capacity_reduction ON asset_positions")
    op.execute("DROP FUNCTION IF EXISTS enforce_asset_position_capacity_reduction()")
    op.execute("DROP TRIGGER IF EXISTS locations_enforce_capacity_reduction ON locations")
    op.execute("DROP FUNCTION IF EXISTS enforce_location_capacity_reduction()")

    # Restore original exclusivity mechanism exactly.
    op.execute(_ORIGINAL_INSERT_INTEGRITY_FUNCTION)

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

    op.drop_constraint("ck_asset_positions_capacity_positive", "asset_positions", type_="check")
    op.drop_column("asset_positions", "capacity")
    op.drop_constraint("ck_locations_capacity_positive", "locations", type_="check")
    op.drop_column("locations", "capacity")
