import uuid
from datetime import datetime, timezone

import pytest

from app.services import tenant_service


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.mark.integration
def test_full_trolley_tray_scenario(client, db_session, active_context_with_farm) -> None:
    tenant_a, user_a, headers_a, farm = active_context_with_farm

    # 2-3: Farm + nursery greenhouse.
    greenhouse_id = client.post(
        f"/farms/{farm.id}/locations", headers=headers_a,
        json={"location_type_code": "greenhouse", "code": "nursery-gh", "name": "Nursery Greenhouse",
              "greenhouse_classification": "nursery"},
    ).json()["id"]
    area_id = client.post(
        f"/farms/{farm.id}/locations", headers=headers_a,
        json={"location_type_code": "area", "code": "germ-area", "name": "Germination Area",
              "parent_location_id": greenhouse_id},
    ).json()["id"]

    # 4: Germination chamber with >= 20 positions.
    chamber_resp = client.post(
        f"/farms/{farm.id}/locations", headers=headers_a,
        json={"location_type_code": "germination_chamber", "code": "GC-01", "name": "Germination Chamber GC-01",
              "parent_location_id": area_id},
    )
    assert chamber_resp.status_code == 201
    chamber_id = chamber_resp.json()["id"]
    bulk_resp = client.post(
        f"/farms/{farm.id}/locations/{chamber_id}/bulk-children", headers=headers_a,
        json={"location_type_code": "chamber_position", "code_prefix": "P", "start": 1, "end": 20, "pad_width": 2},
    )
    assert bulk_resp.status_code == 201
    positions = {p["code"]: p["id"] for p in bulk_resp.json()}
    assert len(positions) == 20

    # 5: Germination trolley with 8 shelves x 5 slots.
    trolley_resp = client.post(
        f"/farms/{farm.id}/assets", headers=headers_a,
        json={"asset_type_code": "germination_trolley", "code": "GT-0001", "name": "Trolley 1"},
    )
    assert trolley_resp.status_code == 201
    trolley_id = trolley_resp.json()["id"]
    positions_resp = client.post(
        f"/farms/{farm.id}/assets/{trolley_id}/positions/generate", headers=headers_a,
        json={"shelf_count": 8, "slots_per_shelf": 5, "shelf_prefix": "SH-", "slot_prefix": "SL-",
              "shelf_pad_width": 2, "slot_pad_width": 2},
    )
    assert positions_resp.status_code == 201
    shelf_slots = positions_resp.json()
    shelf_03_id = next(p["id"] for p in shelf_slots if p["position_kind"] == "shelf" and p["code"] == "SH-03")
    slot_03_04_id = next(
        p["id"] for p in shelf_slots
        if p["position_kind"] == "slot" and p["parent_position_id"] == shelf_03_id and p["code"] == "SL-04"
    )

    # 6: Register seed tray.
    tray_resp = client.post(
        f"/farms/{farm.id}/carriers", headers=headers_a,
        json={"carrier_type_code": "seed_tray", "code": "ST-0001"},
    )
    assert tray_resp.status_code == 201
    tray_id = tray_resp.json()["id"]

    # 7: Place trolley at chamber position P12.
    place_trolley_resp = client.post(
        f"/farms/{farm.id}/movements", headers=headers_a,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "occupant": {"kind": "asset", "id": trolley_id},
            "destination": {"kind": "location", "id": positions["P12"]},
        },
    )
    assert place_trolley_resp.status_code == 201

    # 8: Place seed tray at shelf 3 / slot 4.
    place_tray_resp = client.post(
        f"/farms/{farm.id}/movements", headers=headers_a,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "occupant": {"kind": "carrier", "id": tray_id},
            "destination": {"kind": "asset_position", "id": slot_03_04_id},
        },
    )
    assert place_tray_resp.status_code == 201

    # 9: Resolve the tray's complete location through the trolley.
    resolved_resp = client.get(f"/farms/{farm.id}/carriers/{tray_id}/resolved-location", headers=headers_a)
    assert resolved_resp.status_code == 200
    resolved = resolved_resp.json()
    assert resolved["fixed_location_path"][-1]["code"] == "P12"
    assert resolved["position_path"][-1]["code"] == "SL-04"

    # 10: Move the trolley to chamber position P13.
    move_command_id = str(uuid.uuid4())
    move_resp = client.post(
        f"/farms/{farm.id}/movements", headers=headers_a,
        json={
            "client_command_id": move_command_id, "effective_time": _now_iso(),
            "occupant": {"kind": "asset", "id": trolley_id},
            "destination": {"kind": "location", "id": positions["P13"]},
        },
    )
    assert move_resp.status_code == 201
    first_move_movement_id = move_resp.json()["id"]

    # 11: Tray remains directly assigned to shelf 3 / slot 4.
    tray_occupancy_resp = client.get(f"/farms/{farm.id}/carriers/{tray_id}/occupancy", headers=headers_a)
    assert tray_occupancy_resp.status_code == 200
    assert tray_occupancy_resp.json()["target"] == {"kind": "asset_position", "id": slot_03_04_id}

    # 12: Tray's resolved farm location now ends at P13.
    resolved_after_move = client.get(f"/farms/{farm.id}/carriers/{tray_id}/resolved-location", headers=headers_a).json()
    assert resolved_after_move["fixed_location_path"][-1]["code"] == "P13"

    # 13-14: Retry the same movement command id; no duplicate movement/occupancy/audit.
    replay_resp = client.post(
        f"/farms/{farm.id}/movements", headers=headers_a,
        json={
            "client_command_id": move_command_id, "effective_time": move_resp.json()["effective_time"],
            "occupant": {"kind": "asset", "id": trolley_id},
            "destination": {"kind": "location", "id": positions["P13"]},
        },
    )
    assert replay_resp.status_code == 201
    assert replay_resp.json()["id"] == first_move_movement_id

    trolley_history_resp = client.get(f"/farms/{farm.id}/assets/{trolley_id}/movement-history", headers=headers_a)
    move_events = [m for m in trolley_history_resp.json() if m["id"] == first_move_movement_id]
    assert len(move_events) == 1

    # 15: Cross-tenant access is rejected.
    tenant_b = tenant_service.create_tenant(db_session, code="tenant-b", name="Tenant B")
    from app.services import user_service

    user_b = user_service.create_user(
        db_session, oidc_issuer="iss-b", oidc_subject="user-b", email="b@example.com", display_name="User B"
    )
    from app.services import membership_service

    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}

    cross_tenant_resp = client.get(f"/farms/{farm.id}/carriers/{tray_id}/resolved-location", headers=headers_b)
    assert cross_tenant_resp.status_code == 404
