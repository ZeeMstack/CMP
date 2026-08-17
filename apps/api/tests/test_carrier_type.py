import pytest
from sqlalchemy import select

from app.models.carrier_type import CarrierType

EXPECTED_CODES = {
    "seed_tray",
    "cultivation_plate",
    "grow_cube",
    "grow_bag",
    "harvest_crate",
    # CARRIER-CONFIG-001: two new platform, role-specific Plate types --
    # the legacy generic "cultivation_plate" above is preserved unchanged,
    # never renamed/reinterpreted/backfilled.
    "nursery_cultivation_plate",
    "production_cultivation_plate",
}

# CARRIER-CONFIG-001: requires_specification=True only for seed_tray's own
# label metadata plus the two new role-specific Plate types -- every
# pre-existing type (including seed_tray itself) deliberately stays
# requires_specification=False, see the ticket's own final report.
EXPECTED_REQUIRES_SPECIFICATION = {"nursery_cultivation_plate", "production_cultivation_plate"}
EXPECTED_BIOLOGICAL_POSITION_LABELS = {
    "seed_tray": "Cells",
    "nursery_cultivation_plate": "Holes",
    "production_cultivation_plate": "Holes",
}


@pytest.mark.integration
def test_system_carrier_types_seeded_correctly(db_session) -> None:
    codes = {t.code for t in db_session.execute(select(CarrierType)).scalars()}
    assert codes == EXPECTED_CODES


@pytest.mark.integration
def test_carrier_type_specification_metadata_seeded_correctly(db_session) -> None:
    rows = {t.code: t for t in db_session.execute(select(CarrierType)).scalars()}
    for code, carrier_type in rows.items():
        assert carrier_type.requires_specification == (code in EXPECTED_REQUIRES_SPECIFICATION), code
        assert carrier_type.biological_position_label == EXPECTED_BIOLOGICAL_POSITION_LABELS.get(code), code
