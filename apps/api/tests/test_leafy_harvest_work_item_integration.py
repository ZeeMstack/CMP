"""PILOT-OPS-001 closure: Leafy Harvest -> Farm Work Item linkage, through
the REAL operator-facing route (`POST /farms/{farm_id}/leafy-production/
harvests`) -- the generic `/crop-batches/{batch_id}/harvests` integration
already proven in test_harvest_work_item_integration.py is a different route
the Leafy operator UI never calls. Reuses the exact real-service scenario
helper `test_leafy_harvest_api.py` itself reuses, never a fabricated Plate."""
import uuid
from datetime import timedelta

import pytest

from app.models.harvest_event import HarvestEvent
from app.services import farm_work_item_service
from tests.test_production_disposition import _plate_scenario

pytestmark = pytest.mark.integration


def _record_payload(batch_id, assignment_id, *, work_item_id=None, client_command_id=None, weight="50.000"):
    return {
        "client_command_id": str(client_command_id or uuid.uuid4()),
        "batch_id": str(batch_id),
        "effective_time": None,  # filled in per call
        "produce_lot_code": f"HL-{uuid.uuid4().hex[:8]}",
        "note": None,
        "source_lines": [
            {"batch_carrier_assignment_id": str(assignment_id), "whole_unit_count": 100, "harvested_weight_kg": weight, "note": None}
        ],
        "work_item_id": str(work_item_id) if work_item_id else None,
    }


def _create_operational_item(db_session, tenant, farm, user, batch_id):
    return farm_work_item_service.create_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        work_type="harvest", category="harvest", title="Harvest Leafy Plate", instructions=None, priority="normal",
        due_at=None, assigned_to_user_id=None, crop_batch_id=batch_id, location_id=None, carrier_id=None,
        asset_id=None, quantity=None, quantity_uom_id=None, completion_mode="operational_record",
    )


def test_leafy_harvest_with_work_item_completes_it_with_real_harvest_event_id(
    client, db_session, active_context_with_farm
) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    work_item = _create_operational_item(db_session, tenant, farm, user, batch.id)

    payload = _record_payload(batch.id, root_id, work_item_id=work_item.id)
    payload["effective_time"] = (t0 + timedelta(hours=1)).isoformat()

    resp = client.post(f"/farms/{farm.id}/leafy-production/harvests", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["work_item_link_status"] == "linked"
    harvest_event_id = body["id"]

    updated = farm_work_item_service.get_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, work_item_id=work_item.id
    )
    assert updated.status == "completed"
    assert updated.result_entity_type == "harvest_event"
    assert str(updated.result_entity_id) == harvest_event_id


def test_leafy_harvest_succeeds_even_when_work_item_link_target_is_invalid(
    client, db_session, active_context_with_farm
) -> None:
    """The closure requirement: a Harvest must never be blocked, undone, or
    retried merely because its Work Item link fails -- here the Work Item
    id doesn't exist at all (e.g. a stale/foreign id), the sharpest version
    of a link failure. The Harvest itself must still succeed, keep its real
    Harvest Lot, and report the link outcome as "failed" rather than
    silently swallowing it."""
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)

    payload = _record_payload(batch.id, root_id, work_item_id=uuid.uuid4())
    payload["effective_time"] = (t0 + timedelta(hours=1)).isoformat()

    resp = client.post(f"/farms/{farm.id}/leafy-production/harvests", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["work_item_link_status"] == "failed"
    assert body["produce_lot_id"] is not None
    # canonical_decimal_str strips trailing zeros -- "50.000" normalizes to "50".
    assert body["current_total_harvested_weight_kg"] == "50"

    # No second Harvest was created by the failed-link path -- exactly one
    # HarvestEvent exists for this batch.
    from sqlalchemy import func, select

    count = db_session.execute(
        select(func.count()).select_from(HarvestEvent).where(HarvestEvent.batch_id == batch.id)
    ).scalar_one()
    assert count == 1


def test_leafy_harvest_replay_does_not_execute_harvest_twice_or_relink(
    client, db_session, active_context_with_farm
) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    work_item = _create_operational_item(db_session, tenant, farm, user, batch.id)

    command_id = uuid.uuid4()
    payload = _record_payload(batch.id, root_id, work_item_id=work_item.id, client_command_id=command_id)
    payload["effective_time"] = (t0 + timedelta(hours=1)).isoformat()

    first = client.post(f"/farms/{farm.id}/leafy-production/harvests", json=payload, headers=headers)
    assert first.status_code == 201, first.text
    second = client.post(f"/farms/{farm.id}/leafy-production/harvests", json=payload, headers=headers)
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["work_item_link_status"] == "linked"

    from sqlalchemy import func, select

    count = db_session.execute(
        select(func.count()).select_from(HarvestEvent).where(HarvestEvent.batch_id == batch.id)
    ).scalar_one()
    assert count == 1

    updated = farm_work_item_service.get_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, work_item_id=work_item.id
    )
    assert updated.status == "completed"
