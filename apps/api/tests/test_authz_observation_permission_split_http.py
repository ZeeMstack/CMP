"""AUTHZ-002B1 representative HTTP-level authorization tests proving the
`observation_entry.manage` / `observation_definition.manage` permission
split (replacing the former unified `observation.manage`) is enforced
correctly at the route boundary.

AUTHZ-002B1 deliberately does not yet activate any non-admin role grant
(that is AUTHZ-002B2's job) -- `ROLE_PERMISSIONS` still maps every
approved role other than `tenant_admin` to the empty set. These tests
prove the boundary itself, not a live role policy, using two mechanisms:

- `tenant_admin`, which automatically holds both new permissions (derived
  from every defined `Permission` value, unchanged by this split), for
  the "has both" and "neither denied" cases.
- A temporary, test-scoped `monkeypatch` of one real, already-approved,
  currently-zero-permission role_code's entry in
  `app.core.permissions._ROLE_PERMISSIONS` -- reverted automatically by
  pytest at teardown -- to grant *exactly one* of the two new permissions
  and prove the other is still denied. This exercises the real FastAPI
  dependency chain (`require_permission` -> `has_permission` ->
  `get_permissions_for_role` -> `ROLE_PERMISSIONS` lookup) through a real
  HTTP request and a real, DB-backed membership row using a genuinely
  approved role_code -- not a synthetic identity. No permanent production
  grant is made anywhere in this file.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.core import permissions as permissions_module
from app.core.permissions import Permission
from app.models.audit_event import AuditEvent
from app.services import membership_service, observation_service, tenant_service, user_service
from tests.test_observation import _build_scenario


def _now():
    return datetime.now(timezone.utc)


def _membership_headers(db_session, *, tenant_id, role_code: str) -> dict[str, str]:
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"obs-split-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Observation Split Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}


@pytest.fixture
def only_entry_permission(monkeypatch):
    """Temporarily grants `production_supervisor` -- a real, DB-approved
    role_code with zero grants outside this patch -- ONLY
    Permission.OBSERVATION_ENTRY_MANAGE. Reverted automatically at
    teardown (the key did not exist in `_ROLE_PERMISSIONS` before this
    patch, so pytest deletes it again afterward)."""
    monkeypatch.setitem(
        permissions_module._ROLE_PERMISSIONS,
        "production_supervisor",
        frozenset({Permission.OBSERVATION_ENTRY_MANAGE}),
    )
    return "production_supervisor"


@pytest.fixture
def only_definition_permission(monkeypatch):
    """Temporarily grants `head_grower` ONLY
    Permission.OBSERVATION_DEFINITION_MANAGE."""
    monkeypatch.setitem(
        permissions_module._ROLE_PERMISSIONS,
        "head_grower",
        frozenset({Permission.OBSERVATION_DEFINITION_MANAGE}),
    )
    return "head_grower"


def _definition_payload(code: str) -> dict:
    return {
        "code": code, "name": "Leaf color score", "description": None,
        "value_type": "decimal", "unit": None, "target_scope": "either",
        "min_value": None, "max_value": None,
    }


def _entry_payload(assignment_id) -> dict:
    return {
        "client_command_id": str(uuid.uuid4()),
        "effective_time": _now().isoformat(),
        "note": None,
        "values": [],
        "germination_checks": [
            {
                "batch_carrier_assignment_id": str(assignment_id),
                "inspected_site_count": 200,
                "normal_germinated_site_count": 180,
                "abnormal_germinated_site_count": 10,
                "failed_site_count": 10,
                "note": None,
            }
        ],
    }


# --- A. entry authority, no definition authority -----------------------------


@pytest.mark.integration
def test_entry_only_role_may_record_but_not_define(
    client, db_session, active_context_with_farm, only_entry_permission
) -> None:
    tenant, user, _admin_headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code=only_entry_permission)

    entry_response = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/observations",
        json=_entry_payload(scenario["assignment_ids"][0]),
        headers=headers,
    )
    assert entry_response.status_code == 201

    definition_response = client.post(
        "/observation-definitions", json=_definition_payload(f"DEF-A-{uuid.uuid4().hex[:8]}"), headers=headers
    )
    assert definition_response.status_code == 403


# --- B. definition authority, no entry authority -----------------------------


@pytest.mark.integration
def test_definition_only_role_may_define_but_not_record(
    client, db_session, active_context_with_farm, only_definition_permission
) -> None:
    tenant, user, _admin_headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code=only_definition_permission)

    definition_response = client.post(
        "/observation-definitions", json=_definition_payload(f"DEF-B-{uuid.uuid4().hex[:8]}"), headers=headers
    )
    assert definition_response.status_code == 201

    entry_response = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/observations",
        json=_entry_payload(scenario["assignment_ids"][0]),
        headers=headers,
    )
    assert entry_response.status_code == 403


# --- C. neither authority -----------------------------------------------------


@pytest.mark.integration
def test_role_with_neither_permission_is_denied_both(client, db_session, active_context_with_farm) -> None:
    """`read_only` is a real, DB-approved role with zero granted
    permissions -- no monkeypatch needed, it already has no entry in
    `ROLE_PERMISSIONS`."""
    tenant, user, _admin_headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="read_only")

    definition_response = client.post(
        "/observation-definitions", json=_definition_payload(f"DEF-C-{uuid.uuid4().hex[:8]}"), headers=headers
    )
    assert definition_response.status_code == 403

    entry_response = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/observations",
        json=_entry_payload(scenario["assignment_ids"][0]),
        headers=headers,
    )
    assert entry_response.status_code == 403


# --- D. tenant_admin: both allowed --------------------------------------------


@pytest.mark.integration
def test_tenant_admin_may_both_record_and_define(client, db_session, active_context_with_farm) -> None:
    tenant, user, admin_headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)

    definition_response = client.post(
        "/observation-definitions", json=_definition_payload(f"DEF-D-{uuid.uuid4().hex[:8]}"), headers=admin_headers
    )
    assert definition_response.status_code == 201

    entry_response = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/observations",
        json=_entry_payload(scenario["assignment_ids"][0]),
        headers=admin_headers,
    )
    assert entry_response.status_code == 201


# --- side-effect denial -------------------------------------------------------


@pytest.mark.integration
def test_entry_denial_creates_no_observation_event_or_audit_event(
    client, db_session, active_context_with_farm, only_definition_permission
) -> None:
    """`only_definition_permission` (head_grower) has DEFINITION but not
    ENTRY authority -- proves a denied entry attempt leaves zero
    business/audit side effects, not merely a 403 status code."""
    tenant, user, _admin_headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code=only_definition_permission)

    events_before = observation_service.list_observation_events(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=scenario["batch"].id
    )
    audit_before = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant.id, AuditEvent.action == "crop_batch.observation_recorded")
        .count()
    )

    response = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/observations",
        json=_entry_payload(scenario["assignment_ids"][0]),
        headers=headers,
    )
    assert response.status_code == 403

    events_after = observation_service.list_observation_events(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=scenario["batch"].id
    )
    audit_after = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant.id, AuditEvent.action == "crop_batch.observation_recorded")
        .count()
    )
    assert len(events_after) == len(events_before)
    assert audit_after == audit_before


@pytest.mark.integration
def test_definition_denial_creates_no_observation_definition_or_audit_event(
    client, db_session, active_context_with_farm, only_entry_permission
) -> None:
    """`only_entry_permission` (production_supervisor) has ENTRY but not
    DEFINITION authority -- proves a denied definition-creation attempt
    leaves zero business/audit side effects."""
    tenant, _user, _admin_headers, _farm = active_context_with_farm
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code=only_entry_permission)

    definitions_before = observation_service.list_observation_definitions(db_session, tenant_id=tenant.id)
    audit_before = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant.id, AuditEvent.action == "observation_definition.created")
        .count()
    )

    denied_code = f"DEF-DENIED-{uuid.uuid4().hex[:8]}"
    response = client.post("/observation-definitions", json=_definition_payload(denied_code), headers=headers)
    assert response.status_code == 403

    definitions_after = observation_service.list_observation_definitions(db_session, tenant_id=tenant.id)
    audit_after = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant.id, AuditEvent.action == "observation_definition.created")
        .count()
    )
    assert len(definitions_after) == len(definitions_before)
    assert not any(d.code == denied_code for d in definitions_after)
    assert audit_after == audit_before
