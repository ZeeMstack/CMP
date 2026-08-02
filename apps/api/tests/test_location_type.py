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
}

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
}


@pytest.mark.integration
def test_system_location_types_seeded_correctly(db_session) -> None:
    codes = {t.code for t in db_session.execute(select(LocationType)).scalars()}
    assert codes == EXPECTED_CODES


@pytest.mark.integration
def test_all_approved_hierarchy_pairs_are_seeded(db_session) -> None:
    rows = db_session.execute(
        text(
            "SELECT p.code AS parent_code, c.code AS child_code "
            "FROM location_type_hierarchy_rules r "
            "LEFT JOIN location_types p ON p.id = r.parent_type_id "
            "JOIN location_types c ON c.id = r.child_type_id"
        )
    ).mappings().all()
    pairs = {(row["parent_code"], row["child_code"]) for row in rows}
    assert pairs == APPROVED_PAIRS


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
