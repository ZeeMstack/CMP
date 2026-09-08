"""intervines transplant placement

VINES-OPS-001A -- InterVines Transplant physical placement compatibility.
Adds exactly one `occupancy_compatibility_rules` row: `carrier:grow_cube ->
location:intervines_table`. This is the only compatibility gap left open by
the pre-existing seed data for this exact ticket: `grow_cube` has been a
platform `carrier_types` row since `5f3a9c2d1b44`, and `intervines`/
`intervines_table` have been seeded `location_types` rows (with their own
Nursery-classification-scoped hierarchy rules already in place) since
`9ca4ac801827` -- but no migration has ever connected the two via an
occupancy-compatibility row, so `movement_service._check_compatibility`
would reject a Grow Cube placed on an InterVines Table today.

No new capacity-enforcement trigger is needed here: `b7e2f4a9c1d6`'s
`enforce_transplant_destination_capacity` (attached to
`transplant_destination_lines`) is already generic across every destination
Carrier type, not InterSalads-specific despite its introducing ticket's
name -- it re-validates any destination Carrier's own CarrierType/
CarrierSpecification `biological_position_count` at real transaction commit,
Grow Cube included, with zero changes required here.

Rebased downstream of `475ed950cb4e` (the merge revision closing the
pre-existing `b7e2f4a9c1d6`/`86b9cf24d6ff` two-head split) rather than
directly onto `b7e2f4a9c1d6` alone, so this ticket leaves the migration
graph with exactly one head instead of preserving the ambiguity.

Revision ID: 810e24e6ce43
Revises: 475ed950cb4e
Create Date: 2026-09-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '810e24e6ce43'
down_revision: Union[str, None] = '475ed950cb4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    grow_cube_type_id = bind.execute(
        sa.text("SELECT id FROM carrier_types WHERE code = 'grow_cube'")
    ).scalar_one()
    intervines_table_type_id = bind.execute(
        sa.text("SELECT id FROM location_types WHERE code = 'intervines_table'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO occupancy_compatibility_rules "
            "(id, occupant_carrier_type_id, target_location_type_id) "
            "VALUES (gen_random_uuid(), :occupant_id, :target_id)"
        ),
        {"occupant_id": grow_cube_type_id, "target_id": intervines_table_type_id},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Downgrade guard: never leave live physical data the old model cannot
    # explain -- if any Grow Cube currently occupies an InterVines Table,
    # removing the compatibility rule would make that live state impossible
    # to reproduce under the reverted schema. Do not auto-move Grow Cubes
    # off Tables to force the downgrade through.
    live_occupancy = bind.execute(
        sa.text(
            "SELECT count(*) FROM occupancies o "
            "JOIN carriers c ON c.id = o.occupant_carrier_id "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = 'grow_cube' "
            "JOIN locations l ON l.id = o.target_location_id "
            "JOIN location_types lt ON lt.id = l.location_type_id AND lt.code = 'intervines_table' "
            "WHERE o.end_time IS NULL"
        )
    ).scalar_one()
    if live_occupancy > 0:
        raise RuntimeError(
            "Cannot downgrade past VINES-OPS-001A: "
            f"{live_occupancy} Grow Cube(s) currently occupy an InterVines Table. Removing the "
            "grow_cube -> intervines_table compatibility rule would leave this live physical state "
            "unreproducible under the reverted schema. Move the affected Grow Cube(s) off InterVines "
            "Tables out-of-band before downgrading, or do not downgrade."
        )

    grow_cube_type_id = bind.execute(
        sa.text("SELECT id FROM carrier_types WHERE code = 'grow_cube'")
    ).scalar_one()
    intervines_table_type_id = bind.execute(
        sa.text("SELECT id FROM location_types WHERE code = 'intervines_table'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "DELETE FROM occupancy_compatibility_rules "
            "WHERE occupant_carrier_type_id = :occupant_id AND target_location_type_id = :target_id"
        ),
        {"occupant_id": grow_cube_type_id, "target_id": intervines_table_type_id},
    )
