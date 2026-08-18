"""Core CMP-014 acceptance flow: harvest -> deterministic opening receipt ->
ledger/balance GET -> second harvest -> exact retry -> cross-tenant
rejection -> no ledger mutation routes exist. All via the HTTP API."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models.movement import Movement
from app.models.occupancy import Occupancy


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.mark.integration
def test_produce_lot_ledger_acceptance_flow(client, active_context, db_session) -> None:
    _tenant, _user, headers = active_context
    suffix = uuid.uuid4().hex[:8].upper()

    farm = client.post(
        "/farms", headers=headers,
        json={"code": f"farm-{suffix}", "name": "Ledger Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    ).json()
    farm_id = farm["id"]

    crop = client.post(
        "/crops", headers=headers,
        json={"code": f"crop-{suffix}", "common_name": "Iceberg", "crop_category": "leafy_green"},
    ).json()
    variety = client.post(
        f"/crops/{crop['id']}/varieties", headers=headers, json={"code": f"var-{suffix}", "name": "Mamutik"}
    ).json()
    production_system = client.post(
        "/production-systems", headers=headers, json={"code": f"ps-{suffix}", "name": "Nursery Tray"}
    ).json()
    workflow = client.post(
        "/workflows", headers=headers,
        json={
            "crop_id": crop["id"], "variety_id": variety["id"], "production_system_id": production_system["id"],
            "code": f"wf-{suffix}", "name": "Workflow",
        },
    ).json()
    version = client.post(f"/workflows/{workflow['id']}/versions", headers=headers).json()
    seeding = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={
            "code": "SEEDING", "name": "Seeding", "display_order": 0, "stage_category": "seeding",
            "is_start": True, "is_terminal": False, "required_carrier_type_code": "seed_tray",
        },
    ).json()
    harvesting = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={"code": "HARVESTING", "name": "Harvesting", "display_order": 1, "stage_category": "harvesting", "is_start": False, "is_terminal": False},
    ).json()
    complete = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={"code": "COMPLETE", "name": "Complete", "display_order": 2, "stage_category": "completed", "is_start": False, "is_terminal": True},
    ).json()
    advance = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
        json={"from_stage_id": seeding["id"], "to_stage_id": harvesting["id"], "code": "ADV-1", "name": "Advance 1"},
    ).json()
    client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
        json={"from_stage_id": harvesting["id"], "to_stage_id": complete["id"], "code": "ADV-2", "name": "Advance 2"},
    )
    assert client.post(f"/workflows/{workflow['id']}/versions/{version['id']}/publish", headers=headers).status_code == 200

    batch = client.post(
        f"/farms/{farm_id}/crop-batches", headers=headers,
        json={"code": f"BATCH-{suffix}", "workflow_id": workflow["id"], "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso()},
    ).json()
    seed_lot = client.post(
        f"/farms/{farm_id}/seed-lots", headers=headers,
        json={"crop_id": crop["id"], "variety_id": variety["id"], "code": f"lot-{suffix}"},
    ).json()
    seed_tray_spec = client.post(
        "/carrier-specifications", headers=headers,
        json={
            "carrier_type_code": "seed_tray", "code": f"ST-SPEC-{suffix}", "name": "Test Seed Tray Specification",
            "length_mm": 300, "width_mm": 200, "height_mm": 50, "biological_position_count": 500,
        },
    ).json()
    carriers = [
        client.post(f"/farms/{farm_id}/carriers", headers=headers, json={"specification_id": seed_tray_spec["id"], "code": f"tray-{suffix}-{n}"}).json()
        for n in range(2)
    ]
    sow_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/sowings", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "lines": [
                {"carrier_id": c["id"], "seed_lot_id": seed_lot["id"], "sown_site_count": 100, "seed_count": 100}
                for c in carriers
            ],
        },
    )
    assert sow_resp.status_code == 201
    assignments = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/carriers", headers=headers).json()
    assignment_by_carrier_id = {a["carrier"]["id"]: a["id"] for a in assignments}
    assignment_ids = [assignment_by_carrier_id[c["id"]] for c in carriers]

    occupancy_before = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    movement_before = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()

    transition_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={"configured_transition_id": advance["id"], "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso()},
    )
    assert transition_resp.status_code == 201

    # 1. Harvest -> deterministic opening receipt.
    harvest_command_id = str(uuid.uuid4())
    harvest_payload = {
        "client_command_id": harvest_command_id, "effective_time": _now_iso(),
        "produce_lot_code": f"hlot-{suffix}",
        "source_lines": [{"batch_carrier_assignment_id": assignment_ids[0], "harvested_weight_kg": "12.500", "whole_unit_count": 40}],
    }
    harvest_resp = client.post(f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers, json=harvest_payload)
    assert harvest_resp.status_code == 201
    event = harvest_resp.json()
    lot_id = event["produce_lot_id"]

    # 2. Ledger GET: exactly one harvest_receipt entry, fields match the event/lot.
    ledger_resp = client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_id}/ledger", headers=headers)
    assert ledger_resp.status_code == 200
    ledger = ledger_resp.json()
    assert len(ledger) == 1
    entry = ledger[0]
    assert entry["id"] == lot_id
    assert entry["entry_kind"] == "harvest_receipt"
    assert entry["produce_lot_id"] == lot_id
    assert entry["harvest_event_id"] == event["id"]
    assert entry["weight_delta_kg"] == "12.5"
    assert entry["whole_unit_count_delta"] == 40
    assert entry["note"] is None

    # 3. Balance GET: received == available (only a receipt exists so far).
    balance_resp = client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_id}/balance", headers=headers)
    assert balance_resp.status_code == 200
    balance = balance_resp.json()
    assert balance["produce_lot_id"] == lot_id
    assert balance["received_weight_kg"] == balance["available_weight_kg"] == "12.5"
    assert balance["received_whole_unit_count"] == balance["available_whole_unit_count"] == 40
    assert balance["entry_count"] == 1

    # 4. Occupancy/movement/batch/stage/assignment state unaffected.
    occupancy_after = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    movement_after = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    assert occupancy_after == occupancy_before
    assert movement_after == movement_before
    batch_after = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}", headers=headers).json()
    assert batch_after["state"] == "active"
    assert batch_after["current_stage"]["code"] == "HARVESTING"
    assignments_after = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/carriers", headers=headers).json()
    for a in assignments_after:
        assert a["released_effective_time"] is None

    # 5. Exact retry: no duplicate receipt/ledger entry.
    retry_resp = client.post(f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers, json=harvest_payload)
    assert retry_resp.status_code == 201
    assert retry_resp.json()["id"] == event["id"]
    ledger_after_retry = client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_id}/ledger", headers=headers).json()
    assert len(ledger_after_retry) == 1

    # 6. Second harvest of the other assignment -> a second, independent lot/receipt.
    second_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "produce_lot_code": f"hlot2-{suffix}",
            "source_lines": [{"batch_carrier_assignment_id": assignment_ids[1], "harvested_weight_kg": "3.000"}],
        },
    )
    assert second_resp.status_code == 201
    second_lot_id = second_resp.json()["produce_lot_id"]
    assert second_lot_id != lot_id
    second_ledger = client.get(f"/farms/{farm_id}/harvested-produce-lots/{second_lot_id}/ledger", headers=headers).json()
    assert len(second_ledger) == 1
    assert second_ledger[0]["whole_unit_count_delta"] is None
    # The first lot's own ledger remains exactly as it was.
    assert len(client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_id}/ledger", headers=headers).json()) == 1

    # 7. No ledger mutation routes exist (only GET is registered).
    assert client.post(f"/farms/{farm_id}/harvested-produce-lots/{lot_id}/ledger", headers=headers, json={}).status_code == 405
    assert client.put(f"/farms/{farm_id}/harvested-produce-lots/{lot_id}/ledger", headers=headers, json={}).status_code == 405
    assert client.patch(f"/farms/{farm_id}/harvested-produce-lots/{lot_id}/ledger", headers=headers, json={}).status_code == 405
    assert client.delete(f"/farms/{farm_id}/harvested-produce-lots/{lot_id}/ledger", headers=headers).status_code == 405
    assert client.post(f"/farms/{farm_id}/harvested-produce-lots/{lot_id}/balance", headers=headers, json={}).status_code == 405

    # 8. Cross-tenant access returns 404.
    from app.services import membership_service, tenant_service, user_service

    tenant_b = tenant_service.create_tenant(db_session, code=f"ledger-tenant-b-{suffix}", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=f"ledger-b-{suffix}", email=f"ledgerb-{suffix}@example.com",
        display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    assert client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_id}/ledger", headers=headers_b).status_code == 404
    assert client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_id}/balance", headers=headers_b).status_code == 404
