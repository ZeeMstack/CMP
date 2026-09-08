"""grow_cube transplant source integrity

VINES-OPS-001B -- widens the shared `enforce_transplant_source_line_insert_
integrity` DB trigger function (originally introduced as a SeedlingEntry-only
check, then widened to also accept `nursery_cultivation_plate` by
`283bad02bb69` for NURSERY-OPS-005A) to ALSO accept `grow_cube` as a valid
`batch_carrier_population`-authority source Carrier type.

This is a genuine, required schema-level change discovered while
implementing the InterVines -> Vines Production transfer: the SERVICE-layer
allowlist (`transplant_source_authority.ELIGIBLE_SOURCE_CARRIER_TYPE_CODES`,
a Python-only change) already accepts `grow_cube`, but the DB-level
backstop trigger has its own, independent hardcoded check
(`IF v_carrier_type_code IS DISTINCT FROM 'nursery_cultivation_plate'`) that
would otherwise reject every `grow_cube`-sourced `transplant_source_lines`
insert outright, regardless of the Python-layer check passing. Both layers
must agree on the same eligible-type set -- this migration is that
agreement, applied via `CREATE OR REPLACE FUNCTION` (the same technique
`283bad02bb69` itself already used to widen the function a first time),
never by editing that historical migration file.

The function body is otherwise BYTE-IDENTICAL to `283bad02bb69`'s own
version -- only the type-check condition (now `NOT IN ('nursery_cultivation_
plate', 'grow_cube')`) and the one exception message that named
`nursery_cultivation_plate` specifically (now generic, since it can fire for
either type) are changed. No other trigger, table, or column is touched.

Revision ID: 43246a360bbd
Revises: 810e24e6ce43
Create Date: 2026-09-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '43246a360bbd'
down_revision: Union[str, None] = '810e24e6ce43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_WIDENED_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_transplant_source_line_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_event_batch_id UUID;
        v_event_effective TIMESTAMPTZ;
        v_event_kind TEXT;
        v_assignment_batch_id UUID;
        v_assignment_carrier UUID;
        v_assignment_released TIMESTAMPTZ;
        v_carrier_type_code TEXT;
        v_entry_id UUID;
        v_entry_starting INTEGER;
        v_entry_effective TIMESTAMPTZ;
        v_anchor_value INTEGER;
        v_anchor_time TIMESTAMPTZ;
        v_has_checkpoint BOOLEAN;
        v_latest_disposition TIMESTAMPTZ;
        v_delta_sum INTEGER;
        v_available_before INTEGER;
        v_walk_id UUID;
        v_hops INTEGER;
    BEGIN
        SELECT batch_id, effective_time, event_kind INTO v_event_batch_id, v_event_effective, v_event_kind
        FROM transplant_events WHERE id = NEW.transplant_event_id;

        SELECT batch_id, carrier_id, released_effective_time
        INTO v_assignment_batch_id, v_assignment_carrier, v_assignment_released
        FROM batch_carrier_assignments WHERE id = NEW.source_batch_carrier_assignment_id;
        IF v_assignment_batch_id IS NULL THEN
            RAISE EXCEPTION 'source assignment not found';
        END IF;
        IF v_assignment_batch_id <> v_event_batch_id THEN
            RAISE EXCEPTION 'source assignment does not belong to this transplant event''s batch';
        END IF;
        IF v_assignment_carrier <> NEW.source_carrier_id THEN
            RAISE EXCEPTION 'source carrier does not match assignment carrier';
        END IF;
        IF v_assignment_released IS NOT NULL THEN
            RAISE EXCEPTION 'source assignment is already released';
        END IF;

        -- Resolve the SeedlingEntry via the existing bounded backward
        -- restoration-lineage walk, UNCHANGED.
        v_walk_id := NEW.source_batch_carrier_assignment_id;
        v_hops := 0;
        v_entry_id := NULL;
        LOOP
            SELECT id, starting_living_seedling_count, effective_time
            INTO v_entry_id, v_entry_starting, v_entry_effective
            FROM seedling_entries WHERE batch_carrier_assignment_id = v_walk_id;
            EXIT WHEN v_entry_id IS NOT NULL;
            v_hops := v_hops + 1;
            IF v_hops > 50 THEN
                RAISE EXCEPTION 'restoration lineage exceeds maximum depth for assignment %', NEW.source_batch_carrier_assignment_id;
            END IF;
            SELECT restored_from_batch_carrier_assignment_id INTO v_walk_id
            FROM batch_carrier_assignments WHERE id = v_walk_id;
            EXIT WHEN v_walk_id IS NULL;
        END LOOP;

        IF v_entry_id IS NOT NULL THEN
            -- Existing seed_tray/SeedlingEntry path -- entirely unchanged.
            IF v_event_kind = 'REVERSAL' THEN
                RETURN NEW;
            END IF;

            SELECT c.remainder_after, c.effective_time INTO v_anchor_value, v_anchor_time
            FROM seedling_source_checkpoints c
            WHERE c.seedling_entry_id = v_entry_id
              AND NOT EXISTS (SELECT 1 FROM seedling_source_checkpoints nxt WHERE nxt.previous_checkpoint_id = c.id);
            v_has_checkpoint := v_anchor_value IS NOT NULL;
            IF NOT v_has_checkpoint THEN
                v_anchor_value := v_entry_starting;
                v_anchor_time := v_entry_effective;
            END IF;

            IF v_has_checkpoint THEN
                IF v_event_effective < v_anchor_time THEN
                    RAISE EXCEPTION 'transplant effective_time must not precede the previous checkpoint''s own effective_time';
                ELSIF v_event_effective = v_anchor_time THEN
                    IF v_event_kind <> 'REPLACEMENT' THEN
                        RAISE EXCEPTION 'transplant effective_time must be strictly greater than the previous checkpoint''s own effective_time';
                    END IF;
                END IF;
            ELSE
                IF v_event_effective < v_anchor_time THEN
                    RAISE EXCEPTION 'transplant effective_time precedes the SeedlingEntry''s own effective_time';
                END IF;
            END IF;

            SELECT MAX(effective_time) INTO v_latest_disposition
            FROM seedling_disposition_events
            WHERE seedling_entry_id = v_entry_id AND effective_time > v_anchor_time;
            IF v_latest_disposition IS NOT NULL AND v_event_effective < v_latest_disposition THEN
                RAISE EXCEPTION 'transplant effective_time precedes a disposition already recorded in the currently-open balance window';
            END IF;

            SELECT COALESCE(SUM(quantity_delta), 0) INTO v_delta_sum
            FROM seedling_disposition_events
            WHERE seedling_entry_id = v_entry_id
              AND effective_time > v_anchor_time AND effective_time <= v_event_effective;
            v_available_before := v_anchor_value + v_delta_sum;

            IF NEW.source_plant_count <> v_available_before THEN
                RAISE EXCEPTION 'source_plant_count does not match the authoritative server-derived source availability';
            END IF;

            RETURN NEW;
        END IF;

        -- VINES-OPS-001B: no SeedlingEntry anywhere in this assignment's own
        -- restoration lineage -- the batch_carrier_population authority now
        -- covers TWO Carrier types (nursery_cultivation_plate, grow_cube),
        -- both transplant-created destinations that also became eligible
        -- Transplant sources in their own later ticket. Any other Carrier
        -- type is still rejected with the same message as before.
        SELECT ct.code INTO v_carrier_type_code
        FROM carriers c JOIN carrier_types ct ON ct.id = c.carrier_type_id
        WHERE c.id = v_assignment_carrier;
        IF v_carrier_type_code NOT IN ('nursery_cultivation_plate', 'grow_cube') THEN
            RAISE EXCEPTION 'source assignment has no Seedling biological entry; modern transplant requires a SeedlingEntry-anchored source';
        END IF;

        IF v_event_kind = 'REVERSAL' THEN
            RETURN NEW;
        END IF;

        SELECT c.remainder_after, c.effective_time INTO v_anchor_value, v_anchor_time
        FROM batch_carrier_population_checkpoints c
        WHERE c.batch_carrier_assignment_id = NEW.source_batch_carrier_assignment_id
          AND NOT EXISTS (SELECT 1 FROM batch_carrier_population_checkpoints nxt WHERE nxt.previous_checkpoint_id = c.id);
        v_has_checkpoint := v_anchor_value IS NOT NULL;
        IF NOT v_has_checkpoint THEN
            SELECT dl.assigned_plant_count, te.effective_time INTO v_anchor_value, v_anchor_time
            FROM transplant_destination_lines dl
            JOIN transplant_events te ON te.id = dl.transplant_event_id
            WHERE dl.destination_batch_carrier_assignment_id = NEW.source_batch_carrier_assignment_id;
            IF v_anchor_value IS NULL THEN
                RAISE EXCEPTION 'source assignment has no BatchCarrierPopulationCheckpoint and no TransplantDestinationLine of its own';
            END IF;
        END IF;

        IF v_has_checkpoint THEN
            IF v_event_effective < v_anchor_time THEN
                RAISE EXCEPTION 'transplant effective_time must not precede the previous checkpoint''s own effective_time';
            ELSIF v_event_effective = v_anchor_time THEN
                IF v_event_kind <> 'REPLACEMENT' THEN
                    RAISE EXCEPTION 'transplant effective_time must be strictly greater than the previous checkpoint''s own effective_time';
                END IF;
            END IF;
        ELSE
            IF v_event_effective < v_anchor_time THEN
                RAISE EXCEPTION 'transplant effective_time precedes the destination line''s own transplant event effective_time';
            END IF;
        END IF;

        -- No disposition-style delta ledger exists for this authority in
        -- NURSERY-OPS-005A's scope -- available IS the anchor value.
        IF NEW.source_plant_count <> v_anchor_value THEN
            RAISE EXCEPTION 'source_plant_count does not match the authoritative server-derived source availability';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    op.execute(_WIDENED_FUNCTION)


def downgrade() -> None:
    bind = op.get_bind()

    live_grow_cube_sources = bind.execute(
        sa.text(
            "SELECT count(*) FROM transplant_source_lines tsl "
            "JOIN carriers c ON c.id = tsl.source_carrier_id "
            "JOIN carrier_types ct ON ct.id = c.carrier_type_id AND ct.code = 'grow_cube'"
        )
    ).scalar_one()
    if live_grow_cube_sources > 0:
        raise RuntimeError(
            "Cannot downgrade past VINES-OPS-001B: "
            f"{live_grow_cube_sources} existing transplant_source_lines row(s) already reference a grow_cube "
            "source Carrier. Narrowing enforce_transplant_source_line_insert_integrity back to "
            "nursery_cultivation_plate-only would leave this historical, immutable data unreproducible under "
            "the reverted trigger (a fresh INSERT of an identical row would now be rejected)."
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_transplant_source_line_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_event_batch_id UUID;
            v_event_effective TIMESTAMPTZ;
            v_event_kind TEXT;
            v_assignment_batch_id UUID;
            v_assignment_carrier UUID;
            v_assignment_released TIMESTAMPTZ;
            v_carrier_type_code TEXT;
            v_entry_id UUID;
            v_entry_starting INTEGER;
            v_entry_effective TIMESTAMPTZ;
            v_anchor_value INTEGER;
            v_anchor_time TIMESTAMPTZ;
            v_has_checkpoint BOOLEAN;
            v_latest_disposition TIMESTAMPTZ;
            v_delta_sum INTEGER;
            v_available_before INTEGER;
            v_walk_id UUID;
            v_hops INTEGER;
        BEGIN
            SELECT batch_id, effective_time, event_kind INTO v_event_batch_id, v_event_effective, v_event_kind
            FROM transplant_events WHERE id = NEW.transplant_event_id;

            SELECT batch_id, carrier_id, released_effective_time
            INTO v_assignment_batch_id, v_assignment_carrier, v_assignment_released
            FROM batch_carrier_assignments WHERE id = NEW.source_batch_carrier_assignment_id;
            IF v_assignment_batch_id IS NULL THEN
                RAISE EXCEPTION 'source assignment not found';
            END IF;
            IF v_assignment_batch_id <> v_event_batch_id THEN
                RAISE EXCEPTION 'source assignment does not belong to this transplant event''s batch';
            END IF;
            IF v_assignment_carrier <> NEW.source_carrier_id THEN
                RAISE EXCEPTION 'source carrier does not match assignment carrier';
            END IF;
            IF v_assignment_released IS NOT NULL THEN
                RAISE EXCEPTION 'source assignment is already released';
            END IF;

            v_walk_id := NEW.source_batch_carrier_assignment_id;
            v_hops := 0;
            v_entry_id := NULL;
            LOOP
                SELECT id, starting_living_seedling_count, effective_time
                INTO v_entry_id, v_entry_starting, v_entry_effective
                FROM seedling_entries WHERE batch_carrier_assignment_id = v_walk_id;
                EXIT WHEN v_entry_id IS NOT NULL;
                v_hops := v_hops + 1;
                IF v_hops > 50 THEN
                    RAISE EXCEPTION 'restoration lineage exceeds maximum depth for assignment %', NEW.source_batch_carrier_assignment_id;
                END IF;
                SELECT restored_from_batch_carrier_assignment_id INTO v_walk_id
                FROM batch_carrier_assignments WHERE id = v_walk_id;
                EXIT WHEN v_walk_id IS NULL;
            END LOOP;

            IF v_entry_id IS NOT NULL THEN
                IF v_event_kind = 'REVERSAL' THEN
                    RETURN NEW;
                END IF;

                SELECT c.remainder_after, c.effective_time INTO v_anchor_value, v_anchor_time
                FROM seedling_source_checkpoints c
                WHERE c.seedling_entry_id = v_entry_id
                  AND NOT EXISTS (SELECT 1 FROM seedling_source_checkpoints nxt WHERE nxt.previous_checkpoint_id = c.id);
                v_has_checkpoint := v_anchor_value IS NOT NULL;
                IF NOT v_has_checkpoint THEN
                    v_anchor_value := v_entry_starting;
                    v_anchor_time := v_entry_effective;
                END IF;

                IF v_has_checkpoint THEN
                    IF v_event_effective < v_anchor_time THEN
                        RAISE EXCEPTION 'transplant effective_time must not precede the previous checkpoint''s own effective_time';
                    ELSIF v_event_effective = v_anchor_time THEN
                        IF v_event_kind <> 'REPLACEMENT' THEN
                            RAISE EXCEPTION 'transplant effective_time must be strictly greater than the previous checkpoint''s own effective_time';
                        END IF;
                    END IF;
                ELSE
                    IF v_event_effective < v_anchor_time THEN
                        RAISE EXCEPTION 'transplant effective_time precedes the SeedlingEntry''s own effective_time';
                    END IF;
                END IF;

                SELECT MAX(effective_time) INTO v_latest_disposition
                FROM seedling_disposition_events
                WHERE seedling_entry_id = v_entry_id AND effective_time > v_anchor_time;
                IF v_latest_disposition IS NOT NULL AND v_event_effective < v_latest_disposition THEN
                    RAISE EXCEPTION 'transplant effective_time precedes a disposition already recorded in the currently-open balance window';
                END IF;

                SELECT COALESCE(SUM(quantity_delta), 0) INTO v_delta_sum
                FROM seedling_disposition_events
                WHERE seedling_entry_id = v_entry_id
                  AND effective_time > v_anchor_time AND effective_time <= v_event_effective;
                v_available_before := v_anchor_value + v_delta_sum;

                IF NEW.source_plant_count <> v_available_before THEN
                    RAISE EXCEPTION 'source_plant_count does not match the authoritative server-derived source availability';
                END IF;

                RETURN NEW;
            END IF;

            SELECT ct.code INTO v_carrier_type_code
            FROM carriers c JOIN carrier_types ct ON ct.id = c.carrier_type_id
            WHERE c.id = v_assignment_carrier;
            IF v_carrier_type_code IS DISTINCT FROM 'nursery_cultivation_plate' THEN
                RAISE EXCEPTION 'source assignment has no Seedling biological entry; modern transplant requires a SeedlingEntry-anchored source';
            END IF;

            IF v_event_kind = 'REVERSAL' THEN
                RETURN NEW;
            END IF;

            SELECT c.remainder_after, c.effective_time INTO v_anchor_value, v_anchor_time
            FROM batch_carrier_population_checkpoints c
            WHERE c.batch_carrier_assignment_id = NEW.source_batch_carrier_assignment_id
              AND NOT EXISTS (SELECT 1 FROM batch_carrier_population_checkpoints nxt WHERE nxt.previous_checkpoint_id = c.id);
            v_has_checkpoint := v_anchor_value IS NOT NULL;
            IF NOT v_has_checkpoint THEN
                SELECT dl.assigned_plant_count, te.effective_time INTO v_anchor_value, v_anchor_time
                FROM transplant_destination_lines dl
                JOIN transplant_events te ON te.id = dl.transplant_event_id
                WHERE dl.destination_batch_carrier_assignment_id = NEW.source_batch_carrier_assignment_id;
                IF v_anchor_value IS NULL THEN
                    RAISE EXCEPTION 'nursery_cultivation_plate source assignment has no BatchCarrierPopulationCheckpoint and no TransplantDestinationLine of its own';
                END IF;
            END IF;

            IF v_has_checkpoint THEN
                IF v_event_effective < v_anchor_time THEN
                    RAISE EXCEPTION 'transplant effective_time must not precede the previous checkpoint''s own effective_time';
                ELSIF v_event_effective = v_anchor_time THEN
                    IF v_event_kind <> 'REPLACEMENT' THEN
                        RAISE EXCEPTION 'transplant effective_time must be strictly greater than the previous checkpoint''s own effective_time';
                    END IF;
                END IF;
            ELSE
                IF v_event_effective < v_anchor_time THEN
                    RAISE EXCEPTION 'transplant effective_time precedes the destination line''s own transplant event effective_time';
                END IF;
            END IF;

            IF NEW.source_plant_count <> v_anchor_value THEN
                RAISE EXCEPTION 'source_plant_count does not match the authoritative server-derived source availability';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
