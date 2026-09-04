import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models.location_type import LocationType
from app.models.location_type_hierarchy_rule import LocationTypeHierarchyRule

EXPECTED_CODES = {
    "greenhouse",
    "area",
    "zone",
    "span",
    "seeding_station",
    "germination_chamber",
    "chamber_position",
    "grow_table",
    "table_position",
    "grow_gutter",
    "gutter_side",
    "grow_bag_position",
    "store",
    "store_bin",
    "packing_hall",
    "cold_store",
    "cold_store_position",
    "dispatch_area",
    # DOMAIN-FARM-001: Nursery-specific types, none of which existed before
    # this ticket (the authoritative Nursery topology does not reuse the
    # generic "area"/"grow_table"/"table_position" types for these sections).
    "seedling_area",
    "seedling_table",
    "intersalads",
    "intersalads_table",
    "intervines",
    "intervines_table",
    # STORE-INV-001B: additive Store-hierarchy types
    # (docs/domain/STORE_INVENTORY_MODEL.md §4) -- both structural/
    # non-occupiable, extending the pre-existing store -> store_bin pair.
    "store_area",
    "store_rack",
}

# The generic (classification-agnostic, greenhouse_classification IS NULL)
# rule set — unchanged from before DOMAIN-FARM-001. These rules still exist
# in the DB (nothing was deleted), but govern only locations OUTSIDE any
# classified greenhouse tree (see APPROVED_SCOPED_PAIRS below for what
# actually governs inside one) — `location_service._validate_hierarchy`
# never falls back to this set once a governing classification is resolved.
APPROVED_PAIRS = {
    (None, "greenhouse"),
    (None, "store"),
    (None, "packing_hall"),
    (None, "cold_store"),
    (None, "dispatch_area"),
    ("greenhouse", "area"),
    ("greenhouse", "zone"),
    ("greenhouse", "span"),
    ("area", "seeding_station"),
    ("area", "germination_chamber"),
    ("area", "grow_table"),
    ("area", "zone"),
    ("area", "span"),
    ("zone", "span"),
    ("zone", "grow_table"),
    ("zone", "grow_gutter"),
    ("span", "grow_table"),
    ("span", "grow_gutter"),
    ("germination_chamber", "chamber_position"),
    ("grow_table", "table_position"),
    ("grow_gutter", "gutter_side"),
    ("grow_gutter", "grow_bag_position"),
    ("gutter_side", "grow_bag_position"),
    ("store", "store_bin"),
    ("cold_store", "cold_store_position"),
    # STORE-INV-001B: additive -- the pre-existing (store, store_bin) row
    # above is unchanged; these five extend it into the four frozen Store
    # hierarchy patterns (docs/domain/STORE_INVENTORY_MODEL.md §4).
    ("store", "store_area"),
    ("store", "store_rack"),
    ("store_area", "store_rack"),
    ("store_area", "store_bin"),
    ("store_rack", "store_bin"),
}

# DOMAIN-FARM-001: the authoritative, classification-scoped topology — the
# ONLY rules consulted once a candidate location resolves to inside a
# classified greenhouse tree. (classification, parent_code, child_code).
APPROVED_SCOPED_TRIPLES = {
    ("nursery", "greenhouse", "seeding_station"),
    ("nursery", "greenhouse", "germination_chamber"),
    ("nursery", "greenhouse", "seedling_area"),
    ("nursery", "greenhouse", "intersalads"),
    ("nursery", "greenhouse", "intervines"),
    # NURSERY-OPS-002A: retired from the authoritative Nursery Germination
    # topology -- a Germination Trolley occupies the Chamber directly (no
    # chamber_position). The generic (unscoped) rule below is untouched.
    ("nursery", "seedling_area", "seedling_table"),
    ("nursery", "intersalads", "intersalads_table"),
    ("nursery", "intervines", "intervines_table"),
    ("leafy_greens", "greenhouse", "zone"),
    ("leafy_greens", "zone", "span"),
    ("leafy_greens", "span", "grow_table"),
    ("vines", "greenhouse", "zone"),
    ("vines", "zone", "span"),
    ("vines", "span", "grow_gutter"),
    ("vines", "grow_gutter", "grow_bag_position"),
}


@pytest.mark.integration
def test_system_location_types_seeded_correctly(db_session) -> None:
    codes = {t.code for t in db_session.execute(select(LocationType)).scalars()}
    assert codes == EXPECTED_CODES


@pytest.mark.integration
def test_all_approved_hierarchy_pairs_are_seeded(db_session) -> None:
    """The original 25 generic (classification-agnostic) pairs are
    unmodified by DOMAIN-FARM-001 -- nothing was deleted or rewritten,
    only new classification-scoped rows were added alongside them."""
    rows = db_session.execute(
        text(
            "SELECT p.code AS parent_code, c.code AS child_code "
            "FROM location_type_hierarchy_rules r "
            "LEFT JOIN location_types p ON p.id = r.parent_type_id "
            "JOIN location_types c ON c.id = r.child_type_id "
            "WHERE r.greenhouse_classification IS NULL"
        )
    ).mappings().all()
    pairs = {(row["parent_code"], row["child_code"]) for row in rows}
    assert pairs == APPROVED_PAIRS


@pytest.mark.integration
def test_all_approved_classification_scoped_triples_are_seeded(db_session) -> None:
    rows = db_session.execute(
        text(
            "SELECT r.greenhouse_classification AS classification, p.code AS parent_code, c.code AS child_code "
            "FROM location_type_hierarchy_rules r "
            "JOIN location_types p ON p.id = r.parent_type_id "
            "JOIN location_types c ON c.id = r.child_type_id "
            "WHERE r.greenhouse_classification IS NOT NULL"
        )
    ).mappings().all()
    triples = {(row["classification"], row["parent_code"], row["child_code"]) for row in rows}
    assert triples == APPROVED_SCOPED_TRIPLES


@pytest.mark.integration
def test_duplicate_farm_root_hierarchy_rule_rejected(db_session) -> None:
    greenhouse = db_session.execute(
        select(LocationType).where(LocationType.code == "greenhouse")
    ).scalar_one()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO location_type_hierarchy_rules (id, parent_type_id, child_type_id) "
                    "VALUES (:id, NULL, :child_id)"
                ),
                {"id": uuid.uuid4(), "child_id": greenhouse.id},
            )


@pytest.mark.integration
def test_duplicate_non_root_hierarchy_rule_rejected(db_session) -> None:
    greenhouse = db_session.execute(
        select(LocationType).where(LocationType.code == "greenhouse")
    ).scalar_one()
    area = db_session.execute(select(LocationType).where(LocationType.code == "area")).scalar_one()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO location_type_hierarchy_rules (id, parent_type_id, child_type_id) "
                    "VALUES (:id, :parent_id, :child_id)"
                ),
                {"id": uuid.uuid4(), "parent_id": greenhouse.id, "child_id": area.id},
            )
