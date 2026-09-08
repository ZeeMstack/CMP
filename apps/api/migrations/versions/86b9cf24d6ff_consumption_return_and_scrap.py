"""consumption, return and scrap (STORE-INV-004)

Completes the consumable Inventory lifecycle: Receipt -> Putaway ->
Reservation -> Issue -> Consumption/Return/Scrap, on top of the
already-deployed `a9c3e71fd2b4` (STORE-INV-003 Reservation & Issue). Never
collapses Existence, physical custody, Reservation, or Issue-line
reconciliation -- four separate questions, now joined by a fifth: how much
of what was Issued has actually been consumed, returned, or scrapped.

**Consumption** reduces Existence (a new `consumption` entry_kind on
`InventoryExistenceLedgerEntry`) and reduces an Issue line's own outstanding
balance -- never touches physical custody (the material already left the
Store at Issue time).

**Return** does NOT touch Existence -- it is a physical-custody fact only
(Issued-to-operations -> a Store Bin, same Farm), a new `return`
`movement_kind` on `InventoryStorageMovement` (source NULL, destination a
`store_bin` -- same shape as `putaway`), deliberately excluded from
`get_cohort_total_custody`'s own formula exactly like `issue` is (Return
neither creates nor destroys "put away" material, it only redistributes it
between the Bin and Issued-to-operations buckets).

**Scrap** reduces Existence (a new `scrap` entry_kind, mirrors
`consumption`) from exactly one of three source buckets: Not-put-away (no
storage-movement row, mirrors how a partial Quality action against
"Not put away" writes none either), a specific Store Bin (a new `scrap_bin`
`movement_kind` -- source a `store_bin`, destination NULL, same shape as
`split_out`/`issue`, but UNLIKE those two it IS included in
`get_cohort_total_custody`'s formula as a debit because that quantity has
genuinely left "put away" custody forever), or an Issue line's own
outstanding balance (same shape as Consumption, no storage-movement row).

`inventory_material_events` is the single coherent append-only settlement/
event model for all three commands (`docs/domain/STORE_INVENTORY_MODEL.md`)
-- each row is its OWN top-level idempotent operator command (unique on
`(tenant_id, client_command_id)`, unlike `split_out`/`split_in`/`issue`,
which are internally composed by a larger command). `event_kind` names the
command (`consumption`/`return`/`scrap`); `source_kind` names which bucket
it acts against (`issued`/`store_bin`/`not_put_away`); `issue_line_id`
(when `source_kind = 'issued'`) is the specific `InventoryStorageMovement`
row (`movement_kind = 'issue'`) being settled -- the row IS the Issue line,
so "issued / consumed / returned / scrapped / outstanding" reconciliation
per line is always `SUM()` over this one table, grouped by `issue_line_id`,
never a stored aggregate. `existence_ledger_entry_id`/`storage_movement_id`
point at whichever paired fact(s) this event actually wrote, so nothing is
ever double-counted or orphaned.

Mirrors `dd8b86a52acf`/`e8baaf4a723e`/`a9c3e71fd2b4`'s own established
idiom throughout: append-only (`reject_append_only_mutation`/
`reject_hard_delete`, reused unmodified), a dedicated insert-integrity
trigger that locks the target Issue line row (`FOR UPDATE`) before
re-deriving and re-checking its own outstanding balance -- the actual
concurrency-safety backstop for "two settlements racing the same Issue
line can never over-settle it," matching every other line-balance trigger
in this codebase (`enforce_inventory_reservation_line_entry_insert_integrity`,
`enforce_seedling_disposition_event_insert_integrity`) exactly.

`inventory_storage_movements`'s own insert-integrity trigger is extended via
a NEW versioned function, `..._v3` -- `docs/domain/STORE_INVENTORY_MODEL.md`
§14's "add a new versioned trigger function, widen the CHECK in place, never
touch the old function" idiom, continuing the exact same seam
`a9c3e71fd2b4` already used for `..._v2`. `v1`/`v2` are left completely
untouched; downgrade repoints the trigger back to `v2`.

`inventory_existence_ledger_entries`'s own insert-integrity trigger
(`f1a4c8e7b2d5`) is likewise extended via a NEW versioned function, `..._v2`
-- it additionally blocks a `reversal` from ever targeting a `consumption`/
`scrap` entry (reversing either would restore Existence without restoring
the matching custody/Issue-line state, a genuinely unsafe partial
correction this ticket deliberately does not build). The original function
is left completely untouched; downgrade repoints the trigger back to it.

Downgrade is guarded, never blindly destructive: refuses while any row
exists in `inventory_material_events`, or while any `inventory_storage_
movements` row has `movement_kind IN ('return', 'scrap_bin')`, or while any
`inventory_existence_ledger_entries` row has `entry_kind IN ('consumption',
'scrap')`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "86b9cf24d6ff"
down_revision: str | None = "a9c3e71fd2b4"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


_MOVEMENT_INTEGRITY_FUNCTION_V3 = """
CREATE OR REPLACE FUNCTION enforce_inventory_storage_movement_insert_integrity_v3() RETURNS trigger AS $$
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
        -- v1/v2's own precedent for transfer/split_out/issue) -- an active
        -- source-Bin requirement, where one applies at all, is enforced at
        -- the service layer.
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
        IF NEW.moved_quantity_base > (v_existence_balance - v_total_custody) THEN
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

_LEDGER_INTEGRITY_FUNCTION_V2 = """
CREATE OR REPLACE FUNCTION enforce_inventory_existence_ledger_entry_insert_integrity_v2() RETURNS trigger AS $$
DECLARE
    v_target_kind TEXT;
    v_target_cohort UUID;
    v_target_delta NUMERIC;
BEGIN
    IF NEW.entry_kind = 'reversal' THEN
        SELECT entry_kind, inventory_quantity_cohort_id, quantity_delta_base
            INTO v_target_kind, v_target_cohort, v_target_delta
            FROM inventory_existence_ledger_entries WHERE id = NEW.reversal_of_entry_id;
        IF v_target_kind IS NULL THEN
            RAISE EXCEPTION 'reversal_of_entry_id does not resolve';
        END IF;
        IF v_target_kind = 'reversal' THEN
            RAISE EXCEPTION 'a reversal entry can never itself be the target of another reversal';
        END IF;
        IF v_target_kind IN ('consumption', 'scrap') THEN
            RAISE EXCEPTION 'a consumption or scrap existence entry can never be reversed through the generic reversal path';
        END IF;
        IF v_target_cohort <> NEW.inventory_quantity_cohort_id THEN
            RAISE EXCEPTION 'a reversal must target an entry on the same inventory_quantity_cohort_id';
        END IF;
        IF NEW.quantity_delta_base <> -v_target_delta THEN
            RAISE EXCEPTION 'a reversal entry must exactly negate its target quantity_delta_base';
        END IF;
    END IF;
    IF NEW.entry_kind = 'split_in' THEN
        SELECT entry_kind, quantity_delta_base INTO v_target_kind, v_target_delta
            FROM inventory_existence_ledger_entries WHERE id = NEW.source_split_out_entry_id;
        IF v_target_kind IS DISTINCT FROM 'split_out' THEN
            RAISE EXCEPTION 'source_split_out_entry_id must reference a split_out entry';
        END IF;
        IF NEW.quantity_delta_base <> -v_target_delta THEN
            RAISE EXCEPTION 'a split_in entry must exactly match the magnitude of its split_out counterpart';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_MATERIAL_EVENT_INTEGRITY_FUNCTION = """
CREATE FUNCTION enforce_inventory_material_event_insert_integrity() RETURNS trigger AS $$
DECLARE
    v_cohort_tenant_id UUID;
    v_cohort_farm_id UUID;
    v_line_tenant_id UUID;
    v_line_cohort_id UUID;
    v_line_kind TEXT;
    v_line_issued_qty NUMERIC;
    v_line_settled_qty NUMERIC;
    v_entry_tenant_id UUID;
    v_entry_cohort_id UUID;
    v_entry_kind TEXT;
    v_movement_tenant_id UUID;
    v_movement_cohort_id UUID;
    v_movement_kind TEXT;
BEGIN
    IF NEW.event_kind NOT IN ('consumption', 'return', 'scrap') THEN
        RAISE EXCEPTION 'unrecognized inventory material event kind %', NEW.event_kind;
    END IF;
    IF NEW.source_kind NOT IN ('issued', 'store_bin', 'not_put_away') THEN
        RAISE EXCEPTION 'unrecognized inventory material event source kind %', NEW.source_kind;
    END IF;

    SELECT tenant_id, receiving_farm_id INTO v_cohort_tenant_id, v_cohort_farm_id
    FROM inventory_quantity_cohorts WHERE id = NEW.inventory_quantity_cohort_id FOR UPDATE;
    IF v_cohort_tenant_id IS NULL THEN
        RAISE EXCEPTION 'inventory quantity cohort not found for material event';
    END IF;
    IF v_cohort_tenant_id <> NEW.tenant_id OR v_cohort_farm_id <> NEW.farm_id THEN
        RAISE EXCEPTION 'material event tenant/farm does not match the cohort''s own receiving Farm';
    END IF;

    IF NEW.issue_line_id IS NOT NULL THEN
        SELECT tenant_id, inventory_quantity_cohort_id, movement_kind, moved_quantity_base
            INTO v_line_tenant_id, v_line_cohort_id, v_line_kind, v_line_issued_qty
        FROM inventory_storage_movements WHERE id = NEW.issue_line_id FOR UPDATE;
        IF v_line_tenant_id IS NULL THEN
            RAISE EXCEPTION 'issue line not found for material event';
        END IF;
        IF v_line_tenant_id <> NEW.tenant_id THEN
            RAISE EXCEPTION 'material event tenant does not match the issue line''s own';
        END IF;
        IF v_line_kind <> 'issue' THEN
            RAISE EXCEPTION 'issue_line_id must reference an issue-kind storage movement';
        END IF;
        IF v_line_cohort_id <> NEW.inventory_quantity_cohort_id THEN
            RAISE EXCEPTION 'material event cohort does not match the issue line''s own cohort';
        END IF;

        SELECT COALESCE(SUM(quantity_base), 0) INTO v_line_settled_qty
        FROM inventory_material_events WHERE issue_line_id = NEW.issue_line_id;
        IF v_line_settled_qty + NEW.quantity_base > v_line_issued_qty THEN
            RAISE EXCEPTION 'material event would exceed outstanding issued quantity for issue line %', NEW.issue_line_id;
        END IF;
    END IF;

    IF NEW.existence_ledger_entry_id IS NOT NULL THEN
        SELECT tenant_id, inventory_quantity_cohort_id, entry_kind
            INTO v_entry_tenant_id, v_entry_cohort_id, v_entry_kind
        FROM inventory_existence_ledger_entries WHERE id = NEW.existence_ledger_entry_id;
        IF v_entry_tenant_id IS NULL THEN
            RAISE EXCEPTION 'existence ledger entry not found for material event';
        END IF;
        IF v_entry_tenant_id <> NEW.tenant_id OR v_entry_cohort_id <> NEW.inventory_quantity_cohort_id THEN
            RAISE EXCEPTION 'material event existence ledger entry does not match tenant/cohort';
        END IF;
        IF v_entry_kind NOT IN ('consumption', 'scrap') THEN
            RAISE EXCEPTION 'material event existence ledger entry must be consumption or scrap';
        END IF;
    END IF;

    IF NEW.storage_movement_id IS NOT NULL THEN
        SELECT tenant_id, inventory_quantity_cohort_id, movement_kind
            INTO v_movement_tenant_id, v_movement_cohort_id, v_movement_kind
        FROM inventory_storage_movements WHERE id = NEW.storage_movement_id;
        IF v_movement_tenant_id IS NULL THEN
            RAISE EXCEPTION 'storage movement not found for material event';
        END IF;
        IF v_movement_tenant_id <> NEW.tenant_id OR v_movement_cohort_id <> NEW.inventory_quantity_cohort_id THEN
            RAISE EXCEPTION 'material event storage movement does not match tenant/cohort';
        END IF;
        IF v_movement_kind NOT IN ('return', 'scrap_bin') THEN
            RAISE EXCEPTION 'material event storage movement must be return or scrap_bin';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    bind = op.get_bind()

    # --- Extend inventory_storage_movements for 'return'/'scrap_bin' -------

    op.drop_constraint("ck_inventory_storage_movements_kind_allowed", "inventory_storage_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_storage_movements_kind_allowed", "inventory_storage_movements",
        "movement_kind IN ('putaway', 'transfer', 'split_out', 'split_in', 'issue', 'return', 'scrap_bin')",
    )

    op.drop_constraint("ck_inventory_storage_movements_shape", "inventory_storage_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_storage_movements_shape", "inventory_storage_movements",
        "(movement_kind IN ('putaway', 'split_in', 'return') AND source_location_id IS NULL "
        "  AND destination_location_id IS NOT NULL) "
        "OR (movement_kind = 'transfer' AND source_location_id IS NOT NULL "
        "     AND destination_location_id IS NOT NULL AND source_location_id <> destination_location_id) "
        "OR (movement_kind IN ('split_out', 'issue', 'scrap_bin') AND source_location_id IS NOT NULL "
        "     AND destination_location_id IS NULL)",
    )

    op.drop_constraint(
        "ck_inventory_storage_movements_command_evidence_matches_kind", "inventory_storage_movements", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_storage_movements_command_evidence_matches_kind", "inventory_storage_movements",
        "(movement_kind IN ('putaway', 'transfer') AND client_command_id IS NOT NULL "
        "  AND request_fingerprint IS NOT NULL) "
        "OR (movement_kind IN ('split_out', 'split_in', 'issue', 'return', 'scrap_bin') "
        "  AND client_command_id IS NULL AND request_fingerprint IS NULL)",
    )

    bind.execute(sa.text(_MOVEMENT_INTEGRITY_FUNCTION_V3))
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_storage_movements_enforce_insert_integrity ON inventory_storage_movements"
    )
    op.execute(
        "CREATE TRIGGER inventory_storage_movements_enforce_insert_integrity "
        "BEFORE INSERT ON inventory_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION enforce_inventory_storage_movement_insert_integrity_v3();"
    )

    # --- Extend inventory_existence_ledger_entries for 'consumption'/'scrap' ---

    op.drop_constraint(
        "ck_inventory_existence_ledger_entries_kind_allowed", "inventory_existence_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_existence_ledger_entries_kind_allowed", "inventory_existence_ledger_entries",
        "entry_kind IN ('receipt', 'adjustment', 'reversal', 'split_out', 'split_in', 'consumption', 'scrap')",
    )

    op.drop_constraint(
        "ck_inventory_existence_ledger_entries_envelope", "inventory_existence_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_existence_ledger_entries_envelope", "inventory_existence_ledger_entries",
        "quantity_delta_base = trunc(quantity_delta_base, 3) AND ("
        "  (entry_kind = 'receipt' AND quantity_delta_base > 0 AND quantity_delta_base < 100000000000)"
        "  OR (entry_kind = 'adjustment' AND quantity_delta_base <> 0 "
        "      AND quantity_delta_base > -100000000000 AND quantity_delta_base < 100000000000)"
        "  OR (entry_kind = 'reversal' AND quantity_delta_base <> 0 "
        "      AND quantity_delta_base > -100000000000 AND quantity_delta_base < 100000000000)"
        "  OR (entry_kind = 'split_out' AND quantity_delta_base < 0 AND quantity_delta_base > -100000000000)"
        "  OR (entry_kind = 'split_in' AND quantity_delta_base > 0 AND quantity_delta_base < 100000000000)"
        "  OR (entry_kind = 'consumption' AND quantity_delta_base < 0 AND quantity_delta_base > -100000000000)"
        "  OR (entry_kind = 'scrap' AND quantity_delta_base < 0 AND quantity_delta_base > -100000000000)"
        ")",
    )

    op.drop_constraint(
        "ck_inventory_existence_ledger_entries_typed_source_shape", "inventory_existence_ledger_entries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_inventory_existence_ledger_entries_typed_source_shape", "inventory_existence_ledger_entries",
        "(entry_kind IN ('receipt', 'adjustment', 'split_out', 'consumption', 'scrap') "
        "  AND reversal_of_entry_id IS NULL AND source_split_out_entry_id IS NULL) "
        "OR (entry_kind = 'reversal' "
        "  AND reversal_of_entry_id IS NOT NULL AND source_split_out_entry_id IS NULL) "
        "OR (entry_kind = 'split_in' "
        "  AND reversal_of_entry_id IS NULL AND source_split_out_entry_id IS NOT NULL)",
    )

    bind.execute(sa.text(_LEDGER_INTEGRITY_FUNCTION_V2))
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_existence_ledger_entries_enforce_insert_integrity "
        "ON inventory_existence_ledger_entries"
    )
    op.execute(
        "CREATE TRIGGER inventory_existence_ledger_entries_enforce_insert_integrity "
        "BEFORE INSERT ON inventory_existence_ledger_entries "
        "FOR EACH ROW EXECUTE FUNCTION enforce_inventory_existence_ledger_entry_insert_integrity_v2();"
    )

    # --- New table: inventory_material_events -------------------------------

    op.create_table(
        "inventory_material_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "inventory_quantity_cohort_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_quantity_cohorts.id"), nullable=False,
        ),
        sa.Column("event_kind", sa.String(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("issue_line_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id"), nullable=True),
        sa.Column(
            "destination_location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id"), nullable=True
        ),
        sa.Column("quantity_base", sa.Numeric(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "existence_ledger_entry_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_existence_ledger_entries.id"), nullable=True,
        ),
        sa.Column(
            "storage_movement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_storage_movements.id"),
            nullable=True,
        ),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.CheckConstraint(
            "event_kind IN ('consumption', 'return', 'scrap')", name="ck_inventory_material_events_kind_allowed"
        ),
        sa.CheckConstraint(
            "source_kind IN ('issued', 'store_bin', 'not_put_away')",
            name="ck_inventory_material_events_source_kind_allowed",
        ),
        sa.CheckConstraint(
            "quantity_base > 0 AND quantity_base = trunc(quantity_base, 3) AND quantity_base < 100000000000",
            name="ck_inventory_material_events_quantity_positive",
        ),
        sa.CheckConstraint(
            "event_kind <> 'scrap' OR reason IS NOT NULL",
            name="ck_inventory_material_events_scrap_reason_required",
        ),
        sa.CheckConstraint(
            "(event_kind = 'consumption' AND source_kind = 'issued' AND issue_line_id IS NOT NULL "
            "  AND source_location_id IS NULL AND destination_location_id IS NULL "
            "  AND existence_ledger_entry_id IS NOT NULL AND storage_movement_id IS NULL) "
            "OR (event_kind = 'return' AND source_kind = 'issued' AND issue_line_id IS NOT NULL "
            "  AND source_location_id IS NULL AND destination_location_id IS NOT NULL "
            "  AND existence_ledger_entry_id IS NULL AND storage_movement_id IS NOT NULL) "
            "OR (event_kind = 'scrap' AND source_kind = 'issued' AND issue_line_id IS NOT NULL "
            "  AND source_location_id IS NULL AND destination_location_id IS NULL "
            "  AND existence_ledger_entry_id IS NOT NULL AND storage_movement_id IS NULL) "
            "OR (event_kind = 'scrap' AND source_kind = 'store_bin' AND issue_line_id IS NULL "
            "  AND source_location_id IS NOT NULL AND destination_location_id IS NULL "
            "  AND existence_ledger_entry_id IS NOT NULL AND storage_movement_id IS NOT NULL) "
            "OR (event_kind = 'scrap' AND source_kind = 'not_put_away' AND issue_line_id IS NULL "
            "  AND source_location_id IS NULL AND destination_location_id IS NULL "
            "  AND existence_ledger_entry_id IS NOT NULL AND storage_movement_id IS NULL)",
            name="ck_inventory_material_events_shape_matches_kind",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_material_events_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_inventory_material_events_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_quantity_cohort_id"],
            ["inventory_quantity_cohorts.tenant_id", "inventory_quantity_cohorts.id"],
            name="fk_inventory_material_events_tenant_cohort",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "issue_line_id"],
            ["inventory_storage_movements.tenant_id", "inventory_storage_movements.id"],
            name="fk_inventory_material_events_tenant_issue_line",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_inventory_material_events_tenant_farm_src_location",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "destination_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_inventory_material_events_tenant_farm_dest_location",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "existence_ledger_entry_id"],
            ["inventory_existence_ledger_entries.tenant_id", "inventory_existence_ledger_entries.id"],
            name="fk_inventory_material_events_tenant_ledger_entry",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "storage_movement_id"],
            ["inventory_storage_movements.tenant_id", "inventory_storage_movements.id"],
            name="fk_inventory_material_events_tenant_storage_movement",
        ),
    )
    op.create_index(
        "ux_inventory_material_events_tenant_client_command_id", "inventory_material_events",
        ["tenant_id", "client_command_id"], unique=True,
    )
    bind.execute(sa.text(_MATERIAL_EVENT_INTEGRITY_FUNCTION))
    op.execute(
        "CREATE TRIGGER inventory_material_events_enforce_insert_integrity "
        "BEFORE INSERT ON inventory_material_events "
        "FOR EACH ROW EXECUTE FUNCTION enforce_inventory_material_event_insert_integrity();"
    )
    op.execute(
        "CREATE TRIGGER inventory_material_events_no_update BEFORE UPDATE ON inventory_material_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER inventory_material_events_no_delete BEFORE DELETE ON inventory_material_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )


def downgrade() -> None:
    bind = op.get_bind()

    count = bind.execute(sa.text("SELECT count(*) FROM inventory_material_events")).scalar_one()
    if count > 0:
        raise RuntimeError(
            f"Cannot downgrade past STORE-INV-004: {count} inventory_material_events row(s) exist. Downgrading "
            "would drop real Consumption/Return/Scrap history. Move/export the affected data out-of-band before "
            "downgrading, or do not downgrade."
        )
    movement_count = bind.execute(
        sa.text("SELECT count(*) FROM inventory_storage_movements WHERE movement_kind IN ('return', 'scrap_bin')")
    ).scalar_one()
    if movement_count > 0:
        raise RuntimeError(
            f"Cannot downgrade past STORE-INV-004: {movement_count} 'return'/'scrap_bin' inventory_storage_"
            "movements row(s) exist. Downgrading would drop real physical-custody history."
        )
    ledger_count = bind.execute(
        sa.text("SELECT count(*) FROM inventory_existence_ledger_entries WHERE entry_kind IN ('consumption', 'scrap')")
    ).scalar_one()
    if ledger_count > 0:
        raise RuntimeError(
            f"Cannot downgrade past STORE-INV-004: {ledger_count} 'consumption'/'scrap' inventory_existence_"
            "ledger_entries row(s) exist. Downgrading would drop real existence history."
        )

    op.execute("DROP TRIGGER IF EXISTS inventory_material_events_no_delete ON inventory_material_events")
    op.execute("DROP TRIGGER IF EXISTS inventory_material_events_no_update ON inventory_material_events")
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_material_events_enforce_insert_integrity ON inventory_material_events"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_material_event_insert_integrity()")
    op.drop_index("ux_inventory_material_events_tenant_client_command_id", table_name="inventory_material_events")
    op.drop_table("inventory_material_events")

    op.execute(
        "DROP TRIGGER IF EXISTS inventory_existence_ledger_entries_enforce_insert_integrity "
        "ON inventory_existence_ledger_entries"
    )
    op.execute(
        "CREATE TRIGGER inventory_existence_ledger_entries_enforce_insert_integrity "
        "BEFORE INSERT ON inventory_existence_ledger_entries "
        "FOR EACH ROW EXECUTE FUNCTION enforce_inventory_existence_ledger_entry_insert_integrity();"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_existence_ledger_entry_insert_integrity_v2()")

    op.drop_constraint(
        "ck_inventory_existence_ledger_entries_typed_source_shape", "inventory_existence_ledger_entries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_inventory_existence_ledger_entries_typed_source_shape", "inventory_existence_ledger_entries",
        "(entry_kind IN ('receipt', 'adjustment', 'split_out') "
        "  AND reversal_of_entry_id IS NULL AND source_split_out_entry_id IS NULL) "
        "OR (entry_kind = 'reversal' "
        "  AND reversal_of_entry_id IS NOT NULL AND source_split_out_entry_id IS NULL) "
        "OR (entry_kind = 'split_in' "
        "  AND reversal_of_entry_id IS NULL AND source_split_out_entry_id IS NOT NULL)",
    )
    op.drop_constraint(
        "ck_inventory_existence_ledger_entries_envelope", "inventory_existence_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_existence_ledger_entries_envelope", "inventory_existence_ledger_entries",
        "quantity_delta_base = trunc(quantity_delta_base, 3) AND ("
        "  (entry_kind = 'receipt' AND quantity_delta_base > 0 AND quantity_delta_base < 100000000000)"
        "  OR (entry_kind = 'adjustment' AND quantity_delta_base <> 0 "
        "      AND quantity_delta_base > -100000000000 AND quantity_delta_base < 100000000000)"
        "  OR (entry_kind = 'reversal' AND quantity_delta_base <> 0 "
        "      AND quantity_delta_base > -100000000000 AND quantity_delta_base < 100000000000)"
        "  OR (entry_kind = 'split_out' AND quantity_delta_base < 0 AND quantity_delta_base > -100000000000)"
        "  OR (entry_kind = 'split_in' AND quantity_delta_base > 0 AND quantity_delta_base < 100000000000)"
        ")",
    )
    op.drop_constraint(
        "ck_inventory_existence_ledger_entries_kind_allowed", "inventory_existence_ledger_entries", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_existence_ledger_entries_kind_allowed", "inventory_existence_ledger_entries",
        "entry_kind IN ('receipt', 'adjustment', 'reversal', 'split_out', 'split_in')",
    )

    op.execute(
        "DROP TRIGGER IF EXISTS inventory_storage_movements_enforce_insert_integrity ON inventory_storage_movements"
    )
    op.execute(
        "CREATE TRIGGER inventory_storage_movements_enforce_insert_integrity "
        "BEFORE INSERT ON inventory_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION enforce_inventory_storage_movement_insert_integrity_v2();"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_storage_movement_insert_integrity_v3()")

    op.drop_constraint(
        "ck_inventory_storage_movements_command_evidence_matches_kind", "inventory_storage_movements", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_storage_movements_command_evidence_matches_kind", "inventory_storage_movements",
        "(movement_kind IN ('putaway', 'transfer') AND client_command_id IS NOT NULL "
        "  AND request_fingerprint IS NOT NULL) "
        "OR (movement_kind IN ('split_out', 'split_in', 'issue') AND client_command_id IS NULL "
        "  AND request_fingerprint IS NULL)",
    )
    op.drop_constraint("ck_inventory_storage_movements_shape", "inventory_storage_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_storage_movements_shape", "inventory_storage_movements",
        "(movement_kind IN ('putaway', 'split_in') AND source_location_id IS NULL "
        "  AND destination_location_id IS NOT NULL) "
        "OR (movement_kind = 'transfer' AND source_location_id IS NOT NULL "
        "     AND destination_location_id IS NOT NULL AND source_location_id <> destination_location_id) "
        "OR (movement_kind IN ('split_out', 'issue') AND source_location_id IS NOT NULL "
        "     AND destination_location_id IS NULL)",
    )
    op.drop_constraint("ck_inventory_storage_movements_kind_allowed", "inventory_storage_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_storage_movements_kind_allowed", "inventory_storage_movements",
        "movement_kind IN ('putaway', 'transfer', 'split_out', 'split_in', 'issue')",
    )
