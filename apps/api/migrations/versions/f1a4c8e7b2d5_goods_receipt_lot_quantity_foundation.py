"""goods receipt, tenant-wide inventory lot, and quantity-cohort foundation

STORE-INV-002A.1: implements the schema/service foundation frozen by
`docs/domain/STORE_INVENTORY_MODEL.md` (as amended by the STORE-INV-002A
discovery, commit 56c7e4a) -- `InventoryItemPackaging`, `InventoryItemSeedProfile`
("Seed Details"), the tenant-wide `InventoryLot`, `SeedLot.inventory_lot_id`,
`GoodsReceipt`/`GoodsReceiptLine`, `InventoryQuantityCohort` (including the
split schema), the `InventoryExistenceLedgerEntry` ledger (`receipt`/
`adjustment`/`reversal`/`split_out`/`split_in`), and the
`QualityDispositionEvent` table/automatic-opening-event foundation.

No physical custody/bin-balance table (STORE-INV-002B scope). No human
Quality mutation route exists yet (STORE-INV-002A.2) -- this migration only
ships the table/trigger scaffold that makes the automatic
`RECEIVED_QUARANTINED` opening event, and its permanent
non-reversibility, structurally enforceable from day one.

Key frozen decisions this migration encodes structurally:
- `InventoryLot` is tenant-wide (no `farm_id`); its canonical identity/
  uniqueness key is `(tenant_id, inventory_item_id,
  lower(trim(manufacturer_name)), lower(trim(manufacturer_lot_reference)))`
  ONLY -- `manufacturing_date`/`expiry_date` are immutable attributes of
  that identity, never uniqueness dimensions (service-layer compares them
  for compatibility on a canonical-key match; a mismatch is an explicit
  conflict, never a second lot under the same canonical identity).
- `GoodsReceiptLine` is pure receiving provenance; `InventoryQuantityCohort`
  is the existence-ledger and quality-disposition aggregate root. Every
  posted line gets exactly one deterministic root cohort
  (`id = goods_receipt_line_id`).
- The automatic opening `RECEIVED_QUARANTINED` `QualityDispositionEvent` can
  never be the target of a `REVERSAL` row, a `REVERSAL` can never target
  another `REVERSAL`, a `REVERSAL` must target an event on its own cohort,
  at most one `REVERSAL` may exist per target (partial unique index), and a
  `REVERSAL` may only target the CURRENT (latest, not-yet-reversed) human
  decision for a cohort, never one superseded by a later still-standing
  decision -- all enforced by `enforce_quality_disposition_event_insert_integrity`
  plus `ux_quality_disposition_events_reversal_target`, independent of the
  fact that no route can attempt any of this yet.
- `seed_lots.inventory_lot_id` (nullable, new) is the link direction --
  InventoryLot 1 -> many Farm-scoped SeedLots, at most one per Farm. No
  historical backfill; a linked SeedLot's own `supplier_lot_reference`/
  `expiry_date` are trigger-verified exactly equal to the linked
  InventoryLot's `manufacturer_lot_reference`/`expiry_date` (both sides are
  frozen at creation, so equality can never drift) -- existing sowing
  farm-local-date validation keeps reading SeedLot's own columns, unchanged.

Downgrade is unconditionally guarded (mirrors CMP-018's
`finished_goods_storage_movements` precedent, not the narrower
STORE-INV-001B "only if referenced" guard) -- every new table here is real
operational/traceability history the moment a single row exists, never
reconstructible.

Revision ID: f1a4c8e7b2d5
Revises: 10430de8731e
Create Date: 2026-09-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f1a4c8e7b2d5'
down_revision: Union[str, None] = '10430de8731e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # 1. inventory_item_packaging (tenant-scoped, item-specific)
    # ============================================================
    op.create_table(
        "inventory_item_packaging",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "inventory_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_items.id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("package_quantity", sa.Numeric(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("update_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("update_request_fingerprint", sa.String(), nullable=True),
        sa.Column("deactivation_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deactivation_request_fingerprint", sa.String(), nullable=True),
        sa.Column("reactivation_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reactivation_request_fingerprint", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_inventory_item_packaging_status"),
        sa.CheckConstraint("package_quantity > 0", name="ck_inventory_item_packaging_quantity_positive"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_item_packaging_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_inventory_item_packaging_tenant_item",
        ),
    )
    op.alter_column("inventory_item_packaging", "status", server_default=None)
    op.create_index(
        "ux_inventory_item_packaging_item_code_lower", "inventory_item_packaging",
        ["tenant_id", "inventory_item_id", sa.text("lower(code)")], unique=True,
    )
    op.create_index(
        "ux_inventory_item_packaging_tenant_client_command_id", "inventory_item_packaging",
        ["tenant_id", "client_command_id"], unique=True,
    )
    op.create_index(
        "ux_inventory_item_packaging_tenant_update_command", "inventory_item_packaging",
        ["tenant_id", "update_client_command_id"], unique=True,
        postgresql_where=sa.text("update_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_inventory_item_packaging_tenant_deactivation_command", "inventory_item_packaging",
        ["tenant_id", "deactivation_client_command_id"], unique=True,
        postgresql_where=sa.text("deactivation_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_inventory_item_packaging_tenant_reactivation_command", "inventory_item_packaging",
        ["tenant_id", "reactivation_client_command_id"], unique=True,
        postgresql_where=sa.text("reactivation_client_command_id IS NOT NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_inventory_item_packaging_identity() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id OR NEW.inventory_item_id <> OLD.inventory_item_id
                OR NEW.code <> OLD.code OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION
                    'tenant_id, inventory_item_id, code, and created_at are immutable on inventory_item_packaging';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_item_packaging_enforce_identity
        BEFORE UPDATE ON inventory_item_packaging
        FOR EACH ROW EXECUTE FUNCTION enforce_inventory_item_packaging_identity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_item_packaging_no_delete
        BEFORE DELETE ON inventory_item_packaging
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # ============================================================
    # 2. inventory_item_seed_profiles ("Seed Details")
    # ============================================================
    op.create_table(
        "inventory_item_seed_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "inventory_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_items.id"),
            nullable=False,
        ),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("crops.id"), nullable=False),
        sa.Column("variety_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("varieties.id"), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.Column("update_client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("update_request_fingerprint", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "inventory_item_id", name="uq_inventory_item_seed_profiles_item"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_item_seed_profiles_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id", "client_command_id", name="ux_inventory_item_seed_profiles_tenant_command"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_inventory_item_seed_profiles_tenant_item",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"],
            name="fk_inventory_item_seed_profiles_tenant_crop",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_inventory_item_seed_profiles_tenant_crop_variety",
        ),
    )
    # Structural freeze: once the item has any posted GoodsReceiptLine
    # (checked against the table created later in this same migration --
    # Postgres resolves the function body at CALL time, not CREATE time, so
    # forward-referencing goods_receipt_lines here is safe), Seed Details
    # become fully immutable -- reject UPDATE and DELETE outright. This is
    # attached only after goods_receipt_lines exists (see below).

    # ============================================================
    # 3. inventory_lots (tenant-wide)
    # ============================================================
    op.create_table(
        "inventory_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "inventory_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_items.id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("manufacturer_name", sa.String(), nullable=True),
        sa.Column("manufacturer_lot_reference", sa.String(), nullable=True),
        sa.Column("manufacturing_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "manufacturer_lot_reference IS NULL OR manufacturer_name IS NOT NULL",
            name="ck_inventory_lots_manufacturer_reference_requires_name",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_lots_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_inventory_lots_tenant_item",
        ),
    )
    op.create_index(
        "ux_inventory_lots_tenant_code_lower", "inventory_lots", ["tenant_id", sa.text("lower(code)")],
        unique=True,
    )
    # Canonical identity -- manufacturer name + manufacturer lot reference
    # ONLY. manufacturing_date/expiry_date are deliberately NOT part of this
    # index -- STORE-INV-002A final domain closure, issue A1.
    op.create_index(
        "ux_inventory_lots_tenant_item_manufacturer_identity", "inventory_lots",
        [
            "tenant_id", "inventory_item_id",
            sa.text("lower(trim(manufacturer_name))"), sa.text("lower(trim(manufacturer_lot_reference))"),
        ],
        unique=True,
        postgresql_where=sa.text("manufacturer_name IS NOT NULL AND manufacturer_lot_reference IS NOT NULL"),
    )
    op.execute(
        """
        CREATE TRIGGER inventory_lots_no_update
        BEFORE UPDATE ON inventory_lots
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_lots_no_delete
        BEFORE DELETE ON inventory_lots
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # ============================================================
    # 4. seed_lots.inventory_lot_id (additive)
    # ============================================================
    op.add_column(
        "seed_lots",
        sa.Column("inventory_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_lots.id"), nullable=True),
    )
    op.create_index(
        "ux_seed_lots_inventory_lot_farm", "seed_lots", ["inventory_lot_id", "farm_id"], unique=True,
        postgresql_where=sa.text("inventory_lot_id IS NOT NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_seed_lot_inventory_lot_equality() RETURNS trigger AS $$
        DECLARE
            v_manufacturer_lot_reference TEXT;
            v_expiry_date DATE;
        BEGIN
            IF NEW.inventory_lot_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT manufacturer_lot_reference, expiry_date
                INTO v_manufacturer_lot_reference, v_expiry_date
                FROM inventory_lots WHERE id = NEW.inventory_lot_id;
            IF NEW.supplier_lot_reference IS DISTINCT FROM v_manufacturer_lot_reference
                OR NEW.expiry_date IS DISTINCT FROM v_expiry_date THEN
                RAISE EXCEPTION
                    'seed_lots.supplier_lot_reference/expiry_date must exactly equal the linked '
                    'inventory_lots.manufacturer_lot_reference/expiry_date';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER seed_lots_enforce_inventory_lot_equality
        BEFORE INSERT OR UPDATE ON seed_lots
        FOR EACH ROW EXECUTE FUNCTION enforce_seed_lot_inventory_lot_equality();
        """
    )

    # ============================================================
    # 5. goods_receipts (Farm-scoped header)
    # ============================================================
    op.create_table(
        "goods_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "received_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("supplier_name", sa.String(), nullable=True),
        sa.Column("external_system", sa.String(), nullable=True),
        sa.Column("external_document_id", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_goods_receipts_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_goods_receipts_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_goods_receipts_tenant_farm"
        ),
    )
    op.create_index(
        "ux_goods_receipts_farm_code_lower", "goods_receipts", ["farm_id", sa.text("lower(code)")], unique=True,
    )
    op.create_index(
        "ux_goods_receipts_tenant_client_command_id", "goods_receipts", ["tenant_id", "client_command_id"],
        unique=True,
    )
    op.execute(
        """
        CREATE TRIGGER goods_receipts_no_update
        BEFORE UPDATE ON goods_receipts
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER goods_receipts_no_delete
        BEFORE DELETE ON goods_receipts
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # ============================================================
    # 6. goods_receipt_lines (receiving provenance only)
    # ============================================================
    op.create_table(
        "goods_receipt_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "goods_receipt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("goods_receipts.id"),
            nullable=False,
        ),
        sa.Column(
            "inventory_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_items.id"),
            nullable=False,
        ),
        sa.Column("inventory_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_lots.id"), nullable=True),
        sa.Column("entered_quantity", sa.Numeric(), nullable=True),
        sa.Column("entered_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"), nullable=True),
        sa.Column("conversion_factor_applied", sa.Numeric(), nullable=True),
        sa.Column(
            "packaging_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_item_packaging.id"),
            nullable=True,
        ),
        sa.Column("package_count", sa.Integer(), nullable=True),
        sa.Column("package_quantity_snapshot", sa.Numeric(), nullable=True),
        sa.Column("base_quantity", sa.Numeric(), nullable=False),
        sa.Column("external_line_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "base_quantity > 0 AND base_quantity = trunc(base_quantity, 3) AND base_quantity < 100000000000",
            name="ck_goods_receipt_lines_base_quantity_envelope",
        ),
        sa.CheckConstraint(
            "package_count IS NULL OR package_count > 0", name="ck_goods_receipt_lines_package_count_positive"
        ),
        sa.CheckConstraint(
            "package_quantity_snapshot IS NULL OR package_quantity_snapshot > 0",
            name="ck_goods_receipt_lines_package_quantity_snapshot_positive",
        ),
        sa.CheckConstraint(
            "(entered_quantity IS NOT NULL AND entered_uom_id IS NOT NULL "
            " AND packaging_id IS NULL AND package_count IS NULL AND package_quantity_snapshot IS NULL) "
            "OR (entered_quantity IS NULL AND entered_uom_id IS NULL "
            " AND packaging_id IS NOT NULL AND package_count IS NOT NULL "
            " AND package_quantity_snapshot IS NOT NULL)",
            name="ck_goods_receipt_lines_entry_shape_xor",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_goods_receipt_lines_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "farm_id", "id", name="uq_goods_receipt_lines_tenant_farm_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "farm_id", "goods_receipt_id"],
            ["goods_receipts.tenant_id", "goods_receipts.farm_id", "goods_receipts.id"],
            name="fk_goods_receipt_lines_tenant_farm_receipt",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_goods_receipt_lines_tenant_item",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_lot_id"],
            ["inventory_lots.tenant_id", "inventory_lots.id"],
            name="fk_goods_receipt_lines_tenant_lot",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "packaging_id"],
            ["inventory_item_packaging.tenant_id", "inventory_item_packaging.id"],
            name="fk_goods_receipt_lines_tenant_packaging",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_goods_receipt_line_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_lot_item UUID;
            v_packaging_item UUID;
            v_packaging_status TEXT;
        BEGIN
            IF NEW.inventory_lot_id IS NOT NULL THEN
                SELECT inventory_item_id INTO v_lot_item FROM inventory_lots WHERE id = NEW.inventory_lot_id;
                IF v_lot_item IS NULL OR v_lot_item <> NEW.inventory_item_id THEN
                    RAISE EXCEPTION 'goods_receipt_lines.inventory_lot_id must belong to the same inventory_item_id';
                END IF;
            END IF;
            IF NEW.packaging_id IS NOT NULL THEN
                SELECT inventory_item_id, status INTO v_packaging_item, v_packaging_status
                    FROM inventory_item_packaging WHERE id = NEW.packaging_id;
                IF v_packaging_item IS NULL OR v_packaging_item <> NEW.inventory_item_id THEN
                    RAISE EXCEPTION 'goods_receipt_lines.packaging_id must belong to the same inventory_item_id';
                END IF;
                IF v_packaging_status <> 'active' THEN
                    RAISE EXCEPTION 'goods_receipt_lines.packaging_id must reference an active packaging row';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER goods_receipt_lines_enforce_insert_integrity
        BEFORE INSERT ON goods_receipt_lines
        FOR EACH ROW EXECUTE FUNCTION enforce_goods_receipt_line_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER goods_receipt_lines_no_update
        BEFORE UPDATE ON goods_receipt_lines
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER goods_receipt_lines_no_delete
        BEFORE DELETE ON goods_receipt_lines
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # Now that goods_receipt_lines exists, attach the Seed Details freeze.
    op.execute(
        """
        CREATE FUNCTION enforce_inventory_item_seed_profile_freeze() RETURNS trigger AS $$
        DECLARE
            v_item_id UUID;
            v_has_receipts BOOLEAN;
        BEGIN
            v_item_id := COALESCE(NEW.inventory_item_id, OLD.inventory_item_id);
            SELECT EXISTS(
                SELECT 1 FROM goods_receipt_lines WHERE inventory_item_id = v_item_id
            ) INTO v_has_receipts;
            IF v_has_receipts THEN
                RAISE EXCEPTION
                    'inventory_item_seed_profiles is structurally frozen once its item has any posted '
                    'goods_receipt_lines row';
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_item_seed_profiles_enforce_freeze
        BEFORE UPDATE OR DELETE ON inventory_item_seed_profiles
        FOR EACH ROW EXECUTE FUNCTION enforce_inventory_item_seed_profile_freeze();
        """
    )

    # ============================================================
    # 7. inventory_quantity_cohorts
    # ============================================================
    op.create_table(
        "inventory_quantity_cohorts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "source_goods_receipt_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("goods_receipt_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "inventory_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_items.id"),
            nullable=False,
        ),
        sa.Column("inventory_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_lots.id"), nullable=True),
        sa.Column("receiving_farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column(
            "parent_cohort_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_quantity_cohorts.id"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_quantity_cohorts_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "receiving_farm_id", "source_goods_receipt_line_id"],
            ["goods_receipt_lines.tenant_id", "goods_receipt_lines.farm_id", "goods_receipt_lines.id"],
            name="fk_inventory_quantity_cohorts_tenant_farm_line",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_inventory_quantity_cohorts_tenant_item",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_lot_id"],
            ["inventory_lots.tenant_id", "inventory_lots.id"],
            name="fk_inventory_quantity_cohorts_tenant_lot",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_cohort_id"],
            ["inventory_quantity_cohorts.tenant_id", "inventory_quantity_cohorts.id"],
            name="fk_inventory_quantity_cohorts_tenant_parent",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_inventory_quantity_cohort_lineage() RETURNS trigger AS $$
        DECLARE
            v_parent_item UUID;
            v_parent_lot UUID;
            v_parent_line UUID;
            v_parent_farm UUID;
        BEGIN
            IF NEW.parent_cohort_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT inventory_item_id, inventory_lot_id, source_goods_receipt_line_id, receiving_farm_id
                INTO v_parent_item, v_parent_lot, v_parent_line, v_parent_farm
                FROM inventory_quantity_cohorts WHERE id = NEW.parent_cohort_id;
            IF v_parent_item IS NULL THEN
                RAISE EXCEPTION 'inventory_quantity_cohorts.parent_cohort_id does not resolve';
            END IF;
            IF NEW.inventory_item_id <> v_parent_item
                OR NEW.inventory_lot_id IS DISTINCT FROM v_parent_lot
                OR NEW.source_goods_receipt_line_id <> v_parent_line
                OR NEW.receiving_farm_id <> v_parent_farm THEN
                RAISE EXCEPTION
                    'a split child cohort must share its parent''s inventory_item_id, inventory_lot_id, '
                    'source_goods_receipt_line_id, and receiving_farm_id exactly';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_quantity_cohorts_enforce_lineage
        BEFORE INSERT ON inventory_quantity_cohorts
        FOR EACH ROW EXECUTE FUNCTION enforce_inventory_quantity_cohort_lineage();
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_quantity_cohorts_no_update
        BEFORE UPDATE ON inventory_quantity_cohorts
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_quantity_cohorts_no_delete
        BEFORE DELETE ON inventory_quantity_cohorts
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # ============================================================
    # 8. inventory_existence_ledger_entries
    # ============================================================
    op.create_table(
        "inventory_existence_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "inventory_quantity_cohort_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_quantity_cohorts.id"), nullable=False,
        ),
        sa.Column(
            "inventory_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_items.id"),
            nullable=False,
        ),
        sa.Column("inventory_lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_lots.id"), nullable=True),
        sa.Column("receiving_farm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("farms.id"), nullable=False),
        sa.Column("entry_kind", sa.String(), nullable=False),
        sa.Column("quantity_delta_base", sa.Numeric(), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column(
            "reversal_of_entry_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_existence_ledger_entries.id"), nullable=True,
        ),
        sa.Column(
            "source_split_out_entry_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_existence_ledger_entries.id"), nullable=True,
        ),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_fingerprint", sa.String(), nullable=True),
        sa.CheckConstraint(
            "entry_kind IN ('receipt', 'adjustment', 'reversal', 'split_out', 'split_in')",
            name="ck_inventory_existence_ledger_entries_kind_allowed",
        ),
        sa.CheckConstraint(
            "quantity_delta_base = trunc(quantity_delta_base, 3) AND ("
            "  (entry_kind = 'receipt' AND quantity_delta_base > 0 AND quantity_delta_base < 100000000000)"
            "  OR (entry_kind = 'adjustment' AND quantity_delta_base <> 0 "
            "      AND quantity_delta_base > -100000000000 AND quantity_delta_base < 100000000000)"
            "  OR (entry_kind = 'reversal' AND quantity_delta_base <> 0 "
            "      AND quantity_delta_base > -100000000000 AND quantity_delta_base < 100000000000)"
            "  OR (entry_kind = 'split_out' AND quantity_delta_base < 0 AND quantity_delta_base > -100000000000)"
            "  OR (entry_kind = 'split_in' AND quantity_delta_base > 0 AND quantity_delta_base < 100000000000)"
            ")",
            name="ck_inventory_existence_ledger_entries_envelope",
        ),
        sa.CheckConstraint(
            "entry_kind NOT IN ('adjustment', 'reversal') OR reason IS NOT NULL",
            name="ck_inventory_existence_ledger_entries_reason_required",
        ),
        sa.CheckConstraint(
            "(entry_kind IN ('receipt', 'adjustment', 'split_out') "
            "  AND reversal_of_entry_id IS NULL AND source_split_out_entry_id IS NULL) "
            "OR (entry_kind = 'reversal' "
            "  AND reversal_of_entry_id IS NOT NULL AND source_split_out_entry_id IS NULL) "
            "OR (entry_kind = 'split_in' "
            "  AND reversal_of_entry_id IS NULL AND source_split_out_entry_id IS NOT NULL)",
            name="ck_inventory_existence_ledger_entries_typed_source_shape",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_existence_ledger_entries_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_quantity_cohort_id"],
            ["inventory_quantity_cohorts.tenant_id", "inventory_quantity_cohorts.id"],
            name="fk_inventory_existence_ledger_entries_tenant_cohort",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_item_id"],
            ["inventory_items.tenant_id", "inventory_items.id"],
            name="fk_inventory_existence_ledger_entries_tenant_item",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_lot_id"],
            ["inventory_lots.tenant_id", "inventory_lots.id"],
            name="fk_inventory_existence_ledger_entries_tenant_lot",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reversal_of_entry_id"],
            ["inventory_existence_ledger_entries.tenant_id", "inventory_existence_ledger_entries.id"],
            name="fk_inventory_existence_ledger_entries_tenant_reversal_target",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_split_out_entry_id"],
            ["inventory_existence_ledger_entries.tenant_id", "inventory_existence_ledger_entries.id"],
            name="fk_inventory_existence_ledger_entries_tenant_split_out",
        ),
    )
    op.create_index(
        "ux_inventory_existence_ledger_entries_cohort_receipt", "inventory_existence_ledger_entries",
        ["inventory_quantity_cohort_id"], unique=True, postgresql_where=sa.text("entry_kind = 'receipt'"),
    )
    op.create_index(
        "ux_inventory_existence_ledger_entries_reversal_target", "inventory_existence_ledger_entries",
        ["reversal_of_entry_id"], unique=True, postgresql_where=sa.text("entry_kind = 'reversal'"),
    )
    op.create_index(
        "ux_inventory_existence_ledger_entries_split_out_target", "inventory_existence_ledger_entries",
        ["source_split_out_entry_id"], unique=True, postgresql_where=sa.text("entry_kind = 'split_in'"),
    )
    op.create_index(
        "ux_inventory_existence_ledger_entries_tenant_client_command_id", "inventory_existence_ledger_entries",
        ["tenant_id", "client_command_id"], unique=True, postgresql_where=sa.text("client_command_id IS NOT NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_inventory_existence_ledger_entry_insert_integrity() RETURNS trigger AS $$
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
    )
    op.execute(
        """
        CREATE TRIGGER inventory_existence_ledger_entries_enforce_insert_integrity
        BEFORE INSERT ON inventory_existence_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_inventory_existence_ledger_entry_insert_integrity();
        """
    )
    # Non-negative existence -- deferred so multiple inserts against the
    # same cohort within one transaction (e.g. several split entries) are
    # only re-checked once, at commit, against the final aggregate state.
    op.execute(
        """
        CREATE FUNCTION enforce_inventory_existence_ledger_non_negative() RETURNS trigger AS $$
        DECLARE
            v_balance NUMERIC;
        BEGIN
            SELECT COALESCE(SUM(quantity_delta_base), 0) INTO v_balance
                FROM inventory_existence_ledger_entries
                WHERE inventory_quantity_cohort_id = NEW.inventory_quantity_cohort_id;
            IF v_balance < 0 THEN
                RAISE EXCEPTION 'inventory_quantity_cohort % balance would become negative (%)',
                    NEW.inventory_quantity_cohort_id, v_balance;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER inventory_existence_ledger_entries_enforce_non_negative
        AFTER INSERT ON inventory_existence_ledger_entries
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_inventory_existence_ledger_non_negative();
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_existence_ledger_entries_no_update
        BEFORE UPDATE ON inventory_existence_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_existence_ledger_entries_no_delete
        BEFORE DELETE ON inventory_existence_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )

    # ============================================================
    # 9. quality_disposition_events
    # ============================================================
    op.create_table(
        "quality_disposition_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "inventory_quantity_cohort_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_quantity_cohorts.id"), nullable=False,
        ),
        sa.Column("event_kind", sa.String(), nullable=False),
        sa.Column(
            "reverses_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quality_disposition_events.id"),
            nullable=True,
        ),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("client_command_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_fingerprint", sa.String(), nullable=True),
        sa.CheckConstraint(
            "event_kind IN ('RECEIVED_QUARANTINED', 'RELEASED', 'HELD', 'HOLD_RELEASED', 'REJECTED', 'REVERSAL')",
            name="ck_quality_disposition_events_kind_allowed",
        ),
        sa.CheckConstraint(
            "(event_kind = 'REVERSAL' AND reverses_event_id IS NOT NULL) "
            "OR (event_kind <> 'REVERSAL' AND reverses_event_id IS NULL)",
            name="ck_quality_disposition_events_reversal_shape",
        ),
        sa.CheckConstraint(
            "event_kind <> 'REVERSAL' OR reason IS NOT NULL",
            name="ck_quality_disposition_events_reversal_reason_required",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_quality_disposition_events_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_quantity_cohort_id"],
            ["inventory_quantity_cohorts.tenant_id", "inventory_quantity_cohorts.id"],
            name="fk_quality_disposition_events_tenant_cohort",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reverses_event_id"],
            ["quality_disposition_events.tenant_id", "quality_disposition_events.id"],
            name="fk_quality_disposition_events_tenant_reversal_target",
        ),
    )
    op.create_index(
        "ux_quality_disposition_events_cohort_opening_quarantine", "quality_disposition_events",
        ["inventory_quantity_cohort_id"], unique=True,
        postgresql_where=sa.text("event_kind = 'RECEIVED_QUARANTINED'"),
    )
    op.create_index(
        "ux_quality_disposition_events_reversal_target", "quality_disposition_events", ["reverses_event_id"],
        unique=True, postgresql_where=sa.text("event_kind = 'REVERSAL'"),
    )
    op.execute(
        """
        CREATE FUNCTION enforce_quality_disposition_event_insert_integrity() RETURNS trigger AS $$
        DECLARE
            v_target_kind TEXT;
            v_target_cohort UUID;
            v_target_effective_time TIMESTAMPTZ;
            v_target_recorded_time TIMESTAMPTZ;
            v_superseding_event_id UUID;
        BEGIN
            IF NEW.event_kind = 'REVERSAL' THEN
                SELECT event_kind, inventory_quantity_cohort_id, effective_time, recorded_time
                    INTO v_target_kind, v_target_cohort, v_target_effective_time, v_target_recorded_time
                    FROM quality_disposition_events WHERE id = NEW.reverses_event_id;
                IF v_target_kind IS NULL THEN
                    RAISE EXCEPTION 'reverses_event_id does not resolve';
                END IF;
                IF v_target_kind = 'REVERSAL' THEN
                    RAISE EXCEPTION 'a REVERSAL event can never itself be the target of another REVERSAL';
                END IF;
                -- STORE-INV-002A final domain closure, issue A2: the
                -- automatic opening RECEIVED_QUARANTINED event is a
                -- system/receipt fact, never a human decision, and is
                -- permanently excluded from correction.
                IF v_target_kind = 'RECEIVED_QUARANTINED' THEN
                    RAISE EXCEPTION
                        'the automatic RECEIVED_QUARANTINED opening event can never be reversed';
                END IF;
                IF v_target_cohort <> NEW.inventory_quantity_cohort_id THEN
                    RAISE EXCEPTION 'a REVERSAL must target an event on the same inventory_quantity_cohort_id';
                END IF;
                -- STORE_INVENTORY_MODEL.md §11: a REVERSAL may target only
                -- the CURRENT (latest, not-yet-reversed) human decision for
                -- a cohort, never a superseded one -- e.g. reversing an old
                -- RELEASED while a later HELD still stands is rejected. A
                -- later event only supersedes while it has not itself been
                -- reversed; reversing that later event correctly re-exposes
                -- the event before it as current and eligible again.
                SELECT e2.id INTO v_superseding_event_id
                    FROM quality_disposition_events e2
                    WHERE e2.inventory_quantity_cohort_id = v_target_cohort
                        AND e2.event_kind <> 'REVERSAL'
                        AND (e2.effective_time, e2.recorded_time, e2.id)
                            > (v_target_effective_time, v_target_recorded_time, NEW.reverses_event_id)
                        AND NOT EXISTS (
                            SELECT 1 FROM quality_disposition_events r WHERE r.reverses_event_id = e2.id
                        )
                    LIMIT 1;
                IF v_superseding_event_id IS NOT NULL THEN
                    RAISE EXCEPTION
                        'a REVERSAL may only target the current (latest, not-yet-reversed) disposition '
                        'event for a cohort; % is superseded by %', NEW.reverses_event_id, v_superseding_event_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER quality_disposition_events_enforce_insert_integrity
        BEFORE INSERT ON quality_disposition_events
        FOR EACH ROW EXECUTE FUNCTION enforce_quality_disposition_event_insert_integrity();
        """
    )
    op.execute(
        """
        CREATE TRIGGER quality_disposition_events_no_update
        BEFORE UPDATE ON quality_disposition_events
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER quality_disposition_events_no_delete
        BEFORE DELETE ON quality_disposition_events
        FOR EACH ROW EXECUTE FUNCTION reject_hard_delete();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- guard: never blindly destroy real operational/traceability data ---
    # Unconditional block on row existence (mirrors CMP-018's
    # finished_goods_storage_movements precedent) -- every table here is
    # genuine operational history the moment a single row exists, never
    # reconstructible.
    checks = (
        ("quality_disposition_events", "quality_disposition_events"),
        ("inventory_existence_ledger_entries", "inventory_existence_ledger_entries"),
        ("inventory_quantity_cohorts", "inventory_quantity_cohorts"),
        ("goods_receipt_lines", "goods_receipt_lines"),
        ("goods_receipts", "goods_receipts"),
        ("inventory_lots", "inventory_lots"),
        ("inventory_item_seed_profiles", "inventory_item_seed_profiles"),
        ("inventory_item_packaging", "inventory_item_packaging"),
    )
    for label, table in checks:
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count > 0:
            raise RuntimeError(
                f"Cannot downgrade past STORE-INV-002A.1: {count} {label} row(s) exist. This is real "
                "operational/traceability data, never reconstructible. Move/export the affected data "
                "out-of-band before downgrading, or do not downgrade."
            )
    linked_seed_lot_count = bind.execute(
        sa.text("SELECT count(*) FROM seed_lots WHERE inventory_lot_id IS NOT NULL")
    ).scalar_one()
    if linked_seed_lot_count > 0:
        raise RuntimeError(
            f"Cannot downgrade past STORE-INV-002A.1: {linked_seed_lot_count} seed_lots row(s) carry a "
            "non-NULL inventory_lot_id. Move/export the affected data out-of-band before downgrading, "
            "or do not downgrade."
        )

    # --- quality_disposition_events ---
    op.execute("DROP TRIGGER IF EXISTS quality_disposition_events_no_delete ON quality_disposition_events")
    op.execute("DROP TRIGGER IF EXISTS quality_disposition_events_no_update ON quality_disposition_events")
    op.execute(
        "DROP TRIGGER IF EXISTS quality_disposition_events_enforce_insert_integrity "
        "ON quality_disposition_events"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_quality_disposition_event_insert_integrity()")
    op.drop_index("ux_quality_disposition_events_reversal_target", table_name="quality_disposition_events")
    op.drop_index(
        "ux_quality_disposition_events_cohort_opening_quarantine", table_name="quality_disposition_events"
    )
    op.drop_table("quality_disposition_events")

    # --- inventory_existence_ledger_entries ---
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_existence_ledger_entries_no_delete "
        "ON inventory_existence_ledger_entries"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_existence_ledger_entries_no_update "
        "ON inventory_existence_ledger_entries"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_existence_ledger_entries_enforce_non_negative "
        "ON inventory_existence_ledger_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_existence_ledger_non_negative()")
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_existence_ledger_entries_enforce_insert_integrity "
        "ON inventory_existence_ledger_entries"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_existence_ledger_entry_insert_integrity()")
    op.drop_index(
        "ux_inventory_existence_ledger_entries_tenant_client_command_id",
        table_name="inventory_existence_ledger_entries",
    )
    op.drop_index(
        "ux_inventory_existence_ledger_entries_split_out_target", table_name="inventory_existence_ledger_entries"
    )
    op.drop_index(
        "ux_inventory_existence_ledger_entries_reversal_target", table_name="inventory_existence_ledger_entries"
    )
    op.drop_index(
        "ux_inventory_existence_ledger_entries_cohort_receipt", table_name="inventory_existence_ledger_entries"
    )
    op.drop_table("inventory_existence_ledger_entries")

    # --- inventory_quantity_cohorts ---
    op.execute("DROP TRIGGER IF EXISTS inventory_quantity_cohorts_no_delete ON inventory_quantity_cohorts")
    op.execute("DROP TRIGGER IF EXISTS inventory_quantity_cohorts_no_update ON inventory_quantity_cohorts")
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_quantity_cohorts_enforce_lineage ON inventory_quantity_cohorts"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_quantity_cohort_lineage()")
    op.drop_table("inventory_quantity_cohorts")

    # --- Seed Details freeze (attached after goods_receipt_lines existed) ---
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_item_seed_profiles_enforce_freeze ON inventory_item_seed_profiles"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_item_seed_profile_freeze()")

    # --- goods_receipt_lines ---
    op.execute("DROP TRIGGER IF EXISTS goods_receipt_lines_no_delete ON goods_receipt_lines")
    op.execute("DROP TRIGGER IF EXISTS goods_receipt_lines_no_update ON goods_receipt_lines")
    op.execute(
        "DROP TRIGGER IF EXISTS goods_receipt_lines_enforce_insert_integrity ON goods_receipt_lines"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_goods_receipt_line_insert_integrity()")
    op.drop_table("goods_receipt_lines")

    # --- goods_receipts ---
    op.execute("DROP TRIGGER IF EXISTS goods_receipts_no_delete ON goods_receipts")
    op.execute("DROP TRIGGER IF EXISTS goods_receipts_no_update ON goods_receipts")
    op.drop_index("ux_goods_receipts_tenant_client_command_id", table_name="goods_receipts")
    op.drop_index("ux_goods_receipts_farm_code_lower", table_name="goods_receipts")
    op.drop_table("goods_receipts")

    # --- seed_lots.inventory_lot_id ---
    op.execute("DROP TRIGGER IF EXISTS seed_lots_enforce_inventory_lot_equality ON seed_lots")
    op.execute("DROP FUNCTION IF EXISTS enforce_seed_lot_inventory_lot_equality()")
    op.drop_index("ux_seed_lots_inventory_lot_farm", table_name="seed_lots")
    op.drop_column("seed_lots", "inventory_lot_id")

    # --- inventory_lots ---
    op.execute("DROP TRIGGER IF EXISTS inventory_lots_no_delete ON inventory_lots")
    op.execute("DROP TRIGGER IF EXISTS inventory_lots_no_update ON inventory_lots")
    op.drop_index("ux_inventory_lots_tenant_item_manufacturer_identity", table_name="inventory_lots")
    op.drop_index("ux_inventory_lots_tenant_code_lower", table_name="inventory_lots")
    op.drop_table("inventory_lots")

    # --- inventory_item_seed_profiles ---
    op.drop_table("inventory_item_seed_profiles")

    # --- inventory_item_packaging ---
    op.execute("DROP TRIGGER IF EXISTS inventory_item_packaging_no_delete ON inventory_item_packaging")
    op.execute(
        "DROP TRIGGER IF EXISTS inventory_item_packaging_enforce_identity ON inventory_item_packaging"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_item_packaging_identity()")
    op.drop_index("ux_inventory_item_packaging_tenant_reactivation_command", table_name="inventory_item_packaging")
    op.drop_index("ux_inventory_item_packaging_tenant_deactivation_command", table_name="inventory_item_packaging")
    op.drop_index("ux_inventory_item_packaging_tenant_update_command", table_name="inventory_item_packaging")
    op.drop_index("ux_inventory_item_packaging_tenant_client_command_id", table_name="inventory_item_packaging")
    op.drop_index("ux_inventory_item_packaging_item_code_lower", table_name="inventory_item_packaging")
    op.drop_table("inventory_item_packaging")
