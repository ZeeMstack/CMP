"""intersalads transplant placement

NURSERY-OPS-004B.1 -- InterSalads Transplant backend + atomic physical
placement. Two additive, independent changes, bundled in one migration
following the established convention (e.g. e5b8c3a72f04 bundled a table, seed
data, and multiple triggers together):

1. Adds exactly one `occupancy_compatibility_rules` row:
   `carrier:nursery_cultivation_plate -> location:intersalads_table`. This is
   the only compatibility gap CARRIER-CONFIG-001B's own carrier-type seed
   migration (e5b8c3a72f04) deliberately left open for this exact ticket
   (see that migration's own docstring: "No InterSalads occupancy-
   compatibility rows... all explicitly out of scope for this ticket").
   Does NOT touch `production_cultivation_plate` (a different ticket's
   scope) or the historical generic `cultivation_plate` rows.

2. Adds a database integrity backstop for Transplant destination biological
   capacity, following the exact architecture and conventions
   `f3a8c2e1b975`'s own `enforce_transplant_reconciliation` already
   established for this domain: a `DEFERRABLE INITIALLY DEFERRED`
   `AFTER INSERT` constraint trigger on `transplant_destination_lines`,
   re-validated at real transaction commit (defending against a later,
   separate transaction inserting a row directly via SQL -- the service
   layer, `transplant_service._record_transplant_core`, already enforces
   this identical rule under an already-held Carrier row lock before any
   insert, so this trigger is unreachable via the normal application path
   in ordinary operation). Two conditions, both symmetric with the service-
   layer check:
     a. if the destination Carrier's CarrierType requires a specification
        (`carrier_types.requires_specification`), that Carrier must
        reference a specification with a positive
        `biological_position_count` -- a structurally-invalid destination
        fails closed;
     b. if a `biological_position_count` is known (regardless of whether
        the CarrierType requires one), `assigned_plant_count` must not
        exceed it.
   Deliberately does NOT check `carrier_specifications.status` -- an
   existing active Carrier whose specification has since gone inactive
   remains Transplant-eligible (frozen product rule; deactivation only
   blocks NEW Carrier registrations against that specification, see
   `carrier_specification_service.deactivate_carrier_specification`).
   No new, unrelated generalized trigger framework is introduced -- one
   dedicated function, attached the same way its sibling reconciliation
   triggers already are.

Revision ID: b7e2f4a9c1d6
Revises: d9a417c5e832
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e2f4a9c1d6'
down_revision: Union[str, None] = 'd9a417c5e832'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. carrier:nursery_cultivation_plate -> location:intersalads_table --------
    nursery_plate_type_id = bind.execute(
        sa.text("SELECT id FROM carrier_types WHERE code = 'nursery_cultivation_plate'")
    ).scalar_one()
    intersalads_table_type_id = bind.execute(
        sa.text("SELECT id FROM location_types WHERE code = 'intersalads_table'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO occupancy_compatibility_rules "
            "(id, occupant_carrier_type_id, target_location_type_id) "
            "VALUES (gen_random_uuid(), :occupant_id, :target_id)"
        ),
        {"occupant_id": nursery_plate_type_id, "target_id": intersalads_table_type_id},
    )

    # --- 2. Transplant destination biological-capacity DB backstop -----------------
    op.execute(
        """
        CREATE FUNCTION enforce_transplant_destination_capacity() RETURNS trigger AS $$
        DECLARE
            v_requires_specification BOOLEAN;
            v_biological_position_count INTEGER;
        BEGIN
            SELECT ct.requires_specification, cs.biological_position_count
            INTO v_requires_specification, v_biological_position_count
            FROM carriers c
            JOIN carrier_types ct ON ct.id = c.carrier_type_id
            LEFT JOIN carrier_specifications cs ON cs.id = c.specification_id
            WHERE c.id = NEW.destination_carrier_id;

            IF v_requires_specification AND v_biological_position_count IS NULL THEN
                RAISE EXCEPTION
                    'transplant destination line %: destination carrier % requires a specification with a '
                    'positive biological_position_count, but none is configured',
                    NEW.id, NEW.destination_carrier_id;
            END IF;

            IF v_biological_position_count IS NOT NULL AND NEW.assigned_plant_count > v_biological_position_count THEN
                RAISE EXCEPTION
                    'transplant destination line %: assigned_plant_count (%) exceeds destination carrier %''s '
                    'specification biological_position_count (%)',
                    NEW.id, NEW.assigned_plant_count, NEW.destination_carrier_id, v_biological_position_count;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER transplant_destination_lines_enforce_capacity
        AFTER INSERT ON transplant_destination_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_transplant_destination_capacity();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: never leave live physical data the old model cannot
    # explain -- if any Nursery Cultivation Plate currently occupies an
    # InterSalads Table, removing the compatibility rule would make that live
    # state impossible to reproduce under the reverted schema. Do not
    # auto-move Plates off Tables to force the downgrade through.
    live_occupancy = bind.execute(
        sa.text(
            "SELECT count(*) FROM occupancies o "
            "JOIN carriers c ON c.id = o.occupant_carrier_id "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = 'nursery_cultivation_plate' "
            "JOIN locations l ON l.id = o.target_location_id "
            "JOIN location_types lt ON lt.id = l.location_type_id AND lt.code = 'intersalads_table' "
            "WHERE o.end_time IS NULL"
        )
    ).scalar_one()
    if live_occupancy > 0:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-004B.1: "
            f"{live_occupancy} Nursery Cultivation Plate(s) currently occupy an InterSalads Table. Removing "
            "the nursery_cultivation_plate -> intersalads_table compatibility rule would leave this live "
            "physical state unreproducible under the reverted schema. Move the affected Plate(s) off "
            "InterSalads Tables out-of-band before downgrading, or do not downgrade."
        )

    op.execute(
        "DROP TRIGGER IF EXISTS transplant_destination_lines_enforce_capacity ON transplant_destination_lines"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_transplant_destination_capacity()")

    nursery_plate_type_id = bind.execute(
        sa.text("SELECT id FROM carrier_types WHERE code = 'nursery_cultivation_plate'")
    ).scalar_one()
    intersalads_table_type_id = bind.execute(
        sa.text("SELECT id FROM location_types WHERE code = 'intersalads_table'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "DELETE FROM occupancy_compatibility_rules "
            "WHERE occupant_carrier_type_id = :occupant_id AND target_location_type_id = :target_id"
        ),
        {"occupant_id": nursery_plate_type_id, "target_id": intersalads_table_type_id},
    )
