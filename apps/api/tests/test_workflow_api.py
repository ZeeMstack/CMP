"""PILOT-SETUP-001B6A: HTTP-level authorization and tenant-isolation proofs
for the new read-only `GET /workflows/{workflow_id}` and
`GET /workflows/{workflow_id}/versions` endpoints. Mirrors
test_grade_definition_api.py's own `_role_headers` helper and assertion
style -- these two endpoints reuse the existing `workflow.read`/
`workflow.manage` permissions; no new permission is introduced."""
import uuid

import pytest

from app.models.audit_event import AuditEvent
from app.services import crop_service, membership_service, production_system_service, tenant_service, user_service


def _role_headers(db_session, *, tenant_id, role_code: str) -> dict[str, str]:
    user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"workflow-role-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com", display_name="Workflow Role Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}


def _setup(db_session, tenant):
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="LET", common_name="Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    production_system = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="NURSERY-TRAY", name="Nursery Tray",
        description=None,
    )
    return crop, production_system


def _create_workflow(client, headers, crop, production_system, code="ICE-NUR"):
    response = client.post(
        "/workflows",
        json={
            "crop_id": str(crop.id), "variety_id": None, "production_system_id": str(production_system.id),
            "code": code, "name": "Iceberg Nursery Workflow",
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.integration
def test_get_workflow_succeeds(client, db_session, active_context) -> None:
    tenant, _user, headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _create_workflow(client, headers, crop, production_system)

    response = client.get(f"/workflows/{workflow['id']}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == workflow["id"]
    assert body["code"] == "ICE-NUR"
    for field in ("id", "tenant_id", "crop_id", "variety_id", "production_system_id", "code", "name", "status"):
        assert field in body, f"missing {field} in WorkflowRead"


@pytest.mark.integration
def test_get_unknown_workflow_returns_404(client, active_context) -> None:
    _tenant, _user, headers = active_context
    response = client.get(f"/workflows/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 404


@pytest.mark.integration
def test_cross_tenant_workflow_read_returns_404(client, db_session, active_context) -> None:
    tenant_a, _user, headers_a = active_context
    crop_a, production_system_a = _setup(db_session, tenant_a)
    workflow_a = _create_workflow(client, headers_a, crop_a, production_system_a)

    tenant_b = tenant_service.create_tenant(db_session, code="wf-api-tenant-b", name="Tenant B")
    headers_b = _role_headers(db_session, tenant_id=tenant_b.id, role_code="tenant_admin")

    response = client.get(f"/workflows/{workflow_a['id']}", headers=headers_b)
    assert response.status_code == 404


@pytest.mark.integration
def test_list_workflow_versions_succeeds_and_deterministic_ascending_order(client, db_session, active_context) -> None:
    tenant, _user, headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _create_workflow(client, headers, crop, production_system)

    v1 = client.post(f"/workflows/{workflow['id']}/versions", headers=headers).json()
    v2 = client.post(f"/workflows/{workflow['id']}/versions", headers=headers).json()

    response = client.get(f"/workflows/{workflow['id']}/versions", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert [v["id"] for v in body] == [v1["id"], v2["id"]]
    assert [v["version_number"] for v in body] == [1, 2]
    for field in ("id", "tenant_id", "workflow_id", "version_number", "state", "created_at", "published_at", "retired_at"):
        assert field in body[0], f"missing {field} in WorkflowVersionRead"


@pytest.mark.integration
def test_list_workflow_versions_reflects_draft_published_retired_truthfully(client, db_session, active_context) -> None:
    tenant, _user, headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _create_workflow(client, headers, crop, production_system)

    v1 = client.post(f"/workflows/{workflow['id']}/versions", headers=headers).json()
    stage = client.post(
        f"/workflows/{workflow['id']}/versions/{v1['id']}/stages",
        json={
            "code": "S1", "name": "Stage 1", "display_order": 0, "stage_category": "seeding",
            "expected_duration_minutes": None, "permitted_location_type_code": None,
            "required_carrier_type_code": None, "is_start": True, "is_terminal": True,
        },
        headers=headers,
    )
    assert stage.status_code == 201
    publish = client.post(f"/workflows/{workflow['id']}/versions/{v1['id']}/publish", headers=headers)
    assert publish.status_code == 200
    v2 = client.post(f"/workflows/{workflow['id']}/versions", headers=headers).json()
    stage2 = client.post(
        f"/workflows/{workflow['id']}/versions/{v2['id']}/stages",
        json={
            "code": "S1", "name": "Stage 1", "display_order": 0, "stage_category": "seeding",
            "expected_duration_minutes": None, "permitted_location_type_code": None,
            "required_carrier_type_code": None, "is_start": True, "is_terminal": True,
        },
        headers=headers,
    )
    assert stage2.status_code == 201
    # Publishing v2 is what retires v1 -- a version stays "published" until a
    # later one is actually published, never merely because a new draft exists.
    publish2 = client.post(f"/workflows/{workflow['id']}/versions/{v2['id']}/publish", headers=headers)
    assert publish2.status_code == 200

    response = client.get(f"/workflows/{workflow['id']}/versions", headers=headers)
    body = response.json()
    assert body[0]["id"] == v1["id"]
    assert body[0]["state"] == "retired"
    assert body[0]["published_at"] is not None
    assert body[1]["id"] == v2["id"]
    assert body[1]["state"] == "published"
    assert body[1]["published_at"] is not None


@pytest.mark.integration
def test_list_workflow_versions_unknown_workflow_returns_404(client, active_context) -> None:
    _tenant, _user, headers = active_context
    response = client.get(f"/workflows/{uuid.uuid4()}/versions", headers=headers)
    assert response.status_code == 404


@pytest.mark.integration
def test_list_workflow_versions_cross_tenant_returns_404(client, db_session, active_context) -> None:
    tenant_a, _user, headers_a = active_context
    crop_a, production_system_a = _setup(db_session, tenant_a)
    workflow_a = _create_workflow(client, headers_a, crop_a, production_system_a)
    client.post(f"/workflows/{workflow_a['id']}/versions", headers=headers_a)

    tenant_b = tenant_service.create_tenant(db_session, code="wf-api-tenant-c", name="Tenant C")
    headers_b = _role_headers(db_session, tenant_id=tenant_b.id, role_code="tenant_admin")

    response = client.get(f"/workflows/{workflow_a['id']}/versions", headers=headers_b)
    assert response.status_code == 404


@pytest.mark.integration
def test_workflow_read_role_can_read_but_not_mutate(client, db_session, active_context) -> None:
    """`auditor` holds `workflow.read` but not `workflow.manage` (see
    ROLE_PERMISSIONS) -- proves the two new endpoints are gated by the
    existing read permission, not accidentally left unauthenticated or
    accidentally requiring `manage`."""
    tenant, _user, headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _create_workflow(client, headers, crop, production_system)

    read_headers = _role_headers(db_session, tenant_id=tenant.id, role_code="auditor")

    get_response = client.get(f"/workflows/{workflow['id']}", headers=read_headers)
    assert get_response.status_code == 200
    versions_response = client.get(f"/workflows/{workflow['id']}/versions", headers=read_headers)
    assert versions_response.status_code == 200

    create_response = client.post(
        "/workflows",
        json={
            "crop_id": str(crop.id), "variety_id": None, "production_system_id": str(production_system.id),
            "code": "SHOULD-FAIL", "name": "Should not be created",
        },
        headers=read_headers,
    )
    assert create_response.status_code == 403
    draft_response = client.post(f"/workflows/{workflow['id']}/versions", headers=read_headers)
    assert draft_response.status_code == 403


@pytest.mark.integration
def test_no_permission_denies_read(client, db_session, active_context) -> None:
    """`storekeeper` holds neither `workflow.read` nor `workflow.manage` --
    both new endpoints must deny it, not silently allow read access."""
    tenant, _user, headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _create_workflow(client, headers, crop, production_system)

    no_access_headers = _role_headers(db_session, tenant_id=tenant.id, role_code="storekeeper")
    assert client.get(f"/workflows/{workflow['id']}", headers=no_access_headers).status_code == 403
    assert client.get(f"/workflows/{workflow['id']}/versions", headers=no_access_headers).status_code == 403


@pytest.mark.integration
def test_get_endpoints_perform_no_mutation(client, db_session, active_context) -> None:
    tenant, _user, headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _create_workflow(client, headers, crop, production_system)
    client.post(f"/workflows/{workflow['id']}/versions", headers=headers)
    db_session.commit()

    audit_count_before = db_session.query(AuditEvent).filter_by(tenant_id=tenant.id).count()

    client.get(f"/workflows/{workflow['id']}", headers=headers)
    client.get(f"/workflows/{workflow['id']}/versions", headers=headers)

    audit_count_after = db_session.query(AuditEvent).filter_by(tenant_id=tenant.id).count()
    assert audit_count_after == audit_count_before
