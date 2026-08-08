"""Core CMP-017 acceptance flow: harvest -> pack -> dispatch a partial
weight/count -> list/detail GETs reflect the dispatch -> the finished-
goods ledger and balance reflect the issue -> exact retry returns the
same event with no new rows -> overdraw rejected -> quality hold blocks a
genuinely new dispatch but not an exact retry -> duplicate dispatch code
rejected -> cross-tenant access returns 404 -> exactly 3 dispatch routes
exist and no mutation route does -> exactly one audit event per dispatch
command. All via the HTTP API."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_finished_goods_lot(client, headers, farm_id, suffix, *, package_count=10, packed_weight="8.000"):
    """Farm -> crop/variety/production-system/workflow (2 stages) -> batch
    -> seed lot/carrier -> sow -> stage transition -> harvest -> pack.
    Returns (finished_goods_lot_id, batch_id)."""
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

    harvest_count = package_count * 4
    harvest = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "produce_lot_code": f"hlot-{suffix}",
            "source_lines": [{"batch_carrier_assignment_id": assignment_id, "harvested_weight_kg": packed_weight, "whole_unit_count": harvest_count}],
        },
    ).json()
    lot_id = harvest["produce_lot_id"]

    pack_resp = client.post(
        f"/farms/{farm_id}/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "finished_goods_lot_code": f"fg-{suffix}", "package_count": package_count,
            "packed_output_weight_kg": packed_weight, "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [
                {"harvested_produce_lot_id": lot_id, "consumed_weight_kg": packed_weight, "consumed_whole_unit_count": harvest_count},
            ],
        },
    )
    assert pack_resp.status_code == 201, pack_resp.text
    fg_lot_id = pack_resp.json()["finished_goods_lot"]["id"]
    return fg_lot_id, batch["id"]


@pytest.mark.integration
def test_dispatch_acceptance_flow(client, active_context, db_session) -> None:
    _tenant, _user, headers = active_context
    suffix = uuid.uuid4().hex[:8].upper()

    farm = client.post(
        "/farms", headers=headers,
        json={"code": f"farm-{suffix}", "name": "Dispatch Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    ).json()
    farm_id = farm["id"]

    fg_lot_id, batch_id = _build_finished_goods_lot(client, headers, farm_id, suffix, package_count=10, packed_weight="8.000")

    audit_before = db_session.execute(select(func.count()).select_from(AuditEvent)).scalar_one()

    # Dispatch a partial weight/count.
    dispatch_command_id = str(uuid.uuid4())
    dispatch_payload = {
        "client_command_id": dispatch_command_id, "effective_time": _now_iso(), "code": f"disp-{suffix}",
        "external_reference": "PO-123", "note": None,
        "lines": [{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": "3.000", "dispatched_package_count": 4}],
    }
    dispatch_resp = client.post(f"/farms/{farm_id}/dispatches", headers=headers, json=dispatch_payload)
    assert dispatch_resp.status_code == 201, dispatch_resp.text
    event = dispatch_resp.json()
    assert event["total_dispatched_weight_kg"] == "3"
    assert event["total_dispatched_package_count"] == 4
    assert len(event["lines"]) == 1
    assert event["lines"][0]["finished_goods_lot_id"] == fg_lot_id
    assert event["external_reference"] == "PO-123"

    # Exactly one audit event for the dispatch command.
    audit_after = db_session.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
    assert audit_after == audit_before + 1

    # Detail GET reflects the event.
    detail_resp = client.get(f"/farms/{farm_id}/dispatches/{event['id']}", headers=headers)
    assert detail_resp.status_code == 200
    assert detail_resp.json()["id"] == event["id"]

    # List GET includes the event.
    list_resp = client.get(f"/farms/{farm_id}/dispatches", headers=headers)
    assert list_resp.status_code == 200
    assert any(e["id"] == event["id"] for e in list_resp.json())

    # Ledger shows the dispatch_issue entry; balance reflects it.
    ledger = client.get(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/ledger", headers=headers).json()
    issue = next(e for e in ledger if e["entry_kind"] == "dispatch_issue")
    assert issue["weight_delta_kg"] == "-3"
    assert issue["package_count_delta"] == -4
    assert issue["dispatch_line_id"] == event["lines"][0]["id"]

    balance = client.get(f"/farms/{farm_id}/finished-goods-lots/{fg_lot_id}/balance", headers=headers).json()
    assert balance["available_weight_kg"] == "5"
    assert balance["available_package_count"] == 6

    # Exact retry returns the same event, creates nothing new.
    retry_resp = client.post(f"/farms/{farm_id}/dispatches", headers=headers, json=dispatch_payload)
    assert retry_resp.status_code == 201
    assert retry_resp.json()["id"] == event["id"]
    audit_after_retry = db_session.execute(select(func.count()).select_from(AuditEvent)).scalar_one()
    assert audit_after_retry == audit_after

    # Overdraw rejected (lot only has 5kg / 6 packages left).
    over_resp = client.post(
        f"/farms/{farm_id}/dispatches", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "code": f"disp-over-{suffix}",
            "external_reference": None, "note": None,
            "lines": [{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": "99.000", "dispatched_package_count": 1}],
        },
    )
    assert over_resp.status_code == 409

    # Quality hold on the source batch blocks a genuinely new dispatch.
    hold_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch_id}/quality-holds", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "reason_code": "contamination",
            "reason_text": "suspected contamination",
        },
    )
    assert hold_resp.status_code == 201

    held_resp = client.post(
        f"/farms/{farm_id}/dispatches", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "code": f"disp-held-{suffix}",
            "external_reference": None, "note": None,
            "lines": [{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": "1.000", "dispatched_package_count": 1}],
        },
    )
    assert held_resp.status_code == 409

    # Exact retry of the already-successful dispatch still returns after the hold.
    retry_after_hold = client.post(f"/farms/{farm_id}/dispatches", headers=headers, json=dispatch_payload)
    assert retry_after_hold.status_code == 201
    assert retry_after_hold.json()["id"] == event["id"]

    release_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch_id}/quality-holds/{hold_resp.json()['id']}/release",
        headers=headers,
        json={"client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "release_reason": "cleared"},
    )
    assert release_resp.status_code == 201

    # Duplicate dispatch code (same farm) rejected.
    dup_resp = client.post(
        f"/farms/{farm_id}/dispatches", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "code": f"disp-{suffix}",
            "external_reference": None, "note": None,
            "lines": [{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": "1.000", "dispatched_package_count": 1}],
        },
    )
    assert dup_resp.status_code == 409

    # Cross-tenant access returns 404.
    from app.services import membership_service, tenant_service, user_service

    tenant_b = tenant_service.create_tenant(db_session, code=f"disp-tenant-b-{suffix}", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=f"disp-b-{suffix}", email=f"dispb-{suffix}@example.com",
        display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    assert client.get(f"/farms/{farm_id}/dispatches/{event['id']}", headers=headers_b).status_code == 404

    # No mutation routes exist beyond POST for creation.
    assert client.put(f"/farms/{farm_id}/dispatches/{event['id']}", headers=headers, json={}).status_code == 405
    assert client.delete(f"/farms/{farm_id}/dispatches/{event['id']}", headers=headers).status_code == 405
    assert client.patch(f"/farms/{farm_id}/dispatches/{event['id']}", headers=headers, json={}).status_code == 405


@pytest.mark.integration
def test_exactly_three_dispatch_routes_exist(client) -> None:
    openapi = client.get("/openapi.json").json()
    dispatch_paths = {p: list(v.keys()) for p, v in openapi["paths"].items() if "dispatch" in p}
    methods = sorted(m for ops in dispatch_paths.values() for m in ops)
    assert sorted(dispatch_paths.keys()) == ["/farms/{farm_id}/dispatches", "/farms/{farm_id}/dispatches/{dispatch_event_id}"]
    assert methods == ["get", "get", "post"]
