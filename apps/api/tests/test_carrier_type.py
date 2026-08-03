import pytest
from sqlalchemy import select

from app.models.carrier_type import CarrierType

EXPECTED_CODES = {
    "seed_tray",
    "cultivation_plate",
    "grow_cube",
    "grow_bag",
    "harvest_crate",
}


@pytest.mark.integration
def test_system_carrier_types_seeded_correctly(db_session) -> None:
    codes = {t.code for t in db_session.execute(select(CarrierType)).scalars()}
    assert codes == EXPECTED_CODES
