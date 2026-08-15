import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.schemas.location import LocationCreate
from app.services import farm_service, location_service, tenant_service
from app.services.errors import (
    DuplicateLocationCodeError,
    FarmNotFoundError,
    InactiveParentLocationError,
    InvalidLocationHierarchyError,
    LocationNotFoundError,
)

# --- Application-level (Pydantic) validation — no DB required ---


def test_location_code_trimmed_and_uppercased() -> None:
    payload = LocationCreate(location_type_code="area", code="  a-01  ", name="Area 1")
    assert payload.code == "A-01"


def test_greenhouse_without_classification_rejected_by_schema() -> None:
    with pytest.raises(ValueError):
        LocationCreate(location_type_code="greenhouse", code="GH-01", name="Greenhouse 1")


def test_classification_on_non_greenhouse_rejected_by_schema() -> None:
    with pytest.raises(ValueError):
        LocationCreate(
            location_type_code="area", code="A-01", name="Area 1", greenhouse_classification="nursery"
        )


# --- Integration (DB) ---


def _create(db_session, tenant, farm, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id,
        farm_id=farm.id,
        actor_user_id=user.id,
        parent_location_id=None,
        greenhouse_classification=None,
        occupiable=None,
    )
    defaults.update(overrides)
    return location_service.create_location(db_session, **defaults)


@pytest.mark.integration
def test_nursery_greenhouse_creation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    greenhouse = _create(
        db_session,
        tenant,
        farm,
        user,
        location_type_code="greenhouse",
        code="nursery-gh",
        name="Nursery Greenhouse",
        greenhouse_classification="nursery",
    )
    assert greenhouse.code == "nursery-gh"
    assert greenhouse.greenhouse_classification == "nursery"
    assert greenhouse.parent_location_id is None


@pytest.mark.integration
def test_germination_chamber_creation(db_session, active_context_with_farm) -> None:
    """DOMAIN-FARM-001: the germination chamber is a direct child of the
    nursery greenhouse -- no generic "area" wrapper (that shape belonged to
    the pre-correction generic hierarchy rules, not the authoritative
    Nursery topology)."""
    tenant, user, _headers, farm = active_context_with_farm
    greenhouse = _create(
        db_session,
        tenant,
        farm,
        user,
        location_type_code="greenhouse",
        code="nursery-gh",
        name="Nursery Greenhouse",
        greenhouse_classification="nursery",
    )
    chamber = _create(
        db_session,
        tenant,
        farm,
        user,
        location_type_code="germination_chamber",
        code="GC-01",
        name="Germination Chamber GC-01",
        parent_location_id=greenhouse.id,
    )
    assert chamber.parent_location_id == greenhouse.id


@pytest.mark.integration
def test_case_insensitive_sibling_code_uniqueness(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    greenhouse = _create(
        db_session,
        tenant,
        farm,
        user,
        location_type_code="greenhouse",
        code="gh-1",
        name="GH",
        greenhouse_classification="nursery",
    )
    _create(db_session, tenant, farm, user, location_type_code="germination_chamber", code="chamber-1", name="Chamber", parent_location_id=greenhouse.id)
    with pytest.raises(DuplicateLocationCodeError):
        _create(
            db_session, tenant, farm, user, location_type_code="germination_chamber", code="CHAMBER-1", name="Dup",
            parent_location_id=greenhouse.id,
        )


@pytest.mark.integration
def test_same_code_allowed_under_different_parents(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh_a = _create(db_session, tenant, farm, user, location_type_code="greenhouse", code="gh-a", name="A", greenhouse_classification="nursery")
    gh_b = _create(db_session, tenant, farm, user, location_type_code="greenhouse", code="gh-b", name="B", greenhouse_classification="nursery")
    chamber_a = _create(db_session, tenant, farm, user, location_type_code="germination_chamber", code="CHAMBER-1", name="Chamber A", parent_location_id=gh_a.id)
    chamber_b = _create(db_session, tenant, farm, user, location_type_code="germination_chamber", code="CHAMBER-1", name="Chamber B", parent_location_id=gh_b.id)
    assert chamber_a.code == chamber_b.code
    assert chamber_a.parent_location_id != chamber_b.parent_location_id


@pytest.mark.integration
def test_invalid_parent_child_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    greenhouse = _create(db_session, tenant, farm, user, location_type_code="greenhouse", code="gh-1", name="GH", greenhouse_classification="nursery")
    with pytest.raises(InvalidLocationHierarchyError):
        _create(
            db_session, tenant, farm, user, location_type_code="chamber_position", code="P01", name="Pos",
            parent_location_id=greenhouse.id,
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "parent_type_code,parent_code,child_type_code",
    [
        ("greenhouse", "gh-1", "chamber_position"),
        ("store", "store-1", "area"),
        ("store_bin", "sb-1", "table_position"),
    ],
)
def test_representative_invalid_parent_child_pairs_rejected(
    db_session, active_context_with_farm, parent_type_code, parent_code, child_type_code
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    kwargs = dict(location_type_code=parent_type_code, code=parent_code, name="Parent")
    if parent_type_code == "greenhouse":
        kwargs["greenhouse_classification"] = "nursery"
    elif parent_type_code == "store_bin":
        # NURSERY-OPS-002A retired germination_chamber -> chamber_position
        # from the authoritative Nursery topology, and every Greenhouse now
        # requires a classification (DB-enforced) -- classified greenhouses
        # never fall back to the generic hierarchy rules, so chamber_position
        # (whose only remaining parent, germination_chamber, is unreachable
        # both via any classified Greenhouse and via the generic "area" path)
        # has no legitimate parent left at all. store_bin (fully generic, no
        # greenhouse involved) is an equally valid "some occupiable leaf
        # rejects an arbitrary child" example.
        store = _create(db_session, tenant, farm, user, location_type_code="store", code="store-sb", name="Store")
        kwargs["parent_location_id"] = store.id
    parent = _create(db_session, tenant, farm, user, **kwargs)
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code=child_type_code, code="child-1", name="Child", parent_location_id=parent.id)


@pytest.mark.integration
def test_cross_tenant_parent_rejected(db_session, active_context_with_farm) -> None:
    # The request's own (tenant, farm) must be valid and accessible — the
    # isolation being tested is a *parent_location_id* pointing at a location
    # that belongs to an entirely different tenant/farm, not an inaccessible
    # farm (that's a different, already-covered case: FarmNotFoundError).
    tenant, user, _headers, farm = active_context_with_farm
    other_tenant = tenant_service.create_tenant(db_session, code="other-tenant", name="Other")
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_greenhouse = location_service.create_location(
        db_session,
        tenant_id=other_tenant.id,
        farm_id=other_farm.id,
        actor_user_id=None,
        location_type_code="greenhouse",
        code="gh-other",
        name="Other GH",
        parent_location_id=None,
        greenhouse_classification="nursery",
        occupiable=None,
    )
    with pytest.raises(LocationNotFoundError):
        location_service.create_location(
            db_session,
            tenant_id=tenant.id,
            farm_id=farm.id,
            actor_user_id=user.id,
            location_type_code="area",
            code="area-1",
            name="Area",
            parent_location_id=other_greenhouse.id,
            greenhouse_classification=None,
            occupiable=None,
        )


@pytest.mark.integration
def test_cross_farm_parent_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    greenhouse = _create(db_session, tenant, farm, user, location_type_code="greenhouse", code="gh-1", name="GH", greenhouse_classification="nursery")
    with pytest.raises(LocationNotFoundError):
        location_service.create_location(
            db_session,
            tenant_id=tenant.id,
            farm_id=other_farm.id,
            actor_user_id=user.id,
            location_type_code="area",
            code="area-1",
            name="Area",
            parent_location_id=greenhouse.id,
            greenhouse_classification=None,
            occupiable=None,
        )


@pytest.mark.integration
def test_inactive_parent_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    greenhouse = _create(db_session, tenant, farm, user, location_type_code="greenhouse", code="gh-1", name="GH", greenhouse_classification="nursery")
    # Update via the ORM (not raw SQL) so the identity-map copy of `greenhouse`
    # reflects the change immediately, rather than staying stale in memory.
    greenhouse.status = "inactive"
    db_session.flush()
    with pytest.raises(InactiveParentLocationError):
        _create(db_session, tenant, farm, user, location_type_code="area", code="area-1", name="Area", parent_location_id=greenhouse.id)


@pytest.mark.integration
def test_required_active_membership_for_location_routes(client, db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="no-mem-tenant", name="No Membership")
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="farm-1", name="Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    from app.services import user_service

    user = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="no-mem", email="nm@example.com", display_name="NM"
    )
    response = client.get(
        f"/farms/{farm.id}/locations/tree",
        headers={"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)},
    )
    # AUTH-001D: valid dev identity, no active membership -- a tenant-access
    # failure, 403 (previously 401; aligned with the real bearer path).
    assert response.status_code == 403


@pytest.mark.integration
def test_direct_sql_violating_classification_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    from sqlalchemy import select

    from app.models.location_type import LocationType

    area_type = db_session.execute(select(LocationType).where(LocationType.code == "area")).scalar_one()
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO locations (id, tenant_id, farm_id, location_type_id, code, name, "
                    "status, greenhouse_classification, occupiable) "
                    "VALUES (:id, :tenant_id, :farm_id, :type_id, 'BAD', 'Bad', 'active', 'nursery', false)"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant.id,
                    "farm_id": farm.id,
                    "type_id": area_type.id,
                },
            )


@pytest.mark.integration
def test_greenhouse_type_missing_classification_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    from sqlalchemy import select

    from app.models.location_type import LocationType

    gh_type = db_session.execute(select(LocationType).where(LocationType.code == "greenhouse")).scalar_one()
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO locations (id, tenant_id, farm_id, location_type_id, code, name, "
                    "status, greenhouse_classification, occupiable) "
                    "VALUES (:id, :tenant_id, :farm_id, :type_id, 'BAD', 'Bad', 'active', NULL, false)"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant.id,
                    "farm_id": farm.id,
                    "type_id": gh_type.id,
                },
            )
