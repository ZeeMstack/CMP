"""germination chamber direct trolley occupancy

NURSERY-OPS-002A — FROZEN product decision: there are no fixed/identifiable
Trolley parking positions inside a Germination Chamber. The authoritative
physical model is:

    Nursery Greenhouse
    -> Germination Chamber (occupiable, capacity = number of Trolleys)
        -> Germination Trolley Asset (occupies the Chamber directly)
            -> Shelf/Level AssetPosition
                -> Slot AssetPosition
                    -> Seed Tray Carrier (occupies the Slot)

`chamber_position` (CMP-004/CMP-006) is retired from the *authoritative*
Nursery Germination topology. The LocationType catalog row, its GENERIC
(non-classification-scoped) hierarchy rule, and any existing chamber_position
Location rows OUTSIDE a Nursery Germination Chamber are left completely
untouched -- this migration corrects the Nursery-specific topology and the
germination_trolley compatibility rule only, nothing else. Historical
migrations (3cbaeceee9dc, 8a2c6f1e9d33, 9ca4ac801827) are not edited.

Four changes:

1. Removes the ONE classification-scoped hierarchy rule
   `('nursery', 'germination_chamber', 'chamber_position')` (9ca4ac801827).
   Guarded: fails loudly if any chamber_position Location row already exists
   as a child of a germination_chamber that is itself a direct child of a
   nursery-classified greenhouse (real, pre-existing Nursery topology this
   migration cannot safely discard).

2. Replaces the ONE global `OccupancyCompatibilityRule` row
   `asset:germination_trolley -> location:chamber_position` (8a2c6f1e9d33)
   with `asset:germination_trolley -> location:germination_chamber`.
   Compatibility rules have no classification scoping, so this is a global
   change -- guarded: fails loudly if any ACTIVE Occupancy already has a
   germination_trolley occupant targeting a chamber_position location
   (anywhere), which the new rule set could no longer represent.
   `carrier:seed_tray -> position:slot` is untouched.

3. Sets `occupiable = true` on every existing `germination_chamber` Location
   row. There is no stored flag distinguishing "inherited the old
   default_occupiable=false" from "deliberately set false via the generic
   API" -- given the frozen product decision that a Germination Chamber must
   always be a valid Trolley-occupancy target, and that no feature currently
   depends on any germination_chamber being non-occupiable, migrating all
   existing rows to `true` is safe and unambiguous (ticket section 6).

4. Sets `location_types.default_occupiable = true` for the `germination_chamber`
   catalog row itself (NURSERY-OPS-002A.1). A Germination Chamber is
   unconditionally occupiable by frozen domain rule -- that must be true of
   ANY Germination Chamber created through ANY authorized path (the generic
   `POST /locations` route, not just Farm Setup), not merely a Farm-Setup-
   specific override layered on top of a catalog default that still says
   otherwise. Step 3's existing-row correction and this step are BOTH
   required and neither substitutes for the other: step 3 fixes rows already
   in the database; step 4 fixes what every *future* row defaults to.
   Farm Setup's own explicit `occupiable=True` override at creation
   (`farm_setup_service`) is left in place as defensive clarity -- the same
   pattern already used for `grow_table`/leafy tables -- but is no longer
   the only reason a Chamber ends up occupiable.

Revision ID: c2d6f8a4b153
Revises: a7e4f2c9b381
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c2d6f8a4b153'
down_revision: Union[str, None] = 'a7e4f2c9b381'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- guard 1: real Nursery chamber_position topology ------------------
    orphaned_topology = bind.execute(
        sa.text(
            "SELECT cp.id, cp.code FROM locations cp "
            "JOIN locations gc ON gc.id = cp.parent_location_id "
            "JOIN location_types gc_lt ON gc_lt.id = gc.location_type_id AND gc_lt.code = 'germination_chamber' "
            "JOIN location_types cp_lt ON cp_lt.id = cp.location_type_id AND cp_lt.code = 'chamber_position' "
            "JOIN locations gh ON gh.id = gc.parent_location_id "
            "WHERE gh.greenhouse_classification = 'nursery'"
        )
    ).fetchall()
    if orphaned_topology:
        raise RuntimeError(
            "Cannot retire chamber_position from the authoritative Nursery Germination topology: "
            f"chamber_position row(s) {[str(r[1]) for r in orphaned_topology]} already exist under a Nursery "
            "Germination Chamber. Removing a physical node from existing operational history requires an "
            "explicit operator decision -- resolve this data out-of-band before running this migration."
        )

    # --- guard 2: active Trolley-in-chamber_position occupancy -----------
    orphaned_occupancy = bind.execute(
        sa.text(
            "SELECT o.id FROM occupancies o "
            "JOIN assets a ON a.id = o.occupant_asset_id "
            "JOIN asset_types at ON at.id = a.asset_type_id AND at.code = 'germination_trolley' "
            "JOIN locations l ON l.id = o.target_location_id "
            "JOIN location_types lt ON lt.id = l.location_type_id AND lt.code = 'chamber_position' "
            "WHERE o.end_time IS NULL"
        )
    ).fetchall()
    if orphaned_occupancy:
        raise RuntimeError(
            "Cannot retire the germination_trolley -> chamber_position compatibility rule: "
            f"{len(orphaned_occupancy)} active Occupancy row(s) currently place a Germination Trolley "
            "directly in a chamber_position, which the new germination_trolley -> germination_chamber "
            "rule cannot represent. Move the affected Trolleys out-of-band before running this migration."
        )

    # --- 1. classification-scoped hierarchy rule ---------------------------
    bind.execute(
        sa.text(
            "DELETE FROM location_type_hierarchy_rules "
            "WHERE greenhouse_classification = 'nursery' "
            "AND parent_type_id = (SELECT id FROM location_types WHERE code = 'germination_chamber') "
            "AND child_type_id = (SELECT id FROM location_types WHERE code = 'chamber_position')"
        )
    )

    # --- 2. occupancy compatibility rule ------------------------------------
    bind.execute(
        sa.text(
            "DELETE FROM occupancy_compatibility_rules "
            "WHERE occupant_asset_type_id = (SELECT id FROM asset_types WHERE code = 'germination_trolley') "
            "AND target_location_type_id = (SELECT id FROM location_types WHERE code = 'chamber_position')"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO occupancy_compatibility_rules "
            "(id, occupant_asset_type_id, occupant_carrier_type_id, target_location_type_id, target_position_kind) "
            "VALUES (gen_random_uuid(), "
            "(SELECT id FROM asset_types WHERE code = 'germination_trolley'), NULL, "
            "(SELECT id FROM location_types WHERE code = 'germination_chamber'), NULL)"
        )
    )

    # --- 3. existing Germination Chamber rows become occupiable -------------
    bind.execute(
        sa.text(
            "UPDATE locations SET occupiable = true "
            "WHERE location_type_id = (SELECT id FROM location_types WHERE code = 'germination_chamber') "
            "AND occupiable = false"
        )
    )

    # --- 4. catalog default: every FUTURE Germination Chamber is occupiable -
    bind.execute(
        sa.text(
            "UPDATE location_types SET default_occupiable = true "
            "WHERE code = 'germination_chamber'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: current-model data the old model cannot express --
    current_model_occupancy = bind.execute(
        sa.text(
            "SELECT o.id FROM occupancies o "
            "JOIN assets a ON a.id = o.occupant_asset_id "
            "JOIN asset_types at ON at.id = a.asset_type_id AND at.code = 'germination_trolley' "
            "JOIN locations l ON l.id = o.target_location_id "
            "JOIN location_types lt ON lt.id = l.location_type_id AND lt.code = 'germination_chamber' "
            "WHERE o.end_time IS NULL"
        )
    ).fetchall()
    if current_model_occupancy:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-002A: "
            f"{len(current_model_occupancy)} active Occupancy row(s) place a Germination Trolley directly "
            "in a Germination Chamber (the current model) -- the pre-002A model has no way to represent "
            "this truthfully (it required an intermediate chamber_position). Move the affected Trolleys "
            "out-of-band before downgrading, or do not downgrade."
        )

    # --- revert 2. occupancy compatibility rule -----------------------------
    bind.execute(
        sa.text(
            "DELETE FROM occupancy_compatibility_rules "
            "WHERE occupant_asset_type_id = (SELECT id FROM asset_types WHERE code = 'germination_trolley') "
            "AND target_location_type_id = (SELECT id FROM location_types WHERE code = 'germination_chamber')"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO occupancy_compatibility_rules "
            "(id, occupant_asset_type_id, occupant_carrier_type_id, target_location_type_id, target_position_kind) "
            "VALUES (gen_random_uuid(), "
            "(SELECT id FROM asset_types WHERE code = 'germination_trolley'), NULL, "
            "(SELECT id FROM location_types WHERE code = 'chamber_position'), NULL)"
        )
    )

    # --- revert 1. classification-scoped hierarchy rule ---------------------
    bind.execute(
        sa.text(
            "INSERT INTO location_type_hierarchy_rules "
            "(id, parent_type_id, child_type_id, greenhouse_classification) "
            "VALUES (gen_random_uuid(), "
            "(SELECT id FROM location_types WHERE code = 'germination_chamber'), "
            "(SELECT id FROM location_types WHERE code = 'chamber_position'), 'nursery')"
        )
    )

    # --- revert 3. Germination Chamber occupiable ---------------------------
    # Safe unconditionally at this point: guard above already proved no
    # active Trolley-in-Chamber occupancy exists (the only thing that would
    # make a non-occupiable Chamber an inconsistent state).
    bind.execute(
        sa.text(
            "UPDATE locations SET occupiable = false "
            "WHERE location_type_id = (SELECT id FROM location_types WHERE code = 'germination_chamber')"
        )
    )

    # --- revert 4. catalog default back to pre-002A(.1) value ---------------
    # Same safety reasoning as the row-level revert immediately above: the
    # guard at the top of this function already proved no active
    # Trolley-in-Chamber occupancy exists anywhere, so restoring the old
    # default (new Chambers non-occupiable unless explicitly overridden)
    # cannot orphan any live data.
    bind.execute(
        sa.text(
            "UPDATE location_types SET default_occupiable = false "
            "WHERE code = 'germination_chamber'"
        )
    )
