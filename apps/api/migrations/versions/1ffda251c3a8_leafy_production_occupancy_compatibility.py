"""leafy production occupancy compatibility

NURSERY-OPS-005B -- adds exactly one `occupancy_compatibility_rules` row:
`carrier:production_cultivation_plate -> location:grow_table`. This is the
one compatibility gap 004B.1's own migration (b7e2f4a9c1d6) deliberately
left open for this exact ticket (see that migration's own docstring:
"Does NOT touch `production_cultivation_plate` (a different ticket's
scope)"), and the sole remaining gap identified by NURSERY-OPS-005A's own
design-discovery rounds and the 005B discovery pass.

Purely additive: does not touch the pre-existing generic
`cultivation_plate -> grow_table` rule, the `nursery_cultivation_plate ->
intersalads_table` rule, or any other existing row. Mirrors the exact
pattern `b7e2f4a9c1d6` already established for the sibling
`nursery_cultivation_plate -> intersalads_table` rule.

`grow_table` is reachable only via the classification-scoped hierarchy
rule `("leafy_greens", "span", "grow_table")` (9ca4ac801827) -- enforced at
the application layer by `location_service.create_location`/
`bulk_generate_children` (there is no `location_type_hierarchy_rules`
DB trigger; Location creation is a service-validated write path, unlike
the heavily-trigger-protected Transplant/Batch domain). This means a
`grow_table`-typed Location can only ever exist as a Leafy Greens Span's
child through the only write path that creates Locations -- so this
migration deliberately adds no separate Leafy-greenhouse-ancestry check of
its own; the compatibility rule plus the existing hierarchy invariant
together are sufficient, and the composite service (leafy_production_
transfer_service) relies on this directly rather than re-deriving it.

No new trigger/function is added -- the existing `enforce_occupancy_insert_
integrity` (f91c366cfe57) and `enforce_transplant_destination_capacity`
(b7e2f4a9c1d6) triggers already consult `occupancy_compatibility_rules`/
`carrier_specifications` generically, so this ticket's Movement and
Transplant-destination-capacity enforcement both work for
`production_cultivation_plate` with zero additional DB code.

Revision ID: 1ffda251c3a8
Revises: 283bad02bb69
Create Date: 2026-08-23 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1ffda251c3a8"
down_revision: str | None = "283bad02bb69"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    production_plate_type_id = bind.execute(
        sa.text("SELECT id FROM carrier_types WHERE code = 'production_cultivation_plate'")
    ).scalar_one()
    grow_table_type_id = bind.execute(
        sa.text("SELECT id FROM location_types WHERE code = 'grow_table'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO occupancy_compatibility_rules "
            "(id, occupant_carrier_type_id, target_location_type_id) "
            "VALUES (gen_random_uuid(), :occupant_id, :target_id)"
        ),
        {"occupant_id": production_plate_type_id, "target_id": grow_table_type_id},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Never silently drop real physical placement history -- if any
    # Production Cultivation Plate currently occupies a Leafy grow_table,
    # removing this compatibility rule would make that live state
    # unreproducible under the reverted schema. Mirrors b7e2f4a9c1d6's own
    # identical downgrade guard exactly, for the sibling rule.
    live_occupancy = bind.execute(
        sa.text(
            "SELECT count(*) FROM occupancies o "
            "JOIN carriers c ON c.id = o.occupant_carrier_id "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = 'production_cultivation_plate' "
            "JOIN locations l ON l.id = o.target_location_id "
            "JOIN location_types lt ON lt.id = l.location_type_id AND lt.code = 'grow_table' "
            "WHERE o.end_time IS NULL"
        )
    ).scalar_one()
    if live_occupancy > 0:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-005B: "
            f"{live_occupancy} Production Cultivation Plate(s) currently occupy a Leafy grow_table. Removing "
            "the production_cultivation_plate -> grow_table compatibility rule would leave this live physical "
            "state unreproducible under the reverted schema. Move the affected Plate(s) off Leafy Tables "
            "out-of-band before downgrading, or do not downgrade."
        )

    production_plate_type_id = bind.execute(
        sa.text("SELECT id FROM carrier_types WHERE code = 'production_cultivation_plate'")
    ).scalar_one()
    grow_table_type_id = bind.execute(
        sa.text("SELECT id FROM location_types WHERE code = 'grow_table'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "DELETE FROM occupancy_compatibility_rules "
            "WHERE occupant_carrier_type_id = :occupant_id AND target_location_type_id = :target_id"
        ),
        {"occupant_id": production_plate_type_id, "target_id": grow_table_type_id},
    )
