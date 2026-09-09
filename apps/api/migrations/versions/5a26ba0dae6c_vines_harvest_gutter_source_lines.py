"""vines harvest gutter source lines

VINES-OPS-003 -- extends the existing, crop-agnostic Harvest architecture
(`harvest_events`/`harvest_source_lines`/`harvested_produce_lots`,
CMP-013/HARVEST-OPS-001) to Vines Production instead of building a second
Harvest engine. Confirmed safe to reuse before writing any code: `harvest_
source_lines`/`harvested_produce_lots` carry NO carrier-type restriction of
their own, and the one genuinely Leafy-specific piece -- population
consumption (`harvest_population_events`, HARVEST-OPS-001) -- is an OPTIONAL
side effect `record_leafy_harvest` alone triggers via `_write_harvest_event_
and_lot`'s own `after_lines_inserted` hook, never a hard-coded property of
`HarvestSourceLine`/`HarvestEvent` themselves. `record_vines_harvest`
(service layer, no schema change needed for this part) simply never attaches
that hook -- harvesting a vine plant's fruit never reduces its own living
population, satisfying the ticket's own repeat-harvest requirement with zero
new biological-consumption machinery.

The one genuinely missing piece: `harvest_source_lines.batch_carrier_
assignment_id` (+`carrier_id`) names exactly ONE biological source Carrier --
correct for Leafy (one Production Cultivation Plate = one line), but wrong
for Vines: the ticket's own compact UX records ONE weight per Grow GUTTER
(never one line per Grow Bag, and never a fabricated per-bag split of an
operator-entered Gutter total -- "Do NOT fabricate per-plant [or per-bag]
harvested weights"), and a Gutter is a Location, not a Carrier. This
migration adds `source_location_id` (nullable, FK `locations`) as a second,
mutually-exclusive anchor shape on the SAME `harvest_source_lines` table
(`ck_harvest_source_lines_exactly_one_anchor`) -- never a parallel
`vines_harvest_source_lines` table -- so every downstream consumer (Grading's
own generic `GET /harvested-produce-lots` source listing, the produce-lot
ledger, recall/traceability) keeps working against the ONE shared table
unchanged. `harvest_source_line_grow_bags` is the new, purely-additive Bag-
level lineage snapshot for a location-anchored line (which Bags were
currently living there at harvest time) -- identity only, never a weight,
so no fabrication risk; resolves the ticket's own "Harvest Lot must resolve
back to ... Grow Bag(s) -> Grow Cube(s)" requirement without inventing a
per-Bag quantity.

`HarvestSourceLineCorrection` (HARVEST-OPS-001) needs NO schema change at
all -- confirmed by reading both its own model and its two DB triggers
(`enforce_harvest_source_line_correction_insert_integrity`, `enforce_harvest_
correction_reconciliation`) before writing this migration: neither one ever
references `batch_carrier_assignment_id`/`carrier_id`/any BCA/population
concept, only `harvest_source_line_id` + weight/count. The commercial
correction chain is already fully carrier-agnostic; only the SERVICE-layer
`correct_leafy_harvest` (which loads `BatchCarrierAssignment` unconditionally
for its own population-restoration logic) is Leafy-specific -- `harvest_
service.correct_vines_harvest` is a new, separate, smaller sibling function
that reuses every already-generic piece (`resolve_current_correction`,
`get_current_effective_source_line`, `get_correction_history`, the
fingerprint/idempotency helpers) and skips population entirely, exactly
mirroring `record_vines_harvest`'s own "no population hook" shape.

Two existing trigger functions are widened via `CREATE OR REPLACE FUNCTION`
(never editing the historical migrations that first created them):
`enforce_harvest_source_line_insert_integrity` (branches on which anchor is
populated) and `enforce_harvest_event_insert_integrity` (widens the existing
`cmp.leafy_harvest` transaction-local stage-category bypass to also accept
`cmp.vines_harvest`, set only by `record_vines_harvest`, mirroring `record_
leafy_harvest`'s own established escape-hatch pattern exactly -- Vines
Harvest, like Leafy Harvest, is never gated on `stage_category =
'harvesting'`, since a vine plant keeps producing indefinitely without ever
leaving its own growing/production stage).

Revision ID: 5a26ba0dae6c
Revises: ecedd713789a
Create Date: 2026-09-09 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5a26ba0dae6c"
down_revision: str | None = "ecedd713789a"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


_SOURCE_LINE_INTEGRITY_WITH_LOCATION = """
    CREATE OR REPLACE FUNCTION enforce_harvest_source_line_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_event_batch_id UUID;
        v_event_tenant_id UUID;
        v_event_farm_id UUID;
        v_event_effective TIMESTAMPTZ;
        v_assignment_batch_id UUID;
        v_assignment_carrier UUID;
        v_assignment_released TIMESTAMPTZ;
        v_assignment_effective TIMESTAMPTZ;
        v_carrier_status TEXT;
        v_location_tenant_id UUID;
        v_location_farm_id UUID;
        v_location_status TEXT;
    BEGIN
        SELECT batch_id, tenant_id, farm_id, effective_time
        INTO v_event_batch_id, v_event_tenant_id, v_event_farm_id, v_event_effective
        FROM harvest_events WHERE id = NEW.harvest_event_id;
        IF v_event_batch_id IS NULL THEN
            RAISE EXCEPTION 'harvest event not found';
        END IF;

        IF NEW.batch_carrier_assignment_id IS NOT NULL THEN
            SELECT batch_id, carrier_id, released_effective_time, assigned_effective_time
            INTO v_assignment_batch_id, v_assignment_carrier, v_assignment_released, v_assignment_effective
            FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;
            IF v_assignment_batch_id IS NULL THEN
                RAISE EXCEPTION 'source assignment not found';
            END IF;
            IF v_assignment_batch_id <> v_event_batch_id THEN
                RAISE EXCEPTION 'source assignment does not belong to this harvest event''s batch';
            END IF;
            IF v_assignment_released IS NOT NULL THEN
                RAISE EXCEPTION 'source assignment is not active';
            END IF;
            IF v_assignment_carrier <> NEW.carrier_id THEN
                RAISE EXCEPTION 'carrier does not match source assignment carrier';
            END IF;
            IF v_event_effective < v_assignment_effective THEN
                RAISE EXCEPTION 'harvest event effective time precedes source assignment''s assigned effective time';
            END IF;

            SELECT status INTO v_carrier_status FROM carriers WHERE id = NEW.carrier_id;
            IF v_carrier_status IS DISTINCT FROM 'active' THEN
                RAISE EXCEPTION 'carrier is not active';
            END IF;
        ELSE
            -- VINES-OPS-003: a Location-anchored (Grow Gutter) source line --
            -- no single biological source Carrier, so no assignment/carrier
            -- checks apply. A Location carries no "assigned_effective_time"
            -- of its own to floor against; the batch/stage-run-level
            -- effective_time floors already enforced elsewhere in this same
            -- trigger's own harvest_events check remain the only ordering
            -- rule for this kind of line.
            SELECT tenant_id, farm_id, status INTO v_location_tenant_id, v_location_farm_id, v_location_status
            FROM locations WHERE id = NEW.source_location_id;
            IF v_location_tenant_id IS NULL THEN
                RAISE EXCEPTION 'source location not found';
            END IF;
            IF v_location_tenant_id <> v_event_tenant_id OR v_location_farm_id <> v_event_farm_id THEN
                RAISE EXCEPTION 'source location does not belong to this harvest event''s tenant/farm';
            END IF;
            IF v_location_status <> 'active' THEN
                RAISE EXCEPTION 'source location is not active';
            END IF;
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_HARVEST_EVENT_INTEGRITY_WITH_VINES_BYPASS = """
    CREATE OR REPLACE FUNCTION enforce_harvest_event_insert_integrity() RETURNS trigger AS $$
    DECLARE
        v_batch_tenant_id UUID;
        v_batch_farm_id UUID;
        v_batch_state TEXT;
        v_batch_created TIMESTAMPTZ;
        v_run_batch_id UUID;
        v_run_exited TIMESTAMPTZ;
        v_run_entered TIMESTAMPTZ;
        v_stage_category TEXT;
        v_open_hold_count INTEGER;
    BEGIN
        SELECT tenant_id, farm_id, state, created_effective_time
        INTO v_batch_tenant_id, v_batch_farm_id, v_batch_state, v_batch_created
        FROM crop_batches WHERE id = NEW.batch_id FOR UPDATE;
        IF v_batch_state IS NULL THEN
            RAISE EXCEPTION 'crop batch not found for harvest event';
        END IF;
        IF v_batch_tenant_id <> NEW.tenant_id OR v_batch_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'harvest event tenant/farm does not match the crop batch''s own';
        END IF;
        IF v_batch_state <> 'active' THEN
            RAISE EXCEPTION 'crop batch is not active';
        END IF;
        IF NEW.effective_time > clock_timestamp() THEN
            RAISE EXCEPTION 'harvest event effective time cannot be in the future';
        END IF;
        IF NEW.effective_time < v_batch_created THEN
            RAISE EXCEPTION 'harvest event effective time precedes the batch''s creation effective time';
        END IF;

        SELECT batch_id, exited_effective_time, entered_effective_time
        INTO v_run_batch_id, v_run_exited, v_run_entered
        FROM batch_stage_runs WHERE id = NEW.active_batch_stage_run_id;
        IF v_run_batch_id IS NULL THEN
            RAISE EXCEPTION 'active stage run not found';
        END IF;
        IF v_run_batch_id <> NEW.batch_id THEN
            RAISE EXCEPTION 'stage run does not belong to this batch';
        END IF;
        IF v_run_exited IS NOT NULL THEN
            RAISE EXCEPTION 'harvest requires the batch''s currently active stage run';
        END IF;
        IF NEW.effective_time < v_run_entered THEN
            RAISE EXCEPTION 'harvest event effective time precedes the current stage run''s entry time';
        END IF;

        SELECT s.stage_category INTO v_stage_category
        FROM batch_stage_runs r JOIN workflow_stages s ON s.id = r.workflow_stage_id
        WHERE r.id = NEW.active_batch_stage_run_id;
        -- HARVEST-OPS-001 / VINES-OPS-003: both Leafy Harvest and Vines
        -- Harvest are exempt from this gate -- proven by whichever
        -- transaction-local marker that service path alone sets, never by
        -- inspecting the row itself (HarvestEvent carries no "kind" column
        -- of its own, by design -- one shared table).
        IF v_stage_category IS DISTINCT FROM 'harvesting'
           AND COALESCE(current_setting('cmp.leafy_harvest', true), 'false') <> 'true'
           AND COALESCE(current_setting('cmp.vines_harvest', true), 'false') <> 'true'
        THEN
            RAISE EXCEPTION 'current stage is not a harvesting stage';
        END IF;

        SELECT count(*) INTO v_open_hold_count
        FROM quality_holds h
        WHERE h.batch_id = NEW.batch_id
          AND NOT EXISTS (SELECT 1 FROM quality_hold_releases r WHERE r.quality_hold_id = h.id);
        IF v_open_hold_count > 0 THEN
            RAISE EXCEPTION 'crop batch has an open quality hold';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_STAGE_BYPASS_INTEGRITY_WITH_VINES = """
    CREATE OR REPLACE FUNCTION enforce_leafy_harvest_stage_bypass_integrity() RETURNS trigger AS $$
    DECLARE
        v_stage_category TEXT;
        v_line RECORD;
        v_bca RECORD;
        v_consumption_count INTEGER;
        v_consumption RECORD;
        v_loc RECORD;
    BEGIN
        SELECT s.stage_category INTO v_stage_category
        FROM batch_stage_runs r JOIN workflow_stages s ON s.id = r.workflow_stage_id
        WHERE r.id = NEW.active_batch_stage_run_id;

        IF v_stage_category = 'harvesting' THEN
            RETURN NEW;
        END IF;

        FOR v_line IN
            SELECT id, batch_carrier_assignment_id, source_location_id, whole_unit_count
            FROM harvest_source_lines WHERE harvest_event_id = NEW.id
        LOOP
            IF v_line.source_location_id IS NOT NULL THEN
                -- VINES-OPS-003: a Gutter-anchored line's own independent
                -- re-proof -- the Location genuinely belongs to this
                -- event's own tenant/farm, and (unlike Leafy) NEVER has a
                -- population CONSUMPTION of any kind, by construction --
                -- there is no BCA a location-anchored line could even name
                -- one against.
                SELECT tenant_id, farm_id INTO v_loc FROM locations WHERE id = v_line.source_location_id;
                IF v_loc.tenant_id IS DISTINCT FROM NEW.tenant_id OR v_loc.farm_id IS DISTINCT FROM NEW.farm_id THEN
                    RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s Location does not belong to this event''s own tenant/farm -- not a valid Vines Harvest',
                        NEW.id, v_line.id;
                END IF;
                SELECT count(*) INTO v_consumption_count FROM harvest_population_events
                WHERE original_harvest_source_line_id = v_line.id AND event_kind = 'CONSUMPTION';
                IF v_consumption_count <> 0 THEN
                    RAISE EXCEPTION 'harvest event % source line % is Gutter-anchored but has a population CONSUMPTION -- not a valid Vines Harvest',
                        NEW.id, v_line.id;
                END IF;
                CONTINUE;
            END IF;

            SELECT bca.batch_id, bca.tenant_id, bca.farm_id,
                   bca.population_root_batch_carrier_assignment_id, ct.code AS carrier_type_code
            INTO v_bca
            FROM batch_carrier_assignments bca
            JOIN carriers c ON c.id = bca.carrier_id
            JOIN carrier_types ct ON ct.id = c.carrier_type_id
            WHERE bca.id = v_line.batch_carrier_assignment_id;

            IF v_bca.batch_id IS DISTINCT FROM NEW.batch_id
               OR v_bca.tenant_id IS DISTINCT FROM NEW.tenant_id
               OR v_bca.farm_id IS DISTINCT FROM NEW.farm_id
            THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s BCA does not belong to this event''s own tenant/farm/batch -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;
            IF v_bca.carrier_type_code IS DISTINCT FROM 'production_cultivation_plate' THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line % is not a production_cultivation_plate BCA -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;
            IF v_line.whole_unit_count IS NULL OR v_line.whole_unit_count <= 0 THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line % has no positive whole_unit_count -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;

            SELECT count(*) INTO v_consumption_count FROM harvest_population_events
            WHERE original_harvest_source_line_id = v_line.id AND event_kind = 'CONSUMPTION';
            IF v_consumption_count <> 1 THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line % does not have exactly one original CONSUMPTION -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;

            SELECT batch_carrier_assignment_id, population_root_batch_carrier_assignment_id, quantity_delta
            INTO v_consumption
            FROM harvest_population_events WHERE original_harvest_source_line_id = v_line.id AND event_kind = 'CONSUMPTION';

            IF v_consumption.batch_carrier_assignment_id <> v_line.batch_carrier_assignment_id THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s CONSUMPTION does not reference the exact same BCA -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;
            IF v_consumption.population_root_batch_carrier_assignment_id IS DISTINCT FROM v_bca.population_root_batch_carrier_assignment_id THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s CONSUMPTION does not reference its own BCA''s stored population root -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;
            IF v_consumption.quantity_delta <> -v_line.whole_unit_count THEN
                RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s CONSUMPTION quantity does not match its own whole_unit_count -- not a valid Leafy Harvest',
                    NEW.id, v_line.id;
            END IF;
        END LOOP;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_REJECT_MUTATION_FUNCTION_NAME = "reject_append_only_mutation"
_REJECT_HARD_DELETE_FUNCTION_NAME = "reject_hard_delete"


def upgrade() -> None:
    # --- 1. harvest_source_lines: widen to a second, Location-based anchor -
    op.alter_column("harvest_source_lines", "batch_carrier_assignment_id", nullable=True)
    op.alter_column("harvest_source_lines", "carrier_id", nullable=True)
    op.add_column(
        "harvest_source_lines",
        sa.Column("source_location_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_harvest_source_lines_exactly_one_anchor",
        "harvest_source_lines",
        "(batch_carrier_assignment_id IS NOT NULL AND carrier_id IS NOT NULL AND source_location_id IS NULL) "
        "OR (batch_carrier_assignment_id IS NULL AND carrier_id IS NULL AND source_location_id IS NOT NULL)",
    )
    op.create_unique_constraint(
        "ux_harvest_source_lines_event_location", "harvest_source_lines", ["harvest_event_id", "source_location_id"],
    )
    op.create_foreign_key(
        "fk_harvest_source_lines_tenant_farm_location", "harvest_source_lines", "locations",
        ["tenant_id", "farm_id", "source_location_id"], ["tenant_id", "farm_id", "id"],
    )
    # The existing 4-column (tenant_id, farm_id, harvest_event_id, id)
    # unique constraint can't back a plain (tenant_id, farm_id, id)
    # composite FK -- harvest_source_line_grow_bags carries no harvest_
    # event_id column of its own -- so add that narrower one too.
    op.create_unique_constraint(
        "uq_harvest_source_lines_tenant_farm_id", "harvest_source_lines", ["tenant_id", "farm_id", "id"],
    )

    # --- 2. harvest_source_line_grow_bags: new, additive lineage-only table -
    op.create_table(
        "harvest_source_line_grow_bags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "harvest_source_line_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("harvest_source_lines.id"), nullable=False,
        ),
        sa.Column("grow_bag_carrier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carriers.id"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "harvest_source_line_id", "grow_bag_carrier_id",
            name="ux_harvest_source_line_grow_bags_line_carrier",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvest_source_line_id"],
            ["harvest_source_lines.tenant_id", "harvest_source_lines.farm_id", "harvest_source_lines.id"],
            name="fk_harvest_source_line_grow_bags_tenant_farm_line",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "grow_bag_carrier_id"],
            ["carriers.tenant_id", "carriers.farm_id", "carriers.id"],
            name="fk_harvest_source_line_grow_bags_tenant_farm_carrier",
        ),
    )
    op.create_index(
        "ix_harvest_source_line_grow_bags_line", "harvest_source_line_grow_bags", ["harvest_source_line_id"],
    )
    op.create_index(
        "ix_harvest_source_line_grow_bags_carrier", "harvest_source_line_grow_bags", ["grow_bag_carrier_id"],
    )
    op.execute(
        "CREATE TRIGGER harvest_source_line_grow_bags_no_update "
        "BEFORE UPDATE ON harvest_source_line_grow_bags "
        f"FOR EACH ROW EXECUTE FUNCTION {_REJECT_MUTATION_FUNCTION_NAME}();"
    )
    op.execute(
        "CREATE TRIGGER harvest_source_line_grow_bags_no_delete "
        "BEFORE DELETE ON harvest_source_line_grow_bags "
        f"FOR EACH ROW EXECUTE FUNCTION {_REJECT_HARD_DELETE_FUNCTION_NAME}();"
    )

    # --- 3. widen the three existing trigger functions (CREATE OR REPLACE) -
    op.execute(_SOURCE_LINE_INTEGRITY_WITH_LOCATION)
    op.execute(_HARVEST_EVENT_INTEGRITY_WITH_VINES_BYPASS)
    op.execute(_STAGE_BYPASS_INTEGRITY_WITH_VINES)


def downgrade() -> None:
    bind = op.get_bind()

    vines_lines = bind.execute(
        sa.text("SELECT count(*) FROM harvest_source_lines WHERE source_location_id IS NOT NULL")
    ).scalar_one()
    if vines_lines > 0:
        raise RuntimeError(
            "Cannot downgrade past VINES-OPS-003: "
            f"{vines_lines} existing Location-anchored harvest_source_lines row(s) would be destroyed."
        )
    lineage_rows = bind.execute(
        sa.text("SELECT count(*) FROM harvest_source_line_grow_bags")
    ).scalar_one()
    if lineage_rows > 0:
        raise RuntimeError(
            "Cannot downgrade past VINES-OPS-003: "
            f"{lineage_rows} existing harvest_source_line_grow_bags row(s) would be destroyed."
        )

    # Restore the two widened trigger functions to their exact pre-VINES-OPS-003 bodies.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_harvest_source_line_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_event_batch_id UUID;
            v_event_effective TIMESTAMPTZ;
            v_assignment_batch_id UUID;
            v_assignment_carrier UUID;
            v_assignment_released TIMESTAMPTZ;
            v_assignment_effective TIMESTAMPTZ;
            v_carrier_status TEXT;
        BEGIN
            SELECT batch_id, effective_time INTO v_event_batch_id, v_event_effective
            FROM harvest_events WHERE id = NEW.harvest_event_id;
            IF v_event_batch_id IS NULL THEN
                RAISE EXCEPTION 'harvest event not found';
            END IF;

            SELECT batch_id, carrier_id, released_effective_time, assigned_effective_time
            INTO v_assignment_batch_id, v_assignment_carrier, v_assignment_released, v_assignment_effective
            FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;
            IF v_assignment_batch_id IS NULL THEN
                RAISE EXCEPTION 'source assignment not found';
            END IF;
            IF v_assignment_batch_id <> v_event_batch_id THEN
                RAISE EXCEPTION 'source assignment does not belong to this harvest event''s batch';
            END IF;
            IF v_assignment_released IS NOT NULL THEN
                RAISE EXCEPTION 'source assignment is not active';
            END IF;
            IF v_assignment_carrier <> NEW.carrier_id THEN
                RAISE EXCEPTION 'carrier does not match source assignment carrier';
            END IF;
            IF v_event_effective < v_assignment_effective THEN
                RAISE EXCEPTION 'harvest event effective time precedes source assignment''s assigned effective time';
            END IF;

            SELECT status INTO v_carrier_status FROM carriers WHERE id = NEW.carrier_id;
            IF v_carrier_status IS DISTINCT FROM 'active' THEN
                RAISE EXCEPTION 'carrier is not active';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_harvest_event_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_batch_tenant_id UUID;
            v_batch_farm_id UUID;
            v_batch_state TEXT;
            v_batch_created TIMESTAMPTZ;
            v_run_batch_id UUID;
            v_run_exited TIMESTAMPTZ;
            v_run_entered TIMESTAMPTZ;
            v_stage_category TEXT;
            v_open_hold_count INTEGER;
        BEGIN
            SELECT tenant_id, farm_id, state, created_effective_time
            INTO v_batch_tenant_id, v_batch_farm_id, v_batch_state, v_batch_created
            FROM crop_batches WHERE id = NEW.batch_id FOR UPDATE;
            IF v_batch_state IS NULL THEN
                RAISE EXCEPTION 'crop batch not found for harvest event';
            END IF;
            IF v_batch_tenant_id <> NEW.tenant_id OR v_batch_farm_id <> NEW.farm_id THEN
                RAISE EXCEPTION 'harvest event tenant/farm does not match the crop batch''s own';
            END IF;
            IF v_batch_state <> 'active' THEN
                RAISE EXCEPTION 'crop batch is not active';
            END IF;
            IF NEW.effective_time > clock_timestamp() THEN
                RAISE EXCEPTION 'harvest event effective time cannot be in the future';
            END IF;
            IF NEW.effective_time < v_batch_created THEN
                RAISE EXCEPTION 'harvest event effective time precedes the batch''s creation effective time';
            END IF;

            SELECT batch_id, exited_effective_time, entered_effective_time
            INTO v_run_batch_id, v_run_exited, v_run_entered
            FROM batch_stage_runs WHERE id = NEW.active_batch_stage_run_id;
            IF v_run_batch_id IS NULL THEN
                RAISE EXCEPTION 'active stage run not found';
            END IF;
            IF v_run_batch_id <> NEW.batch_id THEN
                RAISE EXCEPTION 'stage run does not belong to this batch';
            END IF;
            IF v_run_exited IS NOT NULL THEN
                RAISE EXCEPTION 'harvest requires the batch''s currently active stage run';
            END IF;
            IF NEW.effective_time < v_run_entered THEN
                RAISE EXCEPTION 'harvest event effective time precedes the current stage run''s entry time';
            END IF;

            SELECT s.stage_category INTO v_stage_category
            FROM batch_stage_runs r JOIN workflow_stages s ON s.id = r.workflow_stage_id
            WHERE r.id = NEW.active_batch_stage_run_id;
            IF v_stage_category IS DISTINCT FROM 'harvesting'
               AND COALESCE(current_setting('cmp.leafy_harvest', true), 'false') <> 'true'
            THEN
                RAISE EXCEPTION 'current stage is not a harvesting stage';
            END IF;

            SELECT count(*) INTO v_open_hold_count
            FROM quality_holds h
            WHERE h.batch_id = NEW.batch_id
              AND NOT EXISTS (SELECT 1 FROM quality_hold_releases r WHERE r.quality_hold_id = h.id);
            IF v_open_hold_count > 0 THEN
                RAISE EXCEPTION 'crop batch has an open quality hold';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_leafy_harvest_stage_bypass_integrity() RETURNS trigger AS $$
        DECLARE
            v_stage_category TEXT;
            v_line RECORD;
            v_bca RECORD;
            v_consumption_count INTEGER;
            v_consumption RECORD;
        BEGIN
            SELECT s.stage_category INTO v_stage_category
            FROM batch_stage_runs r JOIN workflow_stages s ON s.id = r.workflow_stage_id
            WHERE r.id = NEW.active_batch_stage_run_id;

            IF v_stage_category = 'harvesting' THEN
                RETURN NEW;
            END IF;

            FOR v_line IN
                SELECT id, batch_carrier_assignment_id, whole_unit_count
                FROM harvest_source_lines WHERE harvest_event_id = NEW.id
            LOOP
                SELECT bca.batch_id, bca.tenant_id, bca.farm_id,
                       bca.population_root_batch_carrier_assignment_id, ct.code AS carrier_type_code
                INTO v_bca
                FROM batch_carrier_assignments bca
                JOIN carriers c ON c.id = bca.carrier_id
                JOIN carrier_types ct ON ct.id = c.carrier_type_id
                WHERE bca.id = v_line.batch_carrier_assignment_id;

                IF v_bca.batch_id IS DISTINCT FROM NEW.batch_id
                   OR v_bca.tenant_id IS DISTINCT FROM NEW.tenant_id
                   OR v_bca.farm_id IS DISTINCT FROM NEW.farm_id
                THEN
                    RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s BCA does not belong to this event''s own tenant/farm/batch -- not a valid Leafy Harvest',
                        NEW.id, v_line.id;
                END IF;
                IF v_bca.carrier_type_code IS DISTINCT FROM 'production_cultivation_plate' THEN
                    RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line % is not a production_cultivation_plate BCA -- not a valid Leafy Harvest',
                        NEW.id, v_line.id;
                END IF;
                IF v_line.whole_unit_count IS NULL OR v_line.whole_unit_count <= 0 THEN
                    RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line % has no positive whole_unit_count -- not a valid Leafy Harvest',
                        NEW.id, v_line.id;
                END IF;

                SELECT count(*) INTO v_consumption_count FROM harvest_population_events
                WHERE original_harvest_source_line_id = v_line.id AND event_kind = 'CONSUMPTION';
                IF v_consumption_count <> 1 THEN
                    RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line % does not have exactly one original CONSUMPTION -- not a valid Leafy Harvest',
                        NEW.id, v_line.id;
                END IF;

                SELECT batch_carrier_assignment_id, population_root_batch_carrier_assignment_id, quantity_delta
                INTO v_consumption
                FROM harvest_population_events WHERE original_harvest_source_line_id = v_line.id AND event_kind = 'CONSUMPTION';

                IF v_consumption.batch_carrier_assignment_id <> v_line.batch_carrier_assignment_id THEN
                    RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s CONSUMPTION does not reference the exact same BCA -- not a valid Leafy Harvest',
                        NEW.id, v_line.id;
                END IF;
                IF v_consumption.population_root_batch_carrier_assignment_id IS DISTINCT FROM v_bca.population_root_batch_carrier_assignment_id THEN
                    RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s CONSUMPTION does not reference its own BCA''s stored population root -- not a valid Leafy Harvest',
                        NEW.id, v_line.id;
                END IF;
                IF v_consumption.quantity_delta <> -v_line.whole_unit_count THEN
                    RAISE EXCEPTION 'harvest event % is outside the harvesting stage and source line %''s CONSUMPTION quantity does not match its own whole_unit_count -- not a valid Leafy Harvest',
                        NEW.id, v_line.id;
                END IF;
            END LOOP;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute("DROP TRIGGER IF EXISTS harvest_source_line_grow_bags_no_delete ON harvest_source_line_grow_bags")
    op.execute("DROP TRIGGER IF EXISTS harvest_source_line_grow_bags_no_update ON harvest_source_line_grow_bags")
    op.drop_index("ix_harvest_source_line_grow_bags_carrier", table_name="harvest_source_line_grow_bags")
    op.drop_index("ix_harvest_source_line_grow_bags_line", table_name="harvest_source_line_grow_bags")
    op.drop_table("harvest_source_line_grow_bags")

    op.drop_constraint("fk_harvest_source_lines_tenant_farm_location", "harvest_source_lines", type_="foreignkey")
    op.drop_constraint("uq_harvest_source_lines_tenant_farm_id", "harvest_source_lines", type_="unique")
    op.drop_constraint("ux_harvest_source_lines_event_location", "harvest_source_lines", type_="unique")
    op.drop_constraint("ck_harvest_source_lines_exactly_one_anchor", "harvest_source_lines", type_="check")
    op.drop_column("harvest_source_lines", "source_location_id")
    op.alter_column("harvest_source_lines", "carrier_id", nullable=False)
    op.alter_column("harvest_source_lines", "batch_carrier_assignment_id", nullable=False)
