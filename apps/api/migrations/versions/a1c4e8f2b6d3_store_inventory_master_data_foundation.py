"""store & inventory master data foundation

STORE-INV-001B: implements only what `docs/domain/STORE_INVENTORY_MODEL.md`
freezes as this ticket's scope -- UnitOfMeasure, approved global UOM
conversions, InventoryCategory, InventoryItem, and the `store_area`/
`store_rack` Store-hierarchy extension. No InventoryLot, no Goods Receipt,
no existence/storage ledger, no reservation/issue, no Work Order, no
occupancy-compatibility change (Asset/Carrier custody in a Store remains
STORE-INV-005 scope) -- see the ticket's own explicit exclusion list.

`unit_of_measures`/`uom_conversions` are global, system-seeded, read-only
infrastructure -- no tenant scoping, no mutation API, matching
`location_types`/`carrier_types`/`asset_types`. Global UOM convertibility is
gated by `conversion_family` (not `quantity_kind` alone): `EA`/`SEED` share
`quantity_kind = 'count'` but each carries `conversion_family = NULL`, so a
DB trigger on `uom_conversions` (a CHECK cannot join to the referenced rows)
permanently forbids any row connecting them, or any row spanning two
different non-NULL families. A second trigger rejects inserting the reverse
of an already-stored pair (e.g. `kg -> g` once `g -> kg` exists) -- only one
canonical direction is ever stored; the application computes the inverse.

`inventory_categories`/`inventory_items` are tenant-scoped catalogs
(`Crop`/`ProductionSystem` convention -- no `farm_id`), following
`packaging_units`' idempotency shape widened to a reversible `active <->
inactive` lifecycle with one independent idempotency pair per command
direction (create/update/deactivate/reactivate), never a shared column.
`inventory_items` freezes nothing structurally yet (no `InventoryLot`
exists to reference it) -- `base_uom_id` is deliberately left mutable; the
actual freeze-on-first-operational-use check is STORE-INV-002A scope. Two
tracking-policy CHECK constraints (expiry/QC release each require lot
tracking) are enforced now regardless.

`store_area`/`store_rack` are additive `location_types` rows (both
`default_occupiable = false`); five new generic (`greenhouse_classification
IS NULL`) `location_type_hierarchy_rules` rows extend the existing
`store -> store_bin` pair (left completely untouched) into the four frozen
patterns. No `occupancy_compatibility_rules` change.

Downgrade is guarded, never blindly destructive: it refuses while any
tenant-created `inventory_categories`/`inventory_items` row exists, or any
`Location` uses `store_area`/`store_rack` -- mirroring
`e5b8c3a72f04_carrier_specifications.py`'s own guard idiom.

Revision ID: a1c4e8f2b6d3
Revises: b3bcfef4052e
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a1c4e8f2b6d3'
down_revision: Union[str, None] = 'b3bcfef4052e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (code, name, quantity_kind, conversion_family) -- the exact minimum set,
# case-sensitive as written (kg/g/L/mL never uppercased; EA/SEED stay
# uppercase canonical codes). docs/domain/STORE_INVENTORY_MODEL.md §6.
_UOMS = (
    ("kg", "Kilogram", "mass", "MASS"),
    ("g", "Gram", "mass", "MASS"),
    ("L", "Litre", "volume", "VOLUME"),
    ("mL", "Millilitre", "volume", "VOLUME"),
    ("EA", "Each", "count", None),
    ("SEED", "Seed", "count", None),
)

# (from_code, to_code, multiply_factor) -- one direction only per pair; the
# application computes the inverse. No self-conversion rows, no EA<->SEED,
# no BAG/CAN/PACK.
_CONVERSIONS = (
    ("g", "kg", "0.001"),
    ("mL", "L", "0.001"),
)

# (code, name, default_occupiable)
_NEW_LOCATION_TYPES = (
    ("store_area", "Store Area", False),
    ("store_rack", "Store Rack", False),
)

# (parent_code, child_code) -- generic (greenhouse_classification IS NULL)
# scope, matching the existing store -> store_bin row exactly. store ->
# store_bin itself is untouched.
_NEW_HIERARCHY_RULES = (
    ("store", "store_area"),
    ("store", "store_rack"),
    ("store_area", "store_rack"),
    ("store_area", "store_bin"),
    ("store_rack", "store_bin"),
)

_CROSS_FAMILY_FUNCTION = """
    CREATE FUNCTION enforce_uom_conversion_family_match() RETURNS trigger AS $$
    DECLARE
        v_from_family TEXT;
        v_to_family TEXT;
    BEGIN
        SELECT conversion_family INTO v_from_family FROM unit_of_measures WHERE id = NEW.from_uom_id;
        SELECT conversion_family INTO v_to_family FROM unit_of_measures WHERE id = NEW.to_uom_id;
        IF v_from_family IS NULL OR v_to_family IS NULL OR v_from_family <> v_to_family THEN
            RAISE EXCEPTION
                'uom_conversions: from_uom and to_uom must share the same non-NULL conversion_family';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_NO_REVERSE_PAIR_FUNCTION = """
    CREATE FUNCTION enforce_uom_conversion_no_reverse_pair() RETURNS trigger AS $$
    DECLARE
        v_reverse_exists BOOLEAN;
    BEGIN
        SELECT EXISTS(
            SELECT 1 FROM uom_conversions
            WHERE from_uom_id = NEW.to_uom_id AND to_uom_id = NEW.from_uom_id
        ) INTO v_reverse_exists;
        IF v_reverse_exists THEN
            RAISE EXCEPTION
                'uom_conversions: the reverse pair already exists -- only one canonical direction may be stored';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. unit_of_measures (global, system-seeded, no mutation API) -----
    op.create_table(
        "unit_of_measures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("quantity_kind", sa.String(), nullable=False),
        sa.Column("conversion_family", sa.String(), nullable=True),
        sa.CheckConstraint(
            "quantity_kind IN ('mass', 'volume', 'count')", name="ck_unit_of_measures_quantity_kind_allowed"
        ),
        sa.CheckConstraint(
            "conversion_family IS NULL OR conversion_family IN ('MASS', 'VOLUME')",
            name="ck_unit_of_measures_conversion_family_allowed",
        ),
    )

    uom_ids: dict[str, str] = {}
    for code, name, quantity_kind, conversion_family in _UOMS:
        result = bind.execute(
            sa.text(
                "INSERT INTO unit_of_measures (id, code, name, quantity_kind, conversion_family) "
                "VALUES (gen_random_uuid(), :code, :name, :quantity_kind, :conversion_family) "
                "RETURNING id"
            ),
            {"code": code, "name": name, "quantity_kind": quantity_kind, "conversion_family": conversion_family},
        )
        uom_ids[code] = result.scalar_one()

    # --- 2. uom_conversions (global, system-seeded, no mutation API) ------
    op.create_table(
        "uom_conversions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "from_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"), nullable=False
        ),
        sa.Column(
            "to_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"), nullable=False
        ),
        sa.Column("multiply_factor", sa.Numeric(), nullable=False),
        sa.CheckConstraint("multiply_factor > 0", name="ck_uom_conversions_factor_positive"),
        sa.CheckConstraint("from_uom_id <> to_uom_id", name="ck_uom_conversions_no_self_conversion"),
        sa.UniqueConstraint("from_uom_id", "to_uom_id", name="ux_uom_conversions_from_to"),
    )

    op.execute(_CROSS_FAMILY_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER uom_conversions_enforce_family_match
        BEFORE INSERT OR UPDATE ON uom_conversions
        FOR EACH ROW EXECUTE FUNCTION enforce_uom_conversion_family_match();
        """
    )

    op.execute(_NO_REVERSE_PAIR_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER uom_conversions_enforce_no_reverse_pair
        BEFORE INSERT OR UPDATE ON uom_conversions
        FOR EACH ROW EXECUTE FUNCTION enforce_uom_conversion_no_reverse_pair();
        """
    )

    for from_code, to_code, factor in _CONVERSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO uom_conversions (id, from_uom_id, to_uom_id, multiply_factor) "
                "VALUES (gen_random_uuid(), :from_uom_id, :to_uom_id, :factor)"
            ),
            {"from_uom_id": uom_ids[from_code], "to_uom_id": uom_ids[to_code], "factor": factor},
        )

    # --- 3. inventory_categories (tenant-scoped) ---------------------------
    op.create_table(
        "inventory_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
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
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_inventory_categories_status"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_categories_tenant_id_id"),
    )
    op.alter_column("inventory_categories", "status", server_default=None)
    op.create_index(
        "ux_inventory_categories_tenant_code_lower",
        "inventory_categories", ["tenant_id", sa.text("lower(code)")], unique=True,
    )
    op.create_index(
        "ux_inventory_categories_tenant_client_command_id",
        "inventory_categories", ["tenant_id", "client_command_id"], unique=True,
    )
    op.create_index(
        "ux_inventory_categories_tenant_update_command",
        "inventory_categories", ["tenant_id", "update_client_command_id"], unique=True,
        postgresql_where=sa.text("update_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_inventory_categories_tenant_deactivation_command",
        "inventory_categories", ["tenant_id", "deactivation_client_command_id"], unique=True,
        postgresql_where=sa.text("deactivation_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_inventory_categories_tenant_reactivation_command",
        "inventory_categories", ["tenant_id", "reactivation_client_command_id"], unique=True,
        postgresql_where=sa.text("reactivation_client_command_id IS NOT NULL"),
    )

    op.execute(
        """
        CREATE FUNCTION enforce_inventory_category_identity() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id OR NEW.code <> OLD.code OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'tenant_id, code, and created_at are immutable on inventory_categories';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_categories_enforce_identity
        BEFORE UPDATE ON inventory_categories
        FOR EACH ROW EXECUTE FUNCTION enforce_inventory_category_identity();
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_inventory_category_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'inventory_categories cannot be hard-deleted';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_categories_no_delete
        BEFORE DELETE ON inventory_categories
        FOR EACH ROW EXECUTE FUNCTION reject_inventory_category_delete();
        """
    )

    # --- 4. inventory_items (tenant-scoped) --------------------------------
    op.create_table(
        "inventory_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("inventory_category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "base_uom_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("unit_of_measures.id"), nullable=False
        ),
        sa.Column("lot_tracking_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expiry_tracking_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("qc_release_required", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_inventory_items_status"),
        sa.CheckConstraint(
            "NOT expiry_tracking_required OR lot_tracking_required",
            name="ck_inventory_items_expiry_requires_lot_tracking",
        ),
        sa.CheckConstraint(
            "NOT qc_release_required OR lot_tracking_required",
            name="ck_inventory_items_qc_release_requires_lot_tracking",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inventory_items_tenant_id_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inventory_category_id"],
            ["inventory_categories.tenant_id", "inventory_categories.id"],
            name="fk_inventory_items_tenant_category",
        ),
    )
    op.alter_column("inventory_items", "status", server_default=None)
    op.alter_column("inventory_items", "lot_tracking_required", server_default=None)
    op.alter_column("inventory_items", "expiry_tracking_required", server_default=None)
    op.alter_column("inventory_items", "qc_release_required", server_default=None)
    op.create_index(
        "ux_inventory_items_tenant_code_lower",
        "inventory_items", ["tenant_id", sa.text("lower(code)")], unique=True,
    )
    op.create_index(
        "ux_inventory_items_tenant_client_command_id",
        "inventory_items", ["tenant_id", "client_command_id"], unique=True,
    )
    op.create_index(
        "ux_inventory_items_tenant_update_command",
        "inventory_items", ["tenant_id", "update_client_command_id"], unique=True,
        postgresql_where=sa.text("update_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_inventory_items_tenant_deactivation_command",
        "inventory_items", ["tenant_id", "deactivation_client_command_id"], unique=True,
        postgresql_where=sa.text("deactivation_client_command_id IS NOT NULL"),
    )
    op.create_index(
        "ux_inventory_items_tenant_reactivation_command",
        "inventory_items", ["tenant_id", "reactivation_client_command_id"], unique=True,
        postgresql_where=sa.text("reactivation_client_command_id IS NOT NULL"),
    )

    op.execute(
        """
        CREATE FUNCTION enforce_inventory_item_identity() RETURNS trigger AS $$
        BEGIN
            IF NEW.tenant_id <> OLD.tenant_id OR NEW.code <> OLD.code OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'tenant_id, code, and created_at are immutable on inventory_items';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_items_enforce_identity
        BEFORE UPDATE ON inventory_items
        FOR EACH ROW EXECUTE FUNCTION enforce_inventory_item_identity();
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_inventory_item_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'inventory_items cannot be hard-deleted';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER inventory_items_no_delete
        BEFORE DELETE ON inventory_items
        FOR EACH ROW EXECUTE FUNCTION reject_inventory_item_delete();
        """
    )

    # --- 5. Store hierarchy: store_area/store_rack + 5 hierarchy rules ----
    type_ids: dict[str, str] = {
        row["code"]: row["id"]
        for row in bind.execute(sa.text("SELECT id, code FROM location_types")).mappings().all()
    }
    for code, name, default_occupiable in _NEW_LOCATION_TYPES:
        result = bind.execute(
            sa.text(
                "INSERT INTO location_types (id, code, name, default_occupiable) "
                "VALUES (gen_random_uuid(), :code, :name, :default_occupiable) "
                "RETURNING id"
            ),
            {"code": code, "name": name, "default_occupiable": default_occupiable},
        )
        type_ids[code] = result.scalar_one()

    for parent_code, child_code in _NEW_HIERARCHY_RULES:
        bind.execute(
            sa.text(
                "INSERT INTO location_type_hierarchy_rules "
                "(id, parent_type_id, child_type_id, greenhouse_classification) "
                "VALUES (gen_random_uuid(), :parent_id, :child_id, NULL)"
            ),
            {"parent_id": type_ids[parent_code], "child_id": type_ids[child_code]},
        )


def downgrade() -> None:
    bind = op.get_bind()

    # --- guard: never blindly destroy tenant data --------------------------
    # Checked most-specific-dependency-first: an InventoryItem always
    # implies its own InventoryCategory exists too, so surfacing the item
    # count first gives the caller the most actionable message when both
    # conditions hold at once.
    item_count = bind.execute(sa.text("SELECT count(*) FROM inventory_items")).scalar_one()
    if item_count > 0:
        raise RuntimeError(
            "Cannot downgrade past STORE-INV-001B: "
            f"{item_count} inventory_items row(s) exist. Downgrading would drop real tenant-configured "
            "inventory master data. Move/export the affected data out-of-band before downgrading, "
            "or do not downgrade."
        )

    category_count = bind.execute(sa.text("SELECT count(*) FROM inventory_categories")).scalar_one()
    if category_count > 0:
        raise RuntimeError(
            "Cannot downgrade past STORE-INV-001B: "
            f"{category_count} inventory_categories row(s) exist. Downgrading would drop real "
            "tenant-configured inventory master data. Move/export the affected data out-of-band "
            "before downgrading, or do not downgrade."
        )

    store_location_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
            "WHERE lt.code IN ('store_area', 'store_rack')"
        )
    ).scalar_one()
    if store_location_count > 0:
        raise RuntimeError(
            "Cannot downgrade past STORE-INV-001B: "
            f"{store_location_count} locations row(s) use store_area/store_rack. Downgrading would "
            "orphan real tenant-configured Store structure. Move/export the affected data out-of-band "
            "before downgrading, or do not downgrade."
        )

    # --- only now: remove purely system-seeded structure -------------------
    # Resolves every code referenced by _NEW_HIERARCHY_RULES (not just the
    # two brand-new types) -- store/store_bin are pre-existing rows this
    # migration never created, but their ids are still needed to match the
    # parent/child pairs for deletion.
    type_ids: dict[str, str] = {
        row["code"]: row["id"]
        for row in bind.execute(
            sa.text("SELECT id, code FROM location_types WHERE code IN ('store', 'store_area', 'store_rack', 'store_bin')")
        ).mappings().all()
    }
    for parent_code, child_code in _NEW_HIERARCHY_RULES:
        bind.execute(
            sa.text(
                "DELETE FROM location_type_hierarchy_rules WHERE parent_type_id = :parent_id "
                "AND child_type_id = :child_id AND greenhouse_classification IS NULL"
            ),
            {"parent_id": type_ids.get(parent_code), "child_id": type_ids.get(child_code)},
        )
    bind.execute(sa.text("DELETE FROM location_types WHERE code IN ('store_area', 'store_rack')"))

    op.execute("DROP TRIGGER IF EXISTS inventory_items_no_delete ON inventory_items")
    op.execute("DROP FUNCTION IF EXISTS reject_inventory_item_delete()")
    op.execute("DROP TRIGGER IF EXISTS inventory_items_enforce_identity ON inventory_items")
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_item_identity()")
    op.drop_index("ux_inventory_items_tenant_reactivation_command", table_name="inventory_items")
    op.drop_index("ux_inventory_items_tenant_deactivation_command", table_name="inventory_items")
    op.drop_index("ux_inventory_items_tenant_update_command", table_name="inventory_items")
    op.drop_index("ux_inventory_items_tenant_client_command_id", table_name="inventory_items")
    op.drop_index("ux_inventory_items_tenant_code_lower", table_name="inventory_items")
    op.drop_table("inventory_items")

    op.execute("DROP TRIGGER IF EXISTS inventory_categories_no_delete ON inventory_categories")
    op.execute("DROP FUNCTION IF EXISTS reject_inventory_category_delete()")
    op.execute("DROP TRIGGER IF EXISTS inventory_categories_enforce_identity ON inventory_categories")
    op.execute("DROP FUNCTION IF EXISTS enforce_inventory_category_identity()")
    op.drop_index("ux_inventory_categories_tenant_reactivation_command", table_name="inventory_categories")
    op.drop_index("ux_inventory_categories_tenant_deactivation_command", table_name="inventory_categories")
    op.drop_index("ux_inventory_categories_tenant_update_command", table_name="inventory_categories")
    op.drop_index("ux_inventory_categories_tenant_client_command_id", table_name="inventory_categories")
    op.drop_index("ux_inventory_categories_tenant_code_lower", table_name="inventory_categories")
    op.drop_table("inventory_categories")

    op.execute("DROP TRIGGER IF EXISTS uom_conversions_enforce_no_reverse_pair ON uom_conversions")
    op.execute("DROP FUNCTION IF EXISTS enforce_uom_conversion_no_reverse_pair()")
    op.execute("DROP TRIGGER IF EXISTS uom_conversions_enforce_family_match ON uom_conversions")
    op.execute("DROP FUNCTION IF EXISTS enforce_uom_conversion_family_match()")
    op.drop_table("uom_conversions")
    op.drop_table("unit_of_measures")
