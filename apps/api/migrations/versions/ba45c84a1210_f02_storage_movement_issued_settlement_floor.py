"""F02: storage movement putaway floor includes issued settlement (PILOT-BLOCKER-004)

Fixes a confirmed inventory-accounting defect: the `putaway` branch of
`enforce_inventory_storage_movement_insert_integrity_v3()` (added by
`86b9cf24d6ff`) computes "not put away" as `existence - total_custody`,
omitting the issued-settlement term (`D` -- total Consumption + Scrap ever
settled against this cohort's own Issue lines via `inventory_material_
events`). `total_custody` deliberately excludes `issue`/`return` movements
(neither changes whether material is "put away"), so once any issued
material is later Consumed or Scrapped, `total_custody` goes stale relative
to the cohort's own current custody state -- it no longer falls even though
that quantity has genuinely left the system. The DB-enforced not-put-away
ceiling then sits BELOW the true value, and a subsequently valid Putaway can
be wrongly rejected (confirmed reproduction: Receive 100, Putaway 60, Issue
30, Consume 30 -> true not-put-away is 40, but the v3 trigger computes
100 - 60 = 10 and rejects a Putaway of 20).

Canonical identity (frozen, `app/services/inventory_cohort_accounting_
service.py`): `existence = not_put_away + in_bins + outstanding_issued`,
where `not_put_away = existence - custody_total + settled_from_issued`.
This migration adds the missing `+ settled_from_issued` term to the
putaway branch ONLY -- every other check in v3 (tenant/farm/location
matching, active-destination, effective-time ordering, source-bin-balance
for transfer/split_out/issue/scrap_bin) is carried over verbatim, per
`docs/domain/STORE_INVENTORY_MODEL.md` §14's "add a new versioned trigger
function, widen the CHECK in place, never touch the old function" idiom
(the exact same seam `a9c3e71fd2b4`/`86b9cf24d6ff` already used for
`_v2`/`_v3`). `v1`/`v2`/`v3` are left completely untouched; downgrade
repoints the trigger back to `v3`.

The corresponding application-layer write validators (`inventory_storage_
service.record_putaway`, `inventory_material_event_service.record_scrap`'s
`not_put_away` source, `inventory_quality_service`'s two partial-bucket
validators, and the generic Adjustment/Reversal existence floor in
`inventory_existence_ledger_service`) are fixed in the same change to use
this identical formula (`inventory_cohort_accounting_service.
get_cohort_accounting_snapshot`), so READ MODEL = WRITE VALIDATION =
DATABASE ENFORCEMENT for the same committed state, per the ticket's
acceptance rule.

Downgrade is unconditionally safe (no guard needed): repointing the trigger
back to `v3` only affects FUTURE inserts (triggers do not retroactively
re-validate existing rows), never rewrites or deletes any existing
inventory history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ba45c84a1210"
down_revision: str | None = "2c3b8d0bab94"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


_MOVEMENT_INTEGRITY_FUNCTION_V4 = """
CREATE OR REPLACE FUNCTION enforce_inventory_storage_movement_insert_integrity_v4() RETURNS trigger AS $$
DECLARE
    v_cohort_tenant_id UUID;
    v_cohort_farm_id UUID;
    v_first_location UUID;
    v_second_location UUID;
    v_src_tenant_id UUID;
    v_src_farm_id UUID;
    v_src_type_code TEXT;
    v_dest_tenant_id UUID;
    v_dest_farm_id UUID;
    v_dest_type_code TEXT;
    v_dest_status TEXT;
    v_latest_movement_effective TIMESTAMPTZ;
    v_latest_ledger_effective TIMESTAMPTZ;
    v_existence_balance NUMERIC;
    v_total_custody NUMERIC;
    v_settled_from_issued NUMERIC;
    v_source_balance NUMERIC;
    v_issue_tenant_id UUID;
    v_issue_farm_id UUID;
    v_reservation_line_tenant_id UUID;
BEGIN
    IF NEW.movement_kind NOT IN ('putaway', 'transfer', 'split_out', 'split_in', 'issue', 'return', 'scrap_bin') THEN
        RAISE EXCEPTION 'unrecognized inventory storage movement kind %', NEW.movement_kind;
    END IF;

    SELECT tenant_id, receiving_farm_id INTO v_cohort_tenant_id, v_cohort_farm_id
    FROM inventory_quantity_cohorts WHERE id = NEW.inventory_quantity_cohort_id FOR UPDATE;
    IF v_cohort_tenant_id IS NULL THEN
        RAISE EXCEPTION 'inventory quantity cohort not found for storage movement';
    END IF;
    IF v_cohort_tenant_id <> NEW.tenant_id OR v_cohort_farm_id <> NEW.farm_id THEN
        RAISE EXCEPTION 'storage movement tenant/farm does not match the cohort''s own receiving Farm';
    END IF;

    IF NEW.source_location_id IS NOT NULL AND NEW.destination_location_id IS NOT NULL THEN
        IF NEW.source_location_id < NEW.destination_location_id THEN
            v_first_location := NEW.source_location_id; v_second_location := NEW.destination_location_id;
        ELSE
            v_first_location := NEW.destination_location_id; v_second_location := NEW.source_location_id;
        END IF;
        PERFORM 1 FROM locations WHERE id = v_first_location FOR UPDATE;
        PERFORM 1 FROM locations WHERE id = v_second_location FOR UPDATE;
    ELSIF NEW.source_location_id IS NOT NULL THEN
        PERFORM 1 FROM locations WHERE id = NEW.source_location_id FOR UPDATE;
    ELSIF NEW.destination_location_id IS NOT NULL THEN
        PERFORM 1 FROM locations WHERE id = NEW.destination_location_id FOR UPDATE;
    END IF;

    IF NEW.source_location_id IS NOT NULL THEN
        SELECT l.tenant_id, l.farm_id, lt.code INTO v_src_tenant_id, v_src_farm_id, v_src_type_code
        FROM locations l JOIN location_types lt ON lt.id = l.location_type_id WHERE l.id = NEW.source_location_id;
        IF v_src_tenant_id IS NULL THEN
            RAISE EXCEPTION 'source location not found for storage movement';
        END IF;
        IF v_src_tenant_id <> NEW.tenant_id OR v_src_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'storage movement tenant/farm does not match the source location''s own';
        END IF;
        IF v_src_type_code <> 'store_bin' THEN
            RAISE EXCEPTION 'source location is not a store_bin';
        END IF;
        -- Source is deliberately not required to be active here (mirrors
        -- v1/v2/v3's own precedent for transfer/split_out/issue) -- an
        -- active source-Bin requirement, where one applies at all, is
        -- enforced at the service layer.
    END IF;

    IF NEW.destination_location_id IS NOT NULL THEN
        SELECT l.tenant_id, l.farm_id, lt.code, l.status
        INTO v_dest_tenant_id, v_dest_farm_id, v_dest_type_code, v_dest_status
        FROM locations l JOIN location_types lt ON lt.id = l.location_type_id WHERE l.id = NEW.destination_location_id;
        IF v_dest_tenant_id IS NULL THEN
            RAISE EXCEPTION 'destination location not found for storage movement';
        END IF;
        IF v_dest_tenant_id <> NEW.tenant_id OR v_dest_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'storage movement tenant/farm does not match the destination location''s own';
        END IF;
        IF v_dest_type_code <> 'store_bin' THEN
            RAISE EXCEPTION 'destination location is not a store_bin';
        END IF;
        IF v_dest_status <> 'active' THEN
            RAISE EXCEPTION 'destination location is not active';
        END IF;
    END IF;

    IF NEW.movement_kind = 'issue' THEN
        SELECT tenant_id, farm_id INTO v_issue_tenant_id, v_issue_farm_id
        FROM inventory_issues WHERE id = NEW.issue_id;
        IF v_issue_tenant_id IS NULL THEN
            RAISE EXCEPTION 'inventory issue not found for storage movement';
        END IF;
        IF v_issue_tenant_id <> NEW.tenant_id OR v_issue_farm_id <> NEW.farm_id THEN
            RAISE EXCEPTION 'storage movement tenant/farm does not match the issue header''s own Farm';
        END IF;
    END IF;

    IF NEW.reservation_line_id IS NOT NULL THEN
        SELECT tenant_id INTO v_reservation_line_tenant_id
        FROM inventory_reservation_lines WHERE id = NEW.reservation_line_id;
        IF v_reservation_line_tenant_id IS NULL THEN
            RAISE EXCEPTION 'reservation line not found for storage movement';
        END IF;
        IF v_reservation_line_tenant_id <> NEW.tenant_id THEN
            RAISE EXCEPTION 'storage movement tenant does not match the reservation line''s own';
        END IF;
    END IF;

    SELECT MAX(effective_time) INTO v_latest_movement_effective
    FROM inventory_storage_movements WHERE inventory_quantity_cohort_id = NEW.inventory_quantity_cohort_id;
    IF v_latest_movement_effective IS NOT NULL AND NEW.effective_time < v_latest_movement_effective THEN
        RAISE EXCEPTION 'storage movement effective time precedes this cohort''s latest existing storage movement';
    END IF;
    SELECT MAX(effective_time) INTO v_latest_ledger_effective
    FROM inventory_existence_ledger_entries WHERE inventory_quantity_cohort_id = NEW.inventory_quantity_cohort_id;
    IF v_latest_ledger_effective IS NOT NULL AND NEW.effective_time < v_latest_ledger_effective THEN
        RAISE EXCEPTION 'storage movement effective time precedes this cohort''s latest existence ledger entry';
    END IF;

    SELECT COALESCE(SUM(quantity_delta_base), 0) INTO v_existence_balance
    FROM inventory_existence_ledger_entries WHERE inventory_quantity_cohort_id = NEW.inventory_quantity_cohort_id;

    SELECT COALESCE(SUM(
        CASE WHEN movement_kind IN ('putaway', 'split_in') THEN moved_quantity_base
             WHEN movement_kind IN ('split_out', 'scrap_bin') THEN -moved_quantity_base ELSE 0 END
    ), 0) INTO v_total_custody
    FROM inventory_storage_movements WHERE inventory_quantity_cohort_id = NEW.inventory_quantity_cohort_id;

    IF NEW.movement_kind = 'putaway' THEN
        -- PILOT-BLOCKER-004 F02: not-put-away is `existence - custody +
        -- settled_from_issued` -- `total_custody` alone goes stale
        -- (over-restrictive) once any issued material has since been
        -- Consumed/Scrapped (`inventory_material_events`, which never
        -- writes a storage-movement row and so never moves
        -- `total_custody`).
        SELECT COALESCE(SUM(quantity_base), 0) INTO v_settled_from_issued
        FROM inventory_material_events
        WHERE inventory_quantity_cohort_id = NEW.inventory_quantity_cohort_id
          AND source_kind = 'issued' AND event_kind IN ('consumption', 'scrap');
        IF NEW.moved_quantity_base > (v_existence_balance - v_total_custody + v_settled_from_issued) THEN
            RAISE EXCEPTION 'putaway would exceed not-put-away quantity for cohort %', NEW.inventory_quantity_cohort_id;
        END IF;
    ELSIF NEW.movement_kind IN ('transfer', 'split_out', 'issue', 'scrap_bin') THEN
        SELECT
            COALESCE(SUM(CASE WHEN destination_location_id = NEW.source_location_id THEN moved_quantity_base ELSE 0 END), 0)
            - COALESCE(SUM(CASE WHEN source_location_id = NEW.source_location_id THEN moved_quantity_base ELSE 0 END), 0)
        INTO v_source_balance
        FROM inventory_storage_movements
        WHERE inventory_quantity_cohort_id = NEW.inventory_quantity_cohort_id
          AND (source_location_id = NEW.source_location_id OR destination_location_id = NEW.source_location_id);
        IF NEW.moved_quantity_base > v_source_balance THEN
            RAISE EXCEPTION 'movement would leave source bin with negative custody for cohort %', NEW.inventory_quantity_cohort_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(_MOVEMENT_INTEGRITY_FUNCTION_V4))
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_storage_movements_enforce_insert_integrity ON inventory_storage_movements"
    )
    op.execute(
        "CREATE TRIGGER inventory_storage_movements_enforce_insert_integrity "
        "BEFORE INSERT ON inventory_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION enforce_inventory_storage_movement_insert_integrity_v4();"
    )


def downgrade() -> None:
    # Unconditionally safe: repointing the trigger back to v3 only changes
    # validation for FUTURE inserts (triggers never retroactively re-check
    # existing rows) -- no inventory history is rewritten, no quantities
    # altered, no operational records deleted. No downgrade guard needed.
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_storage_movements_enforce_insert_integrity ON inventory_storage_movements"
    )
    op.execute(
        "CREATE TRIGGER inventory_storage_movements_enforce_insert_integrity "
        "BEFORE INSERT ON inventory_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION enforce_inventory_storage_movement_insert_integrity_v3();"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_storage_movement_insert_integrity_v4()")
