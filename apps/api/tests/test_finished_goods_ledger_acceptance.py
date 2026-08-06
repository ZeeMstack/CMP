"""Core CMP-016 acceptance flow: pack -> deterministic opening receipt ->
ledger/balance GET -> exact retry -> cross-tenant rejection -> no ledger
mutation routes exist. All via the HTTP API, mirroring
test_produce_lot_ledger_acceptance.py's own CMP-014 pattern one level up
the chain."""
import uuid
from datetime import datetime, timezone

import pytest


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.mark.integration
def test_finished_goods_ledger_acceptance_flow(client, active_context, db_session) -> None:
    _tenant, _user, headers = active_context
    suffix = uuid.uuid4().hex[:8].upper()

    farm = client.post(
        "/farms", headers=headers,
        json={"code": f"farm-{suffix}", "name": "FG Ledger Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
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
        json={
            "code": "HARVESTING", "name": "Harvesting", "display_order": 1, "stage_category": "harvesting",
            "is_start": False, "is_terminal": False,
        },
    ).json()
    complete = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={
            "code": "COMPLETE", "name": "Complete", "display_order": 2, "stage_category": "completed",
            "is_start": False, "is_terminal": True,
        },
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
        json={
            "code": f"BATCH-{suffix}", "workflow_id": workflow["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    ).json()
    seed_lot = client.post(
        f"/farms/{farm_id}/seed-lots", headers=headers,
        json={"crop_id": crop["id"], "variety_id": variety["id"], "code": f"lot-{suffix}"},
    ).json()
    carrier = client.post(
        f"/farms/{farm_id}/carriers", headers=headers, json={"carrier_type_code": "seed_tray", "code": f"tray-{suffix}"},
    ).json()
    sow_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/sowings", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "lines": [{"carrier_id": carrier["id"], "seed_lot_id": seed_lot["id"], "sown_site_count": 100, "seed_count": 100}],
        },
    )
    assert sow_resp.status_code == 201
    assignments = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/carriers", headers=headers).json()
    assignment_id = assignments[0]["id"]

    transition_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={"configured_transition_id": advance["id"], "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso()},
    )
    assert transition_resp.status_code == 201

    harvest_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "produce_lot_code": f"hlot-{suffix}",
            "source_lines": [{"batch_carrier_assignment_id": assignment_id, "harvested_weight_kg": "10.000"}],
        },
    )
    assert harvest_resp.status_code == 201
    lot_id = harvest_resp.json()["produce_lot_id"]

    # 1. Pack -> deterministic finished-goods opening receipt.
    pack_command_id = str(uuid.uuid4())
    pack_payload = {
        "client_command_id": pack_command_id, "effective_time": _now_iso(),
        "finished_goods_lot_code": f"fg-{suffix}", "package_count": 7,
        "packed_output_weight_kg": "6.000", "process_loss_weight_kg": "0", "rejected_weight_kg": "4.000",
        "input_lines": [{"harvested_produce_lot_id": lot_id, "consumed_weight_kg": "10.000", "consumed_whole_unit_count": None}],
    }
    pack_resp = client.post(f"/farms/{farm_id}/packing-events", headers=headers, json=pack_payload)
    assert pack_resp.status_code == 201, pack_resp.text
    event = pack_resp.json()
    fg_lot_id = event["finished_goods_lot"]["id"]

    # 2. Ledger GET: exactly one packing_receipt entry, fields match the lot/event.
    ledger_resp = client.get(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/ledger", headers=headers)
    assert ledger_resp.status_code == 200
    ledger = ledger_resp.json()
    assert len(ledger) == 1
    entry = ledger[0]
    assert entry["id"] == fg_lot_id
    assert entry["entry_kind"] == "packing_receipt"
    assert entry["finished_goods_lot_id"] == fg_lot_id
    assert entry["packing_event_id"] == event["id"]
    assert entry["weight_delta_kg"] == "6"
    assert entry["package_count_delta"] == 7
    assert entry["note"] is None

    # 3. Balance GET: received == available (only a receipt exists so far).
    balance_resp = client.get(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/balance", headers=headers)
    assert balance_resp.status_code == 200
    balance = balance_resp.json()
    assert balance["finished_goods_lot_id"] == fg_lot_id
    assert balance["received_weight_kg"] == balance["available_weight_kg"] == "6"
    assert balance["received_package_count"] == balance["available_package_count"] == 7
    assert balance["entry_count"] == 1

    # 4. Exact retry: no duplicate receipt.
    retry_resp = client.post(f"/farms/{farm_id}/packing-events", headers=headers, json=pack_payload)
    assert retry_resp.status_code == 201
    assert retry_resp.json()["id"] == event["id"]
    ledger_after_retry = client.get(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/ledger", headers=headers).json()
    assert len(ledger_after_retry) == 1

    # 5. No ledger mutation routes exist (only GET is registered).
    assert client.post(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/ledger", headers=headers, json={}).status_code == 405
    assert client.put(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/ledger", headers=headers, json={}).status_code == 405
    assert client.patch(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/ledger", headers=headers, json={}).status_code == 405
    assert client.delete(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/ledger", headers=headers).status_code == 405
    assert client.post(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/balance", headers=headers, json={}).status_code == 405

    # 6. Cross-tenant access returns 404.
    from app.services import membership_service, tenant_service, user_service

    tenant_b = tenant_service.create_tenant(db_session, code=f"fgledger-tenant-b-{suffix}", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=f"fgledger-b-{suffix}", email=f"fgledgerb-{suffix}@example.com",
        display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    assert client.get(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/ledger", headers=headers_b).status_code == 404
    assert client.get(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/balance", headers=headers_b).status_code == 404
