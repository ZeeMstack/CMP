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
        destination_kind="location", destination_id=scenario["positions"]["P13"].id, reason=None,
    )

    movements_before = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    occupancies_before = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()

    second = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=command_id, effective_time=effective_time,
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
        destination_kind="location", destination_id=scenario["positions"]["P13"].id, reason=None,
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
        destination_kind="location", destination_id=scenario["positions"]["P13"].id, reason=None,
    )
    with pytest.raises(MovementCommandReusedWithDifferentPayloadError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=command_id, effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=scenario["positions"]["P14"].id, reason=None,
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
        destination_kind="location", destination_id=scenario["positions"]["P13"].id, reason=None,
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
        destination_kind="location", destination_id=scenario["positions"]["P13"].id, reason=None,
    )
    assert replay.id == first.id

    # A genuinely new command against the now-inactive trolley still fails.
    with pytest.raises(InactiveOccupantError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=scenario["positions"]["P14"].id, reason=None,
        )
