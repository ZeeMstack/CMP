"""UX-OPS-001B: focused proof of the minimal additive readiness read-model
fields (`EquipmentReadinessStateRead.entity_code`/`entity_name`/
`equipment_type_code`/`equipment_type_name`/`requires_cleaning`/
`is_in_use`/`latest_cleaning_result`) -- API-level serialization, tenant/
farm isolation, missing/invalid entities, permission behavior, and absence
of N+1 query growth. Does not re-test the frozen lifecycle rules themselves
(see test_equipment_readiness.py) or write-safety/idempotency (see
test_equipment_readiness_write_safety.py) -- this file is scoped strictly
to the new read-model fields."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from app.services import (
    asset_service,
    carrier_service,
    equipment_readiness_service,
    farm_service,
    membership_service,
    tenant_service,
    user_service,
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


# --- Serialization: additive fields present and correct -----------------------------


@pytest.mark.integration
def test_carrier_readiness_read_serializes_additive_fields(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user, carrier_type_code="seed_tray")
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/carriers/{carrier.id}/readiness", headers=headers)
    assert resp.status_code == 200
    body = resp.json()

    assert body["entity_code"] == carrier.code
    # Carrier has no `name` column -- entity_name is honestly null, never guessed.
    assert body["entity_name"] is None
    assert body["equipment_type_code"] == "seed_tray"
    assert body["requires_cleaning"] is True
    assert body["is_in_use"] is False
    assert body["latest_cleaning_result"] is None


@pytest.mark.integration
def test_asset_readiness_read_serializes_additive_fields_non_cleaning_type(
    client, db_session, active_context_with_farm
) -> None:
    tenant, user, headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user, asset_type_code="weighing_scale", name="Scale 7")
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/assets/{asset.id}/readiness", headers=headers)
    assert resp.status_code == 200
    body = resp.json()

    assert body["entity_code"] == asset.code
    assert body["entity_name"] == "Scale 7"
    assert body["equipment_type_code"] == "weighing_scale"
    assert body["requires_cleaning"] is False
    # Documented gap: no authoritative "in active use" signal exists for
    # Assets today -- never guessed, always null.
    assert body["is_in_use"] is None


@pytest.mark.integration
def test_asset_readiness_read_marks_cleaning_required_type(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    asset = _register_asset(db_session, tenant, farm, user, asset_type_code="germination_trolley", name="Trolley 1")
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/assets/{asset.id}/readiness", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["requires_cleaning"] is True


# --- Latest cleaning result: absent, COMPLETED, NEEDS_REWORK ------------------------


@pytest.mark.integration
def test_readiness_read_reflects_latest_cleaning_result(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
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

    resp = client.get(f"/farms/{farm.id}/carriers/{carrier.id}/readiness", headers=headers)
    assert resp.json()["latest_cleaning_result"] == "needs_rework"
    # NEEDS_REWORK must never be surfaced as ready-adjacent -- current_state
    # itself stays CLEANING_COMPLETED (frozen rule), only the new field adds
    # the outcome the old read model couldn't expose at all.
    assert resp.json()["current_state"] == "cleaning_completed"

    # A subsequent successful cleaning cycle updates the latest result.
    equipment_readiness_service.mark_awaiting_cleaning(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(),
    )
    equipment_readiness_service.record_cleaning_completed(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, state_id=state.id,
        client_command_id=uuid.uuid4(), effective_at=_now(), method=None, result="completed", notes=None,
    )
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/carriers/{carrier.id}/readiness", headers=headers)
    assert resp.json()["latest_cleaning_result"] == "completed"


# --- Carrier in-use, from a genuine active BatchCarrierAssignment -------------------


@pytest.mark.integration
def test_readiness_read_reflects_active_carrier_assignment_in_use(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    carrier = s["carriers"][0]
    _sow(db_session, tenant, user, farm, s["batch"], [_simple_line(carrier, s["seed_lot"])])
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/carriers/{carrier.id}/readiness", headers=headers)
    assert resp.json()["is_in_use"] is True, "an active BatchCarrierAssignment must be reflected, never guessed"

    other_carrier = s["carriers"][1]
    resp = client.get(f"/farms/{farm.id}/carriers/{other_carrier.id}/readiness", headers=headers)
    assert resp.json()["is_in_use"] is False


# --- Tenant/farm isolation -----------------------------------------------------------


@pytest.mark.integration
def test_readiness_read_is_tenant_scoped(client, db_session, active_context_with_farm) -> None:
    tenant_a, user_a, headers_a, farm_a = active_context_with_farm
    carrier = _register_carrier(db_session, tenant_a, farm_a, user_a)
    db_session.commit()

    suffix = uuid.uuid4().hex[:8]
    tenant_b = tenant_service.create_tenant(db_session, code=f"ro-b-{suffix}", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="ro-b", oidc_subject=suffix, email=f"b-{suffix}@example.com", display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    db_session.commit()

    resp = client.get(f"/farms/{farm_a.id}/carriers/{carrier.id}/readiness", headers=headers_b)
    assert resp.status_code == 404


@pytest.mark.integration
def test_readiness_list_excludes_other_farms_in_same_tenant(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    db_session.commit()

    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{uuid.uuid4().hex[:6]}", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    db_session.commit()

    resp = client.get(f"/farms/{other_farm.id}/equipment-readiness", headers=headers)
    assert resp.status_code == 200
    assert all(row["id"] != str(carrier.id) for row in resp.json())
    assert all(row["entity_code"] != carrier.code for row in resp.json())


# --- Missing/invalid entities and permissions ---------------------------------------


@pytest.mark.integration
def test_readiness_read_missing_asset_is_404(client, db_session, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    resp = client.get(f"/farms/{farm.id}/assets/{uuid.uuid4()}/readiness", headers=headers)
    assert resp.status_code == 404


@pytest.mark.integration
def test_readiness_manage_command_requires_manage_permission(client, db_session, active_context_with_farm) -> None:
    """`read_only` genuinely holds `equipment_readiness.read` (the GET route
    used throughout this file is reachable by every named role, so it
    cannot itself prove the permission gate) but not `.manage` -- proves the
    additive read-model change did not loosen the existing MANAGE-gated
    `mark-ready` command's own authorization boundary."""
    tenant, user, _headers, farm = active_context_with_farm
    carrier = _register_carrier(db_session, tenant, farm, user)
    state = equipment_readiness_service.get_readiness_for_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id
    )
    db_session.commit()

    suffix = uuid.uuid4().hex[:8]
    ro_user = user_service.create_user(
        db_session, oidc_issuer="ro-user", oidc_subject=suffix, email=f"{suffix}@example.com", display_name="Read Only",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=ro_user.id, role_code="read_only", actor_user_id=None
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(ro_user.id)}
    db_session.commit()

    # Read stays allowed.
    resp = client.get(f"/farms/{farm.id}/carriers/{carrier.id}/readiness", headers=headers)
    assert resp.status_code == 200

    # Mutation (MANAGE-gated) stays denied.
    resp = client.post(
        f"/farms/{farm.id}/equipment-readiness/{state.id}/mark-ready", headers=headers,
        json={"client_command_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 403


# --- No N+1 growth on the list endpoint ----------------------------------------------


@pytest.mark.integration
def test_readiness_list_context_resolution_avoids_n_plus_1_queries(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    for _ in range(6):
        _register_carrier(db_session, tenant, farm, user)
    for _ in range(4):
        _register_asset(db_session, tenant, farm, user, asset_type_code="germination_trolley", name="Trolley")
    db_session.commit()

    states = equipment_readiness_service.list_farm_readiness_states(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert len(states) == 10

    statement_count = 0

    def _count(*args, **kwargs) -> None:
        nonlocal statement_count
        statement_count += 1

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", _count)
    try:
        context = equipment_readiness_service.resolve_readiness_read_context(
            db_session, tenant_id=tenant.id, states=states
        )
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    # A handful of batched queries (assets+types, carriers+types, in-use
    # carrier ids, cleaning events), never one query per one of the 10 rows.
    assert statement_count <= 6, statement_count
    assert len(context["carriers"]) == 6
    assert len(context["assets"]) == 4
