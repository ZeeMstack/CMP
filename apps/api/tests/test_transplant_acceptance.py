"""Core NURSERY-OPS-004A acceptance flow: a real Nursery scenario (sown,
germinated, SeedlingEntry-anchored Seed Trays) built at the service layer
(mirrors test_seedling_disposition.py's own established convention for
Nursery scenario setup), then the actual transplant command -- a
many-to-many split, one fully-lost source tray, one partial-remainder tray
-- exercised end-to-end through the real HTTP API: source assignments
conditionally released, destination assignments opened, checkpoints
created, full lineage visible on the batch's carrier-history endpoint,
idempotent retry, reject reusing a released source, reject reassigning an
already-assigned destination, reject a reused command with a different
payload, retry survives further batch progression, reject cross-tenant
access."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.occupancy import Occupancy
from tests._transplant_scenario import build_transplant_ready_scenario


@pytest.mark.integration
def test_core_transplant_acceptance_flow(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = build_transplant_ready_scenario(db_session, tenant, user, farm, tray_count=5)
    db_session.commit()

    farm_id = str(farm.id)
    batch_id = str(s["batch_id"])
    source_ids = {c.code: str(aid) for c, aid in zip(s["source_carriers"], s["source_assignment_ids"])}
    destination_carriers = s["destination_carriers"]

    occupancy_count_before = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()

    transplant_command_id = str(uuid.uuid4())
    transplant_effective_time = (s["entry_time"] + timedelta(hours=2)).isoformat()
    tray_codes = [c.code for c in s["source_carriers"]]
    transplant_payload = {
        "client_command_id": transplant_command_id, "effective_time": transplant_effective_time,
        "source_lines": [
            {"source_assignment_id": source_ids[tray_codes[0]]},
            {"source_assignment_id": source_ids[tray_codes[1]]},
            {"source_assignment_id": source_ids[tray_codes[2]]},
            {"source_assignment_id": source_ids[tray_codes[3]], "transplant_damage_count": 200},
        ],
        "destination_lines": [
            {"destination_carrier_id": destination_carriers[0].id.__str__(), "assigned_plant_count": 200},
            {"destination_carrier_id": destination_carriers[1].id.__str__(), "assigned_plant_count": 200},
            {"destination_carrier_id": destination_carriers[2].id.__str__(), "assigned_plant_count": 200},
        ],
        "allocations": [
            {"source_assignment_id": source_ids[tray_codes[0]], "destination_carrier_id": destination_carriers[0].id.__str__(), "allocated_plant_count": 200},
            {"source_assignment_id": source_ids[tray_codes[1]], "destination_carrier_id": destination_carriers[1].id.__str__(), "allocated_plant_count": 120},
            {"source_assignment_id": source_ids[tray_codes[1]], "destination_carrier_id": destination_carriers[2].id.__str__(), "allocated_plant_count": 80},
            {"source_assignment_id": source_ids[tray_codes[2]], "destination_carrier_id": destination_carriers[1].id.__str__(), "allocated_plant_count": 80},
            {"source_assignment_id": source_ids[tray_codes[2]], "destination_carrier_id": destination_carriers[2].id.__str__(), "allocated_plant_count": 120},
        ],
    }
    transplant_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch_id}/transplants", headers=headers, json=transplant_payload,
    )
    assert transplant_resp.status_code == 201, transplant_resp.text
    transplant_event = transplant_resp.json()
    assert len(transplant_event["source_lines"]) == 4
    assert len(transplant_event["destination_lines"]) == 3
    assert len(transplant_event["allocations"]) == 5
    assert transplant_event["total_source_available_before"] == 800
    assert transplant_event["total_destination_plant_count"] == 600
    assert transplant_event["total_discarded_plant_count"] == 200
    assert transplant_event["total_remainder_after"] == 0

    # Confirm no occupancy records were created or modified -- this is a
    # pure carrier-assignment transformation, not a location movement.
    occupancy_count_after = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    assert occupancy_count_after == occupancy_count_before

    # Confirm the full carrier-history endpoint shows all assignments (five
    # sowing-origin, four of them released, tray 5 still active, three
    # active transplant-origin) -- immutable history, not overwritten.
    all_assignments = client.get(f"/farms/{farm_id}/crop-batches/{batch_id}/carriers", headers=headers).json()
    assert len(all_assignments) == 8
    released_source_ids = {source_ids[c] for c in tray_codes[:4]}
    released = {a["id"]: a for a in all_assignments if a["released_effective_time"] is not None}
    assert set(released.keys()) == released_source_ids
    for a in released.values():
        assert a["released_by_transplant_event_id"] == transplant_event["id"]
    opened_by_transplant = [a for a in all_assignments if a["opening_transplant_event_id"] == transplant_event["id"]]
    assert len(opened_by_transplant) == 3
    assert all(a["released_effective_time"] is None for a in opened_by_transplant)

    # Confirm each destination carrier traces back to the batch.
    for c in destination_carriers[:3]:
        assignment = client.get(f"/farms/{farm_id}/carriers/{c.id}/batch-assignment", headers=headers).json()
        assert assignment["batch_id"] == batch_id
        assert assignment["opening_transplant_event_id"] == transplant_event["id"]

    transplanted_events = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.transplanted", AuditEvent.entity_id == transplant_event["id"]
        )
    ).scalar_one()
    assert transplanted_events == 1

    # Idempotent retry of the exact same command returns the original event.
    retry_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch_id}/transplants", headers=headers, json=transplant_payload,
    )
    assert retry_resp.status_code == 201
    assert retry_resp.json()["id"] == transplant_event["id"]
    transplants_after_retry = client.get(
        f"/farms/{farm_id}/crop-batches/{batch_id}/transplants", headers=headers
    ).json()
    assert len(transplants_after_retry) == 1
    assert db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.transplanted", AuditEvent.entity_id == transplant_event["id"]
        )
    ).scalar_one() == 1

    # Reject a reused command id carrying a materially different payload.
    tampered_payload = {**transplant_payload}
    tampered_payload["note"] = "different payload, same command id"
    reused_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch_id}/transplants", headers=headers, json=tampered_payload,
    )
    assert reused_resp.status_code == 409

    # Reject re-transplanting an already-released source assignment.
    extra_destination = client.post(
        f"/farms/{farm_id}/carriers", headers=headers,
        json={"carrier_type_code": "cultivation_plate", "code": "CP-TP-EXTRA"},
    ).json()
    reuse_source_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch_id}/transplants", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()),
            "effective_time": (s["entry_time"] + timedelta(hours=3)).isoformat(),
            "source_lines": [{"source_assignment_id": source_ids[tray_codes[0]]}],
            "destination_lines": [{"destination_carrier_id": extra_destination["id"], "assigned_plant_count": 200}],
            "allocations": [
                {
                    "source_assignment_id": source_ids[tray_codes[0]],
                    "destination_carrier_id": extra_destination["id"], "allocated_plant_count": 200,
                }
            ],
        },
    )
    assert reuse_source_resp.status_code == 409

    # Reject reassigning an already-assigned destination carrier. Tray 5's
    # assignment was never touched by the original transplant, so it is
    # still active and eligible -- isolating this rejection to the
    # destination-carrier collision alone.
    reassign_destination_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch_id}/transplants", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()),
            "effective_time": (s["entry_time"] + timedelta(hours=3)).isoformat(),
            "source_lines": [{"source_assignment_id": source_ids[tray_codes[4]]}],
            "destination_lines": [
                {"destination_carrier_id": destination_carriers[0].id.__str__(), "assigned_plant_count": 200}
            ],
            "allocations": [
                {
                    "source_assignment_id": source_ids[tray_codes[4]],
                    "destination_carrier_id": destination_carriers[0].id.__str__(), "allocated_plant_count": 200,
                }
            ],
        },
    )
    assert reassign_destination_resp.status_code == 409

    # Progress the batch to GROWING; retry the original transplant command
    # and confirm it still returns the original event unchanged.
    client.post(
        f"/farms/{farm_id}/crop-batches/{batch_id}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": str(s["transitions"]["t2"].id), "client_command_id": str(uuid.uuid4()),
            "effective_time": (s["entry_time"] + timedelta(hours=4)).isoformat(),
        },
    )
    final_current = client.get(f"/farms/{farm_id}/crop-batches/{batch_id}/current-stage", headers=headers).json()
    assert final_current["current_stage"]["code"] == "GROWING"
    final_retry_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch_id}/transplants", headers=headers, json=transplant_payload,
    )
    assert final_retry_resp.status_code == 201
    assert final_retry_resp.json()["id"] == transplant_event["id"]
    assert db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.transplanted", AuditEvent.entity_id == transplant_event["id"]
        )
    ).scalar_one() == 1

    # Reject cross-tenant access to the transplant event.
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
        f"/farms/{farm_id}/crop-batches/{batch_id}/transplants/{transplant_event['id']}", headers=headers_b
    )
    assert cross_tenant_resp.status_code == 404
