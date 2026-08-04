"""Core CMP-011 acceptance flow: farm -> Iceberg/Mamutik -> seed-tray carriers
-> variety-specific workflow (SEEDING requires seed_tray -> TRANSPLANTING
requires cultivation_plate -> COMPLETE) -> crop batch -> sow four trays ->
progress to TRANSPLANTING -> register cultivation-plate carriers ->
transplant with a many-to-many split and one fully-discarded source tray ->
source assignments released, destination assignments opened, full lineage
visible on the batch's carrier-history endpoint -> idempotent retry ->
reject reusing a released source, reject reassigning an already-assigned
destination, reject a reused command with a different payload -> retry
survives further batch progression -> reject cross-tenant access. All via
the API."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.occupancy import Occupancy


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.mark.integration
def test_core_transplant_acceptance_flow(client, active_context, db_session) -> None:
    _tenant, _user, headers = active_context

    # 1. Create an active farm.
    farm = client.post(
        "/farms", headers=headers,
        json={"code": "tp-farm", "name": "Transplant Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    ).json()
    farm_id = farm["id"]

    # 2. Register Iceberg crop and Mamutik variety.
    crop = client.post(
        "/crops", headers=headers,
        json={"code": "iceberg-tp", "common_name": "Iceberg Lettuce", "crop_category": "leafy_green"},
    ).json()
    variety = client.post(
        f"/crops/{crop['id']}/varieties", headers=headers, json={"code": "mamutik-tp", "name": "Mamutik RZ"}
    ).json()

    # 3. Register an active seed lot for Mamutik.
    seed_lot = client.post(
        f"/farms/{farm_id}/seed-lots", headers=headers,
        json={"crop_id": crop["id"], "variety_id": variety["id"], "code": "LOT-TP-0001"},
    ).json()

    # 4. Create five seed-tray carriers (a fifth is kept back, unused by the
    # main transplant, to later prove destination-collision rejection with
    # a genuinely fresh, unreleased source line).
    source_carriers = [
        client.post(
            f"/farms/{farm_id}/carriers", headers=headers,
            json={"carrier_type_code": "seed_tray", "code": f"ST-TP-{n:04d}"},
        ).json()
        for n in range(1, 6)
    ]

    # 5. Create and publish a variety-specific workflow: SEEDING (seed_tray)
    # -> TRANSPLANTING (cultivation_plate) -> COMPLETE.
    production_system = client.post(
        "/production-systems", headers=headers, json={"code": "tp-ps", "name": "Nursery Tray"}
    ).json()
    workflow = client.post(
        "/workflows", headers=headers,
        json={
            "crop_id": crop["id"], "variety_id": variety["id"], "production_system_id": production_system["id"],
            "code": "tp-workflow", "name": "Iceberg Nursery to Transplant",
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
    transplanting_stage = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={
            "code": "TRANSPLANTING", "name": "Transplanting", "display_order": 1,
            "stage_category": "transplanting", "required_carrier_type_code": "cultivation_plate",
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
    advance_1 = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
        json={
            "from_stage_id": seeding_stage["id"], "to_stage_id": transplanting_stage["id"],
            "code": "ADVANCE-1", "name": "Advance to Transplanting",
        },
    ).json()
    advance_2 = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
        json={
            "from_stage_id": transplanting_stage["id"], "to_stage_id": complete_stage["id"],
            "code": "ADVANCE-2", "name": "Advance to Complete",
        },
    ).json()
    publish_resp = client.post(f"/workflows/{workflow['id']}/versions/{version['id']}/publish", headers=headers)
    assert publish_resp.status_code == 200

    # 6. Create crop batch ICE-TP-0001; confirm it starts in SEEDING.
    batch_resp = client.post(
        f"/farms/{farm_id}/crop-batches", headers=headers,
        json={
            "code": "ICE-TP-0001", "workflow_id": workflow["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    assert batch_resp.status_code == 201
    batch = batch_resp.json()
    assert batch["current_stage"]["code"] == "SEEDING"

    # 7. Sow all five trays, 200 sites/seeds each.
    sow_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/sowings", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "lines": [
                {"carrier_id": c["id"], "seed_lot_id": seed_lot["id"], "sown_site_count": 200, "seed_count": 200}
                for c in source_carriers
            ],
        },
    )
    assert sow_resp.status_code == 201
    source_assignments = {
        a["carrier"]["code"]: a
        for a in client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/carriers", headers=headers).json()
    }
    assert len(source_assignments) == 5
    assert all(a["opening_sowing_event_id"] is not None for a in source_assignments.values())
    assert all(a["opening_transplant_event_id"] is None for a in source_assignments.values())
    source_ids = {c["code"]: source_assignments[c["code"]]["id"] for c in source_carriers}

    occupancy_count_before = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()

    # 8. Progress the batch into TRANSPLANTING.
    transition_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": advance_1["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    assert transition_resp.status_code == 201
    current = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/current-stage", headers=headers).json()
    assert current["current_stage"]["code"] == "TRANSPLANTING"

    # 9. Register three cultivation-plate destination carriers.
    destination_carriers = [
        client.post(
            f"/farms/{farm_id}/carriers", headers=headers,
            json={"carrier_type_code": "cultivation_plate", "code": f"CP-TP-{n:04d}"},
        ).json()
        for n in range(1, 4)
    ]

    # 10 & 11. Transplant: tray 1 -> plate 1 one-to-one; trays 2 & 3 split
    # many-to-many across plates 2 & 3; tray 4 fully discarded (no
    # allocation, discarded_plant_count == source_plant_count).
    transplant_command_id = str(uuid.uuid4())
    transplant_effective_time = _now_iso()
    transplant_payload = {
        "client_command_id": transplant_command_id, "effective_time": transplant_effective_time,
        "source_lines": [
            {"source_assignment_id": source_ids["ST-TP-0001"], "source_plant_count": 200, "discarded_plant_count": 0},
            {"source_assignment_id": source_ids["ST-TP-0002"], "source_plant_count": 200, "discarded_plant_count": 0},
            {"source_assignment_id": source_ids["ST-TP-0003"], "source_plant_count": 200, "discarded_plant_count": 0},
            {"source_assignment_id": source_ids["ST-TP-0004"], "source_plant_count": 200, "discarded_plant_count": 200},
        ],
        "destination_lines": [
            {"destination_carrier_id": destination_carriers[0]["id"], "assigned_plant_count": 200},
            {"destination_carrier_id": destination_carriers[1]["id"], "assigned_plant_count": 200},
            {"destination_carrier_id": destination_carriers[2]["id"], "assigned_plant_count": 200},
        ],
        "allocations": [
            {
                "source_assignment_id": source_ids["ST-TP-0001"],
                "destination_carrier_id": destination_carriers[0]["id"], "allocated_plant_count": 200,
            },
            {
                "source_assignment_id": source_ids["ST-TP-0002"],
                "destination_carrier_id": destination_carriers[1]["id"], "allocated_plant_count": 120,
            },
            {
                "source_assignment_id": source_ids["ST-TP-0002"],
                "destination_carrier_id": destination_carriers[2]["id"], "allocated_plant_count": 80,
            },
            {
                "source_assignment_id": source_ids["ST-TP-0003"],
                "destination_carrier_id": destination_carriers[1]["id"], "allocated_plant_count": 80,
            },
            {
                "source_assignment_id": source_ids["ST-TP-0003"],
                "destination_carrier_id": destination_carriers[2]["id"], "allocated_plant_count": 120,
            },
        ],
    }
    transplant_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/transplants", headers=headers, json=transplant_payload,
    )
    assert transplant_resp.status_code == 201
    transplant_event = transplant_resp.json()
    assert len(transplant_event["source_lines"]) == 4
    assert len(transplant_event["destination_lines"]) == 3
    assert len(transplant_event["allocations"]) == 5
    assert transplant_event["total_source_plant_count"] == 800
    assert transplant_event["total_destination_plant_count"] == 600
    assert transplant_event["total_discarded_plant_count"] == 200

    # 12. Confirm no occupancy records were created or modified — this is a
    # pure carrier-assignment transformation, not a location movement.
    occupancy_count_after = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    assert occupancy_count_after == occupancy_count_before

    # 13. Confirm the full carrier-history endpoint now shows all eight
    # assignments (five sowing-origin, four of them released, tray 5 still
    # active + three active transplant-origin) — immutable history, not
    # overwritten.
    all_assignments = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/carriers", headers=headers).json()
    assert len(all_assignments) == 8
    released_source_ids = {source_ids[c] for c in ("ST-TP-0001", "ST-TP-0002", "ST-TP-0003", "ST-TP-0004")}
    released = {a["id"]: a for a in all_assignments if a["released_effective_time"] is not None}
    assert set(released.keys()) == released_source_ids
    for a in released.values():
        assert a["released_by_transplant_event_id"] == transplant_event["id"]
    opened_by_transplant = [a for a in all_assignments if a["opening_transplant_event_id"] == transplant_event["id"]]
    assert len(opened_by_transplant) == 3
    assert all(a["released_effective_time"] is None for a in opened_by_transplant)

    # 14. Confirm each destination carrier now traces back to the batch via
    # its own single-carrier endpoint.
    for c in destination_carriers:
        assignment = client.get(f"/farms/{farm_id}/carriers/{c['id']}/batch-assignment", headers=headers).json()
        assert assignment["batch_id"] == batch["id"]
        assert assignment["opening_transplant_event_id"] == transplant_event["id"]

    # 15. Confirm exactly one crop_batch.transplanted audit event.
    transplanted_events = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.transplanted", AuditEvent.entity_id == transplant_event["id"]
        )
    ).scalar_one()
    assert transplanted_events == 1

    # 16. Idempotent retry of the exact same command returns the original
    # event; no duplicate lines/allocations/assignments/audit events.
    retry_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/transplants", headers=headers, json=transplant_payload,
    )
    assert retry_resp.status_code == 201
    assert retry_resp.json()["id"] == transplant_event["id"]
    transplants_after_retry = client.get(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/transplants", headers=headers
    ).json()
    assert len(transplants_after_retry) == 1
    assert db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.transplanted", AuditEvent.entity_id == transplant_event["id"]
        )
    ).scalar_one() == 1

    # 17. Reject a reused command id carrying a materially different
    # payload.
    tampered_payload = {**transplant_payload}
    tampered_payload["note"] = "different payload, same command id"
    reused_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/transplants", headers=headers, json=tampered_payload,
    )
    assert reused_resp.status_code == 409

    # 18. Reject re-transplanting an already-released source assignment.
    extra_destination = client.post(
        f"/farms/{farm_id}/carriers", headers=headers,
        json={"carrier_type_code": "cultivation_plate", "code": "CP-TP-EXTRA"},
    ).json()
    reuse_source_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/transplants", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "source_lines": [
                {"source_assignment_id": source_ids["ST-TP-0001"], "source_plant_count": 200, "discarded_plant_count": 0}
            ],
            "destination_lines": [{"destination_carrier_id": extra_destination["id"], "assigned_plant_count": 200}],
            "allocations": [
                {
                    "source_assignment_id": source_ids["ST-TP-0001"],
                    "destination_carrier_id": extra_destination["id"], "allocated_plant_count": 200,
                }
            ],
        },
    )
    assert reuse_source_resp.status_code == 409

    # 19. Reject reassigning an already-assigned destination carrier (one
    # opened by the first transplant) to a fresh command. Tray 5's
    # assignment was deliberately never touched by the original transplant,
    # so it is still active and eligible — isolating this rejection to the
    # destination-carrier collision alone.
    reassign_destination_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/transplants", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "source_lines": [
                {"source_assignment_id": source_ids["ST-TP-0005"], "source_plant_count": 200, "discarded_plant_count": 0}
            ],
            "destination_lines": [
                {"destination_carrier_id": destination_carriers[0]["id"], "assigned_plant_count": 200}
            ],
            "allocations": [
                {
                    "source_assignment_id": source_ids["ST-TP-0005"],
                    "destination_carrier_id": destination_carriers[0]["id"], "allocated_plant_count": 200,
                }
            ],
        },
    )
    assert reassign_destination_resp.status_code == 409

    # 20. Progress the batch to COMPLETE; retry the original transplant
    # command and confirm it still returns the original event unchanged.
    client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": advance_2["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    final_current = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/current-stage", headers=headers).json()
    assert final_current["current_stage"]["code"] == "COMPLETE"
    final_retry_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/transplants", headers=headers, json=transplant_payload,
    )
    assert final_retry_resp.status_code == 201
    assert final_retry_resp.json()["id"] == transplant_event["id"]
    assert db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.transplanted", AuditEvent.entity_id == transplant_event["id"]
        )
    ).scalar_one() == 1

    # 21. Reject cross-tenant access to the transplant event.
    from app.services import membership_service, tenant_service, user_service

    tenant_b = tenant_service.create_tenant(db_session, code="tp-acceptance-tenant-b", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="tp-acceptance-b", email="tpaccb@example.com",
        display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    cross_tenant_resp = client.get(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/transplants/{transplant_event['id']}", headers=headers_b
    )
    assert cross_tenant_resp.status_code == 404
