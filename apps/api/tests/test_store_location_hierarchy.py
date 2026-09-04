"""STORE-INV-001B: additive store_area/store_rack location types and the
five new hierarchy rules -- proves all four frozen patterns
(docs/domain/STORE_INVENTORY_MODEL.md §4) validate through the existing,
unmodified generic Location engine, and that the pre-existing
store -> store_bin pair is untouched."""
import uuid

import pytest

from app.services import farm_service, location_service
from app.services.errors import InvalidLocationHierarchyError


def _farm(db_session, tenant, user, *, code):
    return farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=code, name="Store Test Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )


def _create(db_session, tenant, farm, *, location_type_code, code, parent_location_id=None):
    return location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=None,
        location_type_code=location_type_code, code=code, name=code, parent_location_id=parent_location_id,
        greenhouse_classification=None, occupiable=None,
    )


@pytest.mark.integration
def test_store_direct_to_bin_unchanged(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    farm = _farm(db_session, tenant, user, code=f"sf-{uuid.uuid4().hex[:8]}")
    store = _create(db_session, tenant, farm, location_type_code="store", code="MAIN-STORE")
    bin_ = _create(
        db_session, tenant, farm, location_type_code="store_bin", code="BIN-001", parent_location_id=store.id
    )
    assert bin_.parent_location_id == store.id


@pytest.mark.integration
def test_store_area_to_bin(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    farm = _farm(db_session, tenant, user, code=f"sf-{uuid.uuid4().hex[:8]}")
    store = _create(db_session, tenant, farm, location_type_code="store", code="STORE-A")
    area = _create(
        db_session, tenant, farm, location_type_code="store_area", code="SEED-AREA", parent_location_id=store.id
    )
    bin_ = _create(
        db_session, tenant, farm, location_type_code="store_bin", code="BIN-001", parent_location_id=area.id
    )
    assert area.parent_location_id == store.id
    assert bin_.parent_location_id == area.id
    assert area.occupiable is False


@pytest.mark.integration
def test_store_rack_to_bin(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    farm = _farm(db_session, tenant, user, code=f"sf-{uuid.uuid4().hex[:8]}")
    store = _create(db_session, tenant, farm, location_type_code="store", code="STORE-B")
    rack = _create(
        db_session, tenant, farm, location_type_code="store_rack", code="RACK-01", parent_location_id=store.id
    )
    bin_ = _create(
        db_session, tenant, farm, location_type_code="store_bin", code="BIN-001", parent_location_id=rack.id
    )
    assert rack.parent_location_id == store.id
    assert bin_.parent_location_id == rack.id
    assert rack.occupiable is False


@pytest.mark.integration
def test_store_area_rack_bin_full_chain(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    farm = _farm(db_session, tenant, user, code=f"sf-{uuid.uuid4().hex[:8]}")
    store = _create(db_session, tenant, farm, location_type_code="store", code="STORE-C")
    area = _create(
        db_session, tenant, farm, location_type_code="store_area", code="SEED-AREA", parent_location_id=store.id
    )
    rack = _create(
        db_session, tenant, farm, location_type_code="store_rack", code="RACK-01", parent_location_id=area.id
    )
    bin_ = _create(
        db_session, tenant, farm, location_type_code="store_bin", code="BIN-001", parent_location_id=rack.id
    )
    assert bin_.parent_location_id == rack.id
    assert bin_.occupiable is True


@pytest.mark.integration
def test_multiple_root_stores_per_farm(db_session, active_context) -> None:
    tenant, user, _headers = active_context
    farm = _farm(db_session, tenant, user, code=f"sf-{uuid.uuid4().hex[:8]}")
    main_store = _create(db_session, tenant, farm, location_type_code="store", code="MAIN")
    chemical_store = _create(db_session, tenant, farm, location_type_code="store", code="CHEMICAL")
    assert main_store.id != chemical_store.id
    assert main_store.parent_location_id is None
    assert chemical_store.parent_location_id is None


@pytest.mark.integration
def test_store_shelf_is_not_a_real_type(db_session, active_context) -> None:
    """docs/domain/STORE_INVENTORY_MODEL.md §4: no store_shelf type is
    introduced -- rack -> bin is the deepest granularity."""
    from app.services.errors import LocationTypeNotFoundError

    tenant, user, _headers = active_context
    farm = _farm(db_session, tenant, user, code=f"sf-{uuid.uuid4().hex[:8]}")
    store = _create(db_session, tenant, farm, location_type_code="store", code="STORE-D")
    with pytest.raises(LocationTypeNotFoundError):
        _create(
            db_session, tenant, farm, location_type_code="store_shelf", code="SHELF-01",
            parent_location_id=store.id,
        )


@pytest.mark.integration
def test_greenhouse_cannot_hold_store_area(db_session, active_context) -> None:
    """A greenhouse tree must never accept Store-hierarchy types -- proves
    the classification-scoped/generic rule split is unaffected."""
    tenant, user, _headers = active_context
    farm = _farm(db_session, tenant, user, code=f"sf-{uuid.uuid4().hex[:8]}")
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=None, location_type_code="greenhouse",
        code="GH-01", name="GH-01", parent_location_id=None, greenhouse_classification="leafy_greens",
        occupiable=None,
    )
    with pytest.raises(InvalidLocationHierarchyError):
        _create(
            db_session, tenant, farm, location_type_code="store_area", code="INVALID-AREA",
            parent_location_id=greenhouse.id,
        )
