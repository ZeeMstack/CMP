"""AUTHZ-001B2 representative HTTP-level authorization tests (ticket
sections 8, 10, 11). Mirrors `test_authz_read_enforcement_http.py`'s
representative-cross-section approach, extended to mutation/action
routes: `test_authz_mutation_enforcement_architecture.py` already
structurally proves every tenant-scoped mutation is wired to
require_permission with a real `.manage` Permission. What's new here is
the end-to-end *behavior* -- exercised across a representative
cross-section of domains (location, movement, crop, production_system)
rather than all ~20 -- plus two properties unique to mutations that a
read-only proof can't cover: permission denial must produce ZERO domain
side effects (section 8), and authorization must be evaluated before
idempotency-record lookup, never bypassed by replaying another caller's
client_command_id (section 11).
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.models.audit_event import AuditEvent
from app.services import (
    farm_service,
    location_service,
    membership_service,
    movement_service,
    tenant_service,
    user_service,
)


def _membership_headers(db_session, *, tenant_id, role_code: str) -> dict[str, str]:
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"mut-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Mutation Enforcement User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}


def _new_tenant_with_farm(db_session, *, code_prefix: str):
    tenant = tenant_service.create_tenant(db_session, code=f"t-{code_prefix}-{uuid.uuid4().hex[:8]}", name="Mutation Enforcement Tenant")
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=None, code=f"{code_prefix}-farm", name="Mutation Enforcement Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    return tenant, farm


# --- tenant_admin: allowed across a representative domain sample ------------


@pytest.mark.integration
def test_tenant_admin_can_mutate_across_representative_domains(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm

    assert client.post("/crops", json={
        "code": "crp-a", "common_name": "Lettuce", "scientific_name": None, "crop_category": "leafy_green",
    }, headers=headers).status_code == 201

    assert client.post("/production-systems", json={
        "code": "ps-a", "name": "NFT System", "description": None,
    }, headers=headers).status_code == 201

    response = client.post(f"/farms/{farm.id}/locations", json={
        "location_type_code": "greenhouse", "code": "gh-a", "name": "Greenhouse A",
        "parent_location_id": None, "greenhouse_classification": "leafy_greens", "occupiable": None,
    }, headers=headers)
    assert response.status_code == 201


# --- zero-permission role: 403 on the same representative mutations ---------


@pytest.mark.integration
def test_zero_permission_role_is_forbidden_across_representative_domains(client, db_session) -> None:
    """`operator` is a real, DB-approved role with zero granted
    permissions -- proves the denial generalizes across mutation
    domains, not just the AUTHZ-001A farm proof slice."""
    tenant, farm = _new_tenant_with_farm(db_session, code_prefix="zp")
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="operator")

    assert client.post("/crops", json={
        "code": "crp-z", "common_name": "Lettuce", "scientific_name": None, "crop_category": "leafy_green",
    }, headers=headers).status_code == 403

    assert client.post("/production-systems", json={
        "code": "ps-z", "name": "NFT System", "description": None,
    }, headers=headers).status_code == 403

    response = client.post(f"/farms/{farm.id}/locations", json={
        "location_type_code": "greenhouse", "code": "gh-z", "name": "Greenhouse Z",
        "parent_location_id": None, "greenhouse_classification": "leafy_greens", "occupiable": None,
    }, headers=headers)
    assert response.status_code == 403


# --- same user, different role per tenant, for a MANAGE permission ----------


@pytest.mark.integration
def test_same_user_different_role_per_tenant_for_a_manage_permission(client, db_session) -> None:
    """One user, tenant_admin in Tenant A (has LOCATION_MANAGE), read_only
    in Tenant B (has none) -- selecting Tenant B must still deny,
    proving the role used is always the ACTIVE membership's role_code
    for the SELECTED tenant, never a role held elsewhere."""
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"mut-multitenant-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Mutation Multi Tenant User",
    )
    tenant_a, farm_a = _new_tenant_with_farm(db_session, code_prefix="mt-a")
    tenant_b, farm_b = _new_tenant_with_farm(db_session, code_prefix="mt-b")
    membership_service.add_membership(
        db_session, tenant_id=tenant_a.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user.id, role_code="read_only", actor_user_id=None
    )

    headers_a = {"X-Dev-Tenant-Id": str(tenant_a.id), "X-Dev-User-Id": str(user.id)}
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user.id)}

    body = lambda code: {
        "location_type_code": "greenhouse", "code": code, "name": "Greenhouse",
        "parent_location_id": None, "greenhouse_classification": "leafy_greens", "occupiable": None,
    }
    assert client.post(f"/farms/{farm_a.id}/locations", json=body("gh-mt-a"), headers=headers_a).status_code == 201
    assert client.post(f"/farms/{farm_b.id}/locations", json=body("gh-mt-b"), headers=headers_b).status_code == 403


# --- no membership / inactive membership: fail before permission evaluation -


@pytest.mark.integration
def test_no_membership_fails_before_reaching_a_non_farm_manage_permission(client, db_session) -> None:
    """Structural guarantee: require_permission always wraps
    require_tenant_context, so a caller with no active membership at
    all never reaches ANY permission check, regardless of which
    domain's manage permission the route requires."""
    tenant, farm = _new_tenant_with_farm(db_session, code_prefix="nomem")
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"mut-no-mem-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Mutation No Membership User",
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}

    response = client.post(f"/farms/{farm.id}/locations", json={
        "location_type_code": "greenhouse", "code": "gh-nomem", "name": "Greenhouse",
        "parent_location_id": None, "greenhouse_classification": "leafy_greens", "occupiable": None,
    }, headers=headers)
    assert response.status_code == 403


@pytest.mark.integration
def test_inactive_membership_fails_before_reaching_a_non_farm_manage_permission(client, db_session) -> None:
    """Same contract as AUTH-001D's inactive-membership finding
    (`test_authz_farm_proof.py`), extended to a mutation route: a
    membership row exists but its status is not "active" -- must still
    be 403 before any permission check, not merely before the farm
    proof endpoint specifically."""
    tenant, farm = _new_tenant_with_farm(db_session, code_prefix="inact")
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"mut-inactive-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Mutation Inactive Membership User",
    )
    membership = membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    membership.status = "removed"
    db_session.commit()

    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    response = client.post(f"/farms/{farm.id}/locations", json={
        "location_type_code": "greenhouse", "code": "gh-inact", "name": "Greenhouse",
        "parent_location_id": None, "greenhouse_classification": "leafy_greens", "occupiable": None,
    }, headers=headers)
    assert response.status_code == 403


# --- foreign resource: still 404 after permission succeeds ------------------


@pytest.mark.integration
def test_cross_tenant_movement_destination_is_404_after_permission_succeeds(
    client, db_session, placed_trolley_and_tray
) -> None:
    """A fully-permitted tenant_admin caller (has MOVEMENT_MANAGE) must
    still get 404, not a movement, when the destination location
    belongs to a different tenant -- proves the permission layer and
    the tenant-scoped resource lookup are independent controls, for a
    domain command (not a simple create) beyond the farms proof
    slice."""
    scenario = placed_trolley_and_tray
    tenant, headers, farm = scenario["tenant"], scenario["headers"], scenario["farm"]

    other_tenant, other_farm = _new_tenant_with_farm(db_session, code_prefix="foreign-mv")
    foreign_location = location_service.create_location(
        db_session, tenant_id=other_tenant.id, farm_id=other_farm.id, actor_user_id=None,
        location_type_code="greenhouse", code="foreign-gh", name="Foreign Greenhouse",
        parent_location_id=None, greenhouse_classification="leafy_greens", occupiable=None,
    )

    response = client.post(f"/farms/{farm.id}/movements", json={
        "client_command_id": str(uuid.uuid4()),
        "effective_time": datetime.now(timezone.utc).isoformat(),
        "occupant": {"kind": "asset", "id": str(scenario["trolley"].id)},
        "destination": {"kind": "location", "id": str(foreign_location.id)},
        "reason": None,
    }, headers=headers)
    assert response.status_code == 404


# --- permission denial: zero domain side effects, zero audit events ---------


@pytest.mark.integration
def test_permission_denial_creates_zero_domain_side_effects_or_audit_events(
    client, db_session, placed_trolley_and_tray
) -> None:
    """Section 8's central proof: a 403 must never reach the service
    layer at all. Verified by explicit state checks (occupancy
    unchanged, movement history unchanged, audit-event count unchanged)
    -- not merely by asserting the response status code."""
    scenario = placed_trolley_and_tray
    tenant, farm = scenario["tenant"], scenario["farm"]
    trolley, positions = scenario["trolley"], scenario["positions"]

    # AUTHZ-002B2: `operator` now genuinely holds MOVEMENT_MANAGE (Imperial
    # Pilot policy activation) -- `read_only` is the role that still
    # correctly lacks it, used here in its place.
    zero_permission_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="read_only")

    occupancy_before = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="asset", occupant_id=trolley.id
    )
    history_before = movement_service.get_movement_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="asset", occupant_id=trolley.id
    )
    audit_count_before = db_session.query(AuditEvent).filter(AuditEvent.tenant_id == tenant.id).count()

    response = client.post(f"/farms/{farm.id}/movements", json={
        "client_command_id": str(uuid.uuid4()),
        "effective_time": datetime.now(timezone.utc).isoformat(),
        "occupant": {"kind": "asset", "id": str(trolley.id)},
        "destination": {"kind": "location", "id": str(positions["P13"].id)},
        "reason": None,
    }, headers=zero_permission_headers)
    assert response.status_code == 403

    occupancy_after = movement_service.get_occupancy(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="asset", occupant_id=trolley.id
    )
    history_after = movement_service.get_movement_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, occupant_kind="asset", occupant_id=trolley.id
    )
    audit_count_after = db_session.query(AuditEvent).filter(AuditEvent.tenant_id == tenant.id).count()

    # Occupant remains at its original position (P12, per the fixture) --
    # no unauthorized location/state transition occurred.
    assert occupancy_after.id == occupancy_before.id
    assert occupancy_after.target_location_id == occupancy_before.target_location_id
    assert len(history_after) == len(history_before)
    assert audit_count_after == audit_count_before


@pytest.mark.integration
def test_permission_denial_creates_no_new_location_row(client, db_session, active_context_with_farm) -> None:
    """A second representative domain for section 8's side-effect-denial
    proof, using a simple creation command instead of an occupancy
    command: a denied POST /farms/{farm_id}/locations must not insert a
    Location row, not merely return non-200."""
    tenant, _user, _admin_headers, farm = active_context_with_farm
    zero_permission_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="operator")

    tree_before = location_service.get_farm_tree(db_session, tenant_id=tenant.id, farm_id=farm.id)

    response = client.post(f"/farms/{farm.id}/locations", json={
        "location_type_code": "greenhouse", "code": "gh-denied", "name": "Should Not Exist",
        "parent_location_id": None, "greenhouse_classification": "leafy_greens", "occupiable": None,
    }, headers=zero_permission_headers)
    assert response.status_code == 403

    tree_after = location_service.get_farm_tree(db_session, tenant_id=tenant.id, farm_id=farm.id)
    assert len(tree_after) == len(tree_before)
    assert not any(loc.code == "gh-denied" for loc in tree_after)


# --- idempotency/validation order: authorization runs before any replay -----


@pytest.mark.integration
def test_authorization_is_evaluated_before_idempotency_replay_lookup(
    client, db_session, placed_trolley_and_tray
) -> None:
    """Section 11's core regression guard. Sequence:
    1. tenant_admin executes a movement with a given client_command_id --
       succeeds, occupant relocated.
    2. The SAME tenant_admin replays the identical request (same
       client_command_id, identical payload) -- existing exact-replay
       semantics are unchanged: 201 with the same movement, not a
       duplicate.
    3. A DIFFERENT, zero-permission caller in the SAME tenant then
       replays the exact same client_command_id -- must get 403, never
       the cached/idempotent success result. Proves authorization is
       evaluated on every request before the command layer's own
       idempotency lookup, not bypassed by an existing idempotency
       record."""
    scenario = placed_trolley_and_tray
    tenant, admin_headers, farm = scenario["tenant"], scenario["headers"], scenario["farm"]
    trolley, positions = scenario["trolley"], scenario["positions"]

    client_command_id = str(uuid.uuid4())
    payload = {
        "client_command_id": client_command_id,
        "effective_time": datetime.now(timezone.utc).isoformat(),
        "occupant": {"kind": "asset", "id": str(trolley.id)},
        "destination": {"kind": "location", "id": str(positions["P13"].id)},
        "reason": None,
    }

    first = client.post(f"/farms/{farm.id}/movements", json=payload, headers=admin_headers)
    assert first.status_code == 201
    movement_id = first.json()["id"]

    replay_by_admin = client.post(f"/farms/{farm.id}/movements", json=payload, headers=admin_headers)
    assert replay_by_admin.status_code == 201
    assert replay_by_admin.json()["id"] == movement_id

    # AUTHZ-002B2: `operator` now genuinely holds MOVEMENT_MANAGE (Imperial
    # Pilot policy activation) -- `read_only` is the role that still
    # correctly lacks it, used here in its place.
    zero_permission_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="read_only")
    replay_by_zero_permission = client.post(f"/farms/{farm.id}/movements", json=payload, headers=zero_permission_headers)
    assert replay_by_zero_permission.status_code == 403
    assert "id" not in replay_by_zero_permission.json()
