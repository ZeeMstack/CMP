"""PILOT-OPS-001: Observation -> Farm Work Item linkage (priority
integration #2). Proves a successful Observation completes a linked
OPERATIONAL_RECORD Work Item with the real observation_event id, and that
the Work Item's own Batch/context (set at creation, before the Observation
ever ran) is preserved untouched by the link -- linking only ever writes
the result reference, never the context fields."""
import uuid
from datetime import datetime, timezone

import pytest

from app.services import (
    crop_batch_service,
    crop_service,
    farm_work_item_service,
    observation_service,
    production_system_service,
    workflow_service,
)


def _now():
    return datetime.now(timezone.utc)


def _build_batch_with_definition(db_session, tenant, user, farm, *, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Leafy",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=None,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    growing = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="GROWING", name="Growing", display_order=0, stage_category="production",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=True, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=growing.id, to_stage_id=complete.id, code="ADV-1", name="Advance 1",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    definition = observation_service.register_observation_definition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"DEF-{suffix}", name="Plant height",
        description=None, value_type="decimal", unit="cm", target_scope="crop_batch", min_value=None, max_value=None,
    )
    return {"batch": batch, "definition": definition}


@pytest.mark.integration
def test_observation_with_work_item_completes_it_and_preserves_batch_context(
    client, active_context_with_farm, db_session, monkeypatch
) -> None:
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)

    tenant, user, headers, farm = active_context_with_farm
    scenario = _build_batch_with_definition(db_session, tenant, user, farm)

    work_item = farm_work_item_service.create_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        work_type="observation", category="crop_care", title="Record plant height", instructions=None,
        priority="normal", due_at=None, assigned_to_user_id=None, crop_batch_id=scenario["batch"].id,
        location_id=None, carrier_id=None, asset_id=None, quantity=None, quantity_uom_id=None,
        completion_mode="operational_record",
    )

    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/observations",
        json={
            "client_command_id": str(uuid.uuid4()),
            "effective_time": _now().isoformat(),
            "note": None,
            "values": [
                {"observation_definition_id": str(scenario["definition"].id), "value_decimal": "12.5"}
            ],
            "work_item_id": str(work_item.id),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["work_item_link_status"] == "linked"
    observation_event_id = body["id"]
    assert body["batch_id"] == str(scenario["batch"].id)

    updated = farm_work_item_service.get_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, work_item_id=work_item.id
    )
    assert updated.status == "completed"
    assert updated.result_entity_type == "observation_event"
    assert str(updated.result_entity_id) == observation_event_id
    # Context set at creation -- never overwritten by linking.
    assert updated.crop_batch_id == scenario["batch"].id
