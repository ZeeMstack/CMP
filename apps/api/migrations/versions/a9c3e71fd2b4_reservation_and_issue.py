"""reservation and issue (STORE-INV-003)

Answers "how much usable Store stock is committed?" / "what can still be
issued?" / "what has physically left the Store for farm operations?" on top
of the already-deployed `e8baaf4a723e` (STORE-INV-002B custody). Never
collapses Existence (STORE-INV-002A.1), Physical custody (.002B), Quality
usability (.002A.2), Reservation, or Issue -- five separate questions.

**Reservation** is a fungible CLAIM against usable in-Store quantity of one
`InventoryItem` at one Farm -- frozen at FARM + ITEM, never `InventoryLot`/
cohort/Bin (`docs/domain/STORE_INVENTORY_MODEL.md` §9), so a later Quality
cohort split never requires reservation reassignment. It never touches
Existence, Quality, or physical custody.

- `inventory_reservations`: the immutable header (Farm, code, purpose,
  requester, effective/recorded time) -- one CREATE command, idempotent on
  `(tenant_id, client_command_id)`.
- `inventory_reservation_lines`: one immutable row per Item within a
  reservation, carrying the ORIGINAL requested quantity -- written once,
  atomically with the header, never updated.
- `inventory_reservation_line_entries`: the append-only DEBIT ledger against
  one line -- `release` (an operator freeing unused claim, its own
  idempotent top-level command) or `issue` (composed internally, in the
  SAME transaction, by an Issue command that fulfills part of this line --
  mirrors `inventory_storage_movements.split_out`/`split_in`'s own
  "internally composed, no separate client_command_id" convention). A
  line's remaining balance is always `requested_quantity_base -
  SUM(entries)`, never a stored aggregate -- the codebase's one balance
  idiom, applied here too.

**Issue** is a CUSTODY TRANSFER (§10): Store Bin custody -> "Issued to
operations" custody. It never touches Existence or Quality, and never
creates a Batch/Work Order. Reuses `inventory_storage_movements` (.002B)
rather than a parallel ledger -- a new `movement_kind = 'issue'` (source a
`store_bin`, destination NULL, exactly `split_out`'s own shape) IS the Issue
line: one movement row is simultaneously the physical custody debit and the
Issue line, so nothing is ever double-counted between Bin/"Not put
away"/"Issued to operations". `get_cohort_total_custody`'s existing formula
(putaway/split_in credit, split_out debit) is deliberately left untouched --
'issue' contributes nothing to it (defaults to its `ELSE 0` branch) -- so
"Not put away" (`existence - total_custody`) is provably unaffected by
Issue; "in Store Bin" is instead `total_custody - issued`, computed by the
new `inventory_availability_service`.

- `inventory_issues`: the immutable header (Farm, code, purpose, issuer,
  effective/recorded time, an OPTIONAL `reservation_id` when the whole Issue
  is against one reservation) -- one CREATE command, idempotent on
  `(tenant_id, client_command_id)`, mirrors `InventoryQualityCommand`'s own
  "header written once, before any child event row" shape (a multi-line
  Issue command fans out to N `inventory_storage_movements` rows, each
  composed with `client_command_id = NULL`, `issue_id = <this header>`).
- `inventory_storage_movements` gains `issue_id` (required exactly when
  `movement_kind = 'issue'`) and `reservation_line_id` (optional even then
  -- NULL for a direct Issue line, set when that specific line fulfills
  part of a reservation line).

Mirrors `dd8b86a52acf`/`e8baaf4a723e`'s own trigger idiom: every table here
is append-only (`reject_append_only_mutation`/`reject_hard_delete`, already
defined, reused unmodified), and `inventory_reservation_line_entries` gets
its own full insert-integrity trigger (lock the target line row, re-derive
and re-check its remaining balance) -- defense-in-depth against a direct-SQL
bypass, matching `enforce_inventory_storage_movement_insert_integrity`'s own
justification exactly.

`inventory_storage_movements`'s own insert-integrity trigger is extended via
a NEW versioned function, `..._v2` -- the "add a new versioned trigger
function, widen the CHECK in place, never touch the old function" idiom
`docs/domain/STORE_INVENTORY_MODEL.md` §14 already prescribes for this exact
seam. The v1 function from `e8baaf4a723e` is left completely untouched;
downgrade repoints the trigger back to it.

Downgrade is guarded, never blindly destructive: refuses while any row
exists in any table this migration creates.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a9c3e71fd2b4"
down_revision: str | None = "e8baaf4a723e"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


_MOVEMENT_INTEGRITY_FUNCTION_V2 = """
CREATE OR REPLACE FUNCTION enforce_inventory_storage_movement_insert_integrity_v2() RETURNS trigger AS $$
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
    IF NEW.movement_kind NOT IN ('putaway', 'transfer', 'split_out', 'split_in', 'issue') THEN
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
        -- v1's own precedent for transfer/split_out) -- Issue's own
        -- "active store_bin" requirement is enforced at the service layer,
        -- where it belongs alongside the rest of Issue's business
        -- validation, not as a historical-custody trap at the DB layer.
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
             WHEN movement_kind = 'split_out' THEN -moved_quantity_base ELSE 0 END
    ), 0) INTO v_total_custody
    FROM inventory_storage_movements WHERE inventory_quantity_cohort_id = NEW.inventory_quantity_cohort_id;

    IF NEW.movement_kind = 'putaway' THEN
        IF NEW.moved_quantity_base > (v_existence_balance - v_total_custody) THEN
            RAISE EXCEPTION 'putaway would exceed not-put-away quantity for cohort %', NEW.inventory_quantity_cohort_id;
        END IF;
    ELSIF NEW.movement_kind IN ('transfer', 'split_out', 'issue') THEN
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

_RESERVATION_LINE_ENTRY_INTEGRITY_FUNCTION = """
CREATE OR REPLACE FUNCTION enforce_inventory_reservation_line_entry_insert_integrity() RETURNS trigger AS $$
DECLARE
    v_line_tenant_id UUID;
    v_requested NUMERIC;
    v_debited NUMERIC;
BEGIN
    IF NEW.entry_kind NOT IN ('release', 'issue') THEN
        RAISE EXCEPTION 'unrecognized inventory reservation line entry kind %', NEW.entry_kind;
    END IF;

    SELECT tenant_id, requested_quantity_base INTO v_line_tenant_id, v_requested
    FROM inventory_reservation_lines WHERE id = NEW.reservation_line_id FOR UPDATE;
    IF v_line_tenant_id IS NULL THEN
        RAISE EXCEPTION 'reservation line not found for reservation line entry';
    END IF;
    IF v_line_tenant_id <> NEW.tenant_id THEN
        RAISE EXCEPTION 'reservation line entry tenant does not match the reservation line''s own';
    END IF;

    SELECT COALESCE(SUM(quantity_base), 0) INTO v_debited
    FROM inventory_reservation_line_entries WHERE reservation_line_id = NEW.reservation_line_id;

    IF v_debited + NEW.quantity_base > v_requested THEN
        RAISE EXCEPTION 'reservation line entry would exceed remaining reservation balance for line %', NEW.reservation_line_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "inventory_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_reservations_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_inventory_reservations_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_inventory_reservations_tenant_farm"
        ),
    )
    op.create_index(
        "ux_inventory_reservations_farm_code_lower", "inventory_reservations", ["farm_id", sa.text("lower(code)")],
        unique=True,
    )
    op.create_index(
        "ux_inventory_reservations_tenant_client_command_id", "inventory_reservations",
        ["tenant_id", "client_command_id"], unique=True,
    )
    op.execute(
        "CREATE TRIGGER inventory_reservations_no_update BEFORE UPDATE ON inventory_reservations "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER inventory_reservations_no_delete BEFORE DELETE ON inventory_reservations "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )

    op.create_table(
        "inventory_reservation_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "reservation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_reservations.id"),
            nullable=False,
        ),
        sa.Column("inventory_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("requested_quantity_base", sa.Numeric(), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "requested_quantity_base > 0 AND requested_quantity_base = trunc(requested_quantity_base, 3) "
            "AND requested_quantity_base < 100000000000",
            name="ck_inventory_reservation_lines_quantity_positive",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_reservation_lines_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reservation_id"], ["inventory_reservations.tenant_id", "inventory_reservations.id"],
            name="fk_inventory_reservation_lines_tenant_reservation",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"], ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_inventory_reservation_lines_tenant_item",
        ),
    )
    op.execute(
        "CREATE TRIGGER inventory_reservation_lines_no_update BEFORE UPDATE ON inventory_reservation_lines "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER inventory_reservation_lines_no_delete BEFORE DELETE ON inventory_reservation_lines "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )

    op.create_table(
        "inventory_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("issued_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_issues_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_inventory_issues_tenant_farm"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reservation_id"], ["inventory_reservations.tenant_id", "inventory_reservations.id"],
            name="fk_inventory_issues_tenant_reservation",
        ),
    )
    op.create_index(
        "ux_inventory_issues_farm_code_lower", "inventory_issues", ["farm_id", sa.text("lower(code)")], unique=True,
    )
    op.create_index(
        "ux_inventory_issues_tenant_client_command_id", "inventory_issues", ["tenant_id", "client_command_id"],
        unique=True,
    )
    op.execute(
        "CREATE TRIGGER inventory_issues_no_update BEFORE UPDATE ON inventory_issues "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER inventory_issues_no_delete BEFORE DELETE ON inventory_issues "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )

    op.create_table(
        "inventory_reservation_line_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "reservation_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_reservation_lines.id"),
            nullable=False,
        ),
        sa.Column("entry_kind", sa.String(), nullable=False),
        sa.Column("quantity_base", sa.Numeric(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_fingerprint", sa.String(), nullable=True),
        sa.CheckConstraint("entry_kind IN ('release', 'issue')", name="ck_inventory_reservation_line_entries_kind_allowed"),
        sa.CheckConstraint(
            "quantity_base > 0 AND quantity_base = trunc(quantity_base, 3) AND quantity_base < 100000000000",
            name="ck_inventory_reservation_line_entries_quantity_positive",
        ),
        sa.CheckConstraint(
            "(entry_kind = 'release' AND client_command_id IS NOT NULL AND request_fingerprint IS NOT NULL "
            "  AND issue_id IS NULL) "
            "OR (entry_kind = 'issue' AND client_command_id IS NULL AND request_fingerprint IS NULL "
            "     AND issue_id IS NOT NULL)",
            name="ck_inventory_reservation_line_entries_evidence_matches_kind",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_reservation_line_entries_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reservation_line_id"],
            ["inventory_reservation_lines.tenant_id", "inventory_reservation_lines.id"],
            name="fk_inventory_reservation_line_entries_tenant_line",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "issue_id"], ["inventory_issues.tenant_id", "inventory_issues.id"],
            name="fk_inventory_reservation_line_entries_tenant_issue",
        ),
        sa.Index(
            "ux_inventory_reservation_line_entries_tenant_client_command_id", "tenant_id", "client_command_id",
            unique=True, postgresql_where=sa.text("client_command_id IS NOT NULL"),
        ),
    )
    bind.execute(sa.text(_RESERVATION_LINE_ENTRY_INTEGRITY_FUNCTION))
    op.execute(
        "CREATE TRIGGER inventory_reservation_line_entries_enforce_insert_integrity "
        "BEFORE INSERT ON inventory_reservation_line_entries "
        "FOR EACH ROW EXECUTE FUNCTION enforce_inventory_reservation_line_entry_insert_integrity();"
    )
    op.execute(
        "CREATE TRIGGER inventory_reservation_line_entries_no_update "
        "BEFORE UPDATE ON inventory_reservation_line_entries "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER inventory_reservation_line_entries_no_delete "
        "BEFORE DELETE ON inventory_reservation_line_entries "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )

    # --- Extend inventory_storage_movements (STORE-INV-002B) for 'issue' ---

    op.add_column(
        "inventory_storage_movements",
        sa.Column("issue_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "inventory_storage_movements",
        sa.Column("reservation_line_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_inventory_storage_movements_tenant_issue", "inventory_storage_movements", "inventory_issues",
        ["tenant_id", "issue_id"], ["tenant_id", "id"],
    )
    op.create_foreign_key(
        "fk_inventory_storage_movements_tenant_reservation_line", "inventory_storage_movements",
        "inventory_reservation_lines", ["tenant_id", "reservation_line_id"], ["tenant_id", "id"],
    )

    op.drop_constraint("ck_inventory_storage_movements_kind_allowed", "inventory_storage_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_storage_movements_kind_allowed", "inventory_storage_movements",
        "movement_kind IN ('putaway', 'transfer', 'split_out', 'split_in', 'issue')",
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

    op.create_check_constraint(
        "ck_inventory_storage_movements_issue_reference_matches_kind", "inventory_storage_movements",
        "(movement_kind = 'issue' AND issue_id IS NOT NULL) "
        "OR (movement_kind != 'issue' AND issue_id IS NULL AND reservation_line_id IS NULL)",
    )

    bind.execute(sa.text(_MOVEMENT_INTEGRITY_FUNCTION_V2))
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_storage_movements_enforce_insert_integrity ON inventory_storage_movements"
    )
    op.execute(
        "CREATE TRIGGER inventory_storage_movements_enforce_insert_integrity "
        "BEFORE INSERT ON inventory_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION enforce_inventory_storage_movement_insert_integrity_v2();"
    )


def downgrade() -> None:
    bind = op.get_bind()

    for table in (
        "inventory_reservations", "inventory_reservation_lines", "inventory_reservation_line_entries",
        "inventory_issues",
    ):
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count > 0:
            raise RuntimeError(
                f"Cannot downgrade past STORE-INV-003: {count} {table} row(s) exist. Downgrading would drop real "
                "Reservation/Issue history. Move/export the affected data out-of-band before downgrading, or do "
                "not downgrade."
            )
    # No separate check for `inventory_storage_movements WHERE movement_kind
    # = 'issue'` -- the `inventory_issues` check above already subsumes it:
    # every such movement's `issue_id` is a NOT NULL FK to a header row that
    # is never deleted, so an empty `inventory_issues` table already proves
    # zero 'issue' movements exist.

    op.execute(
        "DROP TRIGGER IF EXISTS inventory_storage_movements_enforce_insert_integrity ON inventory_storage_movements"
    )
    op.execute(
        "CREATE TRIGGER inventory_storage_movements_enforce_insert_integrity "
        "BEFORE INSERT ON inventory_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION enforce_inventory_storage_movement_insert_integrity();"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_storage_movement_insert_integrity_v2()")

    op.drop_constraint(
        "ck_inventory_storage_movements_issue_reference_matches_kind", "inventory_storage_movements", type_="check"
    )
    op.drop_constraint(
        "ck_inventory_storage_movements_command_evidence_matches_kind", "inventory_storage_movements", type_="check"
    )
    op.create_check_constraint(
        "ck_inventory_storage_movements_command_evidence_matches_kind", "inventory_storage_movements",
        "(movement_kind IN ('putaway', 'transfer') AND client_command_id IS NOT NULL "
        "  AND request_fingerprint IS NOT NULL) "
        "OR (movement_kind IN ('split_out', 'split_in') AND client_command_id IS NULL "
        "  AND request_fingerprint IS NULL)",
    )
    op.drop_constraint("ck_inventory_storage_movements_shape", "inventory_storage_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_storage_movements_shape", "inventory_storage_movements",
        "(movement_kind IN ('putaway', 'split_in') AND source_location_id IS NULL "
        "  AND destination_location_id IS NOT NULL) "
        "OR (movement_kind = 'transfer' AND source_location_id IS NOT NULL "
        "     AND destination_location_id IS NOT NULL AND source_location_id <> destination_location_id) "
        "OR (movement_kind = 'split_out' AND source_location_id IS NOT NULL AND destination_location_id IS NULL)",
    )
    op.drop_constraint("ck_inventory_storage_movements_kind_allowed", "inventory_storage_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_storage_movements_kind_allowed", "inventory_storage_movements",
        "movement_kind IN ('putaway', 'transfer', 'split_out', 'split_in')",
    )

    op.drop_constraint(
        "fk_inventory_storage_movements_tenant_reservation_line", "inventory_storage_movements", type_="foreignkey"
    )
    op.drop_constraint("fk_inventory_storage_movements_tenant_issue", "inventory_storage_movements", type_="foreignkey")
    op.drop_column("inventory_storage_movements", "reservation_line_id")
    op.drop_column("inventory_storage_movements", "issue_id")

    op.execute(
        "DROP TRIGGER IF EXISTS inventory_reservation_line_entries_no_delete ON inventory_reservation_line_entries"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_reservation_line_entries_no_update ON inventory_reservation_line_entries"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_reservation_line_entries_enforce_insert_integrity "
        "ON inventory_reservation_line_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_reservation_line_entry_insert_integrity()")
    op.drop_table("inventory_reservation_line_entries")

    op.execute("DROP TRIGGER IF EXISTS inventory_issues_no_delete ON inventory_issues")
    op.execute("DROP TRIGGER IF EXISTS inventory_issues_no_update ON inventory_issues")
    op.drop_table("inventory_issues")

    op.execute("DROP TRIGGER IF EXISTS inventory_reservation_lines_no_delete ON inventory_reservation_lines")
    op.execute("DROP TRIGGER IF EXISTS inventory_reservation_lines_no_update ON inventory_reservation_lines")
    op.drop_table("inventory_reservation_lines")

    op.execute("DROP TRIGGER IF EXISTS inventory_reservations_no_delete ON inventory_reservations")
    op.execute("DROP TRIGGER IF EXISTS inventory_reservations_no_update ON inventory_reservations")
    op.drop_table("inventory_reservations")
