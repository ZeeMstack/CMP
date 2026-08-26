"""POSTHARVEST-OPS-001A: HTTP-level authorization proofs for the
grade-definitions API, reusing the existing `packing.read`/`packing.manage`
permissions (no new grading permission is introduced by this ticket).
Mirrors test_authz_role_activation_http.py's own `_role_headers` helper."""
import uuid
from datetime import datetime, timezone

import pytest

from app.models.membership import TenantMembership
from app.services import crop_service, membership_service, tenant_service, user_service


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _role_headers(db_session, *, tenant_id, role_code: str) -> dict[str, str]:
    user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"grade-role-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com", display_name="Grade Role Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}, user


@pytest.mark.integration
def test_packing_read_role_can_read_but_not_mutate(client, db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="LET", common_name="Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    read_headers, _read_user = _role_headers(db_session, tenant_id=tenant.id, role_code="qc_officer")

    list_response = client.get("/grade-definitions", headers=read_headers)
    assert list_response.status_code == 200

    create_response = client.post(
        "/grade-definitions",
        json={
            "client_command_id": str(uuid.uuid4()), "code": "PREMIUM", "name": "Premium",
            "crop_id": str(crop.id), "variety_id": None, "description": None,
        },
        headers=read_headers,
    )
    assert create_response.status_code == 403


@pytest.mark.integration
def test_packing_manage_role_can_create_and_activate(client, db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="LET", common_name="Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    manage_headers, _manage_user = _role_headers(db_session, tenant_id=tenant.id, role_code="packing_supervisor")

    create_response = client.post(
        "/grade-definitions",
        json={
            "client_command_id": str(uuid.uuid4()), "code": "PREMIUM", "name": "Premium",
            "crop_id": str(crop.id), "variety_id": None, "description": None,
        },
        headers=manage_headers,
    )
    assert create_response.status_code == 201
    definition_id = create_response.json()["id"]

    version_response = client.post(
        f"/grade-definitions/{definition_id}/versions",
        json={"client_command_id": str(uuid.uuid4()), "spec_notes": "Firm heads, no tip-burn"},
        headers=manage_headers,
    )
    assert version_response.status_code == 201
    version_id = version_response.json()["id"]

    activate_response = client.post(
        f"/grade-definitions/{definition_id}/versions/{version_id}/activate",
        json={"client_command_id": str(uuid.uuid4()), "effective_time": _now_iso()},
        headers=manage_headers,
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["status"] == "active"


@pytest.mark.integration
def test_cross_tenant_api_access_returns_404(client, db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = crop_service.register_crop(
        db_session, tenant_id=tenant_a.id, actor_user_id=None, code="LET", common_name="Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    manage_headers_a, _ = _role_headers(db_session, tenant_id=tenant_a.id, role_code="packing_supervisor")
    create_response = client.post(
        "/grade-definitions",
        json={
            "client_command_id": str(uuid.uuid4()), "code": "PREMIUM", "name": "Premium",
            "crop_id": str(crop_a.id), "variety_id": None, "description": None,
        },
        headers=manage_headers_a,
    )
    definition_id = create_response.json()["id"]

    tenant_b = tenant_service.create_tenant(db_session, code="grade-api-tenant-b", name="Tenant B")
    manage_headers_b, _ = _role_headers(db_session, tenant_id=tenant_b.id, role_code="packing_supervisor")

    response = client.get(f"/grade-definitions/{definition_id}", headers=manage_headers_b)
    assert response.status_code == 404


@pytest.mark.integration
def test_inactive_membership_denied(client, db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    manage_headers, manage_user = _role_headers(db_session, tenant_id=tenant.id, role_code="packing_supervisor")

    membership = db_session.query(TenantMembership).filter_by(
        tenant_id=tenant.id, user_id=manage_user.id
    ).one()
    membership.status = "removed"
    db_session.flush()

    response = client.get("/grade-definitions", headers=manage_headers)
    assert response.status_code == 403


@pytest.mark.integration
def test_list_and_detail_responses_expose_required_fields(client, db_session, active_context) -> None:
    tenant, _user, headers = active_context
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="LET", common_name="Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=None, crop_id=crop.id, code="MAM", name="Mamutik RZ",
        supplier_reference=None,
    )
    create_response = client.post(
        "/grade-definitions",
        json={
            "client_command_id": str(uuid.uuid4()), "code": "PREMIUM", "name": "Premium",
            "crop_id": str(crop.id), "variety_id": str(variety.id), "description": "Top tier",
        },
        headers=headers,
    )
    assert create_response.status_code == 201
    body = create_response.json()
    for field in ("id", "tenant_id", "crop_id", "variety_id", "code", "name", "description", "created_at"):
        assert field in body, f"missing {field} in GradeDefinitionRead"

    definition_id = body["id"]
    version_response = client.post(
        f"/grade-definitions/{definition_id}/versions",
        json={"client_command_id": str(uuid.uuid4()), "spec_notes": None},
        headers=headers,
    )
    version_body = version_response.json()
    for field in (
        "id", "tenant_id", "grade_definition_id", "version_number", "status", "effective_from",
        "effective_until", "spec_notes", "created_by", "created_at",
    ):
        assert field in version_body, f"missing {field} in GradeDefinitionVersionRead"

    list_response = client.get(f"/grade-definitions?crop_id={crop.id}", headers=headers)
    assert list_response.status_code == 200
    assert any(d["id"] == definition_id for d in list_response.json())
