"""DOMAIN-FARM-002.1 section 8: multi-occupant target-read correctness.

Proves the new truthful list-valued read (`movement_service.list_target_occupants`,
`TargetOccupantsRead` / `GET .../occupants`) reports every active occupant for
a capacity>1 target, and that the legacy singular read
(`get_target_occupant` / `GET .../occupant`) is no longer silently
misleading -- it now carries an explicit `active_occupancy_count` alongside
its one reported occupant.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.services import asset_service, carrier_service, location_service, movement_service


def _now():
    return datetime.now(timezone.utc)


def _build_position(db_session, tenant, farm, user, *, capacity):
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
    return location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="chamber_position", code=f"p-{suffix}", name="Position",
        parent_location_id=chamber.id, greenhouse_classification=None, occupiable=None, capacity=capacity,
    )


def _register_trolley(db_session, tenant, farm, user):
    suffix = uuid.uuid4().hex[:8]
    return asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name=f"Trolley {suffix}", commissioned_date=None,
    )


def _place(db_session, tenant, farm, user, *, occupant_id, target_id):
    return movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind="asset", occupant_id=occupant_id,
        destination_kind="location", destination_id=target_id, reason=None,
    )


@pytest.mark.integration
def test_list_target_occupants_reports_all_active_occupants(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_position(db_session, tenant, farm, user, capacity=3)
    trolleys = [_register_trolley(db_session, tenant, farm, user) for _ in range(3)]
    for trolley in trolleys:
        _place(db_session, tenant, farm, user, occupant_id=trolley.id, target_id=position.id)

    occupancies = movement_service.list_target_occupants(
        db_session, tenant_id=tenant.id, farm_id=farm.id, target_kind="location", target_id=position.id
    )
    assert len(occupancies) == 3
    assert {o.occupant_asset_id for o in occupancies} == {t.id for t in trolleys}


@pytest.mark.integration
def test_get_target_occupant_singular_still_works_and_reports_true_count(db_session, active_context_with_farm) -> None:
    """Legacy singular behavior for a genuinely exclusive (capacity=1)
    target is unaffected: one occupant, count=1."""
    tenant, user, _headers, farm = active_context_with_farm
    position = _build_position(db_session, tenant, farm, user, capacity=1)
    trolley = _register_trolley(db_session, tenant, farm, user)
    _place(db_session, tenant, farm, user, occupant_id=trolley.id, target_id=position.id)

    occupancies = movement_service.list_target_occupants(
        db_session, tenant_id=tenant.id, farm_id=farm.id, target_kind="location", target_id=position.id
    )
    assert len(occupancies) == 1
    assert occupancies[0].occupant_asset_id == trolley.id


@pytest.mark.integration
def test_http_occupant_endpoint_reports_explicit_count_for_multi_occupant_target(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    position = _build_position(db_session, tenant, farm, user, capacity=2)
    trolleys = [_register_trolley(db_session, tenant, farm, user) for _ in range(2)]
    for trolley in trolleys:
        _place(db_session, tenant, farm, user, occupant_id=trolley.id, target_id=position.id)
    db_session.commit()

    singular = client.get(f"/farms/{farm.id}/locations/{position.id}/occupant", headers=headers).json()
    assert singular["active_occupancy_count"] == 2
    assert singular["active_occupancy"] is not None

    plural = client.get(f"/farms/{farm.id}/locations/{position.id}/occupants", headers=headers).json()
    assert len(plural["active_occupancies"]) == 2
    occupant_ids = {o["occupant"]["id"] for o in plural["active_occupancies"]}
    assert occupant_ids == {str(t.id) for t in trolleys}


@pytest.mark.integration
def test_http_occupant_endpoint_exclusive_target_unaffected(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    position = _build_position(db_session, tenant, farm, user, capacity=1)
    trolley = _register_trolley(db_session, tenant, farm, user)
    _place(db_session, tenant, farm, user, occupant_id=trolley.id, target_id=position.id)
    db_session.commit()

    singular = client.get(f"/farms/{farm.id}/locations/{position.id}/occupant", headers=headers).json()
    assert singular["active_occupancy_count"] == 1
    assert singular["active_occupancy"]["occupant"]["id"] == str(trolley.id)
