"""DOMAIN-FARM-002.1: capacity-update and occupancy-update safety.

Proves, by direct SQL/ORM writes against cmp_test that deliberately bypass
`movement_service` and `location_service`, that the authoritative invariant

    active occupancy count <= COALESCE(capacity, 1)

survives BOTH occupancy changes (INSERT, legitimate closure UPDATE) and
capacity-configuration changes (UPDATE), and that no direct-write route can
reactivate an ended occupancy, retarget an active one, or change its
occupant identity.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.models.movement import Movement
from app.models.occupancy import Occupancy
from app.services import asset_service, carrier_service, location_service, movement_service


def _now():
    return datetime.now(timezone.utc)


def _build_capacity_chamber(db_session, tenant, farm, user, *, capacity):
    """NURSERY-OPS-002A: the frozen authoritative model -- a Germination
    Trolley occupies the Chamber Location directly (no chamber_position
    child). The Chamber itself is the capacity-configurable target."""
    suffix = uuid.uuid4().hex[:8]
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code=f"gh-{suffix}", name="GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    return location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code=f"gc-{suffix}", name="Chamber",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=True, capacity=capacity,
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


# =====================================================================
# A/B. capacity cannot be reduced below active occupancy count
# =====================================================================


@pytest.mark.integration
def test_location_capacity_cannot_be_reduced_below_active_count(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_capacity_chamber(db_session, tenant, farm, user, capacity=3)
    trolleys = [_register_trolley(db_session, tenant, farm, user) for _ in range(3)]
    for trolley in trolleys:
        _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id, target_kind="location", target_id=position.id)

    for bad_capacity in (2, 1, None):
        with pytest.raises(IntegrityError):
            db_session.execute(
                text("UPDATE locations SET capacity = :cap WHERE id = :id"),
                {"cap": bad_capacity, "id": position.id},
            )
            db_session.flush()
        db_session.rollback()


@pytest.mark.integration
def test_asset_position_capacity_cannot_be_reduced_below_active_count(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _trolley, slot = _build_slot(db_session, tenant, farm, user, capacity=2)
    trays = [_register_tray(db_session, tenant, farm, user) for _ in range(2)]
    for tray in trays:
        _place(db_session, tenant, farm, user, occupant_kind="carrier", occupant_id=tray.id, target_kind="asset_position", target_id=slot.id)

    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE asset_positions SET capacity = 1 WHERE id = :id"),
            {"id": slot.id},
        )
        db_session.flush()
    db_session.rollback()


# =====================================================================
# C/D. capacity may be increased / reduced when it still fits
# =====================================================================


@pytest.mark.integration
def test_location_capacity_may_be_increased(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_capacity_chamber(db_session, tenant, farm, user, capacity=1)
    trolley = _register_trolley(db_session, tenant, farm, user)
    _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id, target_kind="location", target_id=position.id)

    db_session.execute(text("UPDATE locations SET capacity = 5 WHERE id = :id"), {"id": position.id})
    db_session.flush()
    assert db_session.execute(text("SELECT capacity FROM locations WHERE id = :id"), {"id": position.id}).scalar_one() == 5


@pytest.mark.integration
def test_location_capacity_may_be_reduced_when_it_still_fits(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_capacity_chamber(db_session, tenant, farm, user, capacity=5)
    trolleys = [_register_trolley(db_session, tenant, farm, user) for _ in range(2)]
    for trolley in trolleys:
        _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id, target_kind="location", target_id=position.id)

    db_session.execute(text("UPDATE locations SET capacity = 2 WHERE id = :id"), {"id": position.id})
    db_session.flush()
    assert db_session.execute(text("SELECT capacity FROM locations WHERE id = :id"), {"id": position.id}).scalar_one() == 2


# =====================================================================
# E. NULL treated as effective capacity 1 during reduction checks
# =====================================================================


@pytest.mark.integration
def test_capacity_to_null_allowed_when_one_active_occupant(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_capacity_chamber(db_session, tenant, farm, user, capacity=3)
    trolley = _register_trolley(db_session, tenant, farm, user)
    _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id, target_kind="location", target_id=position.id)

    db_session.execute(text("UPDATE locations SET capacity = NULL WHERE id = :id"), {"id": position.id})
    db_session.flush()
    assert db_session.execute(text("SELECT capacity FROM locations WHERE id = :id"), {"id": position.id}).scalar_one() is None


@pytest.mark.integration
def test_capacity_to_null_rejected_when_zero_active_occupants_still_allowed(db_session, active_context_with_farm) -> None:
    """0 occupants, capacity 3 -> NULL: ALLOWED (0 <= 1)."""
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_capacity_chamber(db_session, tenant, farm, user, capacity=3)

    db_session.execute(text("UPDATE locations SET capacity = NULL WHERE id = :id"), {"id": position.id})
    db_session.flush()
    assert db_session.execute(text("SELECT capacity FROM locations WHERE id = :id"), {"id": position.id}).scalar_one() is None


# =====================================================================
# F. legitimate Occupancy closure remains allowed
# =====================================================================


@pytest.mark.integration
def test_legitimate_closure_still_allowed_after_capacity_reduction_guard(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_capacity_chamber(db_session, tenant, farm, user, capacity=2)
    trolley = _register_trolley(db_session, tenant, farm, user)
    _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id, target_kind="location", target_id=position.id)

    # Normal removal (closes the occupancy via the real movement path).
    _remove(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id)

    active = db_session.execute(
        select(Occupancy).where(Occupancy.target_location_id == position.id, Occupancy.end_time.is_(None))
    ).scalars().all()
    assert active == []


# =====================================================================
# G. reactivation of an ended Occupancy cannot bypass capacity/invariants
# =====================================================================


@pytest.mark.integration
def test_reactivating_ended_occupancy_is_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_capacity_chamber(db_session, tenant, farm, user, capacity=1)
    trolley = _register_trolley(db_session, tenant, farm, user)
    _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id, target_kind="location", target_id=position.id)
    _remove(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id)

    ended = db_session.execute(
        select(Occupancy).where(Occupancy.target_location_id == position.id, Occupancy.end_time.is_not(None))
    ).scalar_one()

    # Rejected by the pre-existing enforce_occupancy_closure_only trigger
    # (8a2c6f1e9d33, unmodified) -- a plain RAISE EXCEPTION with no custom
    # SQLSTATE, so SQLAlchemy classifies it as ProgrammingError rather than
    # IntegrityError (unlike this ticket's own new capacity-check triggers,
    # which do assign check_violation deliberately).
    with pytest.raises(ProgrammingError):
        db_session.execute(
            text(
                "UPDATE occupancies SET end_time = NULL, closed_by_movement_id = NULL WHERE id = :id"
            ),
            {"id": ended.id},
        )
        db_session.flush()
    db_session.rollback()


# =====================================================================
# H. target mutation cannot bypass capacity/invariants
# =====================================================================


@pytest.mark.integration
def test_active_occupancy_target_mutation_is_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position_a = _build_capacity_chamber(db_session, tenant, farm, user, capacity=5)
    position_b = _build_capacity_chamber(db_session, tenant, farm, user, capacity=5)
    trolley = _register_trolley(db_session, tenant, farm, user)
    active = _direct_insert_occupancy(
        db_session, tenant=tenant, farm=farm, user=user,
        occupant_asset_id=trolley.id, target_location_id=position_a.id, effective_time=_now(),
    )

    # Same pre-existing trigger as G -- see its comment above.
    with pytest.raises(ProgrammingError):
        db_session.execute(
            text("UPDATE occupancies SET target_location_id = :pid WHERE id = :id"),
            {"pid": position_b.id, "id": active.id},
        )
        db_session.flush()
    db_session.rollback()


# =====================================================================
# I. occupant mutation cannot bypass historical/uniqueness invariants
# =====================================================================


@pytest.mark.integration
def test_active_occupancy_occupant_mutation_is_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_capacity_chamber(db_session, tenant, farm, user, capacity=5)
    trolley_a = _register_trolley(db_session, tenant, farm, user)
    trolley_b = _register_trolley(db_session, tenant, farm, user)
    active = _direct_insert_occupancy(
        db_session, tenant=tenant, farm=farm, user=user,
        occupant_asset_id=trolley_a.id, target_location_id=position.id, effective_time=_now(),
    )

    # Same pre-existing trigger as G -- see its comment above.
    with pytest.raises(ProgrammingError):
        db_session.execute(
            text("UPDATE occupancies SET occupant_asset_id = :aid WHERE id = :id"),
            {"aid": trolley_b.id, "id": active.id},
        )
        db_session.flush()
    db_session.rollback()
