"""PILOT-OPS-001 closure: Vines Harvest -> Farm Work Item linkage. Vines
Harvest shares the identical `HarvestEvent`/`HarvestedProduceLot` result
shape as Leafy (see app/api/vines_harvest.py's own PILOT-OPS-001 comment),
so the same reusable `link_operational_result_best_effort` wiring applies
unchanged. One representative proof (not the full Leafy matrix) -- Vines
was optional for this closure ticket."""
import uuid

import pytest

from app.models.harvest_event import HarvestEvent
from app.services import farm_work_item_service
from tests._vines_harvest_scenario import build_vines_harvest_ready_scenario

pytestmark = pytest.mark.integration


def _create_operational_item(db_session, tenant, farm, user, batch_id):
    return farm_work_item_service.create_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        work_type="harvest", category="harvest", title="Harvest Vines Gutter", instructions=None, priority="normal",
        due_at=None, assigned_to_user_id=None, crop_batch_id=batch_id, location_id=None, carrier_id=None,
        asset_id=None, quantity=None, quantity_uom_id=None, completion_mode="operational_record",
    )


def test_vines_harvest_with_work_item_completes_it_with_real_harvest_event_id(
    client, db_session, active_context_with_farm
) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(db_session, tenant, user, farm)
    work_item = _create_operational_item(db_session, tenant, farm, user, s["batch"].id)

    resp = client.post(
        f"/farms/{farm.id}/vines-production/harvests",
        json={
            "client_command_id": str(uuid.uuid4()), "batch_id": str(s["batch"].id),
            "effective_time": s["harvest_time"].isoformat(), "produce_lot_code": f"VHL-{uuid.uuid4().hex[:8]}",
            "note": None,
            "source_lines": [{"gutter_id": str(s["grow_gutter_id"]), "harvested_weight_kg": "10.000", "note": None}],
            "work_item_id": str(work_item.id),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["work_item_link_status"] == "linked"

    updated = farm_work_item_service.get_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, work_item_id=work_item.id
    )
    assert updated.status == "completed"
    assert updated.result_entity_type == "harvest_event"
    assert str(updated.result_entity_id) == body["id"]


def test_vines_harvest_succeeds_even_when_work_item_link_target_is_invalid(
    client, db_session, active_context_with_farm
) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = build_vines_harvest_ready_scenario(db_session, tenant, user, farm)

    resp = client.post(
        f"/farms/{farm.id}/vines-production/harvests",
        json={
            "client_command_id": str(uuid.uuid4()), "batch_id": str(s["batch"].id),
            "effective_time": s["harvest_time"].isoformat(), "produce_lot_code": f"VHL-{uuid.uuid4().hex[:8]}",
            "note": None,
            "source_lines": [{"gutter_id": str(s["grow_gutter_id"]), "harvested_weight_kg": "10.000", "note": None}],
            "work_item_id": str(uuid.uuid4()),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["work_item_link_status"] == "failed"
    assert resp.json()["produce_lot_id"] is not None

    from sqlalchemy import func, select

    count = db_session.execute(
        select(func.count()).select_from(HarvestEvent).where(HarvestEvent.batch_id == s["batch"].id)
    ).scalar_one()
    assert count == 1
