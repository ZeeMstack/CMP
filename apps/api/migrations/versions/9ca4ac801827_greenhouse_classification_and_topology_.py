"""greenhouse classification and topology foundation

Revision ID: 9ca4ac801827
Revises: 68215f964ca9
Create Date: 2026-08-14 04:24:31.653503

DOMAIN-FARM-001: narrows `greenhouse_classification` to the three
authoritative values (`nursery`, `leafy_greens`, `vines` -- drops `mixed`
and `other`), makes it immutable once set, and adds classification-scoped
location-type-hierarchy rules so topology validation can tell three
different greenhouse-internal structures apart instead of relying on one
global, classification-agnostic rule table for everything inside any
greenhouse. Adds six new Nursery-specific location types (seedling_area/
_table, intersalads/_table, intervines/_table). Does not touch, remove, or
reinterpret any existing location row, location type, or generic hierarchy
rule -- see the module docstring in `app/services/location_service.py`'s
`_validate_hierarchy` for how the two rule sets (generic vs
classification-scoped) are kept from ever falling back into each other.

Also adds exactly one `occupancy_compatibility_rules` row: `cultivation_plate
-> grow_table`. This is a direct, necessary consequence of the topology
correction, not new occupancy/capacity functionality (section 11 of the
ticket remains respected -- no movement-service logic, index, or trigger
changes): the authoritative Leafy topology now stops at the Table itself
(no `table_position` beneath it -- see section 7), so the Table is the
occupancy target a Production Cultivation Plate carrier must be able to
occupy directly. Without this row, placing a `cultivation_plate` at a
`grow_table` would be rejected by the pre-existing, unchanged compatibility
check in `movement_service._check_compatibility`, breaking the exact
scenarios this ticket's own required tests (and pre-existing occupancy
tests whose fixtures this ticket updates) exercise. `cultivation_plate ->
table_position` remains exactly as seeded before -- untouched, still valid
wherever `table_position` itself is still reachable.

DOMAIN-FARM-001.1: step 7 of `upgrade()` is an existing-topology guard,
added after the original release of this migration. It positively detects
any pre-existing location inside a classified greenhouse whose actual
parent-type -> child-type edge is not legal under the classification-scoped
rules this migration itself just inserted (step 5), and raises loudly
before the migration can complete -- never silently deleting, reparenting,
retyping, or reclassifying anything. Because the whole `upgrade()` body
runs in one Alembic-managed transaction, raising here rolls back every
earlier step (1-6) atomically along with it, leaving the database exactly
at its pre-upgrade revision with all business data untouched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9ca4ac801827'
down_revision: Union[str, None] = '68215f964ca9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (code, name, default_occupiable) -- new Nursery-specific location types.
_NEW_LOCATION_TYPES = (
    ("seedling_area", "Seedling Area", False),
    ("seedling_table", "Seedling Table", True),
    ("intersalads", "InterSalads", False),
    ("intersalads_table", "InterSalads Table", True),
    ("intervines", "InterVines", False),
    ("intervines_table", "InterVines Table", True),
)

# (classification, parent_code | None, child_code) -- the authoritative,
# exact-chain-only topology permitted inside a classified greenhouse. No
# shortcuts: every level shown is mandatory, not optional, for these three
# templates specifically (this is stricter than the pre-existing generic
# rules, which remain unchanged and still govern everything outside a
# classified greenhouse, per DOMAIN-FARM-001 section 4/5).
_CLASSIFICATION_SCOPED_RULES = (
    # Nursery: Seeding Area/Station, Germination Chamber, Seedling Area,
    # InterSalads, InterVines are all direct children of the greenhouse --
    # no generic "area" wrapper. Does not use zone/span. Does not use
    # grow_gutter/grow_bag_position.
    ("nursery", "greenhouse", "seeding_station"),
    ("nursery", "greenhouse", "germination_chamber"),
    ("nursery", "greenhouse", "seedling_area"),
    ("nursery", "greenhouse", "intersalads"),
    ("nursery", "greenhouse", "intervines"),
    ("nursery", "germination_chamber", "chamber_position"),
    ("nursery", "seedling_area", "seedling_table"),
    ("nursery", "intersalads", "intersalads_table"),
    ("nursery", "intervines", "intervines_table"),
    # Leafy Greens: exact greenhouse -> zone -> span -> grow_table chain.
    # Stops at grow_table -- the Production Cultivation Plate is a Carrier,
    # not a Location, so table_position is never a legal continuation here.
    ("leafy_greens", "greenhouse", "zone"),
    ("leafy_greens", "zone", "span"),
    ("leafy_greens", "span", "grow_table"),
    # Vines: exact greenhouse -> zone -> span -> grow_gutter -> grow_bag_position
    # chain. Grow Gutter Side is NOT part of this path -- gutter_side is
    # deliberately absent from this rule set (see the module docstring).
    ("vines", "greenhouse", "zone"),
    ("vines", "zone", "span"),
    ("vines", "span", "grow_gutter"),
    ("vines", "grow_gutter", "grow_bag_position"),
)

_NARROWED_CLASSIFICATIONS = ("nursery", "leafy_greens", "vines")
_LEGACY_CLASSIFICATIONS_TO_REMOVE = ("mixed", "other")


def upgrade() -> None:
    bind = op.get_bind()

    # --- 0. Refuse to narrow the constraint out from under real data -------
    offending = bind.execute(
        sa.text(
            "SELECT id, code, greenhouse_classification FROM locations "
            "WHERE greenhouse_classification = ANY(:legacy) LIMIT 10"
        ),
        {"legacy": list(_LEGACY_CLASSIFICATIONS_TO_REMOVE)},
    ).mappings().all()
    if offending:
        sample = ", ".join(f"{row['code']} ({row['greenhouse_classification']})" for row in offending)
        raise RuntimeError(
            "DOMAIN-FARM-001 cannot narrow greenhouse_classification: existing location rows use "
            f"a value being removed ('mixed'/'other'). Refusing to silently reinterpret business "
            f"data. Offending rows (up to 10): {sample}"
        )

    # --- 1. Narrow the allowed greenhouse_classification values -------------
    op.drop_constraint(
        "ck_locations_greenhouse_classification_allowed", "locations", type_="check"
    )
    op.create_check_constraint(
        "ck_locations_greenhouse_classification_allowed",
        "locations",
        "greenhouse_classification IS NULL OR greenhouse_classification IN "
        "('nursery', 'leafy_greens', 'vines')",
    )

    # --- 2. Immutability: extend the existing trigger function --------------
    # CREATE OR REPLACE keeps the same function identity, so the existing
    # `locations_enforce_greenhouse_classification` trigger (BEFORE INSERT OR
    # UPDATE) picks up the new behavior without needing to be re-created.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_location_greenhouse_classification() RETURNS trigger AS $$
        DECLARE
            type_code TEXT;
        BEGIN
            SELECT code INTO type_code FROM location_types WHERE id = NEW.location_type_id;
            IF type_code = 'greenhouse' THEN
                IF NEW.greenhouse_classification IS NULL THEN
                    RAISE EXCEPTION 'greenhouse locations require a greenhouse_classification';
                END IF;
            ELSE
                IF NEW.greenhouse_classification IS NOT NULL THEN
                    RAISE EXCEPTION 'only greenhouse locations may have a greenhouse_classification';
                END IF;
            END IF;
            IF TG_OP = 'UPDATE' AND NEW.greenhouse_classification IS DISTINCT FROM OLD.greenhouse_classification THEN
                RAISE EXCEPTION 'greenhouse_classification is immutable once set and cannot be changed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # --- 3. New Nursery-specific location types ------------------------------
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

    # --- 4. Classification scoping on location_type_hierarchy_rules ---------
    op.drop_index("ux_location_type_hierarchy_parent_child", table_name="location_type_hierarchy_rules")
    op.drop_index("ux_location_type_hierarchy_root_child", table_name="location_type_hierarchy_rules")
    op.add_column(
        "location_type_hierarchy_rules",
        sa.Column("greenhouse_classification", sa.String(), nullable=True),
    )
    op.create_check_constraint(
        "ck_location_type_hierarchy_rules_classification_allowed",
        "location_type_hierarchy_rules",
        "greenhouse_classification IS NULL OR greenhouse_classification IN "
        "('nursery', 'leafy_greens', 'vines')",
    )
    op.create_check_constraint(
        "ck_location_type_hierarchy_rules_scoped_requires_parent",
        "location_type_hierarchy_rules",
        "greenhouse_classification IS NULL OR parent_type_id IS NOT NULL",
    )
    op.create_index(
        "ux_location_type_hierarchy_generic_parent_child",
        "location_type_hierarchy_rules",
        ["parent_type_id", "child_type_id"],
        unique=True,
        postgresql_where=sa.text("greenhouse_classification IS NULL AND parent_type_id IS NOT NULL"),
    )
    op.create_index(
        "ux_location_type_hierarchy_generic_root_child",
        "location_type_hierarchy_rules",
        ["child_type_id"],
        unique=True,
        postgresql_where=sa.text("greenhouse_classification IS NULL AND parent_type_id IS NULL"),
    )
    op.create_index(
        "ux_location_type_hierarchy_scoped",
        "location_type_hierarchy_rules",
        ["greenhouse_classification", "parent_type_id", "child_type_id"],
        unique=True,
        postgresql_where=sa.text("greenhouse_classification IS NOT NULL"),
    )

    # --- 5. Insert the classification-scoped rules ---------------------------
    for classification, parent_code, child_code in _CLASSIFICATION_SCOPED_RULES:
        bind.execute(
            sa.text(
                "INSERT INTO location_type_hierarchy_rules "
                "(id, parent_type_id, child_type_id, greenhouse_classification) "
                "VALUES (gen_random_uuid(), :parent_id, :child_id, :classification)"
            ),
            {
                "parent_id": type_ids[parent_code],
                "child_id": type_ids[child_code],
                "classification": classification,
            },
        )

    # --- 6. Occupancy compatibility: cultivation_plate may now occupy a
    # grow_table directly (see module docstring) ----------------------------
    cultivation_plate_type_id = bind.execute(
        sa.text("SELECT id FROM carrier_types WHERE code = 'cultivation_plate'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO occupancy_compatibility_rules "
            "(id, occupant_carrier_type_id, target_location_type_id) "
            "VALUES (gen_random_uuid(), :occupant_id, :target_id)"
        ),
        {"occupant_id": cultivation_plate_type_id, "target_id": type_ids["grow_table"]},
    )

    # --- 7. DOMAIN-FARM-001.1: refuse to leave the database in the new
    # authoritative state if any EXISTING location inside a classified
    # greenhouse has a parent-type -> child-type edge that is not legal
    # under the classification-scoped rules just inserted in step 5. This
    # queries the live rows this migration itself just wrote (step 5), not
    # a second, separately-maintained copy of the rule set -- if the
    # scoped catalog above is ever revised, this check automatically stays
    # in sync with it. The walk is a single downward recursive CTE seeded
    # at every `greenhouse` row (self-classification), not a per-row
    # upward walk -- O(tree size), not O(rows x depth). The greenhouse
    # root itself is excluded (`child.parent_location_id IS NOT NULL`):
    # creating a greenhouse is never classification-scoped (nothing to
    # resolve yet), exactly as `location_service._validate_hierarchy`
    # treats it at runtime.
    offending_edges = bind.execute(
        sa.text(
            """
            WITH RECURSIVE greenhouse_subtree AS (
                SELECT l.id AS location_id, l.id AS greenhouse_id, l.greenhouse_classification
                FROM locations l
                JOIN location_types lt ON lt.id = l.location_type_id
                WHERE lt.code = 'greenhouse'
                UNION ALL
                SELECT c.id, gs.greenhouse_id, gs.greenhouse_classification
                FROM locations c
                JOIN greenhouse_subtree gs ON c.parent_location_id = gs.location_id
            )
            SELECT
                child.id AS child_id, child.code AS child_code, clt.code AS child_type_code,
                parent.id AS parent_id, parent.code AS parent_code, plt.code AS parent_type_code,
                gs.greenhouse_classification AS classification,
                gh.id AS greenhouse_id, gh.code AS greenhouse_code
            FROM greenhouse_subtree gs
            JOIN locations child ON child.id = gs.location_id
            JOIN location_types clt ON clt.id = child.location_type_id
            JOIN locations parent ON parent.id = child.parent_location_id
            JOIN location_types plt ON plt.id = parent.location_type_id
            JOIN locations gh ON gh.id = gs.greenhouse_id
            LEFT JOIN location_type_hierarchy_rules rule
                ON rule.greenhouse_classification = gs.greenhouse_classification
                AND rule.parent_type_id = parent.location_type_id
                AND rule.child_type_id = child.location_type_id
            WHERE child.parent_location_id IS NOT NULL
              AND rule.id IS NULL
            ORDER BY gh.code, parent.code, child.code
            LIMIT 20
            """
        )
    ).mappings().all()
    if offending_edges:
        total = bind.execute(
            sa.text(
                """
                WITH RECURSIVE greenhouse_subtree AS (
                    SELECT l.id AS location_id, l.id AS greenhouse_id, l.greenhouse_classification
                    FROM locations l
                    JOIN location_types lt ON lt.id = l.location_type_id
                    WHERE lt.code = 'greenhouse'
                    UNION ALL
                    SELECT c.id, gs.greenhouse_id, gs.greenhouse_classification
                    FROM locations c
                    JOIN greenhouse_subtree gs ON c.parent_location_id = gs.location_id
                )
                SELECT count(*)
                FROM greenhouse_subtree gs
                JOIN locations child ON child.id = gs.location_id
                JOIN locations parent ON parent.id = child.parent_location_id
                LEFT JOIN location_type_hierarchy_rules rule
                    ON rule.greenhouse_classification = gs.greenhouse_classification
                    AND rule.parent_type_id = parent.location_type_id
                    AND rule.child_type_id = child.location_type_id
                WHERE child.parent_location_id IS NOT NULL
                  AND rule.id IS NULL
                """
            )
        ).scalar_one()
        lines = [
            f"  greenhouse {row['greenhouse_code']} ({row['greenhouse_id']}, classification="
            f"{row['classification']!r}): {row['parent_type_code']} {row['parent_code']} "
            f"({row['parent_id']}) -> {row['child_type_code']} {row['child_code']} ({row['child_id']})"
            for row in offending_edges
        ]
        raise RuntimeError(
            "DOMAIN-FARM-001 cannot activate classification-scoped topology: "
            f"{total} existing location edge(s) inside a classified greenhouse are not legal "
            "under the new authoritative rule set. Refusing to silently delete, reparent, "
            f"retype, or reclassify existing business data. Showing up to 20 of {total}:\n"
            + "\n".join(lines)
        )


def downgrade() -> None:
    bind = op.get_bind()

    cultivation_plate_type_id = bind.execute(
        sa.text("SELECT id FROM carrier_types WHERE code = 'cultivation_plate'")
    ).scalar_one()
    grow_table_type_id = bind.execute(
        sa.text("SELECT id FROM location_types WHERE code = 'grow_table'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "DELETE FROM occupancy_compatibility_rules "
            "WHERE occupant_carrier_type_id = :occupant_id AND target_location_type_id = :target_id"
        ),
        {"occupant_id": cultivation_plate_type_id, "target_id": grow_table_type_id},
    )

    bind.execute(
        sa.text(
            "DELETE FROM location_type_hierarchy_rules WHERE greenhouse_classification IS NOT NULL"
        )
    )

    op.drop_index("ux_location_type_hierarchy_scoped", table_name="location_type_hierarchy_rules")
    op.drop_index("ux_location_type_hierarchy_generic_root_child", table_name="location_type_hierarchy_rules")
    op.drop_index("ux_location_type_hierarchy_generic_parent_child", table_name="location_type_hierarchy_rules")
    op.drop_constraint(
        "ck_location_type_hierarchy_rules_scoped_requires_parent",
        "location_type_hierarchy_rules",
        type_="check",
    )
    op.drop_constraint(
        "ck_location_type_hierarchy_rules_classification_allowed",
        "location_type_hierarchy_rules",
        type_="check",
    )
    op.drop_column("location_type_hierarchy_rules", "greenhouse_classification")

    op.create_index(
        "ux_location_type_hierarchy_parent_child",
        "location_type_hierarchy_rules",
        ["parent_type_id", "child_type_id"],
        unique=True,
        postgresql_where=sa.text("parent_type_id IS NOT NULL"),
    )
    op.create_index(
        "ux_location_type_hierarchy_root_child",
        "location_type_hierarchy_rules",
        ["child_type_id"],
        unique=True,
        postgresql_where=sa.text("parent_type_id IS NULL"),
    )

    new_codes = [code for code, _name, _occ in _NEW_LOCATION_TYPES]
    bind.execute(
        sa.text("DELETE FROM location_types WHERE code = ANY(:codes)"), {"codes": new_codes}
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_location_greenhouse_classification() RETURNS trigger AS $$
        DECLARE
            type_code TEXT;
        BEGIN
            SELECT code INTO type_code FROM location_types WHERE id = NEW.location_type_id;
            IF type_code = 'greenhouse' THEN
                IF NEW.greenhouse_classification IS NULL THEN
                    RAISE EXCEPTION 'greenhouse locations require a greenhouse_classification';
                END IF;
            ELSE
                IF NEW.greenhouse_classification IS NOT NULL THEN
                    RAISE EXCEPTION 'only greenhouse locations may have a greenhouse_classification';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.drop_constraint(
        "ck_locations_greenhouse_classification_allowed", "locations", type_="check"
    )
    op.create_check_constraint(
        "ck_locations_greenhouse_classification_allowed",
        "locations",
        "greenhouse_classification IS NULL OR greenhouse_classification IN "
        "('nursery', 'leafy_greens', 'vines', 'mixed', 'other')",
    )
