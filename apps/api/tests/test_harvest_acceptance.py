"""Core CMP-013 acceptance flow: farm -> crop/variety/production-system ->
workflow -> published version with a harvesting stage -> batch -> sown
carriers -> progress into harvesting -> occupancy on some carriers -> harvest
three of four selected assignments -> one produce lot -> reconciliation ->
traceability -> repeated harvest -> retry -> quality-hold blocking -> lot-code
collision -> cross-tenant rejection. All via the HTTP API."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models.movement import Movement
from app.models.occupancy import Occupancy


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.mark.integration
def test_harvest_acceptance_flow(client, active_context, db_session) -> None:
    _tenant, _user, headers = active_context
    suffix = uuid.uuid4().hex[:8].upper()

    # 1. Farm, crop, variety, workflow, active batch.
    farm = client.post(
        "/farms", headers=headers,
        json={"code": f"farm-{suffix}", "name": "Harvest Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
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

    # 2. Configure a harvesting stage (plus a start stage to seed into and a terminal stage).
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
    advance_to_harvesting = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
        json={"from_stage_id": seeding["id"], "to_stage_id": harvesting["id"], "code": "ADV-1", "name": "Advance 1"},
    ).json()
    client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
        json={"from_stage_id": harvesting["id"], "to_stage_id": complete["id"], "code": "ADV-2", "name": "Advance 2"},
    )
    publish_resp = client.post(f"/workflows/{workflow['id']}/versions/{version['id']}/publish", headers=headers)
    assert publish_resp.status_code == 200

    batch_resp = client.post(
        f"/farms/{farm_id}/crop-batches", headers=headers,
        json={"code": f"BATCH-{suffix}", "workflow_id": workflow["id"], "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso()},
    )
    assert batch_resp.status_code == 201
    batch = batch_resp.json()

    seed_lot = client.post(
        f"/farms/{farm_id}/seed-lots", headers=headers,
        json={"crop_id": crop["id"], "variety_id": variety["id"], "code": f"lot-{suffix}"},
    ).json()

    # 3. Four active carrier assignments via sowing.
    carriers = [
        client.post(f"/farms/{farm_id}/carriers", headers=headers, json={"carrier_type_code": "seed_tray", "code": f"tray-{suffix}-{n}"}).json()
        for n in range(4)
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

    # 4. Occupancy on at least two carriers. Seed-tray carriers occupy an
    # asset position (kind 'slot'), not a location, per the seeded
    # occupancy-compatibility rules — placing them requires a real trolley
    # asset, which is unrelated setup for a harvest test. Two extra
    # cultivation-plate carriers are created and placed on two sibling Grow
    # Tables instead (DOMAIN-FARM-001: the authoritative Leafy topology
    # stops at the Table itself -- there is no further numbered
    # table_position level under it), purely to prove harvest leaves
    # occupancy/movement alone; they are not part of the harvested batch.
    greenhouse_resp = client.post(
        f"/farms/{farm_id}/locations", headers=headers,
        json={
            "location_type_code": "greenhouse", "code": f"gh-{suffix}", "name": "Greenhouse",
            "greenhouse_classification": "leafy_greens",
        },
    )
    assert greenhouse_resp.status_code == 201, greenhouse_resp.text
    greenhouse = greenhouse_resp.json()
    zone_resp = client.post(
        f"/farms/{farm_id}/locations", headers=headers,
        json={"location_type_code": "zone", "code": f"zone-{suffix}", "name": "Zone", "parent_location_id": greenhouse["id"]},
    )
    assert zone_resp.status_code == 201, zone_resp.text
    zone = zone_resp.json()
    span_resp = client.post(
        f"/farms/{farm_id}/locations", headers=headers,
        json={"location_type_code": "span", "code": f"span-{suffix}", "name": "Span", "parent_location_id": zone["id"]},
    )
    assert span_resp.status_code == 201, span_resp.text
    span = span_resp.json()
    position_ids = []
    for n in range(2):
        table_resp = client.post(
            f"/farms/{farm_id}/locations", headers=headers,
            json={
                "location_type_code": "grow_table", "code": f"table-{suffix}-{n}", "name": f"Table {n}",
                "parent_location_id": span["id"], "occupiable": True,
            },
        )
        assert table_resp.status_code == 201, table_resp.text
        position_ids.append(table_resp.json()["id"])

    occupancy_carriers = [
        client.post(
            f"/farms/{farm_id}/carriers", headers=headers,
            json={"carrier_type_code": "cultivation_plate", "code": f"plate-{suffix}-{n}"},
        ).json()
        for n in range(2)
    ]
    for carrier, position_id in zip(occupancy_carriers, position_ids):
        move_resp = client.post(
            f"/farms/{farm_id}/movements", headers=headers,
            json={
                "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
                "occupant": {"kind": "carrier", "id": carrier["id"]},
                "destination": {"kind": "location", "id": position_id},
            },
        )
        assert move_resp.status_code == 201, move_resp.text

    occupancy_before = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    active_occupancy_ids_before = set(
        db_session.execute(select(Occupancy.id).where(Occupancy.end_time.is_(None))).scalars()
    )
    movement_count_before = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    resolved_before = [
        client.get(f"/farms/{farm_id}/carriers/{c['id']}/resolved-location", headers=headers).json()
        for c in carriers
    ]

    # 5. Progress the batch into the harvesting stage.
    transition_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": advance_to_harvesting["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    assert transition_resp.status_code == 201

    # 6-10. Harvest three of the four assignments with Decimal weights/counts, one normalized lot code.
    harvest_command_id = str(uuid.uuid4())
    harvest_payload = {
        "client_command_id": harvest_command_id, "effective_time": _now_iso(),
        "produce_lot_code": f"hlot-{suffix}",
        "source_lines": [
            {"batch_carrier_assignment_id": assignment_ids[0], "harvested_weight_kg": "12.500", "whole_unit_count": 40},
            {"batch_carrier_assignment_id": assignment_ids[1], "harvested_weight_kg": "8.250", "whole_unit_count": 25},
            {"batch_carrier_assignment_id": assignment_ids[2], "harvested_weight_kg": "5.100", "whole_unit_count": 15},
        ],
    }
    harvest_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers, json=harvest_payload
    )
    assert harvest_resp.status_code == 201
    event = harvest_resp.json()
    assert len(event["source_lines"]) == 3
    assert event["total_harvested_weight_kg"] == "25.85"
    assert event["total_whole_unit_count"] == 80

    # 11. Traceability: crop, variety, batch, workflow version, assignments, carriers.
    assert event["crop"]["id"] == crop["id"]
    assert event["variety"]["id"] == variety["id"]
    assert event["batch_id"] == batch["id"]
    assert event["workflow_version_id"] == version["id"]
    for line in event["source_lines"]:
        assert line["batch_carrier_assignment_id"] in assignment_ids[:3]
        assert line["opening_kind"] == "sowing"

    lot = client.get(f"/farms/{farm_id}/harvested-produce-lots/{event['produce_lot_id']}", headers=headers).json()
    assert lot["code"] == f"HLOT-{suffix}"
    assert lot["total_harvested_weight_kg"] == "25.85"
    assert lot["batch_id"] == batch["id"]
    assert lot["crop"]["id"] == crop["id"]

    # 12-13. Fourth unselected assignment unaffected; selected assignments remain active.
    assignments_after = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/carriers", headers=headers).json()
    for a in assignments_after:
        assert a["released_effective_time"] is None

    # 14. Occupancy/movement/resolved locations unchanged.
    occupancy_after = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    active_occupancy_ids_after = set(
        db_session.execute(select(Occupancy.id).where(Occupancy.end_time.is_(None))).scalars()
    )
    movement_count_after = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    assert occupancy_after == occupancy_before
    assert active_occupancy_ids_after == active_occupancy_ids_before
    assert movement_count_after == movement_count_before
    resolved_after = [
        client.get(f"/farms/{farm_id}/carriers/{c['id']}/resolved-location", headers=headers).json()
        for c in carriers
    ]
    assert resolved_after == resolved_before

    # 15. Batch stage and lifecycle unchanged.
    batch_after = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}", headers=headers).json()
    assert batch_after["state"] == "active"
    assert batch_after["current_stage"]["code"] == "HARVESTING"

    # 16-17. Retry the exact command; confirm no duplicates.
    retry_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers, json=harvest_payload
    )
    assert retry_resp.status_code == 201
    assert retry_resp.json()["id"] == event["id"]
    events_after_retry = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers).json()
    assert len(events_after_retry) == 1

    # 18. Second harvest from a previously harvested assignment — repeated harvesting allowed.
    second_harvest_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "produce_lot_code": f"hlot2-{suffix}",
            "source_lines": [{"batch_carrier_assignment_id": assignment_ids[0], "harvested_weight_kg": "1.000"}],
        },
    )
    assert second_harvest_resp.status_code == 201
    assert second_harvest_resp.json()["id"] != event["id"]

    # 19. Place a quality hold and confirm a genuinely new harvest is blocked.
    hold_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/quality-holds", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "reason_code": "pest", "reason_text": "aphids observed",
        },
    )
    assert hold_resp.status_code == 201
    blocked_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "produce_lot_code": f"blocked-{suffix}",
            "source_lines": [{"batch_carrier_assignment_id": assignment_ids[3], "harvested_weight_kg": "1.000"}],
        },
    )
    assert blocked_resp.status_code == 409

    # 20. Exact retry of the pre-hold harvest still succeeds.
    retry_after_hold = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers, json=harvest_payload
    )
    assert retry_after_hold.status_code == 201
    assert retry_after_hold.json()["id"] == event["id"]

    # 21. Reject a duplicate lot code with another command.
    dup_code_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "produce_lot_code": f"hlot-{suffix}",
            "source_lines": [{"batch_carrier_assignment_id": assignment_ids[3], "harvested_weight_kg": "1.000"}],
        },
    )
    assert dup_code_resp.status_code in (409, 422)

    # 22. Reject cross-tenant access.
    from app.services import membership_service, tenant_service, user_service

    tenant_b = tenant_service.create_tenant(db_session, code=f"harvest-tenant-b-{suffix}", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=f"harvest-b-{suffix}", email=f"harvestb-{suffix}@example.com",
        display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    assert client.get(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/harvests/{event['id']}", headers=headers_b
    ).status_code == 404
    assert client.get(
        f"/farms/{farm_id}/harvested-produce-lots/{event['produce_lot_id']}", headers=headers_b
    ).status_code == 404
