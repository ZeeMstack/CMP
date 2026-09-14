"""PILOT-OPS-001: transaction-backed (OPERATIONAL_RECORD) completion --
`farm_work_item_service.link_operational_result` and its best-effort
wrapper. Real Harvest/Observation integration lives in
test_harvest_work_item_integration.py / test_observation_work_item_integration.py;
this file proves the reusable linking mechanism itself in isolation."""
import uuid
from datetime import datetime, timezone

import pytest

from app.services import farm_work_item_service
from app.services.errors import (
    FarmWorkItemCommandReusedWithDifferentPayloadError,
    FarmWorkItemResultConflictError,
    FarmWorkItemWrongCompletionModeError,
)


def _now():
    return datetime.now(timezone.utc)


def _create_operational_item(db_session, tenant, farm, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        work_type="harvest", category="harvest", title="Harvest Batch B-1", instructions=None, priority="normal",
        due_at=None, assigned_to_user_id=None, crop_batch_id=None, location_id=None, carrier_id=None,
        asset_id=None, quantity=None, quantity_uom_id=None, completion_mode="operational_record",
    )
    defaults.update(overrides)
    return farm_work_item_service.create_work_item(db_session, **defaults)


@pytest.mark.integration
def test_link_completes_item_with_result_reference(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_operational_item(db_session, tenant, farm, user)
    result_id = uuid.uuid4()

    completed = farm_work_item_service.link_operational_result(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=uuid.uuid4(), result_entity_type="harvest_event", result_entity_id=result_id,
        effective_time=_now(),
    )
    assert completed.status == "completed"
    assert completed.result_entity_type == "harvest_event"
    assert completed.result_entity_id == result_id
    assert completed.completed_by_user_id is None  # operational-record: no manual completer


@pytest.mark.integration
def test_replay_with_same_client_command_id_does_not_duplicate(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_operational_item(db_session, tenant, farm, user)
    result_id = uuid.uuid4()
    command_id = uuid.uuid4()

    first = farm_work_item_service.link_operational_result(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=command_id, result_entity_type="harvest_event", result_entity_id=result_id,
        effective_time=_now(),
    )
    second = farm_work_item_service.link_operational_result(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=command_id, result_entity_type="harvest_event", result_entity_id=result_id,
        effective_time=_now(),
    )
    assert first.id == second.id == item.id
    assert first.result_entity_id == result_id


@pytest.mark.integration
def test_replay_with_different_client_command_id_same_result_is_idempotent_noop(
    db_session, active_context_with_farm
) -> None:
    """A UI reconciliation retry (fresh client_command_id) pointing at the
    SAME already-linked result must never fail or duplicate -- this is the
    literal "retry/replay does not create duplicate Work Item completion"
    acceptance requirement."""
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_operational_item(db_session, tenant, farm, user)
    result_id = uuid.uuid4()

    farm_work_item_service.link_operational_result(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=uuid.uuid4(), result_entity_type="harvest_event", result_entity_id=result_id,
        effective_time=_now(),
    )
    retried = farm_work_item_service.link_operational_result(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=uuid.uuid4(), result_entity_type="harvest_event", result_entity_id=result_id,
        effective_time=_now(),
    )
    assert retried.status == "completed"
    assert retried.result_entity_id == result_id


@pytest.mark.integration
def test_different_result_on_already_completed_item_is_a_conflict(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_operational_item(db_session, tenant, farm, user)
    farm_work_item_service.link_operational_result(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=uuid.uuid4(), result_entity_type="harvest_event", result_entity_id=uuid.uuid4(),
        effective_time=_now(),
    )
    with pytest.raises(FarmWorkItemResultConflictError):
        farm_work_item_service.link_operational_result(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
            client_command_id=uuid.uuid4(), result_entity_type="harvest_event", result_entity_id=uuid.uuid4(),
            effective_time=_now(),
        )


@pytest.mark.integration
def test_link_rejected_for_manual_record_item(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_operational_item(db_session, tenant, farm, user, completion_mode="manual_record")
    with pytest.raises(FarmWorkItemWrongCompletionModeError):
        farm_work_item_service.link_operational_result(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
            client_command_id=uuid.uuid4(), result_entity_type="harvest_event", result_entity_id=uuid.uuid4(),
            effective_time=_now(),
        )


@pytest.mark.integration
def test_best_effort_wrapper_never_raises_and_reports_status(db_session, active_context_with_farm) -> None:
    """Simulates the Harvest/Observation call-site contract: the
    authoritative operation has already committed, so a link failure must
    never propagate as an exception (CLAUDE.md "Transaction-backed
    completion")."""
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_operational_item(db_session, tenant, farm, user)

    ok_status = farm_work_item_service.link_operational_result_best_effort(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=uuid.uuid4(), result_entity_type="harvest_event", result_entity_id=uuid.uuid4(),
        effective_time=_now(),
    )
    assert ok_status == "linked"

    # A nonexistent work item is a realistic failure mode (bad id from a
    # stale client) -- must report "failed", never raise.
    failed_status = farm_work_item_service.link_operational_result_best_effort(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=uuid.uuid4(),
        client_command_id=uuid.uuid4(), result_entity_type="harvest_event", result_entity_id=uuid.uuid4(),
        effective_time=_now(),
    )
    assert failed_status == "failed"
