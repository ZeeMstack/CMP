import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models.movement import Movement
from app.models.occupancy import Occupancy
from app.services import movement_service
from app.services.errors import InactiveOccupantError, MovementCommandReusedWithDifferentPayloadError


def _now():
    return datetime.now(timezone.utc)


@pytest.mark.integration
def test_duplicate_command_returns_original_movement(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    command_id = uuid.uuid4()
    effective_time = _now()

    first = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, effective_time=effective_time,
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
        destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
    )

    movements_before = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    occupancies_before = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()

    second = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, effective_time=effective_time,
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
        destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
    )

    assert second.id == first.id
    movements_after = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    occupancies_after = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    assert movements_after == movements_before
    assert occupancies_after == occupancies_before


@pytest.mark.integration
def test_reused_command_id_with_different_payload_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    command_id = uuid.uuid4()

    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, effective_time=_now(),
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
        destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
    )
    with pytest.raises(MovementCommandReusedWithDifferentPayloadError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=command_id, effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=scenario["chambers"]["GC-03"].id, reason=None,
        )


@pytest.mark.integration
def test_idempotency_checked_before_mutable_entity_validation(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    command_id = uuid.uuid4()
    effective_time = _now()

    first = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, effective_time=effective_time,
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
        destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
    )

    # The trolley becoming inactive after the fact must not affect a replay of
    # the exact same command — the fingerprint match should short-circuit
    # before any occupant/target re-validation happens.
    scenario["trolley"].status = "inactive"
    db_session.flush()

    replay = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, effective_time=effective_time,
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
        destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
    )
    assert replay.id == first.id

    # A genuinely new command against the now-inactive trolley still fails.
    with pytest.raises(InactiveOccupantError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=scenario["chambers"]["GC-03"].id, reason=None,
        )


@pytest.mark.integration
def test_idempotent_replay_does_not_double_consume_capacity(db_session, active_context_with_farm) -> None:
    """DOMAIN-FARM-002 section 23: an exact replay of the command that
    itself filled the target's only slot must return the original result,
    not fail merely because the target the command itself filled is now
    "full"."""
    import uuid as uuid_module

    from app.services import asset_service, location_service

    tenant, user, _headers, farm = active_context_with_farm
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code=f"gh-{uuid_module.uuid4().hex[:6]}", name="GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    chamber = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code=f"gc-{uuid_module.uuid4().hex[:6]}", name="Chamber",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=True, capacity=1,
    )
    trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{uuid_module.uuid4().hex[:6]}", name="Trolley",
        commissioned_date=None,
    )
    command_id = uuid.uuid4()
    effective_time = _now()

    first = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, effective_time=effective_time,
        occupant_kind="asset", occupant_id=trolley.id,
        destination_kind="location", destination_id=chamber.id, reason=None,
    )
    # The target (capacity=1) is now full -- exactly because of `first`.
    # Replaying the identical command must still return the original
    # movement, not raise TargetOccupiedError.
    replay = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, effective_time=effective_time,
        occupant_kind="asset", occupant_id=trolley.id,
        destination_kind="location", destination_id=chamber.id, reason=None,
    )
    assert replay.id == first.id
    assert (
        db_session.execute(
            select(func.count()).select_from(Occupancy).where(
                Occupancy.target_location_id == chamber.id, Occupancy.end_time.is_(None)
            )
        ).scalar_one()
        == 1
    )
