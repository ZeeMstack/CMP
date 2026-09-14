"""PILOT-OPS-001: Farm Work Item HTTP-layer authorization and command
validation tests, using the real route table + `require_permission`
dependency (never a service-layer bypass)."""
import uuid

import pytest

from app.services import membership_service, tenant_service, user_service


@pytest.fixture
def _dev_auth_enabled(monkeypatch):
    """Mirrors the established `_dev_auth_enabled` fixture pattern used by
    test_quality_hold.py/test_carrier_specification.py -- forces dev-auth on
    for exactly this file's HTTP tests, independent of the ambient .env
    value."""
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)


def _create_payload(**overrides):
    payload = {
        "client_command_id": str(uuid.uuid4()),
        "work_type": "cleaning",
        "category": "cleaning",
        "title": "Clean Germination Trolley 03",
        "priority": "normal",
        "completion_mode": "manual_record",
    }
    payload.update(overrides)
    return payload


@pytest.mark.integration
def test_create_and_get_work_item_round_trip(client, _dev_auth_enabled, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    resp = client.post(f"/farms/{farm.id}/work-items", json=_create_payload(), headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "open"
    assert body["code"].startswith("FW-")

    get_resp = client.get(f"/farms/{farm.id}/work-items/{body['id']}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == body["id"]


@pytest.mark.integration
def test_operator_role_cannot_create_work_item(client, _dev_auth_enabled, active_context_with_farm, db_session) -> None:
    tenant, _admin_user, _admin_headers, farm = active_context_with_farm
    operator = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=uuid.uuid4().hex, email="op@example.com", display_name="Op"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=operator.id, role_code="operator", actor_user_id=None
    )
    op_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(operator.id)}
    resp = client.post(f"/farms/{farm.id}/work-items", json=_create_payload(), headers=op_headers)
    assert resp.status_code == 403


@pytest.mark.integration
def test_operator_can_see_and_start_assigned_work(client, _dev_auth_enabled, active_context_with_farm, db_session) -> None:
    tenant, admin, admin_headers, farm = active_context_with_farm
    operator = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=uuid.uuid4().hex, email="op2@example.com", display_name="Op2"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=operator.id, role_code="operator", actor_user_id=None
    )
    op_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(operator.id)}

    create_resp = client.post(
        f"/farms/{farm.id}/work-items", json=_create_payload(assigned_to_user_id=str(operator.id)),
        headers=admin_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    work_item_id = create_resp.json()["id"]

    list_resp = client.get(f"/farms/{farm.id}/work-items?assigned_to_me=true", headers=op_headers)
    assert list_resp.status_code == 200
    assert [i["id"] for i in list_resp.json()] == [work_item_id]

    start_resp = client.post(
        f"/farms/{farm.id}/work-items/{work_item_id}/start", json={"client_command_id": str(uuid.uuid4())},
        headers=op_headers,
    )
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "in_progress"


@pytest.mark.integration
def test_block_without_reason_rejected(client, _dev_auth_enabled, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    create_resp = client.post(f"/farms/{farm.id}/work-items", json=_create_payload(), headers=headers)
    work_item_id = create_resp.json()["id"]

    missing = client.post(
        f"/farms/{farm.id}/work-items/{work_item_id}/block", json={"client_command_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert missing.status_code == 422

    blank = client.post(
        f"/farms/{farm.id}/work-items/{work_item_id}/block",
        json={"client_command_id": str(uuid.uuid4()), "reason": "   "}, headers=headers,
    )
    assert blank.status_code == 422

    ok = client.post(
        f"/farms/{farm.id}/work-items/{work_item_id}/block",
        json={"client_command_id": str(uuid.uuid4()), "reason": "destination full"}, headers=headers,
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "blocked"
    assert ok.json()["blocked_reason"] == "destination full"


@pytest.mark.integration
def test_manual_complete_rejected_for_operational_record_item(client, _dev_auth_enabled, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    create_resp = client.post(
        f"/farms/{farm.id}/work-items",
        json=_create_payload(work_type="harvest", category="harvest", title="Harvest Batch",
                              completion_mode="operational_record"),
        headers=headers,
    )
    work_item_id = create_resp.json()["id"]

    resp = client.post(
        f"/farms/{farm.id}/work-items/{work_item_id}/complete", json={"client_command_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert resp.status_code == 409


@pytest.mark.integration
def test_cross_tenant_work_item_is_404(client, _dev_auth_enabled, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    create_resp = client.post(f"/farms/{farm.id}/work-items", json=_create_payload(), headers=headers)
    work_item_id = create_resp.json()["id"]

    tenant_b = tenant_service.create_tenant(db_session, code=f"fwi-http-b-{uuid.uuid4().hex[:8]}", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=uuid.uuid4().hex, email="httpb@example.com", display_name="B"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}

    resp = client.get(f"/farms/{farm.id}/work-items/{work_item_id}", headers=headers_b)
    assert resp.status_code == 404

    resp = client.post(
        f"/farms/{farm.id}/work-items/{work_item_id}/start", json={"client_command_id": str(uuid.uuid4())},
        headers=headers_b,
    )
    assert resp.status_code == 404
