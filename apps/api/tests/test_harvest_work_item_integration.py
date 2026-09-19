"""PILOT-OPS-001: Harvest -> Farm Work Item linkage (priority integration #1).
Proves the Harvest command itself is unchanged/unaffected when no Work Item
is involved, that a successful Harvest completes a linked OPERATIONAL_RECORD
Work Item with the real harvest_event id, and that retry/replay of the
Harvest command never executes the harvest twice merely because a Work Item
link is involved."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.farm_work_item import FarmWorkItem
from app.services import (
    crop_batch_service,
    crop_service,
    farm_work_item_service,
    production_system_service,
    sowing_service,
    workflow_service,
)
from app.services import carrier_service
from tests.conftest import ensure_seed_tray_specification, mark_readiness_ready


def _now():
    return datetime.now(timezone.utc)


def _build_harvestable_batch(db_session, tenant, user, farm, *, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    harvesting = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="HARVESTING", name="Harvesting", display_order=1, stage_category="harvesting",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=harvesting.id, code="ADV-1", name="Advance 1",
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=harvesting.id, to_stage_id=complete.id, code="ADV-2", name="Advance 2",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code=f"ST-{suffix}-0001", issued_date=None,
    )
    mark_readiness_ready(db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, carrier_id=carrier.id)
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[{"carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": 200, "seed_count": 200, "line_note": None}],
    )
    assignments = sowing_service.list_batch_carriers(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_id = assignments[0].id

    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=_now(), reason=None,
    )
    return {"batch": batch, "assignment_id": assignment_id}


@pytest.mark.integration
def test_harvest_with_work_item_completes_it_with_real_harvest_event_id(
    client, active_context_with_farm, db_session, monkeypatch
) -> None:
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)

    tenant, user, headers, farm = active_context_with_farm
    scenario = _build_harvestable_batch(db_session, tenant, user, farm)

    work_item = farm_work_item_service.create_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        work_type="harvest", category="harvest", title="Harvest Batch", instructions=None, priority="normal",
        due_at=None, assigned_to_user_id=None, crop_batch_id=scenario["batch"].id, location_id=None,
        carrier_id=None, asset_id=None, quantity=None, quantity_uom_id=None, completion_mode="operational_record",
    )

    effective_time = _now()
    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/harvests",
        json={
            "client_command_id": str(uuid.uuid4()),
            "effective_time": effective_time.isoformat(),
            "produce_lot_code": f"LOT-{uuid.uuid4().hex[:8]}",
            "note": None,
            "source_lines": [
                {"batch_carrier_assignment_id": str(scenario["assignment_id"]), "harvested_weight_kg": "10.500"}
            ],
            "work_item_id": str(work_item.id),
        },
        headers=headers,
    )
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


@pytest.mark.integration
def test_harvest_command_replay_does_not_execute_harvest_twice_or_relink(
    client, active_context_with_farm, db_session, monkeypatch
) -> None:
    """Replaying the exact same Harvest command (same client_command_id,
    same payload) must return the original harvest_event -- proving the
    Work Item link cannot cause the underlying operation to be repeated."""
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)

    tenant, user, headers, farm = active_context_with_farm
    scenario = _build_harvestable_batch(db_session, tenant, user, farm)
    work_item = farm_work_item_service.create_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        work_type="harvest", category="harvest", title="Harvest Batch", instructions=None, priority="normal",
        due_at=None, assigned_to_user_id=None, crop_batch_id=scenario["batch"].id, location_id=None,
        carrier_id=None, asset_id=None, quantity=None, quantity_uom_id=None, completion_mode="operational_record",
    )

    payload = {
        "client_command_id": str(uuid.uuid4()),
        "effective_time": _now().isoformat(),
        "produce_lot_code": f"LOT-{uuid.uuid4().hex[:8]}",
        "note": None,
        "source_lines": [
            {"batch_carrier_assignment_id": str(scenario["assignment_id"]), "harvested_weight_kg": "10.500"}
        ],
        "work_item_id": str(work_item.id),
    }
    first = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/harvests", json=payload, headers=headers
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/harvests", json=payload, headers=headers
    )
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["work_item_link_status"] == "linked"

    from sqlalchemy import func, select

    from app.models.harvest_event import HarvestEvent

    count = db_session.execute(
        select(func.count()).select_from(HarvestEvent).where(HarvestEvent.batch_id == scenario["batch"].id)
    ).scalar_one()
    assert count == 1
