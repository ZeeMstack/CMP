import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.audit_event import AuditEvent
from app.models.movement import Movement
from app.models.occupancy import Occupancy
from app.services import asset_service, carrier_service, farm_service, location_service, movement_service, tenant_service
from app.services.errors import (
    AssetCannotOccupyOwnPositionError,
    AssetNotFoundError,
    CarrierNotFoundError,
    FarmNotFoundError,
    InactiveOccupantError,
    InactiveTargetError,
    IncompatibleOccupantTargetError,
    InvalidEffectiveTimeError,
    LocationNotFoundError,
    NoOpMovementError,
    NothingToRemoveError,
    TargetNotOccupiableError,
    TargetOccupiedError,
)
from tests.conftest import ensure_seed_tray_specification


def _now():
    return datetime.now(timezone.utc)


@pytest.mark.integration
def test_initial_asset_placement(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    occupancy = movement_service.get_occupancy(
        db_session, tenant_id=scenario["tenant"].id, farm_id=scenario["farm"].id,
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
    )
    assert occupancy is not None
    assert occupancy.target_location_id == scenario["chambers"]["GC-01"].id
    assert occupancy.end_time is None
    assert occupancy.opened_by_movement_id == scenario["trolley_movement"].id


@pytest.mark.integration
def test_initial_carrier_placement(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    occupancy = movement_service.get_occupancy(
        db_session, tenant_id=scenario["tenant"].id, farm_id=scenario["farm"].id,
        occupant_kind="carrier", occupant_id=scenario["tray"].id,
    )
    assert occupancy is not None
    assert occupancy.target_asset_position_id == scenario["slot_03_04"].id


@pytest.mark.integration
def test_movement_between_fixed_locations(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    old_occupancy = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="asset", occupant_id=scenario["trolley"].id
    )

    movement = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
        destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
    )
    assert movement.source_location_id == scenario["chambers"]["GC-01"].id
    assert movement.destination_location_id == scenario["chambers"]["GC-02"].id

    db_session.refresh(old_occupancy)
    assert old_occupancy.end_time is not None
    assert old_occupancy.closed_by_movement_id == movement.id

    new_occupancy = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="asset", occupant_id=scenario["trolley"].id
    )
    assert new_occupancy.target_location_id == scenario["chambers"]["GC-02"].id
    assert new_occupancy.opened_by_movement_id == movement.id


@pytest.mark.integration
def test_movement_between_asset_positions(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    shelf_slots = asset_service.get_positions_tree(
        db_session, tenant_id=tenant.id, farm_id=farm.id, asset_id=scenario["trolley"].id
    )
    other_slot = next(
        p for p in shelf_slots
        if p.position_kind == "slot" and p.id != scenario["slot_03_04"].id
    )

    movement = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind="carrier", occupant_id=scenario["tray"].id,
        destination_kind="asset_position", destination_id=other_slot.id, reason=None,
    )
    assert movement.source_asset_position_id == scenario["slot_03_04"].id
    assert movement.destination_asset_position_id == other_slot.id

    occupancy = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=scenario["tray"].id
    )
    assert occupancy.target_asset_position_id == other_slot.id


@pytest.mark.integration
def test_trolley_movement_preserves_tray_direct_occupancy(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    tray_occupancy_before = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=scenario["tray"].id
    )

    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
        destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
    )

    tray_occupancy_after = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=scenario["tray"].id
    )
    assert tray_occupancy_after.id == tray_occupancy_before.id
    assert tray_occupancy_after.target_asset_position_id == scenario["slot_03_04"].id
    assert tray_occupancy_after.end_time is None


@pytest.mark.integration
def test_removal(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]

    movement = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind="carrier", occupant_id=scenario["tray"].id,
        destination_kind=None, destination_id=None, reason="removed for inspection",
    )
    assert movement.destination_location_id is None
    assert movement.destination_asset_position_id is None
    assert movement.source_asset_position_id == scenario["slot_03_04"].id

    occupancy = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=scenario["tray"].id
    )
    assert occupancy is None


@pytest.mark.integration
def test_removal_with_nothing_to_remove_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    tray = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code="ST-9999", issued_date=None,
    )
    with pytest.raises(NothingToRemoveError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="carrier", occupant_id=tray.id,
            destination_kind=None, destination_id=None, reason=None,
        )


@pytest.mark.integration
def test_no_op_movement_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    with pytest.raises(NoOpMovementError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=scenario["chambers"]["GC-01"].id, reason=None,
        )


@pytest.mark.integration
def test_unsupported_occupant_target_combination_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scale = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="weighing_scale", code="WS-01", name="Scale", commissioned_date=None,
    )
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code="gh-1", name="GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    chamber = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code="GC-1", name="Chamber",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=True,
    )
    with pytest.raises(IncompatibleOccupantTargetError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scale.id,
            destination_kind="location", destination_id=chamber.id, reason=None,
        )


@pytest.mark.integration
def test_non_occupiable_location_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    # The Nursery Greenhouse itself is non-occupiable (unlike the fixture's
    # Germination Chambers, which are occupiable under the NURSERY-OPS-002A
    # model) -- a genuinely non-occupiable target, unrelated to chambers.
    with pytest.raises(TargetNotOccupiableError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=scenario["greenhouse"].id, reason=None,
        )


@pytest.mark.integration
def test_occupied_target_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    other_trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code="GT-0002", name="Trolley 2", commissioned_date=None,
    )
    with pytest.raises(TargetOccupiedError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=other_trolley.id,
            destination_kind="location", destination_id=scenario["chambers"]["GC-01"].id, reason=None,
        )


@pytest.mark.integration
def test_one_active_occupancy_per_occupant_enforced_by_postgres(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm = scenario["tenant"], scenario["farm"]
    effective_time = scenario["trolley_movement"].effective_time
    # A legitimately-matching movement (so only the exclusivity index is exercised,
    # not the opening-movement-match trigger) whose destination is P13 for the
    # already-placed trolley, which is still active at P12.
    matching_movement_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO movements (id, tenant_id, farm_id, occupant_asset_id, source_location_id, "
            "destination_location_id, command_type, client_command_id, request_fingerprint, effective_time) "
            "VALUES (:id, :tenant_id, :farm_id, :asset_id, :source_id, :dest_id, 'movement', :client_id, 'fp', :effective_time)"
        ),
        {
            "id": matching_movement_id, "tenant_id": tenant.id, "farm_id": farm.id,
            "asset_id": scenario["trolley"].id, "source_id": scenario["chambers"]["GC-01"].id,
            "dest_id": scenario["chambers"]["GC-02"].id, "client_id": uuid.uuid4(), "effective_time": effective_time,
        },
    )
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO occupancies (id, tenant_id, farm_id, occupant_asset_id, target_location_id, "
                    "effective_time, opened_by_movement_id) "
                    "VALUES (:id, :tenant_id, :farm_id, :asset_id, :location_id, :effective_time, :movement_id)"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id,
                    "asset_id": scenario["trolley"].id, "location_id": scenario["chambers"]["GC-02"].id,
                    "movement_id": matching_movement_id, "effective_time": effective_time,
                },
            )


@pytest.mark.integration
def test_cross_tenant_occupant_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    other_tenant = tenant_service.create_tenant(db_session, code="other-mv-tenant", name="Other")
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    with pytest.raises(AssetNotFoundError):
        movement_service.execute_movement(
            db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, actor_user_id=None,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
        )


@pytest.mark.integration
def test_cross_farm_destination_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="other-farm-mv", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=other_farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code="gh-other", name="GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    with pytest.raises(LocationNotFoundError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=other_greenhouse.id, reason=None,
        )


@pytest.mark.integration
def test_inactive_occupant_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    scenario["trolley"].status = "inactive"
    db_session.flush()
    with pytest.raises(InactiveOccupantError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
        )


@pytest.mark.integration
def test_inactive_destination_location_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    scenario["chambers"]["GC-02"].status = "inactive"
    db_session.flush()
    with pytest.raises(InactiveTargetError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
        )


@pytest.mark.integration
def test_asset_cannot_occupy_own_position_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    with pytest.raises(AssetCannotOccupyOwnPositionError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="asset_position", destination_id=scenario["slot_03_04"].id, reason=None,
        )


@pytest.mark.integration
def test_effective_time_in_future_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    with pytest.raises(InvalidEffectiveTimeError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now() + timedelta(days=1),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
        )


@pytest.mark.integration
def test_effective_time_before_current_occupancy_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    too_early = scenario["trolley_movement"].effective_time - timedelta(days=1)
    with pytest.raises(InvalidEffectiveTimeError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=too_early,
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
        )


@pytest.mark.integration
def test_failed_movement_preserves_original_occupancy(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    other_trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code="GT-0003", name="Trolley 3", commissioned_date=None,
    )
    with pytest.raises(TargetOccupiedError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=other_trolley.id,
            destination_kind="location", destination_id=scenario["chambers"]["GC-01"].id, reason=None,
        )
    occupancy = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="asset", occupant_id=scenario["trolley"].id
    )
    assert occupancy.target_location_id == scenario["chambers"]["GC-01"].id
    assert occupancy.end_time is None


@pytest.mark.integration
def test_failed_movement_creates_no_movement_or_audit_event(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    movements_before = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    audits_before = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "movement.executed")
    ).scalar_one()

    with pytest.raises(NoOpMovementError):
        movement_service.execute_movement(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), effective_time=_now(),
            occupant_kind="asset", occupant_id=scenario["trolley"].id,
            destination_kind="location", destination_id=scenario["chambers"]["GC-01"].id, reason=None,
        )

    movements_after = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    audits_after = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "movement.executed")
    ).scalar_one()
    assert movements_after == movements_before
    assert audits_after == audits_before


@pytest.mark.integration
def test_direct_sql_movement_update_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE movements SET reason = 'tampered' WHERE id = :id"),
                {"id": scenario["trolley_movement"].id},
            )


@pytest.mark.integration
def test_direct_sql_movement_delete_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM movements WHERE id = :id"), {"id": scenario["trolley_movement"].id})


@pytest.mark.integration
def test_direct_sql_occupancy_delete_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    occupancy = movement_service.get_occupancy(
        db_session, tenant_id=scenario["tenant"].id, farm_id=scenario["farm"].id,
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
    )
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM occupancies WHERE id = :id"), {"id": occupancy.id})


@pytest.mark.integration
def test_closed_occupancy_cannot_be_reopened(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    old_occupancy = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="asset", occupant_id=scenario["trolley"].id
    )
    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
        destination_kind="location", destination_id=scenario["chambers"]["GC-02"].id, reason=None,
    )
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE occupancies SET end_time = NULL, closed_by_movement_id = NULL WHERE id = :id"),
                {"id": old_occupancy.id},
            )


@pytest.mark.integration
def test_occupancy_cannot_be_inserted_already_closed(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm = scenario["tenant"], scenario["farm"]
    other_trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=None,
        asset_type_code="germination_trolley", code="GT-0004", name="Trolley 4", commissioned_date=None,
    )
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO occupancies (id, tenant_id, farm_id, occupant_asset_id, target_location_id, "
                    "effective_time, end_time, opened_by_movement_id, closed_by_movement_id) "
                    "VALUES (:id, :tenant_id, :farm_id, :asset_id, :location_id, now(), now(), :movement_id, :movement_id)"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id,
                    "asset_id": other_trolley.id, "location_id": scenario["chambers"]["GC-02"].id,
                    "movement_id": scenario["trolley_movement"].id,
                },
            )


@pytest.mark.integration
def test_opening_movement_destination_mismatch_rejected(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm = scenario["tenant"], scenario["farm"]
    other_trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=None,
        asset_type_code="germination_trolley", code="GT-0005", name="Trolley 5", commissioned_date=None,
    )
    # trolley_movement's destination is P12, but we try to open an occupancy at P13.
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO occupancies (id, tenant_id, farm_id, occupant_asset_id, target_location_id, "
                    "effective_time, opened_by_movement_id) "
                    "VALUES (:id, :tenant_id, :farm_id, :asset_id, :location_id, now(), :movement_id)"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id,
                    "asset_id": other_trolley.id, "location_id": scenario["chambers"]["GC-02"].id,
                    "movement_id": scenario["trolley_movement"].id,
                },
            )
