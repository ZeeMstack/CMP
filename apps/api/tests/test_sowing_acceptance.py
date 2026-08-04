"""Core CMP-009 acceptance flow: farm -> Iceberg/Mamutik -> active seed lot ->
seed-tray carriers -> variety-specific workflow with a seeding start stage
requiring seed_tray -> crop batch -> sowing four trays in one command ->
traceability -> no occupancy side effects -> idempotent retry -> reject
reassigning an already-assigned tray -> retry survives batch progression ->
reject cross-tenant access. All via the API."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.occupancy import Occupancy


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.mark.integration
def test_core_sowing_acceptance_flow(client, active_context, db_session) -> None:
    _tenant, _user, headers = active_context

    # 1. Create an active farm.
    farm = client.post(
        "/farms", headers=headers,
        json={"code": "sow-farm", "name": "Sowing Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    ).json()
    farm_id = farm["id"]

    # 2. Register Iceberg crop and Mamutik variety.
    crop = client.post(
        "/crops", headers=headers,
        json={"code": "iceberg-sow", "common_name": "Iceberg Lettuce", "crop_category": "leafy_green"},
    ).json()
    variety = client.post(
        f"/crops/{crop['id']}/varieties", headers=headers, json={"code": "mamutik-sow", "name": "Mamutik RZ"}
    ).json()

    # 3. Register an active seed lot for Mamutik.
    seed_lot = client.post(
        f"/farms/{farm_id}/seed-lots", headers=headers,
        json={"crop_id": crop["id"], "variety_id": variety["id"], "code": "LOT-0001"},
    ).json()
    assert seed_lot["status"] == "active"

    # 4. Create seed-tray carriers ST-0001..ST-0004.
    carriers = [
        client.post(
            f"/farms/{farm_id}/carriers", headers=headers,
            json={"carrier_type_code": "seed_tray", "code": f"ST-{n:04d}"},
        ).json()
        for n in range(1, 5)
    ]

    # 5. Create and publish a variety-specific workflow whose start stage is
    # seeding and requires seed_tray.
    production_system = client.post(
        "/production-systems", headers=headers, json={"code": "sow-ps", "name": "Nursery Tray"}
    ).json()
    workflow = client.post(
        "/workflows", headers=headers,
        json={
            "crop_id": crop["id"], "variety_id": variety["id"], "production_system_id": production_system["id"],
            "code": "sow-workflow", "name": "Iceberg Nursery",
        },
    ).json()
    version = client.post(f"/workflows/{workflow['id']}/versions", headers=headers).json()
    seeding_stage = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={
            "code": "SEEDING", "name": "Seeding", "display_order": 0, "stage_category": "seeding",
            "required_carrier_type_code": "seed_tray", "is_start": True, "is_terminal": False,
        },
    ).json()
    germination_stage = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={
            "code": "GERMINATION", "name": "Germination", "display_order": 1, "stage_category": "germination",
            "is_start": False, "is_terminal": False,
        },
    ).json()
    complete_stage = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={
            "code": "COMPLETE", "name": "Complete", "display_order": 2, "stage_category": "completed",
            "is_start": False, "is_terminal": True,
        },
    ).json()
    transition_1 = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
        json={
            "from_stage_id": seeding_stage["id"], "to_stage_id": germination_stage["id"],
            "code": "ADVANCE-1", "name": "Advance to Germination",
        },
    ).json()
    client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
        json={
            "from_stage_id": germination_stage["id"], "to_stage_id": complete_stage["id"],
            "code": "ADVANCE-2", "name": "Advance to Complete",
        },
    )
    publish_resp = client.post(f"/workflows/{workflow['id']}/versions/{version['id']}/publish", headers=headers)
    assert publish_resp.status_code == 200

    # 6. Create crop batch ICE-0001.
    batch_resp = client.post(
        f"/farms/{farm_id}/crop-batches", headers=headers,
        json={
            "code": "ICE-0001", "workflow_id": workflow["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    assert batch_resp.status_code == 201
    batch = batch_resp.json()

    # 7. Confirm it starts in the seeding stage.
    assert batch["current_stage"]["code"] == "SEEDING"

    occupancy_count_before = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()

    # 8 & 9. Sow four trays using one command, 200 sites / 200 seeds each.
    sow_command_id = str(uuid.uuid4())
    sow_effective_time = _now_iso()
    sow_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/sowings", headers=headers,
        json={
            "client_command_id": sow_command_id, "effective_time": sow_effective_time,
            "lines": [
                {
                    "carrier_id": c["id"], "seed_lot_id": seed_lot["id"], "sown_site_count": 200,
                    "seed_count": 200,
                }
                for c in carriers
            ],
        },
    )
    assert sow_resp.status_code == 201
    sowing_event = sow_resp.json()
    assert len(sowing_event["lines"]) == 4
    for line in sowing_event["lines"]:
        assert line["sown_site_count"] == 200
        assert line["seed_count"] == 200

    # 10. Confirm four active carrier assignments.
    carriers_resp = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/carriers", headers=headers)
    assert carriers_resp.status_code == 200
    assignments = carriers_resp.json()
    assert len(assignments) == 4
    assert all(a["released_effective_time"] is None for a in assignments)

    # 11. Confirm each tray traces to the seed lot and batch.
    for carrier in carriers:
        assignment_resp = client.get(
            f"/farms/{farm_id}/carriers/{carrier['id']}/batch-assignment", headers=headers
        )
        assert assignment_resp.status_code == 200
        assignment = assignment_resp.json()
        assert assignment["batch_id"] == batch["id"]
        assert assignment["carrier"]["code"] == carrier["code"]
    for line in sowing_event["lines"]:
        assert line["seed_lot"]["id"] == seed_lot["id"]

    # 12. Confirm no occupancy records were created or modified.
    occupancy_count_after = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    assert occupancy_count_after == occupancy_count_before

    # 13 & 14. Retry the same command ID; confirm no duplicate event/line/assignment/audit.
    retry_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/sowings", headers=headers,
        json={
            "client_command_id": sow_command_id, "effective_time": sow_effective_time,
            "lines": [
                {
                    "carrier_id": c["id"], "seed_lot_id": seed_lot["id"], "sown_site_count": 200,
                    "seed_count": 200,
                }
                for c in carriers
            ],
        },
    )
    assert retry_resp.status_code == 201
    assert retry_resp.json()["id"] == sowing_event["id"]
    sowings_after_retry = client.get(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/sowings", headers=headers
    ).json()
    assert len(sowings_after_retry) == 1
    assert len(sowings_after_retry[0]["lines"]) == 4
    assignments_after_retry = client.get(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/carriers", headers=headers
    ).json()
    assert len(assignments_after_retry) == 4
    sown_events = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.sown", AuditEvent.entity_id == uuid.UUID(sowing_event["id"])
        )
    ).scalar_one()
    assert sown_events == 1

    # 15. Attempt assigning one tray to another batch and reject it.
    other_batch_resp = client.post(
        f"/farms/{farm_id}/crop-batches", headers=headers,
        json={
            "code": "ICE-0002", "workflow_id": workflow["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    other_batch = other_batch_resp.json()
    other_seed_lot = client.post(
        f"/farms/{farm_id}/seed-lots", headers=headers,
        json={"crop_id": crop["id"], "variety_id": variety["id"], "code": "LOT-0002"},
    ).json()
    reassign_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{other_batch['id']}/sowings", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "lines": [
                {
                    "carrier_id": carriers[0]["id"], "seed_lot_id": other_seed_lot["id"],
                    "sown_site_count": 100, "seed_count": 100,
                }
            ],
        },
    )
    assert reassign_resp.status_code == 409

    # 16. Progress the original batch to its next workflow stage.
    transition_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": transition_1["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    assert transition_resp.status_code == 201
    current = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/current-stage", headers=headers).json()
    assert current["current_stage"]["code"] == "GERMINATION"

    # 17. Retry the original sowing command and return the original event.
    final_retry_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/sowings", headers=headers,
        json={
            "client_command_id": sow_command_id, "effective_time": sow_effective_time,
            "lines": [
                {
                    "carrier_id": c["id"], "seed_lot_id": seed_lot["id"], "sown_site_count": 200,
                    "seed_count": 200,
                }
                for c in carriers
            ],
        },
    )
    assert final_retry_resp.status_code == 201
    assert final_retry_resp.json()["id"] == sowing_event["id"]
    sown_events_after_progression = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.sown", AuditEvent.entity_id == uuid.UUID(sowing_event["id"])
        )
    ).scalar_one()
    assert sown_events_after_progression == 1

    # 18. Reject cross-tenant access.
    from app.services import membership_service, tenant_service, user_service

    tenant_b = tenant_service.create_tenant(db_session, code="sow-acceptance-tenant-b", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="sow-acceptance-b", email="sowaccb@example.com",
        display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    cross_tenant_resp = client.get(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/sowings/{sowing_event['id']}", headers=headers_b
    )
    assert cross_tenant_resp.status_code == 404
