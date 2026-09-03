import uuid
from datetime import datetime, timezone

import pytest

from app.services import (
    crop_service,
    germination_service,
    production_system_service,
    sowing_service,
    tenant_service,
    workflow_service,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _sow_seed_tray(db_session, tenant, user, farm, *, tray_id: uuid.UUID, seeding_station_id: uuid.UUID) -> None:
    """PILOT-UX-001B: `germination_service.place_tray` (the only route left
    for placing a Seed Tray onto a Germination Trolley position, section 5)
    requires a genuine sowing-origin `BatchCarrierAssignment` -- a
    pre-existing NURSERY-OPS-002A rule this generic-movement acceptance
    scenario never needed before, since it used to reach the Trolley Slot
    through the generic endpoint instead. Minimal scaffold, mirroring
    `test_germination_placement.py`'s own `_build_scenario`, trimmed to
    exactly what one Sowing needs."""
    suffix = uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg Lettuce", scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Iceberg Nursery",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding_stage = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete_stage = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding_stage.id, to_stage_id=complete_stage.id, code="ADVANCE-1", name="Advance 1",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name="Rijk Zwaan", supplier_lot_reference="RZ-001",
        received_date=None, expiry_date=None,
    )
    from app.services import nursery_service

    nursery_service.sow_new_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        seed_lot_id=seed_lot.id, seeding_station_id=seeding_station_id, seeding_machine_id=None,
        effective_time=_now(), note=None,
        trays=[{"carrier_id": tray_id, "sown_site_count": 200, "seeds_sown": 200}],
    )


@pytest.mark.integration
def test_full_trolley_tray_scenario(client, db_session, active_context_with_farm) -> None:
    tenant_a, user_a, headers_a, farm = active_context_with_farm

    # 2-3: Farm + nursery greenhouse.
    greenhouse_id = client.post(
        f"/farms/{farm.id}/locations", headers=headers_a,
        json={"location_type_code": "greenhouse", "code": "nursery-gh", "name": "Nursery Greenhouse",
              "greenhouse_classification": "nursery"},
    ).json()["id"]
    # 4: Two Germination Chambers -- NURSERY-OPS-002A frozen model: the
    # Chamber itself is occupiable, directly by a Germination Trolley Asset
    # (no chamber_position child locations).
    chamber_1_resp = client.post(
        f"/farms/{farm.id}/locations", headers=headers_a,
        json={"location_type_code": "germination_chamber", "code": "GC-01", "name": "Germination Chamber GC-01",
              "parent_location_id": greenhouse_id, "occupiable": True},
    )
    assert chamber_1_resp.status_code == 201
    chamber_1_id = chamber_1_resp.json()["id"]
    chamber_2_resp = client.post(
        f"/farms/{farm.id}/locations", headers=headers_a,
        json={"location_type_code": "germination_chamber", "code": "GC-02", "name": "Germination Chamber GC-02",
              "parent_location_id": greenhouse_id, "occupiable": True},
    )
    assert chamber_2_resp.status_code == 201
    chamber_2_id = chamber_2_resp.json()["id"]
    # Seeding Station -- PILOT-UX-001B: `germination_service.place_tray`
    # (step 8 below) requires a genuine sown Tray, which requires Sowing to
    # have happened at a real Seeding Station.
    seeding_station_resp = client.post(
        f"/farms/{farm.id}/locations", headers=headers_a,
        json={"location_type_code": "seeding_station", "code": "SEED-01", "name": "Seeding Station",
              "parent_location_id": greenhouse_id},
    )
    assert seeding_station_resp.status_code == 201
    seeding_station_id = seeding_station_resp.json()["id"]

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
    seed_tray_spec_resp = client.post(
        "/carrier-specifications", headers=headers_a,
        json={
            "carrier_type_code": "seed_tray", "code": "ST-SPEC-0001", "name": "Test Seed Tray Specification",
            "length_mm": 300, "width_mm": 200, "height_mm": 50, "biological_position_count": 500,
        },
    )
    assert seed_tray_spec_resp.status_code == 201
    seed_tray_spec_id = seed_tray_spec_resp.json()["id"]
    tray_resp = client.post(
        f"/farms/{farm.id}/carriers", headers=headers_a,
        json={"specification_id": seed_tray_spec_id, "code": "ST-0001"},
    )
    assert tray_resp.status_code == 201
    tray_id = tray_resp.json()["id"]
    _sow_seed_tray(db_session, tenant_a, user_a, farm, tray_id=uuid.UUID(tray_id), seeding_station_id=uuid.UUID(seeding_station_id))

    # 7: Place trolley directly into Germination Chamber GC-01.
    place_trolley_resp = client.post(
        f"/farms/{farm.id}/movements", headers=headers_a,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "occupant": {"kind": "asset", "id": trolley_id},
            "destination": {"kind": "location", "id": chamber_1_id},
        },
    )
    assert place_trolley_resp.status_code == 201

    # 8: Place seed tray at shelf 3 / slot 4 -- PILOT-UX-001B section 5: a
    # Seed Tray reaching a Germination Trolley position must go through the
    # Germination domain operation now, never the generic movement endpoint
    # (the generic endpoint is proven to reject this exact combination in
    # test_germination_placement.py; this step exercises the accepting path).
    germination_service.place_tray(
        db_session, tenant_id=tenant_a.id, farm_id=farm.id, actor_user_id=user_a.id,
        client_command_id=uuid.uuid4(), tray_id=uuid.UUID(tray_id), trolley_id=uuid.UUID(trolley_id),
        asset_position_id=uuid.UUID(slot_03_04_id), effective_time=_now(), reason=None,
    )
    db_session.commit()

    # 9: Resolve the tray's complete location through the trolley.
    resolved_resp = client.get(f"/farms/{farm.id}/carriers/{tray_id}/resolved-location", headers=headers_a)
    assert resolved_resp.status_code == 200
    resolved = resolved_resp.json()
    assert resolved["fixed_location_path"][-1]["code"] == "GC-01"
    assert resolved["position_path"][-1]["code"] == "SL-04"

    # 10: Move the trolley to Germination Chamber GC-02.
    move_command_id = str(uuid.uuid4())
    move_resp = client.post(
        f"/farms/{farm.id}/movements", headers=headers_a,
        json={
            "client_command_id": move_command_id, "effective_time": _now_iso(),
            "occupant": {"kind": "asset", "id": trolley_id},
            "destination": {"kind": "location", "id": chamber_2_id},
        },
    )
    assert move_resp.status_code == 201
    first_move_movement_id = move_resp.json()["id"]

    # 11: Tray remains directly assigned to shelf 3 / slot 4.
    tray_occupancy_resp = client.get(f"/farms/{farm.id}/carriers/{tray_id}/occupancy", headers=headers_a)
    assert tray_occupancy_resp.status_code == 200
    assert tray_occupancy_resp.json()["target"] == {"kind": "asset_position", "id": slot_03_04_id}

    # 12: Tray's resolved farm location now ends at GC-02.
    resolved_after_move = client.get(f"/farms/{farm.id}/carriers/{tray_id}/resolved-location", headers=headers_a).json()
    assert resolved_after_move["fixed_location_path"][-1]["code"] == "GC-02"

    # 13-14: Retry the same movement command id; no duplicate movement/occupancy/audit.
    replay_resp = client.post(
        f"/farms/{farm.id}/movements", headers=headers_a,
        json={
            "client_command_id": move_command_id, "effective_time": move_resp.json()["effective_time"],
            "occupant": {"kind": "asset", "id": trolley_id},
            "destination": {"kind": "location", "id": chamber_2_id},
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
