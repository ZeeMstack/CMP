"""PILOT-OPS-001: Shift Handover -- creation, latest-handover retrieval, and
the "never closes/clones referenced Work Items" invariant."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services import farm_work_item_service, shift_handover_service
from app.services.errors import FarmWorkItemNotFoundError, ShiftHandoverCommandReusedWithDifferentPayloadError


def _now():
    return datetime.now(timezone.utc)


def _create_item(db_session, tenant, farm, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        work_type="cleaning", category="cleaning", title="Clean Trolley", instructions=None, priority="normal",
        due_at=None, assigned_to_user_id=None, crop_batch_id=None, location_id=None, carrier_id=None,
        asset_id=None, quantity=None, quantity_uom_id=None, completion_mode="manual_record",
    )
    defaults.update(overrides)
    return farm_work_item_service.create_work_item(db_session, **defaults)


@pytest.mark.integration
def test_create_handover_references_work_items_without_closing_them(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    open_item = _create_item(db_session, tenant, farm, user, title="Open item")

    handover = shift_handover_service.create_handover(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), note="Trolley 03 still needs cleaning", work_item_ids=[open_item.id],
    )
    assert handover.note == "Trolley 03 still needs cleaning"
    referenced = shift_handover_service.get_handover_work_item_ids(db_session, handover_id=handover.id)
    assert referenced == [open_item.id]

    # The referenced Work Item is completely untouched: still OPEN, not
    # cloned into a second row.
    still_open = farm_work_item_service.get_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, work_item_id=open_item.id
    )
    assert still_open.status == "open"
    assert still_open.id == open_item.id


@pytest.mark.integration
def test_latest_handover_returns_most_recent_by_effective_time(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    older = shift_handover_service.create_handover(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now() - timedelta(hours=8), note="Morning shift note", work_item_ids=[],
    )
    newer = shift_handover_service.create_handover(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=_now(), note="Afternoon shift note", work_item_ids=[],
    )
    latest = shift_handover_service.get_latest_handover(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert latest.id == newer.id
    assert latest.id != older.id


@pytest.mark.integration
def test_handover_rejects_unknown_work_item(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(FarmWorkItemNotFoundError):
        shift_handover_service.create_handover(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            effective_time=_now(), note="note", work_item_ids=[uuid.uuid4()],
        )


@pytest.mark.integration
def test_handover_exact_replay_returns_original(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    command_id = uuid.uuid4()
    effective_time = _now()
    first = shift_handover_service.create_handover(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=command_id,
        effective_time=effective_time, note="note", work_item_ids=[],
    )
    second = shift_handover_service.create_handover(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=command_id,
        effective_time=effective_time, note="note", work_item_ids=[],
    )
    assert first.id == second.id


@pytest.mark.integration
def test_handover_same_command_id_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    command_id = uuid.uuid4()
    shift_handover_service.create_handover(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=command_id,
        effective_time=_now(), note="note A", work_item_ids=[],
    )
    with pytest.raises(ShiftHandoverCommandReusedWithDifferentPayloadError):
        shift_handover_service.create_handover(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=command_id,
            effective_time=_now(), note="note B", work_item_ids=[],
        )


# --- HTTP ------------------------------------------------------------------------


@pytest.fixture
def _dev_auth_enabled(monkeypatch):
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)


@pytest.mark.integration
def test_http_create_and_get_latest_handover(client, _dev_auth_enabled, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    resp = client.post(
        f"/farms/{farm.id}/shift-handovers",
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now().isoformat(),
            "note": "Everything nominal, GC-02 pump needs a look tomorrow.", "work_item_ids": [],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    latest = client.get(f"/farms/{farm.id}/shift-handovers/latest", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["id"] == resp.json()["id"]
