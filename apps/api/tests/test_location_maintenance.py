"""UX-IA-001: Location maintenance lifecycle (name update, deactivate,
reactivate) -- service/idempotency/audit/invariant tests. Concurrency lives
in `test_location_maintenance_concurrency.py`.

Deactivation invariants are exercised on two shapes deliberately: the Store
hierarchy (store -> store_area -> store_rack -> store_bin, the first UX
consumer) for the active-children/bottom-up-retirement invariant, and a
germination_chamber + germination_trolley Occupancy (mirroring
`test_occupancy_capacity.py`'s own scenario) for the active-occupancy
invariant -- no occupancy_compatibility_rule exists yet for `store_bin`
(STORE-INV-005 scope), so a Store Bin cannot itself be occupied in this
ticket; the commands under test are generic `Location` operations, not
Store-specific, so proving the occupancy invariant on any occupiable
Location type is equally valid.
"""
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.schemas.location import LocationUpdate
from app.services import asset_service, location_service, movement_service, tenant_service
from app.services.errors import (
    LocationDeactivationReusedWithDifferentPayloadError,
    LocationHasActiveChildrenError,
    LocationHasActiveOccupancyError,
    LocationNotActiveError,
    LocationNotFoundError,
    LocationNotInactiveError,
    LocationParentNotActiveError,
    LocationReactivationReusedWithDifferentPayloadError,
    LocationUpdateReusedWithDifferentPayloadError,
)


def _now():
    return datetime.now(timezone.utc)


def _loc(db_session, tenant, farm, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        parent_location_id=None, greenhouse_classification=None, occupiable=None,
    )
    defaults.update(overrides)
    return location_service.create_location(db_session, **defaults)


def _store_hierarchy(db_session, tenant, farm, user):
    """store -> store_area -> store_rack -> store_bin, each with a unique
    code suffix so this can be called more than once per test."""
    suffix = uuid.uuid4().hex[:8]
    store = _loc(db_session, tenant, farm, user, location_type_code="store", code=f"store-{suffix}", name="Store")
    area = _loc(
        db_session, tenant, farm, user, location_type_code="store_area", code=f"area-{suffix}", name="Area",
        parent_location_id=store.id,
    )
    rack = _loc(
        db_session, tenant, farm, user, location_type_code="store_rack", code=f"rack-{suffix}", name="Rack",
        parent_location_id=area.id,
    )
    bin_ = _loc(
        db_session, tenant, farm, user, location_type_code="store_bin", code=f"bin-{suffix}", name="Bin",
        parent_location_id=rack.id,
    )
    return store, area, rack, bin_


def _chamber(db_session, tenant, farm, user):
    suffix = uuid.uuid4().hex[:8]
    greenhouse = _loc(
        db_session, tenant, farm, user, location_type_code="greenhouse", code=f"gh-{suffix}", name="GH",
        greenhouse_classification="nursery",
    )
    return location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code=f"gc-{suffix}", name="Chamber",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=True,
    )


def _trolley(db_session, tenant, farm, user):
    suffix = uuid.uuid4().hex[:8]
    return asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name="Trolley", commissioned_date=None,
    )


def _place(db_session, tenant, farm, user, *, occupant_id, target_id):
    return movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind="asset", occupant_id=occupant_id,
        destination_kind="location", destination_id=target_id, reason=None,
    )


def _remove(db_session, tenant, farm, user, *, occupant_id):
    return movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind="asset", occupant_id=occupant_id,
        destination_kind=None, destination_id=None, reason=None,
    )


def _second_tenant(db_session, *, code="loc-maint-tenant-b"):
    return tenant_service.create_tenant(db_session, code=code, name="Tenant B")


def _audit_count(db_session, *, action, entity_id):
    return db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == action, AuditEvent.entity_id == entity_id
        )
    ).scalar_one()


# --- Application-level (Pydantic) validation -- no DB required ---


def test_location_update_schema_rejects_code() -> None:
    with pytest.raises(ValidationError):
        LocationUpdate(client_command_id=uuid.uuid4(), name="Renamed", code="NEW-CODE")


# --- Update ---


@pytest.mark.integration
def test_active_location_rename_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, area, _rack, _bin = _store_hierarchy(db_session, tenant, farm, user)
    updated = location_service.update_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=area.id, name="Seed Area",
    )
    assert updated.name == "Seed Area"
    assert updated.code == area.code


@pytest.mark.integration
def test_inactive_location_rename_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    store, _area, _rack, _bin = _store_hierarchy(db_session, tenant, farm, user)
    location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=_bin.id,
    )
    location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=_rack.id,
    )
    location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=_area.id,
    )
    renamed = location_service.update_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=_area.id, name="Renamed While Inactive",
    )
    assert renamed.status == "inactive"
    assert renamed.name == "Renamed While Inactive"


@pytest.mark.integration
def test_update_tenant_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, area, _rack, _bin = _store_hierarchy(db_session, tenant, farm, user)
    tenant_b = _second_tenant(db_session)
    with pytest.raises(LocationNotFoundError):
        location_service.update_location(
            db_session, tenant_id=tenant_b.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=area.id, name="Hijacked",
        )


@pytest.mark.integration
def test_exact_update_replay_returns_original(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, area, _rack, _bin = _store_hierarchy(db_session, tenant, farm, user)
    command_id = uuid.uuid4()
    first = location_service.update_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, location_id=area.id, name="Renamed",
    )
    second = location_service.update_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, location_id=area.id, name="Renamed",
    )
    assert first.id == second.id


@pytest.mark.integration
def test_mismatched_update_replay_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, area, _rack, _bin = _store_hierarchy(db_session, tenant, farm, user)
    command_id = uuid.uuid4()
    location_service.update_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, location_id=area.id, name="First Name",
    )
    with pytest.raises(LocationUpdateReusedWithDifferentPayloadError):
        location_service.update_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=command_id, location_id=area.id, name="Second Name",
        )


# --- Deactivate ---


@pytest.mark.integration
def test_deactivate_active_leaf_no_occupancy_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, _area, _rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    deactivated = location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=bin_.id,
    )
    assert deactivated.status == "inactive"


@pytest.mark.integration
def test_deactivate_blocked_by_active_occupancy(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    chamber = _chamber(db_session, tenant, farm, user)
    trolley = _trolley(db_session, tenant, farm, user)
    _place(db_session, tenant, farm, user, occupant_id=trolley.id, target_id=chamber.id)
    with pytest.raises(LocationHasActiveOccupancyError):
        location_service.deactivate_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=chamber.id,
        )


@pytest.mark.integration
def test_deactivate_not_blocked_by_closed_occupancy(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    chamber = _chamber(db_session, tenant, farm, user)
    trolley = _trolley(db_session, tenant, farm, user)
    _place(db_session, tenant, farm, user, occupant_id=trolley.id, target_id=chamber.id)
    _remove(db_session, tenant, farm, user, occupant_id=trolley.id)
    deactivated = location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=chamber.id,
    )
    assert deactivated.status == "inactive"


@pytest.mark.integration
def test_deactivate_blocked_by_active_child(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, _area, rack, _bin = _store_hierarchy(db_session, tenant, farm, user)
    with pytest.raises(LocationHasActiveChildrenError):
        location_service.deactivate_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=rack.id,
        )


@pytest.mark.integration
def test_deactivate_bottom_up_retirement_succeeds(db_session, active_context_with_farm) -> None:
    """The operator retires a hierarchy bottom-up -- once every child is
    already inactive, the parent's own deactivation succeeds, one explicit
    command per node, never a cascade."""
    tenant, user, _headers, farm = active_context_with_farm
    store, area, rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    for node in (bin_, rack, area, store):
        deactivated = location_service.deactivate_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=node.id,
        )
        assert deactivated.status == "inactive"


@pytest.mark.integration
def test_deactivate_no_cascade_to_siblings(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, _area, rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=bin_.id,
    )
    still_active = location_service.get_location(db_session, tenant_id=tenant.id, farm_id=farm.id, location_id=rack.id)
    assert still_active.status == "active"


@pytest.mark.integration
def test_deactivate_already_inactive_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, _area, _rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=bin_.id,
    )
    with pytest.raises(LocationNotActiveError):
        location_service.deactivate_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=bin_.id,
        )


@pytest.mark.integration
def test_deactivate_tenant_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, _area, _rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    tenant_b = _second_tenant(db_session)
    with pytest.raises(LocationNotFoundError):
        location_service.deactivate_location(
            db_session, tenant_id=tenant_b.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=bin_.id,
        )


@pytest.mark.integration
def test_exact_deactivate_replay_returns_original(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, _area, _rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    command_id = uuid.uuid4()
    first = location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, location_id=bin_.id,
    )
    second = location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, location_id=bin_.id,
    )
    assert first.id == second.id


@pytest.mark.integration
def test_mismatched_deactivate_replay_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store_a, _area_a, _rack_a, bin_a = _store_hierarchy(db_session, tenant, farm, user)
    _store_b, _area_b, _rack_b, bin_b = _store_hierarchy(db_session, tenant, farm, user)
    command_id = uuid.uuid4()
    location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, location_id=bin_a.id,
    )
    with pytest.raises(LocationDeactivationReusedWithDifferentPayloadError):
        location_service.deactivate_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=command_id, location_id=bin_b.id,
        )


# --- Reactivate ---


@pytest.mark.integration
def test_reactivate_inactive_root_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    store, area, rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    for node in (bin_, rack, area, store):
        location_service.deactivate_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=node.id,
        )
    reactivated = location_service.reactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=store.id,
    )
    assert reactivated.status == "active"


@pytest.mark.integration
def test_reactivate_inactive_child_with_active_parent_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, _area, _rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=bin_.id,
    )
    reactivated = location_service.reactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=bin_.id,
    )
    assert reactivated.status == "active"


@pytest.mark.integration
def test_reactivate_blocked_by_inactive_parent(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, _area, rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=bin_.id,
    )
    location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=rack.id,
    )
    with pytest.raises(LocationParentNotActiveError):
        location_service.reactivate_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=bin_.id,
        )


@pytest.mark.integration
def test_reactivate_already_active_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, _area, _rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    with pytest.raises(LocationNotInactiveError):
        location_service.reactivate_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=bin_.id,
        )


@pytest.mark.integration
def test_reactivate_tenant_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, _area, _rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=bin_.id,
    )
    tenant_b = _second_tenant(db_session)
    with pytest.raises(LocationNotFoundError):
        location_service.reactivate_location(
            db_session, tenant_id=tenant_b.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=bin_.id,
        )


@pytest.mark.integration
def test_exact_reactivate_replay_returns_original(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, _area, _rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=bin_.id,
    )
    command_id = uuid.uuid4()
    first = location_service.reactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, location_id=bin_.id,
    )
    second = location_service.reactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, location_id=bin_.id,
    )
    assert first.id == second.id


@pytest.mark.integration
def test_mismatched_reactivate_replay_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store_a, _area_a, _rack_a, bin_a = _store_hierarchy(db_session, tenant, farm, user)
    _store_b, _area_b, _rack_b, bin_b = _store_hierarchy(db_session, tenant, farm, user)
    for bin_ in (bin_a, bin_b):
        location_service.deactivate_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=bin_.id,
        )
    command_id = uuid.uuid4()
    location_service.reactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, location_id=bin_a.id,
    )
    with pytest.raises(LocationReactivationReusedWithDifferentPayloadError):
        location_service.reactivate_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=command_id, location_id=bin_b.id,
        )


# --- Audit ---


@pytest.mark.integration
def test_update_deactivate_reactivate_audit_events(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _store, _area, _rack, bin_ = _store_hierarchy(db_session, tenant, farm, user)
    location_service.update_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=bin_.id, name="Renamed Bin",
    )
    location_service.deactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=bin_.id,
    )
    location_service.reactivate_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), location_id=bin_.id,
    )
    assert _audit_count(db_session, action="location.updated", entity_id=bin_.id) == 1
    assert _audit_count(db_session, action="location.deactivated", entity_id=bin_.id) == 1
    assert _audit_count(db_session, action="location.reactivated", entity_id=bin_.id) == 1

    update_event = db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "location.updated", AuditEvent.entity_id == bin_.id)
    ).scalar_one()
    assert update_event.event_data["name_before"] == "Bin"
    assert update_event.event_data["name_after"] == "Renamed Bin"
