"""DOMAIN-FARM-002: capacity-aware occupancy.

Positive Location/AssetPosition capacity behavior (sections 18-19 of the
ticket), negative/invariant proofs (section 20), and mandatory direct-write
DB-layer enforcement tests that deliberately bypass `movement_service`
(section 21). Concurrency tests live in
`test_occupancy_capacity_concurrency.py`.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.movement import Movement
from app.models.occupancy import Occupancy
from app.services import asset_service, carrier_service, location_service, movement_service, tenant_service, user_service, membership_service, farm_service
from app.services.errors import (
    IncompatibleOccupantTargetError,
    InvalidLocationHierarchyError,
    LocationNotFoundError,
    TargetNotOccupiableError,
    TargetOccupiedError,
)


def _now():
    return datetime.now(timezone.utc)


def _build_chamber(db_session, tenant, farm, user):
    suffix = uuid.uuid4().hex[:8]
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code=f"gh-{suffix}", name="GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    chamber = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code=f"gc-{suffix}", name="Chamber",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=None,
    )
    return greenhouse, chamber


def _build_position(db_session, tenant, farm, user, *, capacity):
    _greenhouse, chamber = _build_chamber(db_session, tenant, farm, user)
    return location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="chamber_position", code=f"p-{uuid.uuid4().hex[:8]}", name="Position",
        parent_location_id=chamber.id, greenhouse_classification=None, occupiable=None, capacity=capacity,
    )


def _register_trolley(db_session, tenant, farm, user):
    suffix = uuid.uuid4().hex[:8]
    return asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name=f"Trolley {suffix}", commissioned_date=None,
    )


def _register_tray(db_session, tenant, farm, user):
    suffix = uuid.uuid4().hex[:8]
    return carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="seed_tray", code=f"ST-{suffix}", issued_date=None,
    )


def _build_slot(db_session, tenant, farm, user, *, capacity):
    trolley = _register_trolley(db_session, tenant, farm, user)
    positions = asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix=f"SH-{uuid.uuid4().hex[:6]}-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2, slot_capacity=capacity,
    )
    slot = next(p for p in positions if p.position_kind == "slot")
    return trolley, slot


def _place(db_session, tenant, farm, user, *, occupant_kind, occupant_id, target_kind, target_id):
    return movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind=occupant_kind, occupant_id=occupant_id,
        destination_kind=target_kind, destination_id=target_id, reason=None,
    )


def _remove(db_session, tenant, farm, user, *, occupant_kind, occupant_id):
    return movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind=occupant_kind, occupant_id=occupant_id,
        destination_kind=None, destination_id=None, reason=None,
    )


def _active_target_count(db_session, *, target_kind, target_id) -> int:
    condition = (
        Occupancy.target_location_id == target_id
        if target_kind == "location"
        else Occupancy.target_asset_position_id == target_id
    )
    return len(db_session.execute(select(Occupancy).where(condition, Occupancy.end_time.is_(None))).scalars().all())


# =====================================================================
# 18. Positive tests -- Location capacity
# =====================================================================


@pytest.mark.integration
@pytest.mark.parametrize("capacity", [None, 1])
def test_location_capacity_null_or_one_is_exclusive(db_session, active_context_with_farm, capacity) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_position(db_session, tenant, farm, user, capacity=capacity)
    t1 = _register_trolley(db_session, tenant, farm, user)
    t2 = _register_trolley(db_session, tenant, farm, user)

    _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=t1.id, target_kind="location", target_id=position.id)
    with pytest.raises(TargetOccupiedError):
        _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=t2.id, target_kind="location", target_id=position.id)
    assert _active_target_count(db_session, target_kind="location", target_id=position.id) == 1


@pytest.mark.integration
def test_location_capacity_two_permits_two_rejects_third(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_position(db_session, tenant, farm, user, capacity=2)
    trolleys = [_register_trolley(db_session, tenant, farm, user) for _ in range(3)]

    _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolleys[0].id, target_kind="location", target_id=position.id)
    _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolleys[1].id, target_kind="location", target_id=position.id)
    with pytest.raises(TargetOccupiedError):
        _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolleys[2].id, target_kind="location", target_id=position.id)
    assert _active_target_count(db_session, target_kind="location", target_id=position.id) == 2


@pytest.mark.integration
def test_location_capacity_three_permits_three_rejects_fourth(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_position(db_session, tenant, farm, user, capacity=3)
    trolleys = [_register_trolley(db_session, tenant, farm, user) for _ in range(4)]

    for trolley in trolleys[:3]:
        _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id, target_kind="location", target_id=position.id)
    with pytest.raises(TargetOccupiedError):
        _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolleys[3].id, target_kind="location", target_id=position.id)
    assert _active_target_count(db_session, target_kind="location", target_id=position.id) == 3


@pytest.mark.integration
def test_location_capacity_frees_slot_on_departure(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_position(db_session, tenant, farm, user, capacity=2)
    trolleys = [_register_trolley(db_session, tenant, farm, user) for _ in range(3)]

    _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolleys[0].id, target_kind="location", target_id=position.id)
    _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolleys[1].id, target_kind="location", target_id=position.id)
    with pytest.raises(TargetOccupiedError):
        _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolleys[2].id, target_kind="location", target_id=position.id)

    _remove(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolleys[0].id)
    # A slot is now free -- the third trolley can enter.
    _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolleys[2].id, target_kind="location", target_id=position.id)
    assert _active_target_count(db_session, target_kind="location", target_id=position.id) == 2


@pytest.mark.integration
def test_bulk_generated_locations_all_receive_configured_capacity(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _greenhouse, chamber = _build_chamber(db_session, tenant, farm, user)
    positions = location_service.bulk_generate_children(
        db_session, tenant_id=tenant.id, farm_id=farm.id, parent_id=chamber.id, actor_user_id=user.id,
        location_type_code="chamber_position", code_prefix=f"BULK-{uuid.uuid4().hex[:6]}-", start=1, end=5,
        pad_width=2, name_template=None, capacity=4,
    )
    assert len(positions) == 5
    assert all(p.capacity == 4 for p in positions)


# =====================================================================
# 19. Positive tests -- AssetPosition capacity
# =====================================================================


@pytest.mark.integration
@pytest.mark.parametrize("capacity", [None, 1])
def test_asset_position_capacity_null_or_one_is_exclusive(db_session, active_context_with_farm, capacity) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _trolley, slot = _build_slot(db_session, tenant, farm, user, capacity=capacity)
    tray1 = _register_tray(db_session, tenant, farm, user)
    tray2 = _register_tray(db_session, tenant, farm, user)

    _place(db_session, tenant, farm, user, occupant_kind="carrier", occupant_id=tray1.id, target_kind="asset_position", target_id=slot.id)
    with pytest.raises(TargetOccupiedError):
        _place(db_session, tenant, farm, user, occupant_kind="carrier", occupant_id=tray2.id, target_kind="asset_position", target_id=slot.id)
    assert _active_target_count(db_session, target_kind="asset_position", target_id=slot.id) == 1


@pytest.mark.integration
def test_asset_position_capacity_two_permits_two_rejects_third(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _trolley, slot = _build_slot(db_session, tenant, farm, user, capacity=2)
    trays = [_register_tray(db_session, tenant, farm, user) for _ in range(3)]

    _place(db_session, tenant, farm, user, occupant_kind="carrier", occupant_id=trays[0].id, target_kind="asset_position", target_id=slot.id)
    _place(db_session, tenant, farm, user, occupant_kind="carrier", occupant_id=trays[1].id, target_kind="asset_position", target_id=slot.id)
    with pytest.raises(TargetOccupiedError):
        _place(db_session, tenant, farm, user, occupant_kind="carrier", occupant_id=trays[2].id, target_kind="asset_position", target_id=slot.id)
    assert _active_target_count(db_session, target_kind="asset_position", target_id=slot.id) == 2


# =====================================================================
# 20. Negative / invariant tests
# =====================================================================


@pytest.mark.integration
@pytest.mark.parametrize("bad_capacity", [0, -1])
def test_schema_rejects_non_positive_location_capacity(bad_capacity) -> None:
    from pydantic import ValidationError

    from app.schemas.location import LocationCreate

    with pytest.raises(ValidationError):
        LocationCreate(location_type_code="chamber_position", code="X", name="X", capacity=bad_capacity)


@pytest.mark.integration
@pytest.mark.parametrize("bad_capacity", [0, -1])
def test_schema_rejects_non_positive_bulk_capacity(bad_capacity) -> None:
    from pydantic import ValidationError

    from app.schemas.location import LocationBulkChildrenCreate

    with pytest.raises(ValidationError):
        LocationBulkChildrenCreate(
            location_type_code="chamber_position", code_prefix="X", start=1, end=1, pad_width=2, capacity=bad_capacity
        )


@pytest.mark.integration
@pytest.mark.parametrize("bad_capacity", [0, -1])
def test_schema_rejects_non_positive_asset_position_capacity(bad_capacity) -> None:
    from pydantic import ValidationError

    from app.schemas.asset_position import AssetPositionsGenerate

    with pytest.raises(ValidationError):
        AssetPositionsGenerate(
            shelf_count=1, slots_per_shelf=1, shelf_prefix="SH-", slot_prefix="SL-",
            shelf_pad_width=2, slot_pad_width=2, shelf_capacity=bad_capacity,
        )


@pytest.mark.integration
@pytest.mark.parametrize("bad_capacity", [0, -1])
def test_db_directly_rejects_invalid_location_capacity(db_session, active_context_with_farm, bad_capacity) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _greenhouse, chamber = _build_chamber(db_session, tenant, farm, user)
    with pytest.raises(IntegrityError):
        location_service.create_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            location_type_code="chamber_position", code=f"bad-{uuid.uuid4().hex[:6]}", name="Bad",
            parent_location_id=chamber.id, greenhouse_classification=None, occupiable=None, capacity=bad_capacity,
        )


@pytest.mark.integration
def test_capacity_does_not_bypass_occupancy_compatibility(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_position(db_session, tenant, farm, user, capacity=5)
    tray = _register_tray(db_session, tenant, farm, user)  # seed_tray is only compatible with 'slot', not chamber_position
    with pytest.raises(IncompatibleOccupantTargetError):
        _place(db_session, tenant, farm, user, occupant_kind="carrier", occupant_id=tray.id, target_kind="location", target_id=position.id)


@pytest.mark.integration
def test_non_occupiable_location_with_capacity_remains_non_occupiable(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _greenhouse, chamber = _build_chamber(db_session, tenant, farm, user)
    # germination_chamber defaults to non-occupiable; force capacity > 1 to
    # prove capacity alone never makes a target occupiable.
    chamber.capacity = 5
    db_session.flush()
    trolley = _register_trolley(db_session, tenant, farm, user)
    with pytest.raises(TargetNotOccupiableError):
        _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id, target_kind="location", target_id=chamber.id)


@pytest.mark.integration
def test_cross_tenant_placement_into_capacity_target_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_position(db_session, tenant, farm, user, capacity=3)

    suffix = uuid.uuid4().hex[:8]
    other_tenant = tenant_service.create_tenant(db_session, code=f"other-{suffix}", name="Other Tenant")
    other_user = user_service.create_user(
        db_session, oidc_issuer="other", oidc_subject=suffix, email=f"other-{suffix}@example.com", display_name="Other User"
    )
    membership_service.add_membership(
        db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None
    )
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code=f"farm-{suffix}", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_trolley = asset_service.register_asset(
        db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, actor_user_id=other_user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name="Other Trolley", commissioned_date=None,
    )
    with pytest.raises(LocationNotFoundError):
        _place(
            db_session, other_tenant, other_farm, other_user,
            occupant_kind="asset", occupant_id=other_trolley.id, target_kind="location", target_id=position.id,
        )


@pytest.mark.integration
def test_occupant_side_uniqueness_preserved_at_db_layer_for_carrier(db_session, active_context_with_farm) -> None:
    """DOMAIN-FARM-002 section 4: a Carrier must never become simultaneously
    present in two Locations merely because targets now support multiple
    occupants. Bypasses movement_service to prove this at the DB layer."""
    tenant, user, _headers, farm = active_context_with_farm
    position_a = _build_position(db_session, tenant, farm, user, capacity=5)
    position_b = _build_position(db_session, tenant, farm, user, capacity=5)
    tray = _register_tray(db_session, tenant, farm, user)
    # seed_tray is only compatible with 'slot' asset positions, not
    # chamber_position locations -- use asset occupant/location target
    # instead so this test isolates occupant-side uniqueness, not compatibility.
    trolley = _register_trolley(db_session, tenant, farm, user)

    now = _now()
    mv1 = Movement(
        id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id, occupant_asset_id=trolley.id,
        destination_location_id=position_a.id, command_type="movement", client_command_id=uuid.uuid4(),
        request_fingerprint="fp-1", effective_time=now, actor_user_id=user.id,
    )
    db_session.add(mv1)
    db_session.flush()
    occ1 = Occupancy(
        id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id, occupant_asset_id=trolley.id,
        target_location_id=position_a.id, effective_time=now, opened_by_movement_id=mv1.id, actor_user_id=user.id,
    )
    db_session.add(occ1)
    db_session.flush()

    mv2 = Movement(
        id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id, occupant_asset_id=trolley.id,
        destination_location_id=position_b.id, command_type="movement", client_command_id=uuid.uuid4(),
        request_fingerprint="fp-2", effective_time=now, actor_user_id=user.id,
    )
    db_session.add(mv2)
    db_session.flush()
    occ2 = Occupancy(
        id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id, occupant_asset_id=trolley.id,
        target_location_id=position_b.id, effective_time=now, opened_by_movement_id=mv2.id, actor_user_id=user.id,
    )
    db_session.add(occ2)
    with pytest.raises(IntegrityError):
        db_session.flush()


# =====================================================================
# 21. Database direct-write enforcement tests (mandatory, bypass movement_service)
# =====================================================================


def _direct_insert_occupancy(db_session, *, tenant, farm, user, occupant_asset_id=None, occupant_carrier_id=None,
                              target_location_id=None, target_asset_position_id=None, effective_time):
    movement = Movement(
        id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id,
        occupant_asset_id=occupant_asset_id, occupant_carrier_id=occupant_carrier_id,
        destination_location_id=target_location_id, destination_asset_position_id=target_asset_position_id,
        command_type="movement", client_command_id=uuid.uuid4(),
        request_fingerprint=f"direct-{uuid.uuid4().hex}", effective_time=effective_time, actor_user_id=user.id,
    )
    db_session.add(movement)
    db_session.flush()
    occupancy = Occupancy(
        id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id,
        occupant_asset_id=occupant_asset_id, occupant_carrier_id=occupant_carrier_id,
        target_location_id=target_location_id, target_asset_position_id=target_asset_position_id,
        effective_time=effective_time, opened_by_movement_id=movement.id, actor_user_id=user.id,
    )
    db_session.add(occupancy)
    db_session.flush()
    return occupancy


@pytest.mark.integration
def test_direct_write_cannot_exceed_location_capacity_one(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_position(db_session, tenant, farm, user, capacity=1)
    trolleys = [_register_trolley(db_session, tenant, farm, user) for _ in range(2)]
    now = _now()

    _direct_insert_occupancy(
        db_session, tenant=tenant, farm=farm, user=user,
        occupant_asset_id=trolleys[0].id, target_location_id=position.id, effective_time=now,
    )
    with pytest.raises(IntegrityError):
        _direct_insert_occupancy(
            db_session, tenant=tenant, farm=farm, user=user,
            occupant_asset_id=trolleys[1].id, target_location_id=position.id, effective_time=now,
        )


@pytest.mark.integration
def test_direct_write_cannot_exceed_location_capacity_two(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_position(db_session, tenant, farm, user, capacity=2)
    trolleys = [_register_trolley(db_session, tenant, farm, user) for _ in range(3)]
    now = _now()

    _direct_insert_occupancy(
        db_session, tenant=tenant, farm=farm, user=user,
        occupant_asset_id=trolleys[0].id, target_location_id=position.id, effective_time=now,
    )
    _direct_insert_occupancy(
        db_session, tenant=tenant, farm=farm, user=user,
        occupant_asset_id=trolleys[1].id, target_location_id=position.id, effective_time=now,
    )
    with pytest.raises(IntegrityError):
        _direct_insert_occupancy(
            db_session, tenant=tenant, farm=farm, user=user,
            occupant_asset_id=trolleys[2].id, target_location_id=position.id, effective_time=now,
        )


@pytest.mark.integration
def test_direct_write_cannot_exceed_asset_position_capacity_two(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _trolley, slot = _build_slot(db_session, tenant, farm, user, capacity=2)
    trays = [_register_tray(db_session, tenant, farm, user) for _ in range(3)]
    now = _now()

    _direct_insert_occupancy(
        db_session, tenant=tenant, farm=farm, user=user,
        occupant_carrier_id=trays[0].id, target_asset_position_id=slot.id, effective_time=now,
    )
    _direct_insert_occupancy(
        db_session, tenant=tenant, farm=farm, user=user,
        occupant_carrier_id=trays[1].id, target_asset_position_id=slot.id, effective_time=now,
    )
    with pytest.raises(IntegrityError):
        _direct_insert_occupancy(
            db_session, tenant=tenant, farm=farm, user=user,
            occupant_carrier_id=trays[2].id, target_asset_position_id=slot.id, effective_time=now,
        )
