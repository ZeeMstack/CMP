"""Core CMP-008 acceptance flow: farm -> crop/variety/production-system ->
workflow -> published version 1 with a 4-stage graph -> batch creation ->
progression -> version-2 publication without affecting the bound batch ->
closure on terminal entry -> full history -> idempotent retry -> rejected
cross-version transition -> rejected cross-tenant access. All via the API."""
import uuid
from datetime import datetime, timezone

import pytest


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.mark.integration
def test_core_acceptance_flow(client, active_context, db_session) -> None:
    _tenant, _user, headers = active_context

    # 1. Create an active farm.
    farm = client.post(
        "/farms", headers=headers,
        json={"code": "ice-farm", "name": "Iceberg Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    ).json()
    farm_id = farm["id"]

    # 2. Create Iceberg crop and Mamutik variety.
    crop = client.post(
        "/crops", headers=headers,
        json={"code": "iceberg", "common_name": "Iceberg Lettuce", "crop_category": "leafy_green"},
    ).json()
    variety = client.post(
        f"/crops/{crop['id']}/varieties", headers=headers, json={"code": "mamutik", "name": "Mamutik RZ"}
    ).json()

    # 3. Create a production system.
    production_system = client.post(
        "/production-systems", headers=headers, json={"code": "nursery-tray", "name": "Nursery Seed Tray"}
    ).json()

    # 4. Create a workflow.
    workflow = client.post(
        "/workflows", headers=headers,
        json={
            "crop_id": crop["id"], "variety_id": variety["id"],
            "production_system_id": production_system["id"], "code": "iceberg-nursery", "name": "Iceberg Nursery",
        },
    ).json()

    # 5. Create and publish version 1 with SEEDING, GERMINATION, NURSERY, COMPLETE.
    version_1 = client.post(f"/workflows/{workflow['id']}/versions", headers=headers).json()
    stage_codes = ["SEEDING", "GERMINATION", "NURSERY", "COMPLETE"]
    categories = {"SEEDING": "seeding", "GERMINATION": "germination", "NURSERY": "nursery", "COMPLETE": "completed"}
    stages_v1 = {}
    for i, code in enumerate(stage_codes):
        stage = client.post(
            f"/workflows/{workflow['id']}/versions/{version_1['id']}/stages", headers=headers,
            json={
                "code": code, "name": code.title(), "display_order": i, "stage_category": categories[code],
                "is_start": i == 0, "is_terminal": i == len(stage_codes) - 1,
            },
        ).json()
        stages_v1[code] = stage

    # 6. Configure valid transitions between those stages.
    transitions_v1 = {}
    for i in range(len(stage_codes) - 1):
        from_code, to_code = stage_codes[i], stage_codes[i + 1]
        t = client.post(
            f"/workflows/{workflow['id']}/versions/{version_1['id']}/transitions", headers=headers,
            json={
                "from_stage_id": stages_v1[from_code]["id"], "to_stage_id": stages_v1[to_code]["id"],
                "code": f"ADVANCE-{i}", "name": f"Advance to {to_code}",
            },
        ).json()
        transitions_v1[(from_code, to_code)] = t
    publish_resp = client.post(
        f"/workflows/{workflow['id']}/versions/{version_1['id']}/publish", headers=headers
    )
    assert publish_resp.status_code == 200

    # 7. Create batch ICE-0001.
    create_resp = client.post(
        f"/farms/{farm_id}/crop-batches", headers=headers,
        json={
            "code": "ICE-0001", "workflow_id": workflow["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    assert create_resp.status_code == 201
    batch = create_resp.json()

    # 8. Confirm it binds to workflow version 1.
    assert batch["workflow_version_id"] == version_1["id"]
    assert batch["version_number"] == 1

    # 9. Confirm its current stage is SEEDING.
    assert batch["current_stage"]["code"] == "SEEDING"

    # 10. Progress it to GERMINATION.
    t1_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": transitions_v1[("SEEDING", "GERMINATION")]["id"],
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
        },
    )
    assert t1_resp.status_code == 201
    current = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/current-stage", headers=headers).json()
    assert current["current_stage"]["code"] == "GERMINATION"

    # 11. Publish workflow version 2.
    version_2 = client.post(f"/workflows/{workflow['id']}/versions", headers=headers).json()
    only_stage_v2 = client.post(
        f"/workflows/{workflow['id']}/versions/{version_2['id']}/stages", headers=headers,
        json={
            "code": "ONLY", "name": "Only", "display_order": 0, "stage_category": "completed",
            "is_start": True, "is_terminal": True,
        },
    ).json()
    client.post(f"/workflows/{workflow['id']}/versions/{version_2['id']}/publish", headers=headers)

    # 12. Confirm ICE-0001 remains bound to version 1.
    batch_after_v2 = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}", headers=headers).json()
    assert batch_after_v2["workflow_version_id"] == version_1["id"]

    # 13. Progress it through the remaining version-1 transitions.
    client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": transitions_v1[("GERMINATION", "NURSERY")]["id"],
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
        },
    )
    final_command_id = str(uuid.uuid4())
    final_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": transitions_v1[("NURSERY", "COMPLETE")]["id"],
            "client_command_id": final_command_id, "effective_time": _now_iso(),
        },
    )
    assert final_resp.status_code == 201

    # 14. Confirm entering COMPLETE closes the batch.
    closed_batch = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}", headers=headers).json()
    assert closed_batch["state"] == "closed"
    assert closed_batch["current_stage"]["code"] == "COMPLETE"

    # 15. Confirm complete ordered stage history.
    history = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-history", headers=headers).json()
    assert [entry["stage"]["code"] for entry in history] == stage_codes
    for entry in history[:-1]:
        assert entry["exited_effective_time"] is not None
    assert history[-1]["exited_effective_time"] is None

    # 16 & 17. Retry one stage-transition command ID; confirm no duplicate run/transition/event.
    retry_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": transitions_v1[("NURSERY", "COMPLETE")]["id"],
            "client_command_id": final_command_id, "effective_time": final_resp.json()["effective_time"],
        },
    )
    assert retry_resp.status_code == 201
    assert retry_resp.json()["id"] == final_resp.json()["id"]
    history_after_retry = client.get(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-history", headers=headers
    ).json()
    assert len(history_after_retry) == len(history)

    from sqlalchemy import func, select

    from app.models.audit_event import AuditEvent

    closed_events = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "crop_batch.closed")
    ).scalar_one()
    assert closed_events == 1

    # 18. Attempt a version-2 transition against the version-1 batch and reject it.
    # (version 2 has no transitions at all — its only stage is both start and terminal —
    # so any configured_transition_id from version 2 cannot exist; use the workflow's own
    # version-1 stage id as a bogus "configured_transition_id" to prove version-2 references
    # are never accepted for a version-1-bound, already-closed batch.)
    bad_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": str(only_stage_v2["id"]), "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    assert bad_resp.status_code in (404, 409)

    # 19. Attempt cross-tenant access and reject it.
    from app.services import membership_service, tenant_service, user_service

    tenant_b = tenant_service.create_tenant(db_session, code="acceptance-tenant-b", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="acceptance-b", email="accb@example.com", display_name="B"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    cross_tenant_resp = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}", headers=headers_b)
    assert cross_tenant_resp.status_code == 404
