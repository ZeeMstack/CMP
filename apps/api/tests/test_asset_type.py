import pytest
from sqlalchemy import select

from app.models.asset_type import AssetType

EXPECTED_TYPES = {
    "germination_trolley": True,
    "transfer_trolley": False,
    "seeding_machine": False,
    "weighing_scale": False,
    "label_printer": False,
}


@pytest.mark.integration
def test_system_asset_types_seeded_correctly(db_session) -> None:
    rows = db_session.execute(select(AssetType)).scalars().all()
    seeded = {t.code: t.supports_positions for t in rows}
    assert seeded == EXPECTED_TYPES


@pytest.mark.integration
def test_only_germination_trolley_supports_positions(db_session) -> None:
    trolley = db_session.execute(
        select(AssetType).where(AssetType.code == "germination_trolley")
    ).scalar_one()
    assert trolley.supports_positions is True
