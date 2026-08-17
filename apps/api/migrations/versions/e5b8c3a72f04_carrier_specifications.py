"""carrier specifications

CARRIER-CONFIG-001 -- introduces a tenant-configurable reusable physical
Carrier Specification layer between the platform-defined `CarrierType` (a
role, e.g. "seed_tray") and the individually-traceable `Carrier` (a
physical object, e.g. "ST-000001"):

    CarrierType (platform) -> CarrierSpecification (tenant) -> Carrier (farm)

One new table:

`carrier_specifications` -- a tenant-scoped, reusable physical design
("200 Cell Tray", "150 Hole Nursery Plate") a Carrier optionally references.
Physical equipment configuration only -- length/width/height in canonical
integer millimeters (no `dimension_unit` column, no conversion framework)
plus `biological_position_count` (the physical cell/hole count of the
reusable DESIGN). Deliberately never a crop/variety/planting-density fact,
and deliberately independent of `SowingEventLine.sown_site_count`/
`seed_count` (operational, per-sowing facts) and of
`TransplantDestinationLine.assigned_plant_count` (operational, per-cycle
fact) -- this migration adds no constraint linking any of them. Structural
fields (`carrier_type_id`, `code`, dimensions, `biological_position_count`)
freeze the moment the first `Carrier` references the specification
(`enforce_carrier_specification_structural_freeze`, backstopping the
service-layer check); `name`/`status` stay editable indefinitely. No hard
delete -- `status IN ('active', 'inactive')` only, matching the existing
`Crop`/`Variety`/`ProductionSystem` config-table convention exactly (none of
those three has a delete endpoint or a hard-delete-rejection trigger
either -- this migration does not invent one here).

`carrier_types` gains two platform metadata columns:

- `requires_specification` (bool, default false) -- whether a Carrier of
  this type must supply a `specification_id` at registration. Seeded here
  as `true` for the two brand-new role-specific Plate types (below) only;
  every pre-existing type (`seed_tray`, `cultivation_plate`, `grow_cube`,
  `grow_bag`, `harvest_crate`) stays `false` -- flipping `seed_tray` to
  `true` is deliberately deferred to a future, dedicated ticket (see the
  CARRIER-CONFIG-001 final report): dozens of pre-existing test scenario
  helpers across unrelated domains register `seed_tray` Carriers as
  incidental setup, and forcing every one of them to also fabricate a
  specification here would violate this ticket's own "no rewriting
  historical scenarios" constraint. `seed_tray`'s
  `biological_position_label` is still seeded now (`'Cells'`) since that is
  pure, harmless display metadata, independent of the enforcement decision.
- `biological_position_label` (nullable string) -- pure UI display hint
  ("Cells", "Holes"); no arithmetic anywhere ever reads it.

Two new platform `carrier_types` rows: `nursery_cultivation_plate`,
`production_cultivation_plate` -- both `requires_specification=true`,
`biological_position_label='Holes'`. The existing generic `cultivation_plate`
row is never renamed, reinterpreted, or backfilled -- historical workflows
that reference it keep meaning exactly what they always meant.

`carriers` gains a nullable `specification_id` FK, tenant-safe via a
composite `ForeignKeyConstraint(["tenant_id", "specification_id"], ...)`
(mirroring `Variety.crop_id -> Crop`'s own established composite-FK
precedent) -- never a bare single-column FK, so tenant isolation is a DB
guarantee, not a frontend-filtering concern (CLAUDE.md rule 2). Legacy
Carrier rows keep `specification_id = NULL` -- never fabricated.
`enforce_carrier_specification_type_consistency` (new trigger on `carriers`)
backstops the service-layer check that `Carrier.carrier_type_id` always
agrees with its own `CarrierSpecification.carrier_type_id` whenever a
specification is referenced.

No InterSalads occupancy-compatibility rows, no Sowing capacity enforcement,
no Transplant destination-capacity enforcement -- all explicitly out of
scope for this ticket (see the ticket's own exclusions).

Revision ID: e5b8c3a72f04
Revises: c8f1d4a92b6e
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e5b8c3a72f04'
down_revision: Union[str, None] = 'c8f1d4a92b6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STRUCTURAL_FREEZE_FUNCTION = """
    CREATE FUNCTION enforce_carrier_specification_structural_freeze() RETURNS trigger AS $$
    DECLARE
        v_referenced BOOLEAN;
    BEGIN
        IF NEW.carrier_type_id IS DISTINCT FROM OLD.carrier_type_id
           OR NEW.code IS DISTINCT FROM OLD.code
           OR NEW.length_mm IS DISTINCT FROM OLD.length_mm
           OR NEW.width_mm IS DISTINCT FROM OLD.width_mm
           OR NEW.height_mm IS DISTINCT FROM OLD.height_mm
           OR NEW.biological_position_count IS DISTINCT FROM OLD.biological_position_count
        THEN
            SELECT EXISTS(SELECT 1 FROM carriers WHERE specification_id = OLD.id) INTO v_referenced;
            IF v_referenced THEN
                RAISE EXCEPTION
                    'carrier_specification structural fields are frozen once a Carrier references it';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """

_TYPE_CONSISTENCY_FUNCTION = """
    CREATE FUNCTION enforce_carrier_specification_type_consistency() RETURNS trigger AS $$
    DECLARE
        v_spec_type_id UUID;
    BEGIN
        IF NEW.specification_id IS NOT NULL THEN
            SELECT carrier_type_id INTO v_spec_type_id
            FROM carrier_specifications WHERE id = NEW.specification_id;
            IF v_spec_type_id IS NULL THEN
                RAISE EXCEPTION 'carrier_specification not found';
            END IF;
            IF v_spec_type_id <> NEW.carrier_type_id THEN
                RAISE EXCEPTION
                    'carrier carrier_type_id does not match its specification''s carrier_type_id';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. carrier_types: platform specification metadata -------------------------
    op.add_column(
        "carrier_types",
        sa.Column("requires_specification", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("carrier_types", sa.Column("biological_position_label", sa.String(), nullable=True))
    op.alter_column("carrier_types", "requires_specification", server_default=None)

    bind.execute(
        sa.text("UPDATE carrier_types SET biological_position_label = 'Cells' WHERE code = 'seed_tray'")
    )

    new_carrier_types = (
        ("nursery_cultivation_plate", "Nursery Cultivation Plate", True, "Holes"),
        ("production_cultivation_plate", "Production Cultivation Plate", True, "Holes"),
    )
    for code, name, requires_specification, label in new_carrier_types:
        bind.execute(
            sa.text(
                "INSERT INTO carrier_types (id, code, name, requires_specification, biological_position_label) "
                "VALUES (gen_random_uuid(), :code, :name, :requires_specification, :label)"
            ),
            {"code": code, "name": name, "requires_specification": requires_specification, "label": label},
        )

    # --- 2. carrier_specifications (new) ---------------------------------------------
    op.create_table(
        "carrier_specifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "carrier_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carrier_types.id"), nullable=False
        ),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("length_mm", sa.Integer(), nullable=True),
        sa.Column("width_mm", sa.Integer(), nullable=True),
        sa.Column("height_mm", sa.Integer(), nullable=True),
        sa.Column("biological_position_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_carrier_specifications_status"),
        sa.CheckConstraint(
            "length_mm IS NULL OR length_mm > 0", name="ck_carrier_specifications_length_positive"
        ),
        sa.CheckConstraint(
            "width_mm IS NULL OR width_mm > 0", name="ck_carrier_specifications_width_positive"
        ),
        sa.CheckConstraint(
            "height_mm IS NULL OR height_mm > 0", name="ck_carrier_specifications_height_positive"
        ),
        sa.CheckConstraint(
            "biological_position_count IS NULL OR biological_position_count > 0",
            name="ck_carrier_specifications_position_count_positive",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_carrier_specifications_tenant_id_id"),
    )
    op.alter_column("carrier_specifications", "status", server_default=None)
    op.create_index(
        "ux_carrier_specifications_tenant_code_lower",
        "carrier_specifications", ["tenant_id", sa.text("lower(code)")], unique=True,
    )

    op.execute(_STRUCTURAL_FREEZE_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER carrier_specifications_enforce_structural_freeze
        BEFORE UPDATE ON carrier_specifications
        FOR EACH ROW EXECUTE FUNCTION enforce_carrier_specification_structural_freeze();
        """
    )

    # --- 3. carriers.specification_id (new, nullable, tenant-safe) -------------------
    op.add_column("carriers", sa.Column("specification_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_carriers_specification", "carriers", "carrier_specifications", ["specification_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_carriers_tenant_specification", "carriers", "carrier_specifications",
        ["tenant_id", "specification_id"], ["tenant_id", "id"],
    )

    op.execute(_TYPE_CONSISTENCY_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER carriers_enforce_specification_type_consistency
        BEFORE INSERT OR UPDATE ON carriers
        FOR EACH ROW EXECUTE FUNCTION enforce_carrier_specification_type_consistency();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # --- section 33: downgrade guards -- never silently drop real tenant
    # configuration or orphan a Carrier's own meaning. -------------------------------
    specification_count = bind.execute(sa.text("SELECT count(*) FROM carrier_specifications")).scalar_one()
    if specification_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CARRIER-CONFIG-001: "
            f"{specification_count} carrier_specifications row(s) exist. Downgrading would drop real "
            "tenant-configured physical Carrier designs. Move/export the affected data out-of-band "
            "before downgrading, or do not downgrade."
        )

    referenced_count = bind.execute(
        sa.text("SELECT count(*) FROM carriers WHERE specification_id IS NOT NULL")
    ).scalar_one()
    if referenced_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CARRIER-CONFIG-001: "
            f"{referenced_count} carriers row(s) reference a specification. Downgrading would orphan "
            "that reference. Move/export the affected data out-of-band before downgrading, or do not "
            "downgrade."
        )

    plate_type_carrier_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM carriers c JOIN carrier_types ct ON ct.id = c.carrier_type_id "
            "WHERE ct.code IN ('nursery_cultivation_plate', 'production_cultivation_plate')"
        )
    ).scalar_one()
    if plate_type_carrier_count > 0:
        raise RuntimeError(
            "Cannot downgrade past CARRIER-CONFIG-001: "
            f"{plate_type_carrier_count} carriers row(s) use nursery_cultivation_plate/"
            "production_cultivation_plate. Dropping those carrier_types would orphan their meaning. "
            "Move/export the affected data out-of-band before downgrading, or do not downgrade."
        )

    op.execute(
        "DROP TRIGGER IF EXISTS carriers_enforce_specification_type_consistency ON carriers"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_carrier_specification_type_consistency()")
    op.drop_constraint("fk_carriers_tenant_specification", "carriers", type_="foreignkey")
    op.drop_constraint("fk_carriers_specification", "carriers", type_="foreignkey")
    op.drop_column("carriers", "specification_id")

    op.execute(
        "DROP TRIGGER IF EXISTS carrier_specifications_enforce_structural_freeze ON carrier_specifications"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_carrier_specification_structural_freeze()")
    op.drop_index("ux_carrier_specifications_tenant_code_lower", table_name="carrier_specifications")
    op.drop_table("carrier_specifications")

    bind.execute(
        sa.text(
            "DELETE FROM carrier_types WHERE code IN "
            "('nursery_cultivation_plate', 'production_cultivation_plate')"
        )
    )
    bind.execute(
        sa.text("UPDATE carrier_types SET biological_position_label = NULL WHERE code = 'seed_tray'")
    )
    op.drop_column("carrier_types", "biological_position_label")
    op.drop_column("carrier_types", "requires_specification")
