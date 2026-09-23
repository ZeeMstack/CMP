"""UX-OPS-001B R1 (review blocker #3): proof that
`equipment_readiness_service.compute_readiness_actions`/
`primary_readiness_action` -- the backend-owned, single source of truth for
which readiness commands are currently valid, now exposed additively as
`EquipmentReadinessStateRead.available_actions`/`primary_action` -- exactly
mirror the frozen lifecycle rules (docs/domain/EQUIPMENT_READINESS_MODEL.md
PART 6/7) the frontend used to duplicate. Two layers:

1. Pure unit tests of the computed-facts function itself (ported verbatim
   from the deleted frontend `equipmentReadinessActions.test.ts` -- same
   cases, same expectations, now the only copy).
2. A cross-check against the REAL transition commands for the
   safety-critical `mark_ready` action: for a representative set of states,
   `compute_readiness_actions(...)` saying `mark_ready` is/isn't available
   is asserted to exactly predict whether calling the real `mark_ready`
   command succeeds or raises -- so this computed fact can never silently
   drift from what the backend actually enforces.

Also covers the new fields' API serialization and the `resolve_readiness_
read_context` farm_id defense-in-depth scoping added in the same change
(does not re-test the other additive read-model fields -- see
test_equipment_readiness_read_model.py for those)."""

import uuid
from datetime import datetime, timezone

import pytest

from app.services import (
    asset_service,
    carrier_service,
    equipment_readiness_service,
)
from app.services.errors import (
    EquipmentReadinessCarrierInUseError,
    EquipmentReadinessCleaningNotCompletedError,
    EquipmentReadinessInvalidTransitionError,
)
from tests.conftest import ensure_seed_tray_specification
from tests.test_sowing import _build_scenario, _simple_line, _sow


def _now():
    return datetime.now(timezone.utc)


def _register_carrier(db_session, tenant, farm, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, carrier_type_code="seed_tray",
        code=f"ST-{uuid.uuid4().hex[:8]}", issued_date=None,
    )
    defaults.update(overrides)
    if defaults["carrier_type_code"] == "seed_tray" and defaults.get("specification_id") is None:
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


# --- 1. Pure unit tests: compute_readiness_actions / primary_readiness_action -------


def _actions(**kwargs):
    defaults = dict(
        current_state="unknown", entity_type="carrier", requires_cleaning=True,
        is_in_use=False, latest_cleaning_result=None,
    )
    defaults.update(kwargs)
    return equipment_readiness_service.compute_readiness_actions(**defaults)


def test_cleaning_required_unknown_never_offers_mark_ready():
    actions = _actions(current_state="unknown", requires_cleaning=True)
    assert "mark_ready" not in actions
    assert "mark_awaiting_cleaning" in actions


def test_non_cleaning_unknown_can_expose_mark_ready_when_otherwise_valid():
    actions = _actions(
        current_state="unknown", requires_cleaning=False, entity_type="asset", is_in_use=None,
    )
    assert "mark_ready" in actions
    assert "mark_awaiting_cleaning" not in actions


def test_non_cleaning_unknown_carrier_blocked_by_active_assignment_does_not_offer_mark_ready():
    actions = _actions(current_state="unknown", requires_cleaning=False, is_in_use=True)
    assert "mark_ready" not in actions


def test_cleaning_completed_needs_rework_never_offers_mark_ready():
    actions = _actions(current_state="cleaning_completed", latest_cleaning_result="needs_rework")
    assert "mark_ready" not in actions
    # The recovery path stays available.
    assert "mark_awaiting_cleaning" in actions


def test_cleaning_completed_completed_offers_mark_ready_when_not_blocked():
    actions = _actions(current_state="cleaning_completed", latest_cleaning_result="completed", is_in_use=False)
    assert "mark_ready" in actions


def test_cleaning_completed_completed_but_in_use_still_blocks_mark_ready():
    actions = _actions(current_state="cleaning_completed", latest_cleaning_result="completed", is_in_use=True)
    assert "mark_ready" not in actions


def test_ready_non_cleaning_type_offers_no_mark_awaiting_cleaning():
    actions = _actions(current_state="ready", requires_cleaning=False)
    assert "mark_awaiting_cleaning" not in actions


def test_ready_cleaning_required_type_offers_mark_awaiting_cleaning():
    actions = _actions(current_state="ready", requires_cleaning=True)
    assert "mark_awaiting_cleaning" in actions


def test_damaged_offers_only_send_to_maintenance_and_retire():
    assert _actions(current_state="damaged") == ["send_to_maintenance", "retire"]


def test_maintenance_offers_return_report_damage_and_retire():
    assert _actions(current_state="maintenance") == ["return_from_maintenance", "report_damage", "retire"]


def test_retired_is_terminal_no_actions_at_all():
    assert _actions(current_state="retired") == []


def test_awaiting_cleaning_offers_record_cleaning_not_mark_ready():
    actions = _actions(current_state="awaiting_cleaning")
    assert "record_cleaning" in actions
    assert "mark_ready" not in actions


def test_primary_action_is_none_for_retired():
    assert equipment_readiness_service.primary_readiness_action(_actions(current_state="retired")) is None


def test_primary_action_is_never_exceptional():
    actions = _actions(current_state="unknown", requires_cleaning=True)
    assert equipment_readiness_service.primary_readiness_action(actions) == "mark_awaiting_cleaning"


def test_primary_action_falls_back_to_re_clean_when_mark_ready_blocked():
    actions = _actions(current_state="cleaning_completed", latest_cleaning_result="completed", is_in_use=True)
    assert equipment_readiness_service.primary_readiness_action(actions) == "mark_awaiting_cleaning"


# --- 2. Cross-check against the real mark_ready command ------------------------------


@pytest.mark.integration
def test_mark_ready_availability_matches_computed_action_unknown_non_cleaning(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user, asset_type_code="weighing_scale")
    db_session.commit()
    state = equipment_readiness_service.get_readiness_for_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, asset_id=asset.id
    )
    assert state.current_state == "unknown"

    computed = equipment_readiness_service.compute_readiness_actions(
        current_state=state.current_state, entity_type="asset", requires_cleaning=False,
        is_in_use=None, latest_cleaning_result=None,
    )
    assert "mark_ready" in computed

    result = equipment_readiness_service.mark_ready(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    assert result.current_state == "ready"


@pytest.mark.integration
def test_mark_ready_availability_matches_computed_action_unknown_cleaning_required(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    db_session.commit()
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    assert state.current_state == "unknown"

    computed = equipment_readiness_service.compute_readiness_actions(
        current_state=state.current_state, entity_type="carrier", requires_cleaning=True,
        is_in_use=False, latest_cleaning_result=None,
    )
    assert "mark_ready" not in computed

    with pytest.raises(EquipmentReadinessInvalidTransitionError):
        equipment_readiness_service.mark_ready(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
            client_command_id=uuid.uuid4(),
        )


@pytest.mark.integration
def test_mark_ready_availability_matches_computed_action_cleaning_completed_needs_rework(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    db_session.commit()
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    equipment_readiness_service.mark_awaiting_cleaning(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    equipment_readiness_service.record_cleaning_completed(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), effective_at=_now(), method=None, result="needs_rework", notes=None,
    )
    db_session.commit()

    computed = equipment_readiness_service.compute_readiness_actions(
        current_state="cleaning_completed", entity_type="carrier", requires_cleaning=True,
        is_in_use=False, latest_cleaning_result="needs_rework",
    )
    assert "mark_ready" not in computed

    with pytest.raises(EquipmentReadinessCleaningNotCompletedError):
        equipment_readiness_service.mark_ready(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
            client_command_id=uuid.uuid4(),
        )


@pytest.mark.integration
def test_mark_ready_availability_matches_computed_action_cleaning_completed_completed(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    db_session.commit()
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    equipment_readiness_service.mark_awaiting_cleaning(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    equipment_readiness_service.record_cleaning_completed(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), effective_at=_now(), method=None, result="completed", notes=None,
    )
    db_session.commit()

    computed = equipment_readiness_service.compute_readiness_actions(
        current_state="cleaning_completed", entity_type="carrier", requires_cleaning=True,
        is_in_use=False, latest_cleaning_result="completed",
    )
    assert "mark_ready" in computed

    result = equipment_readiness_service.mark_ready(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    assert result.current_state == "ready"


@pytest.mark.integration
def test_mark_ready_availability_matches_computed_action_carrier_in_use_blocks(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    carrier = s["carriers"][0]
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    equipment_readiness_service.mark_awaiting_cleaning(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    equipment_readiness_service.record_cleaning_completed(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), effective_at=_now(), method=None, result="completed", notes=None,
    )
    db_session.commit()
    equipment_readiness_service.mark_ready(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    db_session.commit()

    _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(carrier, s["seed_lot"])])
    db_session.commit()
    equipment_readiness_service.mark_awaiting_cleaning(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    equipment_readiness_service.record_cleaning_completed(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), effective_at=_now(), method=None, result="completed", notes=None,
    )
    db_session.commit()

    computed = equipment_readiness_service.compute_readiness_actions(
        current_state="cleaning_completed", entity_type="carrier", requires_cleaning=True,
        is_in_use=True, latest_cleaning_result="completed",
    )
    assert "mark_ready" not in computed

    with pytest.raises(EquipmentReadinessCarrierInUseError):
        equipment_readiness_service.mark_ready(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
            client_command_id=uuid.uuid4(),
        )


# --- API serialization of the new fields ----------------------------------------------


@pytest.mark.integration
def test_readiness_read_serializes_available_actions_and_primary_action(
    client, db_session, active_context_with_farm
) -> None:
    tenant, user, headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/carriers/{carrier.id}/readiness", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["available_actions"] == ["mark_awaiting_cleaning", "report_damage", "send_to_maintenance", "retire"]
    assert body["primary_action"] == "mark_awaiting_cleaning"


@pytest.mark.integration
def test_readiness_read_serializes_empty_actions_for_retired(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    db_session.commit()
    equipment_readiness_service.retire(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/carriers/{carrier.id}/readiness", headers=headers)
    assert resp.json()["available_actions"] == []
    assert resp.json()["primary_action"] is None


# --- resolve_readiness_read_context: farm_id defense-in-depth scoping ----------------


@pytest.mark.integration
def test_resolve_read_context_does_not_cross_farm_boundary(db_session, active_context_with_farm) -> None:
    """A state whose own `farm_id` does not match the Asset it points at
    (a data-integrity condition that must never happen in practice, since
    every real caller resolves states within a single farm) must resolve
    NO entry for that asset, rather than silently leaking it across farms
    -- proves the R1 `farm_id.in_(...)` filter added to every sub-query in
    `resolve_readiness_read_context` actually does something, not just that
    tenant_id scoping (already covered elsewhere) still works."""
    tenant, user, _headers, farm_a = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm_a, user, asset_type_code="weighing_scale")
    db_session.commit()
    state = equipment_readiness_service.get_readiness_for_asset(
        db_session, tenant_id=tenant.id, farm_id=farm_a.id, asset_id=asset.id
    )

    from app.services import farm_service

    farm_b = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{uuid.uuid4().hex[:6]}",
        name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    db_session.commit()

    # Simulate a state whose farm_id disagrees with its Asset's real farm --
    # in-memory only, never persisted. Refreshed (undoes the post-commit
    # expiry) then detached before mutating: identity fields are
    # DB-trigger-immutable (PART 8), and a still-session-attached mutation
    # would autoflush an UPDATE straight into that trigger.
    db_session.refresh(state)
    db_session.expunge(state)
    state.farm_id = farm_b.id

    context = equipment_readiness_service.resolve_readiness_read_context(
        db_session, tenant_id=tenant.id, states=[state]
    )
    assert asset.id not in context["assets"]
