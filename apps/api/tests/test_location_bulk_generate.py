import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.location import Location
from app.schemas.location import MAX_BULK_CHILDREN, LocationBulkChildrenCreate
from app.services import location_service
from app.services.errors import DuplicateLocationCodeError

# --- Application-level (Pydantic) validation — no DB required ---


def test_bulk_generation_above_max_rejected_before_database_writes() -> None:
    with pytest.raises(ValueError):
        LocationBulkChildrenCreate(
            location_type_code="chamber_position",
            code_prefix="P",
            start=1,
            end=MAX_BULK_CHILDREN + 1,
            pad_width=3,
        )


def test_bulk_generation_at_max_is_allowed() -> None:
    payload = LocationBulkChildrenCreate(
        location_type_code="chamber_position", code_prefix="P", start=1, end=MAX_BULK_CHILDREN, pad_width=3
    )
    assert payload.end - payload.start + 1 == MAX_BULK_CHILDREN


def test_bulk_generation_invalid_range_rejected() -> None:
    with pytest.raises(ValueError):
        LocationBulkChildrenCreate(location_type_code="chamber_position", code_prefix="P", start=5, end=1, pad_width=2)


# --- Integration (DB) ---


@pytest.mark.integration
def test_atomic_generation_of_20_chamber_positions(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code="nursery-gh", name="Nursery Greenhouse",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    area = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="area", code="germ-area", name="Germination Area",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=None,
    )
    chamber = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code="GC-01", name="Germination Chamber GC-01",
        parent_location_id=area.id, greenhouse_classification=None, occupiable=None,
    )

    created = location_service.bulk_generate_children(
        db_session,
        tenant_id=tenant.id,
        farm_id=farm.id,
        parent_id=chamber.id,
        actor_user_id=user.id,
        location_type_code="chamber_position",
        code_prefix="P",
        start=1,
        end=20,
        pad_width=2,
        name_template=None,
    )
    assert len(created) == 20
    assert {c.code for c in created} == {f"P{n:02d}" for n in range(1, 21)}
    assert all(c.parent_location_id == chamber.id for c in created)
    assert all(c.occupiable for c in created)  # chamber_position default_occupiable = true

    audit_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "location.bulk_generated")
    ).scalar_one()
    assert audit_count == 1


@pytest.mark.integration
def test_bulk_generation_collision_leaves_no_locations_or_audit_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code="gh-1", name="GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    area = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="area", code="germ-area", name="Germination Area",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=None,
    )
    chamber = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code="GC-01", name="Chamber",
        parent_location_id=area.id, greenhouse_classification=None, occupiable=None,
    )
    # Pre-create P05 so the batch collides mid-range.
    location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="chamber_position", code="P05", name="Preexisting",
        parent_location_id=chamber.id, greenhouse_classification=None, occupiable=None,
    )

    with pytest.raises(DuplicateLocationCodeError):
        location_service.bulk_generate_children(
            db_session,
            tenant_id=tenant.id,
            farm_id=farm.id,
            parent_id=chamber.id,
            actor_user_id=user.id,
            location_type_code="chamber_position",
            code_prefix="P",
            start=1,
            end=10,
            pad_width=2,
            name_template=None,
        )

    remaining = db_session.execute(
        select(func.count()).select_from(Location).where(Location.parent_location_id == chamber.id)
    ).scalar_one()
    assert remaining == 1  # only the pre-existing P05, nothing from the failed batch

    bulk_audit_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "location.bulk_generated")
    ).scalar_one()
    assert bulk_audit_count == 0
