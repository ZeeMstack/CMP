import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from app.services import carrier_service, location_service, movement_service


def _now():
    return datetime.now(timezone.utc)


@pytest.mark.integration
def test_asset_resolved_location_direct_placement(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm = scenario["tenant"], scenario["farm"]
    resolved = movement_service.get_resolved_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="asset", occupant_id=scenario["trolley"].id
    )
    assert resolved["direct_target"] == {"kind": "location", "id": scenario["positions"]["P12"].id}
    assert resolved["unresolved_reason"] is None
    codes = [entry["code"] for entry in resolved["fixed_location_path"]]
    assert codes == ["nursery-gh", "GC-01", "P12"]
    assert resolved["path_string"] == "nursery-gh / GC-01 / P12"


@pytest.mark.integration
def test_carrier_resolved_location_via_trolley(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm = scenario["tenant"], scenario["farm"]
    resolved = movement_service.get_resolved_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=scenario["tray"].id
    )
    assert resolved["direct_target"] == {"kind": "asset_position", "id": scenario["slot_03_04"].id}
    assert [e["code"] for e in resolved["position_path"]] == ["SH-03", "SL-04"]
    assert resolved["containing_asset"]["code"] == "GT-0001"
    assert [e["code"] for e in resolved["fixed_location_path"]] == ["nursery-gh", "GC-01", "P12"]
    assert resolved["path_string"] == "nursery-gh / GC-01 / P12 / GT-0001 / SH-03 / SL-04"
    assert resolved["unresolved_reason"] is None


@pytest.mark.integration
def test_moving_trolley_updates_tray_resolved_location_without_changing_tray_occupancy(
    db_session, placed_trolley_and_tray
) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]
    tray_occupancy_before = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=scenario["tray"].id
    )

    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
        destination_kind="location", destination_id=scenario["positions"]["P13"].id, reason=None,
    )

    resolved = movement_service.get_resolved_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=scenario["tray"].id
    )
    assert resolved["fixed_location_path"][-1]["code"] == "P13"

    tray_occupancy_after = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=scenario["tray"].id
    )
    assert tray_occupancy_after.id == tray_occupancy_before.id
    assert tray_occupancy_after.target_asset_position_id == scenario["slot_03_04"].id


@pytest.mark.integration
def test_carrier_resolved_location_unresolved_when_trolley_unplaced(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm, user = scenario["tenant"], scenario["farm"], scenario["user"]

    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind="asset", occupant_id=scenario["trolley"].id,
        destination_kind=None, destination_id=None, reason="removed",
    )

    resolved = movement_service.get_resolved_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=scenario["tray"].id
    )
    assert resolved["fixed_location_path"] is None
    assert resolved["unresolved_reason"] == "containing asset has no active fixed-location occupancy"
    # The tray itself is unaffected by the trolley's removal.
    assert resolved["position_path"] is not None
    assert resolved["containing_asset"]["code"] == "GT-0001"


@pytest.mark.integration
def test_direct_carrier_placement_in_fixed_location_resolved(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code="vine-gh", name="Vine GH",
        parent_location_id=None, greenhouse_classification="vines", occupiable=None,
    )
    zone = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="zone", code="zone-1", name="Zone",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=None,
    )
    span = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="span", code="span-1", name="Span",
        parent_location_id=zone.id, greenhouse_classification=None, occupiable=None,
    )
    gutter = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="grow_gutter", code="gutter-1", name="Gutter",
        parent_location_id=span.id, greenhouse_classification=None, occupiable=None,
    )
    bag_position = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="grow_bag_position", code="BP-01", name="Bag Position 1",
        parent_location_id=gutter.id, greenhouse_classification=None, occupiable=None,
    )
    grow_bag = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="grow_bag", code="GB-00001", issued_date=None,
    )
    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind="carrier", occupant_id=grow_bag.id,
        destination_kind="location", destination_id=bag_position.id, reason=None,
    )
    resolved = movement_service.get_resolved_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=grow_bag.id
    )
    assert resolved["position_path"] is None
    assert resolved["containing_asset"] is None
    assert [e["code"] for e in resolved["fixed_location_path"]] == ["vine-gh", "zone-1", "span-1", "gutter-1", "BP-01"]


@pytest.mark.integration
def test_resolved_location_avoids_n_plus_1_queries(db_session, placed_trolley_and_tray) -> None:
    scenario = placed_trolley_and_tray
    tenant, farm = scenario["tenant"], scenario["farm"]
    statement_count = 0

    def _count(*args, **kwargs) -> None:
        nonlocal statement_count
        statement_count += 1

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", _count)
    try:
        movement_service.get_resolved_location(
            db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="carrier", occupant_id=scenario["tray"].id
        )
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    # A handful of scoped queries/CTEs, not one query per ancestor in either
    # the position path (2 levels) or the fixed-location path (3 levels) —
    # a naive per-ancestor implementation would scale with depth well past this.
    assert statement_count <= 12, statement_count
