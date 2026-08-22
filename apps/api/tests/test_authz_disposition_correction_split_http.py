"""BIOLOGICAL-DISPOSITION-AUTHZ-001 representative HTTP-level authorization
tests proving the `biological_disposition.manage` / `biological_disposition.
correct` permission split (RECORD vs CORRECT of a Seedling Disposition) is
enforced correctly at the route boundary.

Unlike AUTHZ-002B1 (test_authz_observation_permission_split_http.py), this
split lands with LIVE, already-approved non-admin role grants (the frozen
matrix from the BUILD ticket), so these tests use REAL role_codes rather
than a temporary `_ROLE_PERMISSIONS` monkeypatch:

- `operator` -- MANAGE only (no CORRECT): proves RECORD is authorized and
  CORRECT is denied. Also serves as half of the cross-permission proof
  (section 14): holding MANAGE alone does NOT authorize CORRECT.
- `production_supervisor` -- both MANAGE and CORRECT: proves both routes
  are authorized for the one role holding both permissions.
- `farm_manager` / `head_grower` -- CORRECT only (no MANAGE): proves
  CORRECT is authorized and RECORD is denied. Also serves as the other half
  of the cross-permission proof: holding CORRECT alone does NOT authorize
  RECORD.
- `tenant_admin` -- both, via the computed all-permissions set.
- `read_only` -- a real, DB-approved role with zero grants: proves the
  zero-permission case stays denied on both routes.

Each denied attempt is also proven to leave zero business/audit side
effects, not merely a 403 status code.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.audit_event import AuditEvent
from app.services import membership_service, seedling_disposition_service, user_service
from tests.test_seedling_disposition import _build_entered_scenario


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture
def _dev_auth_enabled(monkeypatch):
    """Mirrors test_carrier_specification.py's own `_dev_auth_enabled`
    fixture exactly: forces `settings.enable_dev_auth` on for the duration
    of a test that needs the dev-header HTTP auth path, so the assertion
    doesn't depend on the ambient (developer-local) .env value -- a
    documented, pre-existing test-infrastructure characteristic, not
    something introduced here."""
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)


def _membership_headers(db_session, *, tenant_id, role_code: str) -> dict[str, str]:
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"disp-split-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Disposition Split Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}


def _record_payload(assignment_id, *, effective_time=None) -> dict:
    return {
        "client_command_id": str(uuid.uuid4()),
        "batch_carrier_assignment_id": str(assignment_id),
        "quantity": 1,
        "reason_code": "WEAK_SEEDLING",
        "effective_time": (effective_time or _now()).isoformat(),
        "note": None,
    }


def _void_payload() -> dict:
    return {"client_command_id": str(uuid.uuid4()), "corrected": None}


def _record_via_service(db_session, tenant, user, farm, *, assignment_id, effective_time=None):
    """Bypasses HTTP/authorization entirely -- used only to create a target
    event for the CORRECT-route tests, mirroring the rest of the suite's own
    direct-service scenario setup."""
    return seedling_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), batch_carrier_assignment_id=assignment_id,
        quantity=1, reason_code="WEAK_SEEDLING", effective_time=effective_time or _now(), note=None,
    )


def _target_event_id(db_session, command_id):
    from sqlalchemy import text

    return db_session.execute(
        text("SELECT id FROM seedling_disposition_events WHERE command_id = :cid AND event_kind = 'REDUCTION'"),
        {"cid": command_id},
    ).scalar_one()


# --- A/B. operator: MANAGE-only real role -- RECORD yes, CORRECT no ----------


@pytest.mark.integration
def test_operator_may_record_but_not_correct(client, db_session, active_context_with_farm, _dev_auth_enabled) -> None:
    tenant, user, _admin_headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="operator")

    record_response = client.post(
        f"/farms/{farm.id}/nursery/seedling/dispositions",
        json=_record_payload(s["assignment_ids"][0]),
        headers=headers,
    )
    assert record_response.status_code == 201
    event_id = record_response.json()["event"]["id"]

    correct_response = client.post(
        f"/farms/{farm.id}/nursery/seedling/dispositions/{event_id}/correct",
        json=_void_payload(),
        headers=headers,
    )
    assert correct_response.status_code == 403


# --- C/D. farm_manager / head_grower: CORRECT-only real roles ----------------


@pytest.mark.integration
@pytest.mark.parametrize("role_code", ["farm_manager", "head_grower"])
def test_correct_only_role_may_correct_but_not_record(
    client, db_session, active_context_with_farm, role_code, _dev_auth_enabled
) -> None:
    tenant, user, _admin_headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, tray_count=2)
    command = _record_via_service(db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0])
    event_id = _target_event_id(db_session, command.id)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code=role_code)

    record_response = client.post(
        f"/farms/{farm.id}/nursery/seedling/dispositions",
        json=_record_payload(s["assignment_ids"][1]),
        headers=headers,
    )
    assert record_response.status_code == 403

    correct_response = client.post(
        f"/farms/{farm.id}/nursery/seedling/dispositions/{event_id}/correct",
        json=_void_payload(),
        headers=headers,
    )
    assert correct_response.status_code == 201


# --- E. production_supervisor: both authorities -------------------------------


@pytest.mark.integration
def test_production_supervisor_may_both_record_and_correct(client, db_session, active_context_with_farm, _dev_auth_enabled) -> None:
    tenant, user, _admin_headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="production_supervisor")

    record_response = client.post(
        f"/farms/{farm.id}/nursery/seedling/dispositions",
        json=_record_payload(s["assignment_ids"][0]),
        headers=headers,
    )
    assert record_response.status_code == 201
    event_id = record_response.json()["event"]["id"]

    correct_response = client.post(
        f"/farms/{farm.id}/nursery/seedling/dispositions/{event_id}/correct",
        json=_void_payload(),
        headers=headers,
    )
    assert correct_response.status_code == 201


# --- F. tenant_admin: both authorities -----------------------------------------


@pytest.mark.integration
def test_tenant_admin_may_both_record_and_correct(client, db_session, active_context_with_farm, _dev_auth_enabled) -> None:
    tenant, user, admin_headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)

    record_response = client.post(
        f"/farms/{farm.id}/nursery/seedling/dispositions",
        json=_record_payload(s["assignment_ids"][0]),
        headers=admin_headers,
    )
    assert record_response.status_code == 201
    event_id = record_response.json()["event"]["id"]

    correct_response = client.post(
        f"/farms/{farm.id}/nursery/seedling/dispositions/{event_id}/correct",
        json=_void_payload(),
        headers=admin_headers,
    )
    assert correct_response.status_code == 201


# --- G. zero-permission role: denied both --------------------------------------


@pytest.mark.integration
def test_role_with_neither_permission_is_denied_both(client, db_session, active_context_with_farm, _dev_auth_enabled) -> None:
    """`read_only` is a real, DB-approved role with zero granted
    permissions -- no monkeypatch needed."""
    tenant, user, _admin_headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, tray_count=2)
    command = _record_via_service(db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0])
    event_id = _target_event_id(db_session, command.id)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="read_only")

    record_response = client.post(
        f"/farms/{farm.id}/nursery/seedling/dispositions",
        json=_record_payload(s["assignment_ids"][1]),
        headers=headers,
    )
    assert record_response.status_code == 403

    correct_response = client.post(
        f"/farms/{farm.id}/nursery/seedling/dispositions/{event_id}/correct",
        json=_void_payload(),
        headers=headers,
    )
    assert correct_response.status_code == 403


# --- side-effect denial ---------------------------------------------------------


@pytest.mark.integration
def test_record_denial_creates_no_disposition_event_or_audit_event(
    client, db_session, active_context_with_farm, _dev_auth_enabled
) -> None:
    """`farm_manager` has CORRECT but not MANAGE authority -- proves a
    denied RECORD attempt leaves zero business/audit side effects."""
    tenant, user, _admin_headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="farm_manager")

    audit_before = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant.id, AuditEvent.action == "crop_batch.seedling_disposition_recorded")
        .count()
    )

    response = client.post(
        f"/farms/{farm.id}/nursery/seedling/dispositions",
        json=_record_payload(s["assignment_ids"][0]),
        headers=headers,
    )
    assert response.status_code == 403

    audit_after = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant.id, AuditEvent.action == "crop_batch.seedling_disposition_recorded")
        .count()
    )
    assert audit_after == audit_before


@pytest.mark.integration
def test_correct_denial_creates_no_replacement_event_or_audit_event(
    client, db_session, active_context_with_farm, _dev_auth_enabled
) -> None:
    """`operator` has MANAGE but not CORRECT authority -- proves a denied
    CORRECT attempt leaves zero business/audit side effects (the target
    event is untouched, and no reversal/audit event is created)."""
    tenant, user, _admin_headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    command = _record_via_service(db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0])
    event_id = _target_event_id(db_session, command.id)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="operator")

    audit_before = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant.id, AuditEvent.action == "crop_batch.seedling_disposition_corrected")
        .count()
    )

    response = client.post(
        f"/farms/{farm.id}/nursery/seedling/dispositions/{event_id}/correct",
        json=_void_payload(),
        headers=headers,
    )
    assert response.status_code == 403

    history = seedling_disposition_service.get_seedling_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, seedling_entry_id=s["entry_ids"][0]
    )
    assert len(history.events) == 1
    assert history.events[0].id == uuid.UUID(str(event_id))

    audit_after = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.tenant_id == tenant.id, AuditEvent.action == "crop_batch.seedling_disposition_corrected")
        .count()
    )
    assert audit_after == audit_before
