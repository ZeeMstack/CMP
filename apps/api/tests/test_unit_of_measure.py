"""STORE-INV-001B: UnitOfMeasure/UomConversion seed-data and
conversion-family enforcement tests."""
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models.unit_of_measure import UnitOfMeasure
from app.models.uom_conversion import UomConversion
from app.services import unit_of_measure_service
from app.services.errors import UnitOfMeasureNotFoundError


def _uom(db_session, code: str) -> UnitOfMeasure:
    return db_session.execute(select(UnitOfMeasure).where(UnitOfMeasure.code == code)).scalar_one()


@pytest.mark.integration
def test_exact_seeded_codes(db_session) -> None:
    codes = {u.code for u in unit_of_measure_service.list_uoms(db_session)}
    assert codes == {"kg", "g", "L", "mL", "EA", "SEED"}


@pytest.mark.integration
def test_codes_are_case_sensitive_not_uppercased(db_session) -> None:
    kg = _uom(db_session, "kg")
    assert kg.code == "kg"
    ml = _uom(db_session, "mL")
    assert ml.code == "mL"
    # "KG" was never seeded -- only the lowercase canonical symbol was.
    uppercased = db_session.execute(
        select(UnitOfMeasure).where(UnitOfMeasure.code == "KG")
    ).scalar_one_or_none()
    assert uppercased is None


@pytest.mark.integration
def test_quantity_kind_and_conversion_family_seeded_correctly(db_session) -> None:
    kg = _uom(db_session, "kg")
    assert kg.quantity_kind == "mass"
    assert kg.conversion_family == "MASS"
    L = _uom(db_session, "L")
    assert L.quantity_kind == "volume"
    assert L.conversion_family == "VOLUME"
    ea = _uom(db_session, "EA")
    assert ea.quantity_kind == "count"
    assert ea.conversion_family is None
    seed = _uom(db_session, "SEED")
    assert seed.quantity_kind == "count"
    assert seed.conversion_family is None


@pytest.mark.integration
def test_exact_seeded_conversions(db_session) -> None:
    g_to_kg = db_session.execute(
        select(UomConversion).where(
            UomConversion.from_uom_id == _uom(db_session, "g").id,
            UomConversion.to_uom_id == _uom(db_session, "kg").id,
        )
    ).scalar_one()
    assert float(g_to_kg.multiply_factor) == pytest.approx(0.001)

    ml_to_l = db_session.execute(
        select(UomConversion).where(
            UomConversion.from_uom_id == _uom(db_session, "mL").id,
            UomConversion.to_uom_id == _uom(db_session, "L").id,
        )
    ).scalar_one()
    assert float(ml_to_l.multiply_factor) == pytest.approx(0.001)


@pytest.mark.integration
def test_no_inverse_or_self_or_ea_seed_rows(db_session) -> None:
    all_conversions = list(db_session.execute(select(UomConversion)).scalars())
    assert len(all_conversions) == 2
    kg_id, g_id = _uom(db_session, "kg").id, _uom(db_session, "g").id
    ea_id, seed_id = _uom(db_session, "EA").id, _uom(db_session, "SEED").id
    pairs = {(c.from_uom_id, c.to_uom_id) for c in all_conversions}
    assert (kg_id, g_id) not in pairs
    assert (ea_id, seed_id) not in pairs
    assert (seed_id, ea_id) not in pairs


@pytest.mark.integration
def test_cross_family_conversion_rejected_at_db_level(db_session) -> None:
    ea_id = _uom(db_session, "EA").id
    seed_id = _uom(db_session, "SEED").id
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO uom_conversions (id, from_uom_id, to_uom_id, multiply_factor) "
                    "VALUES (:id, :from_id, :to_id, 1)"
                ),
                {"id": uuid.uuid4(), "from_id": ea_id, "to_id": seed_id},
            )


@pytest.mark.integration
def test_null_family_conversion_rejected_at_db_level(db_session) -> None:
    """EA (conversion_family NULL) -> kg (MASS) must be rejected even
    though this isn't a same-quantity_kind case at all -- the trigger
    checks conversion_family, never quantity_kind."""
    ea_id = _uom(db_session, "EA").id
    kg_id = _uom(db_session, "kg").id
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO uom_conversions (id, from_uom_id, to_uom_id, multiply_factor) "
                    "VALUES (:id, :from_id, :to_id, 1)"
                ),
                {"id": uuid.uuid4(), "from_id": ea_id, "to_id": kg_id},
            )


@pytest.mark.integration
def test_reverse_pair_conversion_rejected_at_db_level(db_session) -> None:
    """Only one canonical direction is ever stored -- g -> kg is seeded, so
    the reverse (kg -> g) must be rejected even though it independently
    satisfies every other rule (same family, factor > 0, not self)."""
    g_id = _uom(db_session, "g").id
    kg_id = _uom(db_session, "kg").id
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO uom_conversions (id, from_uom_id, to_uom_id, multiply_factor) "
                    "VALUES (:id, :from_id, :to_id, 1000)"
                ),
                {"id": uuid.uuid4(), "from_id": kg_id, "to_id": g_id},
            )


@pytest.mark.integration
def test_reverse_pair_conversion_rejected_for_ml_l(db_session) -> None:
    ml_id = _uom(db_session, "mL").id
    l_id = _uom(db_session, "L").id
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO uom_conversions (id, from_uom_id, to_uom_id, multiply_factor) "
                    "VALUES (:id, :from_id, :to_id, 1000)"
                ),
                {"id": uuid.uuid4(), "from_id": l_id, "to_id": ml_id},
            )


@pytest.mark.integration
def test_self_conversion_rejected_at_db_level(db_session) -> None:
    kg_id = _uom(db_session, "kg").id
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO uom_conversions (id, from_uom_id, to_uom_id, multiply_factor) "
                    "VALUES (:id, :from_id, :from_id, 1)"
                ),
                {"id": uuid.uuid4(), "from_id": kg_id},
            )


@pytest.mark.integration
def test_get_uom_not_found(db_session) -> None:
    with pytest.raises(UnitOfMeasureNotFoundError):
        unit_of_measure_service.get_uom(db_session, uom_id=uuid.uuid4())
