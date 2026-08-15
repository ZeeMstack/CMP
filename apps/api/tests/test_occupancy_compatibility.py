import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models.asset_type import AssetType
from app.models.carrier_type import CarrierType
from app.models.location_type import LocationType
from app.models.occupancy_compatibility_rule import OccupancyCompatibilityRule

EXPECTED_RULES = {
    # NURSERY-OPS-002A: the Germination Trolley occupies the Germination
    # Chamber Location directly -- chamber_position is retired from the
    # authoritative Nursery Germination topology.
    ("asset", "germination_trolley", "location", "germination_chamber"),
    ("carrier", "seed_tray", "position", "slot"),
    ("carrier", "cultivation_plate", "location", "table_position"),
    ("carrier", "grow_cube", "location", "table_position"),
    ("carrier", "grow_bag", "location", "grow_bag_position"),
    # DOMAIN-FARM-001: the authoritative Leafy topology stops at grow_table
    # itself (no table_position beneath it) -- the Production Cultivation
    # Plate carrier must be able to occupy the table directly.
    ("carrier", "cultivation_plate", "location", "grow_table"),
}


@pytest.mark.integration
def test_seeded_compatibility_rules_match_approved_set(db_session) -> None:
    rows = db_session.execute(
        text(
            "SELECT at.code AS asset_code, ct.code AS carrier_code, "
            "lt.code AS location_code, r.target_position_kind AS position_kind "
            "FROM occupancy_compatibility_rules r "
            "LEFT JOIN asset_types at ON at.id = r.occupant_asset_type_id "
            "LEFT JOIN carrier_types ct ON ct.id = r.occupant_carrier_type_id "
            "LEFT JOIN location_types lt ON lt.id = r.target_location_type_id"
        )
    ).mappings().all()
    actual = set()
    for row in rows:
        occupant_kind = "asset" if row["asset_code"] else "carrier"
        occupant_code = row["asset_code"] or row["carrier_code"]
        if row["location_code"]:
            actual.add((occupant_kind, occupant_code, "location", row["location_code"]))
        else:
            actual.add((occupant_kind, occupant_code, "position", row["position_kind"]))
    assert actual == EXPECTED_RULES


@pytest.mark.integration
def test_duplicate_asset_location_rule_rejected(db_session) -> None:
    trolley_type = db_session.execute(
        select(AssetType).where(AssetType.code == "germination_trolley")
    ).scalar_one()
    chamber_type = db_session.execute(
        select(LocationType).where(LocationType.code == "germination_chamber")
    ).scalar_one()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO occupancy_compatibility_rules (id, occupant_asset_type_id, target_location_type_id) "
                    "VALUES (:id, :asset_type_id, :location_type_id)"
                ),
                {"id": uuid.uuid4(), "asset_type_id": trolley_type.id, "location_type_id": chamber_type.id},
            )


@pytest.mark.integration
def test_duplicate_asset_position_rule_rejected(db_session) -> None:
    trolley_type = db_session.execute(
        select(AssetType).where(AssetType.code == "germination_trolley")
    ).scalar_one()
    db_session.execute(
        text(
            "INSERT INTO occupancy_compatibility_rules (id, occupant_asset_type_id, target_position_kind) "
            "VALUES (:id, :asset_type_id, 'slot')"
        ),
        {"id": uuid.uuid4(), "asset_type_id": trolley_type.id},
    )
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO occupancy_compatibility_rules (id, occupant_asset_type_id, target_position_kind) "
                    "VALUES (:id, :asset_type_id, 'slot')"
                ),
                {"id": uuid.uuid4(), "asset_type_id": trolley_type.id},
            )


@pytest.mark.integration
def test_duplicate_carrier_location_rule_rejected(db_session) -> None:
    plate_type = db_session.execute(
        select(CarrierType).where(CarrierType.code == "cultivation_plate")
    ).scalar_one()
    table_position_type = db_session.execute(
        select(LocationType).where(LocationType.code == "table_position")
    ).scalar_one()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO occupancy_compatibility_rules (id, occupant_carrier_type_id, target_location_type_id) "
                    "VALUES (:id, :carrier_type_id, :location_type_id)"
                ),
                {"id": uuid.uuid4(), "carrier_type_id": plate_type.id, "location_type_id": table_position_type.id},
            )


@pytest.mark.integration
def test_duplicate_carrier_position_rule_rejected(db_session) -> None:
    tray_type = db_session.execute(select(CarrierType).where(CarrierType.code == "seed_tray")).scalar_one()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO occupancy_compatibility_rules (id, occupant_carrier_type_id, target_position_kind) "
                    "VALUES (:id, :carrier_type_id, 'slot')"
                ),
                {"id": uuid.uuid4(), "carrier_type_id": tray_type.id},
            )
