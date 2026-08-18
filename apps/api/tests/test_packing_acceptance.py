"""Core CMP-015 acceptance flow: harvest two produce lots -> pack a
selected weight from both into one finished-goods lot -> exact
reconciliation -> exact retry -> overconsumption rejected -> quality hold
blocks a genuinely new packing command but not an exact retry -> mixed
crop/variety rejected -> duplicate finished-goods-lot code rejected ->
cross-tenant access returns 404. All via the HTTP API."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.movement import Movement
from app.models.occupancy import Occupancy


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.mark.integration
def test_packing_acceptance_flow(client, active_context, db_session) -> None:
    _tenant, _user, headers = active_context
    suffix = uuid.uuid4().hex[:8].upper()

    farm = client.post(
        "/farms", headers=headers,
        json={"code": f"farm-{suffix}", "name": "Packing Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
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
    seed_tray_spec = client.post(
        "/carrier-specifications", headers=headers,
        json={
            "carrier_type_code": "seed_tray", "code": f"ST-SPEC-{suffix}", "name": "Test Seed Tray Specification",
            "length_mm": 300, "width_mm": 200, "height_mm": 50, "biological_position_count": 500,
        },
    ).json()
    carriers = [
        client.post(
            f"/farms/{farm_id}/carriers", headers=headers,
            json={"specification_id": seed_tray_spec["id"], "code": f"tray-{suffix}-{n}"},
        ).json()
        for n in range(3)
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

    transition_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={"configured_transition_id": advance["id"], "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso()},
    )
    assert transition_resp.status_code == 201

    # Two independent harvest events -> two independent produce lots, same crop/variety.
    harvest_a = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "produce_lot_code": f"hlot-a-{suffix}",
            "source_lines": [{"batch_carrier_assignment_id": assignment_ids[0], "harvested_weight_kg": "10.000", "whole_unit_count": 40}],
        },
    ).json()
    harvest_b = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "produce_lot_code": f"hlot-b-{suffix}",
            "source_lines": [{"batch_carrier_assignment_id": assignment_ids[1], "harvested_weight_kg": "5.000", "whole_unit_count": 20}],
        },
    ).json()
    lot_a_id, lot_b_id = harvest_a["produce_lot_id"], harvest_b["produce_lot_id"]

    balance_a = client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_a_id}/balance", headers=headers).json()
    balance_b = client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_b_id}/balance", headers=headers).json()
    assert balance_a["available_weight_kg"] == "10" and balance_a["available_whole_unit_count"] == 40
    assert balance_b["available_weight_kg"] == "5" and balance_b["available_whole_unit_count"] == 20

    occupancy_before = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    movement_before = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    assignment_before = db_session.execute(select(func.count()).select_from(BatchCarrierAssignment)).scalar_one()

    # 1-13. Pack a partial weight from both lots into one finished-goods lot.
    pack_command_id = str(uuid.uuid4())
    pack_payload = {
        "client_command_id": pack_command_id, "effective_time": _now_iso(),
        "finished_goods_lot_code": f"fg-{suffix}", "package_count": 12,
        "packed_output_weight_kg": "10.500", "process_loss_weight_kg": "0.300", "rejected_weight_kg": "0.200",
        "input_lines": [
            {"harvested_produce_lot_id": lot_a_id, "consumed_weight_kg": "8.000", "consumed_whole_unit_count": 32},
            {"harvested_produce_lot_id": lot_b_id, "consumed_weight_kg": "3.000", "consumed_whole_unit_count": 12},
        ],
    }
    pack_resp = client.post(f"/farms/{farm_id}/packing-events", headers=headers, json=pack_payload)
    assert pack_resp.status_code == 201, pack_resp.text
    event = pack_resp.json()
    assert event["total_input_weight_kg"] == "11"
    assert event["packed_output_weight_kg"] == "10.5"
    assert len(event["input_lines"]) == 2
    fg_lot_id = event["finished_goods_lot"]["id"]
    assert event["finished_goods_lot"]["package_count"] == 12

    # 8. Confirm one event, one output lot, two input lines, two ledger debits.
    fg_resp = client.get(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}", headers=headers)
    assert fg_resp.status_code == 200
    fg = fg_resp.json()
    assert fg["net_packed_weight_kg"] == "10.5"
    assert sorted(fg["source_produce_lot_ids"]) == sorted([lot_a_id, lot_b_id])

    ledger_a = client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_a_id}/ledger", headers=headers).json()
    ledger_b = client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_b_id}/ledger", headers=headers).json()
    assert len(ledger_a) == 2 and len(ledger_b) == 2
    debit_a = next(e for e in ledger_a if e["entry_kind"] == "packing_consumption")
    debit_b = next(e for e in ledger_b if e["entry_kind"] == "packing_consumption")
    assert debit_a["weight_delta_kg"] == "-8"
    assert debit_a["whole_unit_count_delta"] == -32
    assert debit_a["packing_event_id"] == event["id"]
    assert debit_a["harvest_event_id"] is None
    assert debit_b["weight_delta_kg"] == "-3"

    # 9. Source balances decrease exactly.
    balance_a_after = client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_a_id}/balance", headers=headers).json()
    balance_b_after = client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_b_id}/balance", headers=headers).json()
    assert balance_a_after["available_weight_kg"] == "2" and balance_a_after["available_whole_unit_count"] == 8
    assert balance_b_after["available_weight_kg"] == "2" and balance_b_after["available_whole_unit_count"] == 8
    assert balance_a_after["received_weight_kg"] == "10"

    # 12. Assignment/stage/occupancy/movement traceability unaffected.
    occupancy_after = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    movement_after = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    assignment_after = db_session.execute(select(func.count()).select_from(BatchCarrierAssignment)).scalar_one()
    assert occupancy_after == occupancy_before
    assert movement_after == movement_before
    assert assignment_after == assignment_before
    batch_after = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}", headers=headers).json()
    assert batch_after["state"] == "active"

    # 13. Exact retry -> no duplicates.
    retry_resp = client.post(f"/farms/{farm_id}/packing-events", headers=headers, json=pack_payload)
    assert retry_resp.status_code == 201
    assert retry_resp.json()["id"] == event["id"]
    assert len(client.get(f"/farms/{farm_id}/harvested-produce-lots/{lot_a_id}/ledger", headers=headers).json()) == 2

    # 14. Overconsumption rejected (lot A only has 2kg / 8 units left).
    over_resp = client.post(
        f"/farms/{farm_id}/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "finished_goods_lot_code": f"fg-over-{suffix}", "package_count": 1,
            "packed_output_weight_kg": "5.000", "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [
                {"harvested_produce_lot_id": lot_a_id, "consumed_weight_kg": "5.000", "consumed_whole_unit_count": 8},
            ],
        },
    )
    assert over_resp.status_code == 409

    # 15. Place a hold on batch -> blocks a genuinely new packing command.
    hold_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/quality-holds", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "reason_code": "contamination",
            "reason_text": "suspected contamination",
        },
    )
    assert hold_resp.status_code == 201

    held_resp = client.post(
        f"/farms/{farm_id}/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "finished_goods_lot_code": f"fg-held-{suffix}", "package_count": 1,
            "packed_output_weight_kg": "1.000", "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [
                {"harvested_produce_lot_id": lot_a_id, "consumed_weight_kg": "1.000", "consumed_whole_unit_count": 4},
            ],
        },
    )
    assert held_resp.status_code == 409

    # 16. Exact retry of the already-successful pack still returns after the hold.
    retry_after_hold = client.post(f"/farms/{farm_id}/packing-events", headers=headers, json=pack_payload)
    assert retry_after_hold.status_code == 201
    assert retry_after_hold.json()["id"] == event["id"]

    # Release the hold so the batch no longer blocks unrelated later steps.
    release_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/quality-holds/{hold_resp.json()['id']}/release",
        headers=headers,
        json={"client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "release_reason": "cleared"},
    )
    assert release_resp.status_code == 201

    # 17. Mixed crop/variety inputs rejected.
    other_variety = client.post(
        f"/crops/{crop['id']}/varieties", headers=headers, json={"code": f"var2-{suffix}", "name": "Other"}
    ).json()
    other_workflow = client.post(
        "/workflows", headers=headers,
        json={
            "crop_id": crop["id"], "variety_id": other_variety["id"], "production_system_id": production_system["id"],
            "code": f"wf2-{suffix}", "name": "Workflow 2",
        },
    ).json()
    other_version = client.post(f"/workflows/{other_workflow['id']}/versions", headers=headers).json()
    other_seeding = client.post(
        f"/workflows/{other_workflow['id']}/versions/{other_version['id']}/stages", headers=headers,
        json={
            "code": "SEEDING", "name": "Seeding", "display_order": 0, "stage_category": "seeding",
            "is_start": True, "is_terminal": False, "required_carrier_type_code": "seed_tray",
        },
    ).json()
    other_harvesting = client.post(
        f"/workflows/{other_workflow['id']}/versions/{other_version['id']}/stages", headers=headers,
        json={
            "code": "HARVESTING", "name": "Harvesting", "display_order": 1, "stage_category": "harvesting",
            "is_start": False, "is_terminal": False,
        },
    ).json()
    other_complete = client.post(
        f"/workflows/{other_workflow['id']}/versions/{other_version['id']}/stages", headers=headers,
        json={
            "code": "COMPLETE", "name": "Complete", "display_order": 2, "stage_category": "completed",
            "is_start": False, "is_terminal": True,
        },
    ).json()
    other_advance = client.post(
        f"/workflows/{other_workflow['id']}/versions/{other_version['id']}/transitions", headers=headers,
        json={"from_stage_id": other_seeding["id"], "to_stage_id": other_harvesting["id"], "code": "ADV-1", "name": "Advance"},
    ).json()
    client.post(
        f"/workflows/{other_workflow['id']}/versions/{other_version['id']}/transitions", headers=headers,
        json={"from_stage_id": other_harvesting["id"], "to_stage_id": other_complete["id"], "code": "ADV-2", "name": "Advance 2"},
    )
    assert client.post(f"/workflows/{other_workflow['id']}/versions/{other_version['id']}/publish", headers=headers).status_code == 200
    other_batch = client.post(
        f"/farms/{farm_id}/crop-batches", headers=headers,
        json={
            "code": f"BATCH2-{suffix}", "workflow_id": other_workflow["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    ).json()
    other_seed_lot = client.post(
        f"/farms/{farm_id}/seed-lots", headers=headers,
        json={"crop_id": crop["id"], "variety_id": other_variety["id"], "code": f"olot-{suffix}"},
    ).json()
    other_carrier = client.post(
        f"/farms/{farm_id}/carriers", headers=headers, json={"specification_id": seed_tray_spec["id"], "code": f"otray-{suffix}"},
    ).json()
    client.post(
        f"/farms/{farm_id}/crop-batches/{other_batch['id']}/sowings", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "lines": [{"carrier_id": other_carrier["id"], "seed_lot_id": other_seed_lot["id"], "sown_site_count": 50, "seed_count": 50}],
        },
    )
    other_assignments = client.get(f"/farms/{farm_id}/crop-batches/{other_batch['id']}/carriers", headers=headers).json()
    other_assignment_id = other_assignments[0]["id"]
    client.post(
        f"/farms/{farm_id}/crop-batches/{other_batch['id']}/stage-transitions", headers=headers,
        json={"configured_transition_id": other_advance["id"], "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso()},
    )
    other_harvest = client.post(
        f"/farms/{farm_id}/crop-batches/{other_batch['id']}/harvests", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "produce_lot_code": f"olotharvest-{suffix}",
            "source_lines": [{"batch_carrier_assignment_id": other_assignment_id, "harvested_weight_kg": "2.000"}],
        },
    ).json()
    mixed_resp = client.post(
        f"/farms/{farm_id}/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "finished_goods_lot_code": f"fg-mixed-{suffix}", "package_count": 1,
            "packed_output_weight_kg": "2.500", "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [
                {"harvested_produce_lot_id": lot_b_id, "consumed_weight_kg": "0.500", "consumed_whole_unit_count": None},
                {"harvested_produce_lot_id": other_harvest["produce_lot_id"], "consumed_weight_kg": "2.000", "consumed_whole_unit_count": None},
            ],
        },
    )
    assert mixed_resp.status_code == 422

    # 18. Duplicate finished-goods-lot code rejected.
    dup_resp = client.post(
        f"/farms/{farm_id}/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "finished_goods_lot_code": f"fg-{suffix}", "package_count": 1,
            "packed_output_weight_kg": "1.000", "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [
                {"harvested_produce_lot_id": lot_b_id, "consumed_weight_kg": "1.000", "consumed_whole_unit_count": 4},
            ],
        },
    )
    assert dup_resp.status_code == 409

    # 19. Cross-tenant access returns 404.
    from app.services import membership_service, tenant_service, user_service

    tenant_b = tenant_service.create_tenant(db_session, code=f"pack-tenant-b-{suffix}", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=f"pack-b-{suffix}", email=f"packb-{suffix}@example.com",
        display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    assert client.get(f"/farms/{farm_id}/packing-events/{event['id']}", headers=headers_b).status_code == 404
    assert client.get(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}", headers=headers_b).status_code == 404

    # No mutation routes exist beyond POST for creation.
    assert client.put(f"/farms/{farm_id}/packing-events/{event['id']}", headers=headers, json={}).status_code == 405
    assert client.delete(f"/farms/{farm_id}/packing-events/{event['id']}", headers=headers).status_code == 405
    assert client.patch(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}", headers=headers, json={}).status_code == 405
