"""PILOT-ASSET-001: Equipment Readiness lifecycle -- focused proof of the
frozen rules in docs/domain/EQUIPMENT_READINESS_MODEL.md. Empty != Ready,
Cleaning Completed != Ready, active occupancy blocks READY, damaged/
maintenance/retired equipment cannot become READY improperly, retired is
terminal, and cleaning/readiness history is preserved."""

import uuid
from datetime import datetime, timezone

import pytest

from app.services import (
    asset_service,
    carrier_service,
    equipment_readiness_service,
    membership_service,
    nursery_service,
    tenant_service,
    user_service,
)
from app.services.errors import (
    EquipmentReadinessCarrierInUseError,
    EquipmentReadinessCleaningNotCompletedError,
    EquipmentReadinessCleaningNotRequiredError,
    EquipmentReadinessInvalidTransitionError,
    EquipmentReadinessNotTrackedError,
    EquipmentReadinessStateNotFoundError,
)


def _now():
    return datetime.now(timezone.utc)


def _register_carrier(db_session, tenant, farm, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, carrier_type_code="seed_tray",
        code=f"ST-{uuid.uuid4().hex[:8]}", issued_date=None,
    )
    defaults.update(overrides)
    # CARRIER-CONFIG-001B: seed_tray now requires a CarrierSpecification --
    # supply the tenant's default one (idempotent helper from
    # tests/conftest.py, the same one every other seed_tray-registering
    # test in this suite already relies on) unless the caller already
    # overrode carrier_type_code to something that doesn't require one.
    if defaults["carrier_type_code"] == "seed_tray" and defaults.get("specification_id") is None:
        from tests.conftest import ensure_seed_tray_specification

        spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
        defaults["specification_id"] = spec.id
    return carrier_service.register_carrier(db_session, **defaults)


def _register_asset(db_session, tenant, farm, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_type_code="weighing_scale",
        code=f"WS-{uuid.uuid4().hex[:8]}", name="Scale", commissioned_date=None,
    )
    defaults.update(overrides)
    return asset_service.register_asset(db_session, **defaults)


# --- Proof 1: empty reusable equipment is NOT automatically READY ------------------


@pytest.mark.integration
def test_new_carrier_starts_unknown_not_ready(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    assert state.current_state == "unknown"


@pytest.mark.integration
def test_non_readiness_tracked_type_has_no_state(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user, carrier_type_code="grow_bag", code="GB-00001")
    with pytest.raises(EquipmentReadinessNotTrackedError):
        equipment_readiness_service.get_readiness_for_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
        )


# --- Proof 2: active occupancy prevents READY allocation for another use -----------


@pytest.mark.integration
def test_mark_ready_blocked_by_active_batch_carrier_assignment(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )

    class _FakeAssignment:
        pass

    # Simulate an active assignment via the same authoritative query
    # `mark_ready` itself uses, rather than driving a full Sowing command
    # (out of this focused test's scope) -- proves the blocking CHECK
    # itself, not the whole Sowing pipeline.
    monkey_active = equipment_readiness_service.has_active_batch_carrier_assignment
    equipment_readiness_service.has_active_batch_carrier_assignment = (
        lambda db, *, tenant_id, carrier_id: True
    )
    try:
        with pytest.raises(EquipmentReadinessCarrierInUseError):
            equipment_readiness_service.mark_ready(
                db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
                client_command_id=uuid.uuid4(),
            )
    finally:
        equipment_readiness_service.has_active_batch_carrier_assignment = monkey_active


# --- Proofs 3/17: Awaiting Cleaning / non-ready excluded from available reads ------


@pytest.mark.integration
def test_awaiting_cleaning_seed_tray_excluded_from_available(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    available_before = nursery_service.list_available_seed_trays(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert any(a.id == carrier.id for a in available_before), "UNKNOWN tray must remain allocation-eligible"

    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    equipment_readiness_service.mark_awaiting_cleaning(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    available_after = nursery_service.list_available_seed_trays(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert not any(a.id == carrier.id for a in available_after)


# --- Proof 4: Cleaning Completed does not automatically mean READY ----------------


@pytest.mark.integration
def test_cleaning_completed_does_not_auto_ready(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    equipment_readiness_service.mark_awaiting_cleaning(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    state, event = equipment_readiness_service.record_cleaning_completed(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), effective_at=_now(), method="wash", result="completed", notes=None,
    )
    assert state.current_state == "cleaning_completed"
    assert event.result == "completed"

    # Still excluded from "available" until the deliberate mark_ready.
    available = nursery_service.list_available_seed_trays(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert not any(a.id == carrier.id for a in available)


# --- Proof 5: explicit Mark Ready works when prerequisites satisfied --------------


@pytest.mark.integration
def test_mark_ready_succeeds_after_completed_cleaning(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    equipment_readiness_service.mark_awaiting_cleaning(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    state, _event = equipment_readiness_service.record_cleaning_completed(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), effective_at=_now(), method=None, result="completed", notes=None,
    )
    ready = equipment_readiness_service.mark_ready(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    assert ready.current_state == "ready"
    available = nursery_service.list_available_seed_trays(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert any(a.id == carrier.id for a in available)


@pytest.mark.integration
def test_mark_ready_rejects_needs_rework_cleaning(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    equipment_readiness_service.mark_awaiting_cleaning(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    state, _event = equipment_readiness_service.record_cleaning_completed(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), effective_at=_now(), method=None, result="needs_rework", notes="still dirty",
    )
    with pytest.raises(EquipmentReadinessCleaningNotCompletedError):
        equipment_readiness_service.mark_ready(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
            client_command_id=uuid.uuid4(),
        )


# --- Proof 6: damaged item cannot become READY improperly -------------------------


@pytest.mark.integration
def test_damaged_item_cannot_mark_ready(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    state = equipment_readiness_service.report_damage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), note="cracked corner",
    )
    assert state.current_state == "damaged"
    with pytest.raises(EquipmentReadinessInvalidTransitionError):
        equipment_readiness_service.mark_ready(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
            client_command_id=uuid.uuid4(),
        )


# --- Proof 7: maintenance item unavailable -----------------------------------------


@pytest.mark.integration
def test_maintenance_asset_cannot_mark_ready_until_returned(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, asset_id=asset.id
    )
    state = equipment_readiness_service.send_to_maintenance(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), note="calibration due",
    )
    assert state.current_state == "maintenance"
    with pytest.raises(EquipmentReadinessInvalidTransitionError):
        equipment_readiness_service.mark_ready(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
            client_command_id=uuid.uuid4(),
        )
    # weighing_scale has requires_cleaning=False -- returns straight to READY.
    returned = equipment_readiness_service.return_from_maintenance(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    assert returned.current_state == "ready"


# --- Proof 8: retired item cannot return to READY (terminal) ----------------------


@pytest.mark.integration
def test_retired_is_terminal(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    state = equipment_readiness_service.retire(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), note="end of life",
    )
    assert state.current_state == "retired"
    db_session.refresh(carrier)
    assert carrier.status == "retired"
    with pytest.raises(EquipmentReadinessInvalidTransitionError):
        equipment_readiness_service.mark_ready(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
            client_command_id=uuid.uuid4(),
        )
    with pytest.raises(EquipmentReadinessInvalidTransitionError):
        equipment_readiness_service.mark_awaiting_cleaning(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
            client_command_id=uuid.uuid4(),
        )


# --- Proof 9/10: cleaning and readiness history preserved -------------------------


@pytest.mark.integration
def test_cleaning_and_readiness_history_preserved(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    equipment_readiness_service.mark_awaiting_cleaning(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    state, event = equipment_readiness_service.record_cleaning_completed(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), effective_at=_now(), method="wash", result="completed", notes=None,
    )
    equipment_readiness_service.mark_ready(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )

    history = equipment_readiness_service.list_readiness_history(db_session, tenant_id=tenant.id, state_id=state.id)
    actions = [h.action for h in history]
    assert "equipment_readiness.marked_awaiting_cleaning" in actions
    assert "equipment_readiness.cleaning_recorded" in actions
    assert "equipment_readiness.marked_ready" in actions

    cleaning_history = equipment_readiness_service.list_cleaning_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    assert len(cleaning_history) == 1
    assert cleaning_history[0].id == event.id


# --- Proof 18: UNKNOWN legacy equipment behavior is truthful ----------------------


@pytest.mark.integration
def test_unknown_state_is_not_silently_treated_as_ready_flag(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    assert state.current_state == "unknown"
    assert state.current_state != "ready"
    # UNKNOWN remains allocation-eligible per the pilot transition rule
    # (avoids a mass operational outage) without ever being reported AS
    # "ready" itself.
    available = nursery_service.list_available_seed_trays(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert any(a.id == carrier.id for a in available)


# --- Proof 20: cross-tenant isolation ----------------------------------------------


@pytest.mark.integration
def test_readiness_state_cross_tenant_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )

    tenant_b = tenant_service.create_tenant(db_session, code=f"eqr-b-{uuid.uuid4().hex[:8]}", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=uuid.uuid4().hex, email="eqrb@example.com", display_name="B"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    with pytest.raises(EquipmentReadinessStateNotFoundError):
        equipment_readiness_service.mark_ready(
            db_session, tenant_id=tenant_b.id, farm_id=farm.id, actor_user_id=user_b.id, state_id=state.id,
            client_command_id=uuid.uuid4(),
        )


# --- Idempotency --------------------------------------------------------------------


@pytest.mark.integration
def test_mark_ready_exact_replay_returns_original(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user, carrier_type_code="harvest_crate", code=f"HC-{uuid.uuid4().hex[:8]}")
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    equipment_readiness_service.mark_awaiting_cleaning(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    state, _event = equipment_readiness_service.record_cleaning_completed(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), effective_at=_now(), method=None, result="completed", notes=None,
    )
    command_id = uuid.uuid4()
    first = equipment_readiness_service.mark_ready(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=command_id,
    )
    second = equipment_readiness_service.mark_ready(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=command_id,
    )
    assert first.id == second.id
    assert first.current_state == "ready"


# --- Proof 19: QR actions prepare readiness workflow but never mutate ------------


@pytest.mark.integration
def test_qr_readiness_actions_never_mutate_state(db_session, active_context_with_farm) -> None:
    from app.services import qr_service

    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state_before = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    assert state_before.current_state == "unknown"

    qr = qr_service.generate_or_get_qr_identifier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, entity_type="carrier", entity_id=carrier.id,
        actor_user_id=user.id,
    )
    context = qr_service.resolve_scan_context(db_session, tenant_id=tenant.id, qr_identifier=qr, may=lambda _p: True)
    assert any(a.label == "View Readiness" for a in context.actions)

    state_after = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    assert state_after.current_state == "unknown"
    assert state_after.state_changed_at == state_before.state_changed_at


@pytest.mark.integration
def test_mark_awaiting_cleaning_rejected_when_not_required(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, asset_id=asset.id
    )
    with pytest.raises(EquipmentReadinessCleaningNotRequiredError):
        equipment_readiness_service.mark_awaiting_cleaning(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
            client_command_id=uuid.uuid4(),
        )
