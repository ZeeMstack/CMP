"""POSTHARVEST-OPS-001B: HTTP-level authorization proofs for the
packaging-units/pack-specifications APIs, reusing packing.read/
packing.manage exactly as GradeDefinition does. Mirrors
test_grade_definition_api.py's own `_role_headers` helper."""
import uuid
from datetime import datetime, timezone

import pytest

from app.models.membership import TenantMembership
from app.services import crop_service, membership_service, tenant_service, user_service


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _role_headers(db_session, *, tenant_id, role_code: str):
    user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"pspec-role-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com", display_name="Pack Spec Role Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}, user


@pytest.mark.integration
def test_packing_read_role_can_read_but_not_mutate(client, db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    read_headers, _read_user = _role_headers(db_session, tenant_id=tenant.id, role_code="qc_officer")

    list_response = client.get("/packaging-units", headers=read_headers)
    assert list_response.status_code == 200

    create_response = client.post(
        "/packaging-units",
        json={"client_command_id": str(uuid.uuid4()), "code": "CARTON", "name": "Carton"},
        headers=read_headers,
    )
    assert create_response.status_code == 403

    spec_list_response = client.get("/pack-specifications", headers=read_headers)
    assert spec_list_response.status_code == 200


@pytest.mark.integration
def test_packing_manage_role_can_create_full_chain(client, db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="LET", common_name="Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    manage_headers, _manage_user = _role_headers(db_session, tenant_id=tenant.id, role_code="packing_supervisor")

    unit_response = client.post(
        "/packaging-units",
        json={"client_command_id": str(uuid.uuid4()), "code": "CARTON", "name": "Carton"},
        headers=manage_headers,
    )
    assert unit_response.status_code == 201
    unit_id = unit_response.json()["id"]

    spec_response = client.post(
        "/pack-specifications",
        json={
            "client_command_id": str(uuid.uuid4()), "code": "SPEC-1", "name": "Spec 1", "crop_id": str(crop.id),
            "variety_id": None, "customer_reference": None,
        },
        headers=manage_headers,
    )
    assert spec_response.status_code == 201
    spec_id = spec_response.json()["id"]

    version_response = client.post(
        f"/pack-specifications/{spec_id}/versions",
        json={
            "client_command_id": str(uuid.uuid4()), "grade_definition_version_id": None,
            "packaging_unit_id": unit_id, "nominal_net_weight_kg": "2.500", "whole_units_per_pack": None,
            "spec_notes": None,
        },
        headers=manage_headers,
    )
    assert version_response.status_code == 201
    version_id = version_response.json()["id"]

    activate_response = client.post(
        f"/pack-specifications/{spec_id}/versions/{version_id}/activate",
        json={"client_command_id": str(uuid.uuid4()), "effective_time": _now_iso()},
        headers=manage_headers,
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["status"] == "active"

    retire_unit_response = client.post(
        f"/packaging-units/{unit_id}/retire",
        json={"client_command_id": str(uuid.uuid4())},
        headers=manage_headers,
    )
    assert retire_unit_response.status_code == 200
    assert retire_unit_response.json()["status"] == "retired"


@pytest.mark.integration
def test_cross_tenant_api_access_returns_404(client, db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = crop_service.register_crop(
        db_session, tenant_id=tenant_a.id, actor_user_id=None, code="LET", common_name="Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    manage_headers_a, _ = _role_headers(db_session, tenant_id=tenant_a.id, role_code="packing_supervisor")
    unit_response = client.post(
        "/packaging-units", json={"client_command_id": str(uuid.uuid4()), "code": "CARTON", "name": "Carton"},
        headers=manage_headers_a,
    )
    unit_id = unit_response.json()["id"]
    spec_response = client.post(
        "/pack-specifications",
        json={
            "client_command_id": str(uuid.uuid4()), "code": "SPEC-1", "name": "Spec 1", "crop_id": str(crop_a.id),
            "variety_id": None, "customer_reference": None,
        },
        headers=manage_headers_a,
    )
    spec_id = spec_response.json()["id"]

    tenant_b = tenant_service.create_tenant(db_session, code="pspec-api-tenant-b", name="Tenant B")
    manage_headers_b, _ = _role_headers(db_session, tenant_id=tenant_b.id, role_code="packing_supervisor")

    assert client.get(f"/packaging-units/{unit_id}", headers=manage_headers_b).status_code == 404
    assert client.get(f"/pack-specifications/{spec_id}", headers=manage_headers_b).status_code == 404


@pytest.mark.integration
def test_inactive_membership_denied(client, db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    manage_headers, manage_user = _role_headers(db_session, tenant_id=tenant.id, role_code="packing_supervisor")

    membership = db_session.query(TenantMembership).filter_by(
        tenant_id=tenant.id, user_id=manage_user.id
    ).one()
    membership.status = "removed"
    db_session.flush()

    response = client.get("/packaging-units", headers=manage_headers)
    assert response.status_code == 403


@pytest.mark.integration
def test_tenant_isolated_lists(client, db_session, active_context) -> None:
    tenant_a, _user, headers_a = active_context
    crop_a = crop_service.register_crop(
        db_session, tenant_id=tenant_a.id, actor_user_id=None, code="LET", common_name="Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    client.post(
        "/packaging-units", json={"client_command_id": str(uuid.uuid4()), "code": "CARTON", "name": "Carton"},
        headers=headers_a,
    )
    client.post(
        "/pack-specifications",
        json={
            "client_command_id": str(uuid.uuid4()), "code": "SPEC-1", "name": "Spec 1", "crop_id": str(crop_a.id),
            "variety_id": None, "customer_reference": None,
        },
        headers=headers_a,
    )

    tenant_b = tenant_service.create_tenant(db_session, code="pspec-isolated-tenant-b", name="Tenant B")
    headers_b, _ = _role_headers(db_session, tenant_id=tenant_b.id, role_code="tenant_admin")

    units_b = client.get("/packaging-units", headers=headers_b).json()
    specs_b = client.get("/pack-specifications", headers=headers_b).json()
    assert units_b == []
    assert specs_b == []

    units_a = client.get("/packaging-units", headers=headers_a).json()
    specs_a = client.get("/pack-specifications", headers=headers_a).json()
    assert len(units_a) == 1
    assert len(specs_a) == 1
