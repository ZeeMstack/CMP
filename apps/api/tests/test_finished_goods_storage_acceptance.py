"""Core CMP-018 acceptance flow: harvest -> pack -> place into a cold-store
position -> transfer between positions -> release -> a dispatch that
exceeds unplaced quantity is rejected -> release then dispatch succeeds ->
placement/movement-history/location-inventory GETs reflect reality ->
exact replay -> non-storage location rejected -> cross-tenant access
returns 404 -> no mutation route beyond movement POST. All via the HTTP
API."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_finished_goods_lot(client, headers, farm_id, suffix, *, package_count=10, packed_weight="10.000"):
    """Farm -> crop/variety/production-system/workflow (2 stages) -> batch
    -> seed lot/carrier -> sow -> stage transition -> harvest -> pack.
    Returns finished_goods_lot_id."""
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
    carrier = client.post(
        f"/farms/{farm_id}/carriers", headers=headers, json={"specification_id": seed_tray_spec["id"], "code": f"tray-{suffix}"},
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

    harvest_count = package_count * 4
    harvest = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "produce_lot_code": f"hlot-{suffix}",
            "source_lines": [{"batch_carrier_assignment_id": assignment_id, "harvested_weight_kg": packed_weight, "whole_unit_count": harvest_count}],
        },
    ).json()
    lot_id = harvest["produce_lot_id"]

    # POSTHARVEST-OPS-001E: Packing no longer accepts a HarvestedProduceLot
    # directly -- grade the lot's full weight into one GradedProduceLot and
    # activate a PackSpecificationVersion before packing.
    packing_hall = client.post(
        f"/farms/{farm_id}/locations", headers=headers,
        json={"location_type_code": "packing_hall", "code": f"pack-hall-{suffix}", "name": "Processing Hall"},
    ).json()
    grade_def = client.post(
        "/grade-definitions", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "code": f"grade-{suffix}", "name": "Standard",
            "crop_id": crop["id"], "variety_id": None,
        },
    ).json()
    grade_version = client.post(
        f"/grade-definitions/{grade_def['id']}/versions", headers=headers,
        json={"client_command_id": str(uuid.uuid4())},
    ).json()
    assert client.post(
        f"/grade-definitions/{grade_def['id']}/versions/{grade_version['id']}/activate", headers=headers,
        json={"client_command_id": str(uuid.uuid4()), "effective_time": _now_iso()},
    ).status_code == 200
    packaging_unit = client.post(
        "/packaging-units", headers=headers,
        json={"client_command_id": str(uuid.uuid4()), "code": f"unit-{suffix}", "name": "Carton"},
    ).json()
    pack_spec = client.post(
        "/pack-specifications", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "code": f"spec-{suffix}", "name": "Standard Pack",
            "crop_id": crop["id"], "variety_id": None,
        },
    ).json()
    pack_spec_version = client.post(
        f"/pack-specifications/{pack_spec['id']}/versions", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "grade_definition_version_id": None,
            "packaging_unit_id": packaging_unit["id"], "nominal_net_weight_kg": "1.000", "whole_units_per_pack": None,
        },
    ).json()
    assert client.post(
        f"/pack-specifications/{pack_spec['id']}/versions/{pack_spec_version['id']}/activate", headers=headers,
        json={"client_command_id": str(uuid.uuid4()), "effective_time": _now_iso()},
    ).status_code == 200

    grading_resp = client.post(
        f"/farms/{farm_id}/grading-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "source_harvested_produce_lot_id": lot_id,
            "processing_hall_location_id": packing_hall["id"], "effective_time": _now_iso(), "note": None,
            "input_presented_weight_kg": packed_weight, "input_presented_whole_unit_count": harvest_count,
            "rejected_weight_kg": "0", "rejected_whole_unit_count": 0,
            "loss_weight_kg": "0", "loss_whole_unit_count": 0,
            "sample_weight_kg": "0", "sample_whole_unit_count": 0,
            "remainder_weight_kg": "0", "remainder_whole_unit_count": 0,
            "outputs": [
                {
                    "grade_definition_version_id": grade_version["id"], "code": f"GPL-{suffix}",
                    "output_weight_kg": packed_weight, "output_whole_unit_count": harvest_count,
                }
            ],
        },
    )
    assert grading_resp.status_code == 201, grading_resp.text
    gpl_id = grading_resp.json()["outputs"][0]["id"]

    pack_resp = client.post(
        f"/farms/{farm_id}/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "pack_specification_version_id": pack_spec_version["id"],
            "finished_goods_lot_code": f"fg-{suffix}", "package_count": package_count,
            "packed_output_weight_kg": packed_weight, "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [
                {"graded_produce_lot_id": gpl_id, "consumed_weight_kg": packed_weight, "consumed_whole_unit_count": harvest_count},
            ],
        },
    )
    assert pack_resp.status_code == 201, pack_resp.text
    return pack_resp.json()["finished_goods_lot"]["id"]


def _create_cold_store_position(client, headers, farm_id, suffix, *, code_suffix=""):
    cold_store = client.post(
        f"/farms/{farm_id}/locations", headers=headers,
        json={"location_type_code": "cold_store", "code": f"CS-{suffix}{code_suffix}", "name": "Cold Store"},
    ).json()
    position = client.post(
        f"/farms/{farm_id}/locations", headers=headers,
        json={
            "location_type_code": "cold_store_position", "code": f"POS-{suffix}{code_suffix}", "name": "Position",
            "parent_location_id": cold_store["id"],
        },
    ).json()
    return position["id"]


@pytest.mark.integration
def test_storage_acceptance_flow(client, active_context, db_session) -> None:
    _tenant, _user, headers = active_context
    suffix = uuid.uuid4().hex[:8].upper()

    farm = client.post(
        "/farms", headers=headers,
        json={"code": f"farm-{suffix}", "name": "Storage Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    ).json()
    farm_id = farm["id"]

    fg_lot_id = _build_finished_goods_lot(client, headers, farm_id, suffix, package_count=10, packed_weight="10.000")
    pos_a = _create_cold_store_position(client, headers, farm_id, suffix, code_suffix="-A")
    pos_b = _create_cold_store_position(client, headers, farm_id, suffix, code_suffix="-B")

    audit_before = db_session.execute(select(func.count()).select_from(AuditEvent)).scalar_one()

    place_payload = {
        "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "finished_goods_lot_id": fg_lot_id,
        "movement_kind": "place", "destination_location_id": pos_a, "moved_weight_kg": "6.000",
        "moved_package_count": 6, "note": None,
    }
    place_resp = client.post(f"/farms/{farm_id}/finished-goods-storage-movements", headers=headers, json=place_payload)
    assert place_resp.status_code == 201, place_resp.text
    place_event = place_resp.json()
    assert place_event["moved_weight_kg"] == "6"

    audit_after_place = db_session.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
    assert audit_after_place == audit_before + 1

    # Exact replay creates nothing new.
    replay_resp = client.post(f"/farms/{farm_id}/finished-goods-storage-movements", headers=headers, json=place_payload)
    assert replay_resp.status_code == 201
    assert replay_resp.json()["id"] == place_event["id"]
    audit_after_replay = db_session.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
    assert audit_after_replay == audit_after_place

    # Transfer 2kg from A to B.
    transfer_resp = client.post(
        f"/farms/{farm_id}/finished-goods-storage-movements", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "finished_goods_lot_id": fg_lot_id,
            "movement_kind": "transfer", "source_location_id": pos_a, "destination_location_id": pos_b,
            "moved_weight_kg": "2.000", "moved_package_count": 2, "note": None,
        },
    )
    assert transfer_resp.status_code == 201, transfer_resp.text

    placement = client.get(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/placements", headers=headers).json()
    assert placement["available_weight_kg"] == "10"
    assert placement["total_placed_weight_kg"] == "6"
    assert placement["unplaced_weight_kg"] == "4"
    balances = {loc["location_id"]: loc for loc in placement["locations"]}
    assert balances[pos_a]["weight_kg"] == "4"
    assert balances[pos_b]["weight_kg"] == "2"

    history = client.get(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/storage-movements", headers=headers).json()
    assert len(history) == 2

    inventory_a = client.get(f"/farms/{farm_id}/locations/{pos_a}/finished-goods-inventory", headers=headers).json()
    assert len(inventory_a["lots"]) == 1
    assert inventory_a["lots"][0]["weight_kg"] == "4"

    # Dispatch beyond unplaced (4kg unplaced) must be rejected.
    over_dispatch = client.post(
        f"/farms/{farm_id}/dispatches", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "code": f"disp-over-{suffix}",
            "external_reference": None, "note": None,
            "lines": [{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": "5.000", "dispatched_package_count": 5}],
        },
    )
    assert over_dispatch.status_code == 409

    # Release 2kg from B, then dispatch exactly 5kg (now 6kg unplaced) succeeds.
    release_resp = client.post(
        f"/farms/{farm_id}/finished-goods-storage-movements", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "finished_goods_lot_id": fg_lot_id,
            "movement_kind": "release", "source_location_id": pos_b, "moved_weight_kg": "2.000",
            "moved_package_count": 2, "note": None,
        },
    )
    assert release_resp.status_code == 201, release_resp.text

    dispatch_resp = client.post(
        f"/farms/{farm_id}/dispatches", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "code": f"disp-{suffix}",
            "external_reference": None, "note": None,
            "lines": [{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": "5.000", "dispatched_package_count": 5}],
        },
    )
    assert dispatch_resp.status_code == 201, dispatch_resp.text

    # Placing into a non-storage-eligible location (a greenhouse) is rejected.
    greenhouse = client.post(
        f"/farms/{farm_id}/locations", headers=headers,
        json={
            "location_type_code": "greenhouse", "code": f"GH-{suffix}", "name": "Greenhouse",
            "greenhouse_classification": "leafy_greens",
        },
    ).json()
    bad_place = client.post(
        f"/farms/{farm_id}/finished-goods-storage-movements", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "finished_goods_lot_id": fg_lot_id,
            "movement_kind": "place", "destination_location_id": greenhouse["id"], "moved_weight_kg": "1.000",
            "moved_package_count": 1, "note": None,
        },
    )
    assert bad_place.status_code == 422

    # A nonexistent location id is a genuine 404, not a 422.
    bad_place_missing = client.post(
        f"/farms/{farm_id}/finished-goods-storage-movements", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "finished_goods_lot_id": fg_lot_id,
            "movement_kind": "place", "destination_location_id": str(uuid.uuid4()), "moved_weight_kg": "1.000",
            "moved_package_count": 1, "note": None,
        },
    )
    assert bad_place_missing.status_code == 404

    # Cross-tenant access returns 404.
    from app.services import membership_service, tenant_service, user_service

    tenant_b = tenant_service.create_tenant(db_session, code=f"storage-tenant-b-{suffix}", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=f"storage-b-{suffix}", email=f"storageb-{suffix}@example.com",
        display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    assert client.get(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/placements", headers=headers_b).status_code == 404

    # No mutation routes exist beyond POST for creation -- there is no
    # per-movement detail route at all, so PUT/DELETE against the
    # collection path itself (the only path that exists) must be 405.
    assert client.put(f"/farms/{farm_id}/finished-goods-storage-movements", headers=headers, json={}).status_code == 405
    assert client.delete(f"/farms/{farm_id}/finished-goods-storage-movements", headers=headers).status_code == 405
