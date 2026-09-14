"""PILOT-OPS-001: Farm Work Item service-layer lifecycle, idempotency, and
tenant-isolation tests. HTTP-layer/authorization tests live in
test_farm_work_item_http.py; transaction-backed (operational-record)
completion in test_farm_work_item_operational_completion.py."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services import farm_work_item_service, membership_service, tenant_service, user_service
from app.services.errors import (
    FarmWorkItemCommandReusedWithDifferentPayloadError,
    FarmWorkItemInvalidTransitionError,
    FarmWorkItemManualCompletionNotAllowedError,
    FarmWorkItemNotAssignableError,
    FarmWorkItemNotFoundError,
    UserNotFoundError,
)


def _now():
    return datetime.now(timezone.utc)


def _create_manual_item(db_session, tenant, farm, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        work_type="cleaning", category="cleaning", title="Clean Germination Trolley 03", instructions=None,
        priority="normal", due_at=None, assigned_to_user_id=None, crop_batch_id=None, location_id=None,
        carrier_id=None, asset_id=None, quantity=None, quantity_uom_id=None, completion_mode="manual_record",
    )
    defaults.update(overrides)
    return farm_work_item_service.create_work_item(db_session, **defaults)


@pytest.mark.integration
def test_create_generates_human_readable_code_and_open_status(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_manual_item(db_session, tenant, farm, user)
    assert item.status == "open"
    assert item.code.startswith("FW-")
    assert item.completion_mode == "manual_record"


@pytest.mark.integration
def test_create_exact_replay_returns_original(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    command_id = uuid.uuid4()
    first = _create_manual_item(db_session, tenant, farm, user, client_command_id=command_id)
    second = _create_manual_item(db_session, tenant, farm, user, client_command_id=command_id)
    assert first.id == second.id


@pytest.mark.integration
def test_create_same_command_id_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    command_id = uuid.uuid4()
    _create_manual_item(db_session, tenant, farm, user, client_command_id=command_id, title="A")
    with pytest.raises(FarmWorkItemCommandReusedWithDifferentPayloadError):
        _create_manual_item(db_session, tenant, farm, user, client_command_id=command_id, title="B")


@pytest.mark.integration
def test_create_rejects_unknown_assignee(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(UserNotFoundError):
        _create_manual_item(db_session, tenant, farm, user, assigned_to_user_id=uuid.uuid4())


# --- lifecycle ---------------------------------------------------------------------


@pytest.mark.integration
def test_start_requires_open_status(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_manual_item(db_session, tenant, farm, user)
    started = farm_work_item_service.start_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=uuid.uuid4(),
    )
    assert started.status == "in_progress"
    with pytest.raises(FarmWorkItemInvalidTransitionError):
        farm_work_item_service.start_work_item(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
            client_command_id=uuid.uuid4(),
        )


@pytest.mark.integration
def test_operator_cannot_start_work_assigned_to_someone_else(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    other = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=uuid.uuid4().hex, email="other@example.com", display_name="Other"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=other.id, role_code="operator", actor_user_id=None
    )
    item = _create_manual_item(db_session, tenant, farm, user, assigned_to_user_id=other.id)
    with pytest.raises(FarmWorkItemNotAssignableError):
        farm_work_item_service.start_work_item(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
            client_command_id=uuid.uuid4(),
        )


@pytest.mark.integration
def test_block_requires_reason_and_records_it(db_session, active_context_with_farm) -> None:
    """Schema-level enforcement (blank/missing `reason` rejected before this
    service function is ever reached) is proved in
    test_farm_work_item_http.py::test_block_without_reason_rejected; this
    proves the service records the reason it is given."""
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_manual_item(db_session, tenant, farm, user)
    blocked = farm_work_item_service.block_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=uuid.uuid4(), reason="destination full",
    )
    assert blocked.status == "blocked"
    assert blocked.blocked_reason == "destination full"
    assert blocked.blocked_by_user_id == user.id


@pytest.mark.integration
def test_unblock_resumes_to_in_progress_and_clears_reason(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_manual_item(db_session, tenant, farm, user)
    farm_work_item_service.block_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=uuid.uuid4(), reason="equipment unavailable",
    )
    resumed = farm_work_item_service.unblock_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=uuid.uuid4(),
    )
    assert resumed.status == "in_progress"
    assert resumed.blocked_reason is None
    assert resumed.blocked_by_user_id is None


@pytest.mark.integration
def test_manual_completion_records_operator_and_time(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_manual_item(db_session, tenant, farm, user)
    before = _now()
    completed = farm_work_item_service.complete_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=uuid.uuid4(), completion_note="done",
    )
    assert completed.status == "completed"
    assert completed.completed_by_user_id == user.id
    assert completed.completed_at is not None and completed.completed_at >= before
    assert completed.completion_note == "done"


@pytest.mark.integration
def test_manual_complete_rejected_for_operational_record_item(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_manual_item(db_session, tenant, farm, user, work_type="harvest", category="harvest",
                                title="Harvest Batch B-1", completion_mode="operational_record")
    with pytest.raises(FarmWorkItemManualCompletionNotAllowedError):
        farm_work_item_service.complete_work_item(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
            client_command_id=uuid.uuid4(), completion_note=None,
        )


@pytest.mark.integration
def test_cancel_is_terminal_and_idempotent_on_replay(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_manual_item(db_session, tenant, farm, user)
    command_id = uuid.uuid4()
    cancelled = farm_work_item_service.cancel_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=command_id, reason="no longer needed",
    )
    assert cancelled.status == "cancelled"
    replay = farm_work_item_service.cancel_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=command_id, reason="no longer needed",
    )
    assert replay.id == cancelled.id
    with pytest.raises(FarmWorkItemInvalidTransitionError):
        farm_work_item_service.cancel_work_item(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
            client_command_id=uuid.uuid4(), reason="again",
        )


# --- due window / carryover-relevant persistence ------------------------------------


@pytest.mark.integration
def test_due_at_persists_for_carryover_classification(db_session, active_context_with_farm) -> None:
    """The board's Carryover section is derived client-side from `due_at`
    (see docs/domain/FARM_WORK_ITEM_MODEL.md) -- the backend's only
    obligation is storing and returning it faithfully."""
    tenant, user, _headers, farm = active_context_with_farm
    yesterday = _now() - timedelta(days=1)
    item = _create_manual_item(db_session, tenant, farm, user, due_at=yesterday)
    fetched = farm_work_item_service.get_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, work_item_id=item.id
    )
    assert fetched.due_at == yesterday


# --- tenant isolation ----------------------------------------------------------------


@pytest.mark.integration
def test_foreign_tenant_cannot_read_or_mutate_work_item(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    item = _create_manual_item(db_session, tenant, farm, user)

    tenant_b = tenant_service.create_tenant(db_session, code=f"fwi-b-{uuid.uuid4().hex[:8]}", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=uuid.uuid4().hex, email="b@example.com", display_name="B"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )

    with pytest.raises(FarmWorkItemNotFoundError):
        farm_work_item_service.get_work_item(
            db_session, tenant_id=tenant_b.id, farm_id=farm.id, work_item_id=item.id
        )
    with pytest.raises(FarmWorkItemNotFoundError):
        farm_work_item_service.start_work_item(
            db_session, tenant_id=tenant_b.id, farm_id=farm.id, actor_user_id=user_b.id, work_item_id=item.id,
            client_command_id=uuid.uuid4(),
        )


@pytest.mark.integration
def test_list_work_items_excludes_terminal_statuses_by_default(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    open_item = _create_manual_item(db_session, tenant, farm, user, title="Open")
    completed_item = _create_manual_item(db_session, tenant, farm, user, title="Will complete")
    farm_work_item_service.complete_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=completed_item.id,
        client_command_id=uuid.uuid4(), completion_note=None,
    )
    cancelled_item = _create_manual_item(db_session, tenant, farm, user, title="Will cancel")
    farm_work_item_service.cancel_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=cancelled_item.id,
        client_command_id=uuid.uuid4(), reason=None,
    )

    default_list = farm_work_item_service.list_work_items(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert [i.id for i in default_list] == [open_item.id]

    with_completed = farm_work_item_service.list_work_items(
        db_session, tenant_id=tenant.id, farm_id=farm.id, include_completed=True
    )
    ids_with_completed = {i.id for i in with_completed}
    assert open_item.id in ids_with_completed
    assert completed_item.id in ids_with_completed
    assert cancelled_item.id in ids_with_completed


@pytest.mark.integration
def test_list_work_items_scoped_to_farm_and_assignee(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    mine = _create_manual_item(db_session, tenant, farm, user, assigned_to_user_id=user.id, title="Mine")
    _create_manual_item(db_session, tenant, farm, user, title="Unassigned")
    items = farm_work_item_service.list_work_items(
        db_session, tenant_id=tenant.id, farm_id=farm.id, assigned_to_user_id=user.id
    )
    assert [i.id for i in items] == [mine.id]
