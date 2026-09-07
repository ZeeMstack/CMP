"""inventory storage custody (STORE-INV-002B)

Physical custody / putaway for quantity-bearing consumable Inventory --
"where is that material physically held inside the Farm Store?" Purely
additive on top of the already-deployed `abcdb6f371f9` (never edited, same
as `f1a4c8e7b2d5` before it). Mirrors `FinishedGoodsStorageMovement`
(`dd8b86a52acf`)'s own proven shape almost exactly: one immutable,
insert-only movement table; balance always `SUM`-derived, never a stored
`current_bin_id`/`current_quantity`; a full insert-integrity trigger
locking the aggregate root (here, `InventoryQuantityCohort`, reusing `.1`'s
own lock target) plus referenced Location rows in deterministic sorted-UUID
order, re-deriving and re-checking every balance the service layer already
checked -- defense-in-depth against a direct-SQL bypass, not merely a
structural sanity check.

One new table, `inventory_storage_movements`:

- `putaway` (source NULL, destination a `store_bin`): "Not put away" -> a
  Bin. Never changes `InventoryExistenceLedgerEntry` balances or Quality
  disposition -- existence, custody, and usability remain three separate
  questions (docs/domain/STORE_INVENTORY_MODEL.md §8B/§11).
- `transfer` (source and destination both `store_bin`, distinct, resolved
  to the SAME Farm via each Location's own `farm_id` -- cross-Farm transfer
  is out of scope and structurally impossible here, never merely
  unimplemented).
- `split_out`/`split_in`: never an operator command (no `client_command_id`/
  `request_fingerprint` -- CHECK-enforced) -- the custody-side half of a
  Quality partial split/correction that acts against a specific Bin bucket,
  composed internally by `inventory_quality_service` in the SAME
  transaction as the Quality command's own commit. `split_out` debits the
  PARENT cohort's custody in that Bin; `split_in` credits the CHILD
  cohort's custody in the SAME Bin -- a logical custody reclassification,
  never a physical move (the Bin's own total is unchanged, proven by the
  trigger's exact split_out/split_in pairing check). A partial action
  against the "Not put away" bucket writes no row at all.

"Not put away" is always derived -- `cohort existence balance - SUM(this
cohort's own signed custody)` -- never a fabricated Bin or a stored
aggregate. A future Issue/Work-Order custody bucket extends this same
derivation (existence - custody - reserved, or similar) without touching
this table's shape.

Downgrade is guarded, never blindly destructive: refuses while any
`inventory_storage_movements` row exists -- mirrors `dd8b86a52acf`'s own
guard idiom exactly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e8baaf4a723e"
down_revision: str | None = "abcdb6f371f9"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

STORAGE_ELIGIBLE_LOCATION_TYPE_CODE = "store_bin"

_INTEGRITY_FUNCTION = """
CREATE OR REPLACE FUNCTION enforce_inventory_storage_movement_insert_integrity() RETURNS trigger AS $$
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
BEGIN
    IF NEW.movement_kind NOT IN ('putaway', 'transfer', 'split_out', 'split_in') THEN
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

    -- Lock referenced location rows in deterministic sorted-UUID order,
    -- matching the application's own ordering exactly (avoids a
    -- transfer-vs-transfer deadlock between two movements referencing the
    -- same pair of locations in reversed roles).
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
        -- Source is deliberately not required to be active -- no
        -- Location-deactivation guard should be able to permanently trap
        -- already-recorded custody (mirrors FinishedGoodsStorageMovement's
        -- own precedent exactly).
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
    ELSIF NEW.movement_kind IN ('transfer', 'split_out') THEN
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

    op.create_table(
        "inventory_storage_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "inventory_quantity_cohort_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_quantity_cohorts.id"), nullable=False,
        ),
        sa.Column("movement_kind", sa.String(), nullable=False),
        sa.Column("source_location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id"), nullable=True),
        sa.Column(
            "destination_location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id"), nullable=True
        ),
        sa.Column("moved_quantity_base", sa.Numeric(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_fingerprint", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.CheckConstraint(
            "movement_kind IN ('putaway', 'transfer', 'split_out', 'split_in')",
            name="ck_inventory_storage_movements_kind_allowed",
        ),
        sa.CheckConstraint(
            "(movement_kind IN ('putaway', 'split_in') AND source_location_id IS NULL "
            "  AND destination_location_id IS NOT NULL) "
            "OR (movement_kind = 'transfer' AND source_location_id IS NOT NULL "
            "     AND destination_location_id IS NOT NULL AND source_location_id <> destination_location_id) "
            "OR (movement_kind = 'split_out' AND source_location_id IS NOT NULL AND destination_location_id IS NULL)",
            name="ck_inventory_storage_movements_shape",
        ),
        sa.CheckConstraint(
            "moved_quantity_base > 0 AND moved_quantity_base = trunc(moved_quantity_base, 3) "
            "AND moved_quantity_base < 100000000000",
            name="ck_inventory_storage_movements_quantity_positive",
        ),
        sa.CheckConstraint(
            "(movement_kind IN ('putaway', 'transfer') AND client_command_id IS NOT NULL "
            "  AND request_fingerprint IS NOT NULL) "
            "OR (movement_kind IN ('split_out', 'split_in') AND client_command_id IS NULL "
            "  AND request_fingerprint IS NULL)",
            name="ck_inventory_storage_movements_command_evidence_matches_kind",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_storage_movements_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_quantity_cohort_id"],
            ["inventory_quantity_cohorts.tenant_id", "inventory_quantity_cohorts.id"],
            name="fk_inventory_storage_movements_tenant_cohort",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "source_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_inventory_storage_movements_tenant_farm_src_location",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "destination_location_id"],
            ["locations.tenant_id", "locations.farm_id", "locations.id"],
            name="fk_inventory_storage_movements_tenant_farm_dest_location",
        ),
    )
    op.create_index(
        "ux_inventory_storage_movements_tenant_client_command_id", "inventory_storage_movements",
        ["tenant_id", "client_command_id"], unique=True,
        postgresql_where=sa.text("client_command_id IS NOT NULL"),
    )

    bind.execute(sa.text(_INTEGRITY_FUNCTION))
    op.execute(
        "CREATE TRIGGER inventory_storage_movements_enforce_insert_integrity "
        "BEFORE INSERT ON inventory_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION enforce_inventory_storage_movement_insert_integrity();"
    )
    op.execute(
        "CREATE TRIGGER inventory_storage_movements_no_update BEFORE UPDATE ON inventory_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();"
    )
    op.execute(
        "CREATE TRIGGER inventory_storage_movements_no_delete BEFORE DELETE ON inventory_storage_movements "
        "FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();"
    )


def downgrade() -> None:
    bind = op.get_bind()

    movement_count = bind.execute(sa.text("SELECT count(*) FROM inventory_storage_movements")).scalar_one()
    if movement_count > 0:
        raise RuntimeError(
            "Cannot downgrade past STORE-INV-002B: "
            f"{movement_count} inventory_storage_movements row(s) exist. Downgrading would drop real physical "
            "custody history. Move/export the affected data out-of-band before downgrading, or do not downgrade."
        )

    op.execute("DROP TRIGGER IF EXISTS inventory_storage_movements_no_delete ON inventory_storage_movements")
    op.execute("DROP TRIGGER IF EXISTS inventory_storage_movements_no_update ON inventory_storage_movements")
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_storage_movements_enforce_insert_integrity "
        "ON inventory_storage_movements"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_storage_movement_insert_integrity()")
    op.drop_index("ux_inventory_storage_movements_tenant_client_command_id", table_name="inventory_storage_movements")
    op.drop_table("inventory_storage_movements")
