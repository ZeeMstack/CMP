"""PILOT-ASSET-001: Critical Equipment Incident lifecycle -- focused proof
of docs/domain/EQUIPMENT_READINESS_MODEL.md's frozen rules. Incident !=
Work Item, Incident != Crop Issue, Work Item Complete != Incident Resolved,
resolution/closure are deliberate, and Equipment Attention surfaces open
critical incidents."""

import uuid
from datetime import datetime, timezone

import pytest

from app.services import (
    asset_service,
    equipment_attention_service,
    equipment_incident_service,
    farm_work_item_service,
    membership_service,
    tenant_service,
    user_service,
)
from app.services.errors import (
    EquipmentIncidentInvalidTransitionError,
    EquipmentIncidentNotFoundError,
)


def _now():
    return datetime.now(timezone.utc)


def _register_asset(db_session, tenant, farm, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_type_code="weighing_scale",
        code=f"WS-{uuid.uuid4().hex[:8]}", name="Scale", commissioned_date=None,
    )
    defaults.update(overrides)
    return asset_service.register_asset(db_session, **defaults)


def _open_incident(db_session, tenant, farm, user, asset, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        asset_id=asset.id, location_id=None, potentially_impacted_location_id=None, severity="high",
        category="scale", description="Scale reads inconsistently", detected_at=_now(),
        assigned_owner_user_id=None, notes=None,
    )
    defaults.update(overrides)
    return equipment_incident_service.open_incident(db_session, **defaults)


@pytest.mark.integration
def test_open_incident_generates_code_and_open_status(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user)
    incident = _open_incident(db_session, tenant, farm, user, asset)
    assert incident.status == "open"
    assert incident.code.startswith("EI-")
    assert incident.asset_id == asset.id


# --- Proof 11: Equipment Incident does not create Crop Issue ----------------------


@pytest.mark.integration
def test_open_incident_never_touches_crop_issues_table(db_session, active_context_with_farm) -> None:
    from sqlalchemy import select

    from app.models.crop_issue import CropIssue

    tenant, user, _headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user)
    before = db_session.execute(select(CropIssue.id)).scalars().all()
    _open_incident(db_session, tenant, farm, user, asset)
    after = db_session.execute(select(CropIssue.id)).scalars().all()
    assert before == after


# --- Proof 12/13: Incident can link a FarmWorkItem; completing it never resolves --


@pytest.mark.integration
def test_work_item_links_to_incident_but_completion_does_not_resolve_it(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user)
    incident = _open_incident(db_session, tenant, farm, user, asset)

    item = farm_work_item_service.create_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), work_type="maintenance", category="maintenance",
        title="Recalibrate scale", instructions=None, priority="high", due_at=None,
        assigned_to_user_id=None, crop_batch_id=None, location_id=None, carrier_id=None, asset_id=asset.id,
        equipment_incident_id=incident.id, quantity=None, quantity_uom_id=None, completion_mode="manual_record",
    )
    assert item.equipment_incident_id == incident.id

    completed = farm_work_item_service.complete_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=item.id,
        client_command_id=uuid.uuid4(), completion_note="recalibrated",
    )
    assert completed.status == "completed"

    refreshed = equipment_incident_service.get_incident(
        db_session, tenant_id=tenant.id, farm_id=farm.id, incident_id=incident.id
    )
    assert refreshed.status == "open"


# --- Proof 14: Incident resolution is deliberate (resolve then close, two steps) --


@pytest.mark.integration
def test_resolve_and_close_are_two_deliberate_commands(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user)
    incident = _open_incident(db_session, tenant, farm, user, asset)

    with pytest.raises(EquipmentIncidentInvalidTransitionError):
        equipment_incident_service.close_incident(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, incident_id=incident.id,
            client_command_id=uuid.uuid4(), close_note=None,
        )

    resolved = equipment_incident_service.resolve_incident(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, incident_id=incident.id,
        client_command_id=uuid.uuid4(), resolution_note="pump repaired",
    )
    assert resolved.status == "resolved"

    closed = equipment_incident_service.close_incident(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, incident_id=incident.id,
        client_command_id=uuid.uuid4(), close_note="verified",
    )
    assert closed.status == "closed"


@pytest.mark.integration
def test_acknowledge_action_lifecycle(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user)
    incident = _open_incident(db_session, tenant, farm, user, asset)

    acknowledged = equipment_incident_service.acknowledge_incident(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, incident_id=incident.id,
        client_command_id=uuid.uuid4(),
    )
    assert acknowledged.status == "acknowledged"
    assert acknowledged.acknowledged_at is not None

    in_progress = equipment_incident_service.mark_action_in_progress(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, incident_id=incident.id,
        client_command_id=uuid.uuid4(),
    )
    assert in_progress.status == "action_in_progress"


# --- Proof 15: critical open incidents appear in Equipment Attention --------------


@pytest.mark.integration
def test_open_incident_appears_in_equipment_attention(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user, code=f"WS-CRIT-{uuid.uuid4().hex[:6]}")
    incident = _open_incident(db_session, tenant, farm, user, asset, severity="critical")

    attention = equipment_attention_service.get_equipment_attention(db_session, tenant_id=tenant.id, farm_id=farm.id)
    matching = [a for a in attention if a.equipment_incident_id == incident.id]
    assert len(matching) == 1
    assert matching[0].kind == "OPEN_INCIDENT"
    assert matching[0].severity == "critical"

    # Resolving + closing removes it from the live attention feed.
    equipment_incident_service.resolve_incident(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, incident_id=incident.id,
        client_command_id=uuid.uuid4(), resolution_note="fixed",
    )
    equipment_incident_service.close_incident(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, incident_id=incident.id,
        client_command_id=uuid.uuid4(), close_note=None,
    )
    attention_after = equipment_attention_service.get_equipment_attention(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert not any(a.equipment_incident_id == incident.id for a in attention_after)


# --- Proof 20: cross-tenant isolation ----------------------------------------------


@pytest.mark.integration
def test_incident_cross_tenant_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user)
    incident = _open_incident(db_session, tenant, farm, user, asset)

    tenant_b = tenant_service.create_tenant(db_session, code=f"eqi-b-{uuid.uuid4().hex[:8]}", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=uuid.uuid4().hex, email="eqib@example.com", display_name="B"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    with pytest.raises(EquipmentIncidentNotFoundError):
        equipment_incident_service.get_incident(
            db_session, tenant_id=tenant_b.id, farm_id=farm.id, incident_id=incident.id
        )


# --- Idempotency --------------------------------------------------------------------


@pytest.mark.integration
def test_open_incident_exact_replay_returns_original(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user)
    command_id = uuid.uuid4()
    # Same `detected_at` on both calls -- an exact replay must carry an
    # identical payload, not just an identical client_command_id.
    detected_at = _now()
    first = _open_incident(db_session, tenant, farm, user, asset, client_command_id=command_id, detected_at=detected_at)
    second = _open_incident(db_session, tenant, farm, user, asset, client_command_id=command_id, detected_at=detected_at)
    assert first.id == second.id
