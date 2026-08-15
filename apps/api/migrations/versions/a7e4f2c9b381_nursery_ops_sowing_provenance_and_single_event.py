"""nursery ops: sowing provenance and single-sowing-event rule

NURSERY-OPS-001 / NURSERY-OPS-001.1: additive, backward-compatible changes
to the existing CMP-009 Sowing schema (extended, never redesigned). This
candidate migration was corrected in place under NURSERY-OPS-001.1 (still
uncommitted at the time -- no data migration/split was needed):

1. `sowing_events` gains two new nullable columns:
   - `seeding_station_id` (FK -> `locations`, composite tenant/farm-scoped,
     reusing the existing `uq_locations_tenant_farm_id`) -- provenance of
     which Seeding Station a sowing command was executed at. Validated by
     the service layer (must resolve to an active `seeding_station`
     location under a Nursery-classified Greenhouse in this tenant/farm).
   - `seeding_machine_id` (plain FK -> `assets.id`, NOT composite -- `Asset`
     is documented, farm-level equipment referenced only as event
     provenance, never owned by a specific Location; matches how
     FARM-SETUP-001.1 already treats Trolley/Seeding Machine references).
     Optional; validated by the service layer when present (must resolve
     to an active `seeding_machine` asset in this tenant/farm).
   Both are NULL on every pre-existing row -- fully backward compatible,
   no data migration.

2. `sowing_events` gains a new `UNIQUE(batch_id)` constraint
   (`ux_sowing_events_batch_id`): NURSERY-OPS-001 makes "at most one
   Sowing Event per Crop Batch, ever" a system-wide, DB-enforced
   invariant -- superseding CMP-009's own previously-documented design
   ("a batch may be sown multiple times as separate carriers become
   ready", see SEED_SOWING_MODEL.md). This is an explicit, deliberate
   product decision for this ticket, not an oversight -- see
   SEED_SOWING_MODEL.md's NURSERY-OPS-001 addendum. The downgrade guard
   below defensively checks no batch already has more than one
   SowingEvent before allowing a downgrade past this point.

3. (NURSERY-OPS-001.1) `sowing_events` gains a new NOT NULL `seed_lot_id`
   column -- the canonical, single Seed Lot for the event. CMP-009's
   original design put `seed_lot_id` only on each `SowingEventLine`, with
   no DB-level guarantee that every line of one event referenced the same
   lot (direct SQL, and even the general/legacy
   `POST /crop-batches/{id}/sowings` route's own request shape, could
   insert two lines of one event against two DIFFERENT Seed Lots of the
   same crop/variety -- proven by
   `test_direct_sql_mixed_seed_lot_lines_rejected` /
   `test_sow_batch_mixed_seed_lot_lines_rejected_by_service`). Backfilled
   from each event's existing (necessarily-uniform, or the backfill itself
   raises loudly rather than guessing) line data before being made NOT
   NULL. `enforce_sowing_event_line_insert_integrity` (CMP-009,
   `d17a4e2f9c86`) is replaced (`CREATE OR REPLACE FUNCTION`, matching
   CMP-011's own established precedent for correcting an earlier
   migration's trigger from a later one, never editing the historical
   migration file itself) to also reject any line whose `seed_lot_id`
   disagrees with its event's canonical one. Downgrade drops the column
   and restores the original CMP-009 function body verbatim -- no
   destructive-data guard is needed for this column specifically, since it
   is fully re-derivable from `sowing_event_lines` (which are untouched)
   on any future re-upgrade.

4. (NURSERY-OPS-001.1) `sowing_event_lines.sown_site_count` becomes
   NULLABLE. "Sown site/cell count" and "Seeds Sown" are genuinely
   different, separately-observed facts (see SEED_SOWING_MODEL.md) --
   CMP-009 required both, and the NURSERY-OPS-001 operator command (which
   only ever asks for Seeds Sown) was silently setting
   `sown_site_count = seed_count`, fabricating an unobserved
   one-seed-per-site assumption. NULL now honestly represents "not
   recorded"; the existing CHECK constraints (`> 0`,
   `seed_count >= sown_site_count`) both already pass automatically on
   NULL under Postgres CHECK semantics, so neither needs to change.
   Downgrade restores NOT NULL, guarded: it fails loudly (not by letting a
   raw NOT NULL violation surface) if any row already has a NULL
   `sown_site_count`, since inventing a site count to force the downgrade
   through would itself be exactly the fabrication this change removes.

Revision ID: a7e4f2c9b381
Revises: f91c366cfe57
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a7e4f2c9b381'
down_revision: Union[str, None] = 'f91c366cfe57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ORIGINAL_LINE_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_sowing_event_line_insert_integrity() RETURNS trigger AS $$
    DECLARE
        assignment_event_id UUID;
        assignment_carrier_id UUID;
        event_batch_id UUID;
        wf_crop_id UUID;
        wf_variety_id UUID;
        lot_crop_id UUID;
        lot_variety_id UUID;
    BEGIN
        SELECT opening_sowing_event_id, carrier_id INTO assignment_event_id, assignment_carrier_id
        FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;

        IF assignment_event_id IS NULL THEN
            RAISE EXCEPTION 'batch carrier assignment not found';
        END IF;
        IF assignment_event_id <> NEW.sowing_event_id THEN
            RAISE EXCEPTION 'assignment does not belong to this sowing event';
        END IF;
        IF assignment_carrier_id <> NEW.carrier_id THEN
            RAISE EXCEPTION 'assignment carrier does not match this line''s carrier';
        END IF;

        SELECT batch_id INTO event_batch_id FROM sowing_events WHERE id = NEW.sowing_event_id;

        SELECT w.crop_id, w.variety_id INTO wf_crop_id, wf_variety_id
        FROM crop_batches cb
        JOIN workflow_versions wv ON wv.id = cb.workflow_version_id
        JOIN workflows w ON w.id = wv.workflow_id
        WHERE cb.id = event_batch_id;

        SELECT crop_id, variety_id INTO lot_crop_id, lot_variety_id
        FROM seed_lots WHERE id = NEW.seed_lot_id;

        IF lot_crop_id IS DISTINCT FROM wf_crop_id THEN
            RAISE EXCEPTION 'seed lot crop does not match the batch''s workflow crop';
        END IF;
        IF wf_variety_id IS NULL OR lot_variety_id IS DISTINCT FROM wf_variety_id THEN
            RAISE EXCEPTION 'seed lot variety does not match the batch''s workflow variety';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_CANONICAL_SEED_LOT_LINE_INTEGRITY_FUNCTION = """
    CREATE OR REPLACE FUNCTION enforce_sowing_event_line_insert_integrity() RETURNS trigger AS $$
    DECLARE
        assignment_event_id UUID;
        assignment_carrier_id UUID;
        event_batch_id UUID;
        event_seed_lot_id UUID;
        wf_crop_id UUID;
        wf_variety_id UUID;
        lot_crop_id UUID;
        lot_variety_id UUID;
    BEGIN
        SELECT opening_sowing_event_id, carrier_id INTO assignment_event_id, assignment_carrier_id
        FROM batch_carrier_assignments WHERE id = NEW.batch_carrier_assignment_id;

        IF assignment_event_id IS NULL THEN
            RAISE EXCEPTION 'batch carrier assignment not found';
        END IF;
        IF assignment_event_id <> NEW.sowing_event_id THEN
            RAISE EXCEPTION 'assignment does not belong to this sowing event';
        END IF;
        IF assignment_carrier_id <> NEW.carrier_id THEN
            RAISE EXCEPTION 'assignment carrier does not match this line''s carrier';
        END IF;

        SELECT batch_id, seed_lot_id INTO event_batch_id, event_seed_lot_id
        FROM sowing_events WHERE id = NEW.sowing_event_id;

        -- NURSERY-OPS-001.1: every line of one Sowing Event must reference
        -- the SAME Seed Lot as the event's own canonical seed_lot_id --
        -- closes the gap where two lines of one event could otherwise
        -- reference two different Seed Lots of the same crop/variety.
        IF NEW.seed_lot_id IS DISTINCT FROM event_seed_lot_id THEN
            RAISE EXCEPTION 'seed lot must match the sowing event''s canonical seed lot';
        END IF;

        SELECT w.crop_id, w.variety_id INTO wf_crop_id, wf_variety_id
        FROM crop_batches cb
        JOIN workflow_versions wv ON wv.id = cb.workflow_version_id
        JOIN workflows w ON w.id = wv.workflow_id
        WHERE cb.id = event_batch_id;

        SELECT crop_id, variety_id INTO lot_crop_id, lot_variety_id
        FROM seed_lots WHERE id = NEW.seed_lot_id;

        IF lot_crop_id IS DISTINCT FROM wf_crop_id THEN
            RAISE EXCEPTION 'seed lot crop does not match the batch''s workflow crop';
        END IF;
        IF wf_variety_id IS NULL OR lot_variety_id IS DISTINCT FROM wf_variety_id THEN
            RAISE EXCEPTION 'seed lot variety does not match the batch''s workflow variety';
        END IF;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    op.add_column(
        "sowing_events", sa.Column("seeding_station_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "sowing_events", sa.Column("seeding_machine_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_sowing_events_tenant_farm_seeding_station",
        "sowing_events", "locations",
        ["tenant_id", "farm_id", "seeding_station_id"], ["tenant_id", "farm_id", "id"],
    )
    op.create_foreign_key(
        "fk_sowing_events_seeding_machine", "sowing_events", "assets", ["seeding_machine_id"], ["id"]
    )
    op.create_unique_constraint("ux_sowing_events_batch_id", "sowing_events", ["batch_id"])

    # --- NURSERY-OPS-001.1: canonical seed_lot_id on sowing_events --------
    bind = op.get_bind()
    op.add_column(
        "sowing_events", sa.Column("seed_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("seed_lots.id"), nullable=True)
    )
    op.create_foreign_key(
        "fk_sowing_events_tenant_farm_seed_lot",
        "sowing_events", "seed_lots",
        ["tenant_id", "farm_id", "seed_lot_id"], ["tenant_id", "farm_id", "id"],
    )
    mixed = bind.execute(
        sa.text(
            "SELECT sowing_event_id FROM sowing_event_lines "
            "GROUP BY sowing_event_id HAVING count(DISTINCT seed_lot_id) > 1"
        )
    ).fetchall()
    if mixed:
        raise RuntimeError(
            "Cannot backfill sowing_events.seed_lot_id: sowing_event(s) "
            f"{[str(r[0]) for r in mixed]} already have lines referencing more than one "
            "Seed Lot, which NURSERY-OPS-001.1 forbids. This pre-existing data must be "
            "corrected out-of-band before this migration can run."
        )
    # `sowing_events_no_update` (CMP-009, d17a4e2f9c86) rejects ANY UPDATE
    # unconditionally, including this migration-time backfill of a brand
    # new column -- it exists to stop application-level mutation of
    # historical rows, not a schema migration establishing a new column's
    # initial values. Disabled only for the duration of this one
    # statement, inside this migration's own transaction (rolled back
    # automatically with everything else if anything here fails).
    bind.execute(sa.text("ALTER TABLE sowing_events DISABLE TRIGGER sowing_events_no_update"))
    bind.execute(
        sa.text(
            "UPDATE sowing_events SET seed_lot_id = ("
            "SELECT sel.seed_lot_id FROM sowing_event_lines sel "
            "WHERE sel.sowing_event_id = sowing_events.id LIMIT 1"
            ")"
        )
    )
    bind.execute(sa.text("ALTER TABLE sowing_events ENABLE TRIGGER sowing_events_no_update"))
    op.alter_column("sowing_events", "seed_lot_id", nullable=False)
    bind.execute(sa.text(_CANONICAL_SEED_LOT_LINE_INTEGRITY_FUNCTION))

    # --- NURSERY-OPS-001.1: sown_site_count is an honestly-optional,
    # separately-observed fact, not silently equal to seed_count ----------
    op.alter_column("sowing_event_lines", "sown_site_count", nullable=True)


def downgrade() -> None:
    bind = op.get_bind()

    # --- downgrade guard: never corrupt or silently discard NURSERY-OPS-001
    # provenance/invariant history -----------------------------------------
    unsafe = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM sowing_events "
            " WHERE seeding_station_id IS NOT NULL OR seeding_machine_id IS NOT NULL) AS provenance_count, "
            "(SELECT count(*) FROM (SELECT batch_id FROM sowing_events GROUP BY batch_id HAVING count(*) > 1) d) "
            "AS multi_sown_batch_count"
        )
    ).mappings().first()
    if unsafe["provenance_count"] > 0:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-001: sowing_events rows carry seeding_station_id/"
            "seeding_machine_id provenance that would be silently discarded. Remove or migrate the "
            "offending data out-of-band before downgrading, or do not downgrade."
        )
    if unsafe["multi_sown_batch_count"] > 0:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-001: at least one crop_batch already has more than one "
            "sowing_event, which the pre-NURSERY-OPS-001 schema permits but would be inconsistent with "
            "removing ux_sowing_events_batch_id silently. Remove or migrate the offending data "
            "out-of-band before downgrading, or do not downgrade."
        )

    unrecorded_site_count = bind.execute(
        sa.text("SELECT count(*) FROM sowing_event_lines WHERE sown_site_count IS NULL")
    ).scalar_one()
    if unrecorded_site_count > 0:
        raise RuntimeError(
            "Cannot downgrade past NURSERY-OPS-001.1: "
            f"{unrecorded_site_count} sowing_event_line row(s) have no recorded sown_site_count. "
            "Restoring NOT NULL would require fabricating a site count that was never observed. "
            "Remove or migrate the offending data out-of-band before downgrading, or do not downgrade."
        )
    op.alter_column("sowing_event_lines", "sown_site_count", nullable=False)

    # seed_lot_id is fully re-derivable from sowing_event_lines (untouched
    # by this downgrade) on a future re-upgrade, so no destructive-data
    # guard is needed for it specifically -- restore the original CMP-009
    # trigger body first (it no longer references seed_lot_id), then drop.
    bind.execute(sa.text(_ORIGINAL_LINE_INTEGRITY_FUNCTION))
    op.drop_constraint("fk_sowing_events_tenant_farm_seed_lot", "sowing_events", type_="foreignkey")
    op.drop_column("sowing_events", "seed_lot_id")

    op.drop_constraint("ux_sowing_events_batch_id", "sowing_events", type_="unique")
    op.drop_constraint("fk_sowing_events_seeding_machine", "sowing_events", type_="foreignkey")
    op.drop_constraint("fk_sowing_events_tenant_farm_seeding_station", "sowing_events", type_="foreignkey")
    op.drop_column("sowing_events", "seeding_machine_id")
    op.drop_column("sowing_events", "seeding_station_id")
