"""DOMAIN-FARM-002.2: authorization and tenant-isolation verification for
the two new multi-occupant read routes added by DOMAIN-FARM-002.1:

    GET /farms/{farm_id}/locations/{location_id}/occupants
    GET /farms/{farm_id}/assets/{asset_id}/positions/{position_id}/occupants

Confirms (by direct HTTP calls, not inference): both are gated by the SAME
existing read permission as their singular counterparts (location.read,
asset.read respectively -- reconfirmed structurally in
test_authz_read_enforcement_architecture.py, which already covers these two
routes automatically via live route-table introspection); tenant isolation
holds (own-tenant succeeds, cross-tenant 404s, no cross-tenant occupant data
ever returned); the existing generic 403/404 semantics are unchanged; no
role gap exists to test denial against for these two baseline-context
permissions (every one of the 12 active roles holds location.read and
asset.read -- see test_authz_read_enforcement_http.py's own note on this),
so "unauthorized" here is proven via the real reachable case: a caller with
no active membership in the target tenant.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.services import (
    asset_service,
    farm_service,
    location_service,
    membership_service,
    tenant_service,
    user_service,
)
from tests.conftest import ensure_seed_tray_specification


def _now():
    return datetime.now(timezone.utc)


def _tenant_with_membership(db_session, *, role_code: str):
    suffix = uuid.uuid4().hex[:8]
    tenant = tenant_service.create_tenant(db_session, code=f"occ-authz-{suffix}", name="Occupants Authz Tenant")
    user = user_service.create_user(
        db_session, oidc_issuer="occ-authz", oidc_subject=suffix, email=f"{suffix}@example.com",
        display_name="Occupants Authz User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    return tenant, user, headers, farm


def _build_position(db_session, tenant, farm, user, *, capacity):
    """NURSERY-OPS-002A: the frozen authoritative model -- a Germination
    Trolley occupies the Chamber Location directly (no chamber_position)."""
    suffix = uuid.uuid4().hex[:8]
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code=f"gh-{suffix}", name="GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    return location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code=f"gc-{suffix}", name="Chamber",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=True, capacity=capacity,
    )


def _register_trolley(db_session, tenant, farm, user):
    suffix = uuid.uuid4().hex[:8]
    return asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name=f"Trolley {suffix}", commissioned_date=None,
    )


def _build_slot(db_session, tenant, farm, user, *, capacity):
    trolley = _register_trolley(db_session, tenant, farm, user)
    positions = asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix=f"SH-{uuid.uuid4().hex[:6]}-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2, slot_capacity=capacity,
    )
    return trolley, next(p for p in positions if p.position_kind == "slot")


def _place(db_session, tenant, farm, user, *, occupant_kind, occupant_id, target_kind, target_id):
    from app.services import movement_service

    return movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=_now(),
        occupant_kind=occupant_kind, occupant_id=occupant_id,
        destination_kind=target_kind, destination_id=target_id, reason=None,
    )


# =====================================================================
# B/C. permission dependency reconfirmed via live HTTP behavior
# (structural proof already in test_authz_read_enforcement_architecture.py)
# =====================================================================


@pytest.mark.integration
@pytest.mark.parametrize("role_code", ["tenant_admin", "production_supervisor", "read_only", "auditor", "operator"])
def test_location_occupants_route_readable_by_every_role_holding_location_read(client, db_session, role_code) -> None:
    """H: mechanically verify across tenant_admin, an operational role,
    and read_only/auditor -- all 12 active roles hold location.read, so
    all succeed here (see module docstring)."""
    tenant, user, headers, farm = _tenant_with_membership(db_session, role_code=role_code)
    position = _build_position(db_session, tenant, farm, user, capacity=2)
    trolleys = [_register_trolley(db_session, tenant, farm, user) for _ in range(2)]
    for trolley in trolleys:
        _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id, target_kind="location", target_id=position.id)
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/locations/{position.id}/occupants", headers=headers)
    assert resp.status_code == 200, (role_code, resp.text)
    body = resp.json()
    assert len(body["active_occupancies"]) == 2


@pytest.mark.integration
@pytest.mark.parametrize("role_code", ["tenant_admin", "production_supervisor", "read_only", "auditor", "operator"])
def test_position_occupants_route_readable_by_every_role_holding_asset_read(client, db_session, role_code) -> None:
    tenant, user, headers, farm = _tenant_with_membership(db_session, role_code=role_code)
    trolley, slot = _build_slot(db_session, tenant, farm, user, capacity=1)
    from app.services import carrier_service

    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    tray = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code=f"ST-{uuid.uuid4().hex[:8]}", issued_date=None,
    )
    _place(db_session, tenant, farm, user, occupant_kind="carrier", occupant_id=tray.id, target_kind="asset_position", target_id=slot.id)
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/assets/{trolley.id}/positions/{slot.id}/occupants", headers=headers)
    assert resp.status_code == 200, (role_code, resp.text)
    assert len(resp.json()["active_occupancies"]) == 1


# =====================================================================
# G. unauthorized (no membership in the target tenant) -> generic 403
# =====================================================================


@pytest.mark.integration
def test_location_occupants_route_denies_caller_with_no_membership(client, db_session) -> None:
    tenant, user, _headers, farm = _tenant_with_membership(db_session, role_code="tenant_admin")
    position = _build_position(db_session, tenant, farm, user, capacity=1)

    outsider = user_service.create_user(
        db_session, oidc_issuer="occ-authz", oidc_subject=f"outsider-{uuid.uuid4().hex[:8]}",
        email=f"outsider-{uuid.uuid4().hex[:8]}@example.com", display_name="Outsider",
    )
    outsider_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(outsider.id)}
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/locations/{position.id}/occupants", headers=outsider_headers)
    assert resp.status_code == 403
    assert "role" not in resp.json()["detail"].lower()
    assert "permission" not in resp.json()["detail"].lower() or resp.json()["detail"] == "You don't have permission to perform this action"


@pytest.mark.integration
def test_position_occupants_route_denies_caller_with_no_membership(client, db_session) -> None:
    tenant, user, _headers, farm = _tenant_with_membership(db_session, role_code="tenant_admin")
    trolley, slot = _build_slot(db_session, tenant, farm, user, capacity=1)

    outsider = user_service.create_user(
        db_session, oidc_issuer="occ-authz", oidc_subject=f"outsider-{uuid.uuid4().hex[:8]}",
        email=f"outsider-{uuid.uuid4().hex[:8]}@example.com", display_name="Outsider",
    )
    outsider_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(outsider.id)}
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/assets/{trolley.id}/positions/{slot.id}/occupants", headers=outsider_headers)
    assert resp.status_code == 403


# =====================================================================
# E/F. tenant isolation: own-tenant succeeds, cross-tenant 404s,
# no cross-tenant occupant data ever returned
# =====================================================================


@pytest.mark.integration
def test_location_occupants_cross_tenant_lookup_is_404_not_leaked(client, db_session) -> None:
    tenant_a, user_a, headers_a, farm_a = _tenant_with_membership(db_session, role_code="tenant_admin")
    tenant_b, user_b, headers_b, farm_b = _tenant_with_membership(db_session, role_code="tenant_admin")

    position_a = _build_position(db_session, tenant_a, farm_a, user_a, capacity=2)
    trolleys = [_register_trolley(db_session, tenant_a, farm_a, user_a) for _ in range(2)]
    for trolley in trolleys:
        _place(db_session, tenant_a, farm_a, user_a, occupant_kind="asset", occupant_id=trolley.id, target_kind="location", target_id=position_a.id)
    db_session.commit()

    # Tenant A reading its own target succeeds and every returned
    # occupancy actually belongs to Tenant A.
    own = client.get(f"/farms/{farm_a.id}/locations/{position_a.id}/occupants", headers=headers_a)
    assert own.status_code == 200
    body = own.json()
    assert len(body["active_occupancies"]) == 2
    assert all(o["tenant_id"] == str(tenant_a.id) for o in body["active_occupancies"])

    # Tenant B querying Tenant A's farm_id/location_id combination: 404,
    # not a 200 with an empty/partial/leaked body.
    cross = client.get(f"/farms/{farm_a.id}/locations/{position_a.id}/occupants", headers=headers_b)
    assert cross.status_code == 404
    assert cross.json() == {"detail": "Not found"}

    # Also: Tenant B's OWN farm_id, but Tenant A's location_id (mismatched
    # farm/location pair) must still 404, never resolve cross-tenant.
    cross2 = client.get(f"/farms/{farm_b.id}/locations/{position_a.id}/occupants", headers=headers_b)
    assert cross2.status_code == 404


@pytest.mark.integration
def test_position_occupants_cross_tenant_lookup_is_404_not_leaked(client, db_session) -> None:
    tenant_a, user_a, headers_a, farm_a = _tenant_with_membership(db_session, role_code="tenant_admin")
    tenant_b, _user_b, headers_b, farm_b = _tenant_with_membership(db_session, role_code="tenant_admin")

    trolley_a, slot_a = _build_slot(db_session, tenant_a, farm_a, user_a, capacity=1)
    from app.services import carrier_service

    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant_a.id, actor_user_id=user_a.id)
    tray = carrier_service.register_carrier(
        db_session, tenant_id=tenant_a.id, farm_id=farm_a.id, actor_user_id=user_a.id,
        specification_id=seed_tray_spec.id, code=f"ST-{uuid.uuid4().hex[:8]}", issued_date=None,
    )
    _place(db_session, tenant_a, farm_a, user_a, occupant_kind="carrier", occupant_id=tray.id, target_kind="asset_position", target_id=slot_a.id)
    db_session.commit()

    own = client.get(f"/farms/{farm_a.id}/assets/{trolley_a.id}/positions/{slot_a.id}/occupants", headers=headers_a)
    assert own.status_code == 200
    body = own.json()
    assert len(body["active_occupancies"]) == 1
    assert body["active_occupancies"][0]["tenant_id"] == str(tenant_a.id)

    cross = client.get(f"/farms/{farm_a.id}/assets/{trolley_a.id}/positions/{slot_a.id}/occupants", headers=headers_b)
    assert cross.status_code == 404
    assert cross.json() == {"detail": "Not found"}

    cross2 = client.get(f"/farms/{farm_b.id}/assets/{trolley_a.id}/positions/{slot_a.id}/occupants", headers=headers_b)
    assert cross2.status_code == 404


# =====================================================================
# nonexistent target -> 404, same shape as cross-tenant (no distinguishing leak)
# =====================================================================


@pytest.mark.integration
def test_location_occupants_nonexistent_target_is_404(client, db_session) -> None:
    tenant, _user, headers, farm = _tenant_with_membership(db_session, role_code="tenant_admin")
    resp = client.get(f"/farms/{farm.id}/locations/{uuid.uuid4()}/occupants", headers=headers)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not found"}


@pytest.mark.integration
def test_position_occupants_nonexistent_target_is_404(client, db_session) -> None:
    tenant, user, headers, farm = _tenant_with_membership(db_session, role_code="tenant_admin")
    trolley = _register_trolley(db_session, tenant, farm, user)
    db_session.commit()
    resp = client.get(f"/farms/{farm.id}/assets/{trolley.id}/positions/{uuid.uuid4()}/occupants", headers=headers)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not found"}


# =====================================================================
# J. plural read contract: empty / one / three occupants, deterministic order
# =====================================================================


@pytest.mark.integration
def test_location_occupants_empty_target_returns_empty_list(client, db_session) -> None:
    tenant, user, headers, farm = _tenant_with_membership(db_session, role_code="tenant_admin")
    position = _build_position(db_session, tenant, farm, user, capacity=1)
    resp = client.get(f"/farms/{farm.id}/locations/{position.id}/occupants", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["active_occupancies"] == []


@pytest.mark.integration
def test_location_occupants_three_occupants_all_returned_in_deterministic_order(client, db_session) -> None:
    tenant, user, headers, farm = _tenant_with_membership(db_session, role_code="tenant_admin")
    position = _build_position(db_session, tenant, farm, user, capacity=3)
    trolleys = [_register_trolley(db_session, tenant, farm, user) for _ in range(3)]
    for trolley in trolleys:
        _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id, target_kind="location", target_id=position.id)
    db_session.commit()

    resp1 = client.get(f"/farms/{farm.id}/locations/{position.id}/occupants", headers=headers)
    resp2 = client.get(f"/farms/{farm.id}/locations/{position.id}/occupants", headers=headers)
    assert resp1.status_code == 200 and resp2.status_code == 200
    ids1 = [o["occupant"]["id"] for o in resp1.json()["active_occupancies"]]
    ids2 = [o["occupant"]["id"] for o in resp2.json()["active_occupancies"]]
    assert sorted(ids1) == sorted(str(t.id) for t in trolleys)
    assert ids1 == ids2  # deterministic across repeated calls


# =====================================================================
# K. legacy singular endpoint: no crash, explicit count, plural remains authoritative
# =====================================================================


@pytest.mark.integration
def test_singular_endpoint_does_not_crash_and_states_true_count_for_multi_capacity_target(client, db_session) -> None:
    tenant, user, headers, farm = _tenant_with_membership(db_session, role_code="tenant_admin")
    position = _build_position(db_session, tenant, farm, user, capacity=3)
    trolleys = [_register_trolley(db_session, tenant, farm, user) for _ in range(3)]
    for trolley in trolleys:
        _place(db_session, tenant, farm, user, occupant_kind="asset", occupant_id=trolley.id, target_kind="location", target_id=position.id)
    db_session.commit()

    singular = client.get(f"/farms/{farm.id}/locations/{position.id}/occupant", headers=headers)
    assert singular.status_code == 200
    body = singular.json()
    assert body["active_occupancy"] is not None  # one occupant reported, not a crash
    assert body["active_occupancy_count"] == 3    # but explicitly not claimed complete

    plural = client.get(f"/farms/{farm.id}/locations/{position.id}/occupants", headers=headers)
    assert len(plural.json()["active_occupancies"]) == 3  # plural remains the authoritative complete read
