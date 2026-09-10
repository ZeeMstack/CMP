"""PLANNING-OPS-001 focused backend tests: Production Requirement and
Seeding Program lifecycle, demand/coverage math (no false precision),
UOM validation, crop/variety consistency, tenant/farm isolation,
permissions, idempotency, and the Sowing integration (planned vs actual,
one Crop Batch per Sowing preserved, unplanned Sowing still valid,
planning changes never rewrite an already-linked actual Sowing)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.services import membership_service


def _d(value) -> Decimal:
    """Compare quantities by numeric value, not by JSON string formatting
    (Decimal JSON serialization trailing-zero behavior is an implementation
    detail, not part of this ticket's contract)."""
    return Decimal(str(value))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uom_id(client, headers, code: str) -> str:
    resp = client.get("/uoms", headers=headers)
    assert resp.status_code == 200
    for uom in resp.json():
        if uom["code"] == code:
            return uom["id"]
    raise AssertionError(f"UOM {code!r} not seeded")


def _build_sowable_workflow(client, headers, farm_id, *, suffix: str):
    """Mirrors test_sowing_acceptance.py's setup: a variety-specific
    workflow whose start stage is seeding and requires seed_tray, plus one
    active seed lot. Returns (crop, variety, workflow_id, seed_lot)."""
    crop = client.post(
        "/crops", headers=headers,
        json={"code": f"crop-{suffix}", "common_name": "Iceberg Lettuce", "crop_category": "leafy_green"},
    ).json()
    variety = client.post(
        f"/crops/{crop['id']}/varieties", headers=headers, json={"code": f"var-{suffix}", "name": "Mamutik RZ"}
    ).json()
    seed_lot = client.post(
        f"/farms/{farm_id}/seed-lots", headers=headers,
        json={"crop_id": crop["id"], "variety_id": variety["id"], "code": f"lot-{suffix}"},
    ).json()
    production_system = client.post(
        "/production-systems", headers=headers, json={"code": f"ps-{suffix}", "name": "Nursery Tray"}
    ).json()
    workflow = client.post(
        "/workflows", headers=headers,
        json={
            "crop_id": crop["id"], "variety_id": variety["id"], "production_system_id": production_system["id"],
            "code": f"wf-{suffix}", "name": "Iceberg Nursery",
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
    complete_stage = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={
            "code": "COMPLETE", "name": "Complete", "display_order": 1, "stage_category": "completed",
            "is_start": False, "is_terminal": True,
        },
    ).json()
    client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
        json={
            "from_stage_id": seeding_stage["id"], "to_stage_id": complete_stage["id"], "code": "ADVANCE",
            "name": "Advance",
        },
    )
    publish_resp = client.post(f"/workflows/{workflow['id']}/versions/{version['id']}/publish", headers=headers)
    assert publish_resp.status_code == 200
    return crop, variety, workflow["id"], seed_lot


def _make_carrier(client, headers, farm_id, *, code: str) -> dict:
    spec = client.post(
        "/carrier-specifications", headers=headers,
        json={
            "carrier_type_code": "seed_tray", "code": f"SPEC-{code}", "name": "Test Seed Tray Specification",
            "length_mm": 300, "width_mm": 200, "height_mm": 50, "biological_position_count": 500,
        },
    )
    if spec.status_code != 201:
        # A seed_tray specification with this code may already exist from a
        # prior call within the same test -- reuse an existing active one.
        specs = client.get("/carrier-specifications", headers=headers).json()
        spec_id = next(s["id"] for s in specs if s["code"] == f"SPEC-{code}")
    else:
        spec_id = spec.json()["id"]
    return client.post(
        f"/farms/{farm_id}/carriers", headers=headers, json={"specification_id": spec_id, "code": code}
    ).json()


def _make_batch(client, headers, farm_id, workflow_id, *, code: str) -> dict:
    resp = client.post(
        f"/farms/{farm_id}/crop-batches", headers=headers,
        json={"code": code, "workflow_id": workflow_id, "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso()},
    )
    assert resp.status_code == 201
    return resp.json()


def _sow(client, headers, farm_id, batch_id, carrier_id, seed_lot_id, *, seeding_program_line_id=None):
    payload = {
        "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
        "lines": [{"carrier_id": carrier_id, "seed_lot_id": seed_lot_id, "sown_site_count": 100, "seed_count": 100}],
    }
    if seeding_program_line_id is not None:
        payload["seeding_program_line_id"] = seeding_program_line_id
    return client.post(f"/farms/{farm_id}/crop-batches/{batch_id}/sowings", headers=headers, json=payload)


def _requirement_payload(crop_id, variety_id, uom_id, **overrides):
    payload = {
        "client_command_id": str(uuid.uuid4()), "crop_id": crop_id, "variety_id": variety_id,
        "required_by_date": "2026-10-15", "required_quantity": "30000", "quantity_uom_id": uom_id,
        "reference": "Customer A", "notes": "initial plan",
    }
    payload.update(overrides)
    return payload


def _line_payload(crop_id, variety_id, seed_uom_id, coverage_uom_id, **overrides):
    payload = {
        "client_command_id": str(uuid.uuid4()), "planned_sow_date": "2026-09-01", "crop_id": crop_id,
        "variety_id": variety_id, "planned_quantity": "20000", "planned_quantity_uom_id": seed_uom_id,
        "expected_coverage_quantity": "10000", "expected_coverage_uom_id": coverage_uom_id, "notes": None,
    }
    payload.update(overrides)
    return payload


# === Production Requirement ==========================================================


@pytest.mark.integration
def test_create_requirement_idempotent_replay_and_conflict(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    crop = client.post(
        "/crops", headers=headers, json={"code": "ice", "common_name": "Iceberg", "crop_category": "leafy_green"}
    ).json()
    variety = client.post(f"/crops/{crop['id']}/varieties", headers=headers, json={"code": "mam", "name": "Mamutik"}).json()
    kg = _uom_id(client, headers, "kg")

    payload = _requirement_payload(crop["id"], variety["id"], kg)
    resp = client.post(f"/farms/{farm.id}/production-requirements", headers=headers, json=payload)
    assert resp.status_code == 201
    requirement = resp.json()
    assert requirement["code"].startswith("PR-")
    assert requirement["status"] == "open"
    assert _d(requirement["fulfillment"]["demand_quantity"]) == Decimal("30000")
    assert _d(requirement["fulfillment"]["planned_coverage_quantity"]) == Decimal("0")
    assert _d(requirement["fulfillment"]["gap_quantity"]) == Decimal("30000")
    assert requirement["fulfillment"]["actual_sowings_count"] == 0

    # Exact replay -> same requirement, no duplicate.
    replay = client.post(f"/farms/{farm.id}/production-requirements", headers=headers, json=payload)
    assert replay.status_code == 201
    assert replay.json()["id"] == requirement["id"]
    listing = client.get(f"/farms/{farm.id}/production-requirements", headers=headers).json()
    assert len([r for r in listing if r["id"] == requirement["id"]]) == 1

    # Same client_command_id, different payload -> conflict.
    conflicting = dict(payload)
    conflicting["required_quantity"] = "99999"
    conflict_resp = client.post(f"/farms/{farm.id}/production-requirements", headers=headers, json=conflicting)
    assert conflict_resp.status_code == 409


@pytest.mark.integration
def test_requirement_farm_and_tenant_isolation(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    crop = client.post(
        "/crops", headers=headers, json={"code": "ice", "common_name": "Iceberg", "crop_category": "leafy_green"}
    ).json()
    variety = client.post(f"/crops/{crop['id']}/varieties", headers=headers, json={"code": "mam", "name": "Mamutik"}).json()
    kg = _uom_id(client, headers, "kg")
    requirement = client.post(
        f"/farms/{farm.id}/production-requirements", headers=headers,
        json=_requirement_payload(crop["id"], variety["id"], kg),
    ).json()

    other_farm = client.post(
        "/farms", headers=headers,
        json={"code": "other-farm", "name": "Other Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    ).json()
    other_farm_list = client.get(f"/farms/{other_farm['id']}/production-requirements", headers=headers).json()
    assert other_farm_list == []
    other_farm_get = client.get(
        f"/farms/{other_farm['id']}/production-requirements/{requirement['id']}", headers=headers
    )
    assert other_farm_get.status_code == 404

    from app.services import tenant_service, user_service

    other_tenant = tenant_service.create_tenant(db_session, code="other-tenant", name="Other Tenant")
    other_user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject="other-user", email="other@example.com",
        display_name="Other User",
    )
    membership_service.add_membership(
        db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None
    )
    other_headers = {"X-Dev-Tenant-Id": str(other_tenant.id), "X-Dev-User-Id": str(other_user.id)}
    cross_tenant_resp = client.get(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}", headers=other_headers
    )
    assert cross_tenant_resp.status_code in (403, 404)


@pytest.mark.integration
def test_requirement_update_only_while_open(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    crop = client.post(
        "/crops", headers=headers, json={"code": "ice", "common_name": "Iceberg", "crop_category": "leafy_green"}
    ).json()
    variety = client.post(f"/crops/{crop['id']}/varieties", headers=headers, json={"code": "mam", "name": "Mamutik"}).json()
    kg = _uom_id(client, headers, "kg")
    requirement = client.post(
        f"/farms/{farm.id}/production-requirements", headers=headers,
        json=_requirement_payload(crop["id"], variety["id"], kg),
    ).json()

    update_resp = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/update", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "required_by_date": "2026-11-01", "required_quantity": "35000",
            "reference": "Customer B", "notes": "revised",
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["required_by_date"] == "2026-11-01"
    assert _d(updated["required_quantity"]) == Decimal("35000")
    assert updated["reference"] == "Customer B"

    close_resp = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/close", headers=headers,
        json={"client_command_id": str(uuid.uuid4())},
    )
    assert close_resp.status_code == 200
    assert close_resp.json()["status"] == "closed"

    blocked = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/update", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "required_by_date": "2026-12-01", "required_quantity": "1",
            "reference": None, "notes": None,
        },
    )
    assert blocked.status_code == 409


@pytest.mark.integration
def test_requirement_close_and_cancel_idempotent(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    crop = client.post(
        "/crops", headers=headers, json={"code": "ice", "common_name": "Iceberg", "crop_category": "leafy_green"}
    ).json()
    variety = client.post(f"/crops/{crop['id']}/varieties", headers=headers, json={"code": "mam", "name": "Mamutik"}).json()
    kg = _uom_id(client, headers, "kg")
    requirement = client.post(
        f"/farms/{farm.id}/production-requirements", headers=headers,
        json=_requirement_payload(crop["id"], variety["id"], kg),
    ).json()

    first_close = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/close", headers=headers,
        json={"client_command_id": str(uuid.uuid4())},
    )
    assert first_close.status_code == 200
    second_close = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/close", headers=headers,
        json={"client_command_id": str(uuid.uuid4())},
    )
    assert second_close.status_code == 200
    assert second_close.json()["status"] == "closed"

    cancel_resp = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/cancel", headers=headers,
        json={"client_command_id": str(uuid.uuid4())},
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    reclose_cancelled = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/close", headers=headers,
        json={"client_command_id": str(uuid.uuid4())},
    )
    assert reclose_cancelled.status_code == 422


# === Seeding Program Line + coverage math ============================================


@pytest.mark.integration
def test_seeding_program_numeric_proof(client, active_context_with_farm) -> None:
    """The ticket's own PLANNING NUMERIC PROOF: 30,000 kg demand; plan
    lines covering 10k+10k+5k = 25,000 kg planned coverage, 5,000 kg gap.
    Linking one actual Sowing to Plan A must NOT change demand or planned
    coverage -- seeds sown is never subtracted from demand kg."""
    _tenant, _user, headers, farm = active_context_with_farm
    crop, variety, workflow_id, seed_lot = _build_sowable_workflow(client, headers, farm.id, suffix="proof")
    kg = _uom_id(client, headers, "kg")
    seed_uom = _uom_id(client, headers, "SEED")

    requirement = client.post(
        f"/farms/{farm.id}/production-requirements", headers=headers,
        json=_requirement_payload(crop["id"], variety["id"], kg),
    ).json()

    for label, coverage in (("A", "10000"), ("B", "10000"), ("C", "5000")):
        resp = client.post(
            f"/farms/{farm.id}/production-requirements/{requirement['id']}/seeding-program-lines", headers=headers,
            json=_line_payload(crop["id"], variety["id"], seed_uom, kg, expected_coverage_quantity=coverage),
        )
        assert resp.status_code == 201, resp.text
        if label == "A":
            plan_a_line_id = resp.json()["id"]

    after_planning = client.get(f"/farms/{farm.id}/production-requirements/{requirement['id']}", headers=headers).json()
    fulfillment = after_planning["fulfillment"]
    assert _d(fulfillment["demand_quantity"]) == Decimal("30000")
    assert _d(fulfillment["planned_coverage_quantity"]) == Decimal("25000")
    assert _d(fulfillment["gap_quantity"]) == Decimal("5000")
    assert fulfillment["is_overplanned"] is False
    assert fulfillment["actual_sowings_count"] == 0
    assert fulfillment["planned_lines_count"] == 3

    carrier = _make_carrier(client, headers, farm.id, code="ST-PROOF-0001")
    batch = _make_batch(client, headers, farm.id, workflow_id, code="BATCH-PROOF-0001")
    sow_resp = _sow(
        client, headers, farm.id, batch["id"], carrier["id"], seed_lot["id"], seeding_program_line_id=plan_a_line_id
    )
    assert sow_resp.status_code == 201, sow_resp.text

    after_sowing = client.get(f"/farms/{farm.id}/production-requirements/{requirement['id']}", headers=headers).json()
    fulfillment_after = after_sowing["fulfillment"]
    assert _d(fulfillment_after["demand_quantity"]) == Decimal("30000")
    assert _d(fulfillment_after["planned_coverage_quantity"]) == Decimal("25000")
    assert _d(fulfillment_after["gap_quantity"]) == Decimal("5000")
    assert fulfillment_after["actual_sowings_count"] == 1


@pytest.mark.integration
def test_overplanned_state(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    crop = client.post(
        "/crops", headers=headers, json={"code": "ice", "common_name": "Iceberg", "crop_category": "leafy_green"}
    ).json()
    variety = client.post(f"/crops/{crop['id']}/varieties", headers=headers, json={"code": "mam", "name": "Mamutik"}).json()
    kg = _uom_id(client, headers, "kg")
    seed_uom = _uom_id(client, headers, "SEED")
    requirement = client.post(
        f"/farms/{farm.id}/production-requirements", headers=headers,
        json=_requirement_payload(crop["id"], variety["id"], kg, required_quantity="10000"),
    ).json()
    client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/seeding-program-lines", headers=headers,
        json=_line_payload(crop["id"], variety["id"], seed_uom, kg, expected_coverage_quantity="15000"),
    )
    fulfillment = client.get(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}", headers=headers
    ).json()["fulfillment"]
    assert fulfillment["is_overplanned"] is True
    assert _d(fulfillment["overplanned_quantity"]) == Decimal("5000")
    assert _d(fulfillment["gap_quantity"]) == Decimal("0")


@pytest.mark.integration
def test_seeding_program_line_uom_validation(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    crop = client.post(
        "/crops", headers=headers, json={"code": "ice", "common_name": "Iceberg", "crop_category": "leafy_green"}
    ).json()
    variety = client.post(f"/crops/{crop['id']}/varieties", headers=headers, json={"code": "mam", "name": "Mamutik"}).json()
    kg = _uom_id(client, headers, "kg")
    ea = _uom_id(client, headers, "EA")
    requirement = client.post(
        f"/farms/{farm.id}/production-requirements", headers=headers,
        json=_requirement_payload(crop["id"], variety["id"], kg),
    ).json()

    # planned_quantity_uom_id must be a count UOM, not kg.
    bad_planned_uom = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/seeding-program-lines", headers=headers,
        json=_line_payload(crop["id"], variety["id"], kg, kg),
    )
    assert bad_planned_uom.status_code == 422

    # expected_coverage_uom_id must match the requirement's own UOM (kg), not EA.
    bad_coverage_uom = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/seeding-program-lines", headers=headers,
        json=_line_payload(crop["id"], variety["id"], ea, ea),
    )
    assert bad_coverage_uom.status_code == 422


@pytest.mark.integration
def test_seeding_program_line_crop_must_match_requirement(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    crop_a = client.post(
        "/crops", headers=headers, json={"code": "ice", "common_name": "Iceberg", "crop_category": "leafy_green"}
    ).json()
    variety_a = client.post(f"/crops/{crop_a['id']}/varieties", headers=headers, json={"code": "mam", "name": "Mamutik"}).json()
    crop_b = client.post(
        "/crops", headers=headers, json={"code": "tom", "common_name": "Tomato", "crop_category": "vine"}
    ).json()
    kg = _uom_id(client, headers, "kg")
    seed_uom = _uom_id(client, headers, "SEED")
    requirement = client.post(
        f"/farms/{farm.id}/production-requirements", headers=headers,
        json=_requirement_payload(crop_a["id"], variety_a["id"], kg),
    ).json()

    mismatched = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/seeding-program-lines", headers=headers,
        json=_line_payload(crop_b["id"], None, seed_uom, kg),
    )
    assert mismatched.status_code == 422


@pytest.mark.integration
def test_seeding_program_line_update_and_cancel(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    crop, variety, workflow_id, seed_lot = _build_sowable_workflow(client, headers, farm.id, suffix="upd")
    kg = _uom_id(client, headers, "kg")
    seed_uom = _uom_id(client, headers, "SEED")
    requirement = client.post(
        f"/farms/{farm.id}/production-requirements", headers=headers,
        json=_requirement_payload(crop["id"], variety["id"], kg),
    ).json()
    line = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/seeding-program-lines", headers=headers,
        json=_line_payload(crop["id"], variety["id"], seed_uom, kg),
    ).json()

    update_resp = client.post(
        f"/farms/{farm.id}/seeding-program-lines/{line['id']}/update", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "planned_sow_date": "2026-09-05",
            "planned_quantity": "22000", "expected_coverage_quantity": "11000", "notes": "adjusted",
        },
    )
    assert update_resp.status_code == 200
    assert _d(update_resp.json()["planned_quantity"]) == Decimal("22000")

    # Once an actual Sowing links to this line, edits must be rejected.
    carrier = _make_carrier(client, headers, farm.id, code="ST-UPD-0001")
    batch = _make_batch(client, headers, farm.id, workflow_id, code="BATCH-UPD-0001")
    sow_resp = _sow(
        client, headers, farm.id, batch["id"], carrier["id"], seed_lot["id"], seeding_program_line_id=line["id"]
    )
    assert sow_resp.status_code == 201

    blocked_update = client.post(
        f"/farms/{farm.id}/seeding-program-lines/{line['id']}/update", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "planned_sow_date": "2026-09-06",
            "planned_quantity": "1", "expected_coverage_quantity": "1", "notes": None,
        },
    )
    assert blocked_update.status_code == 409

    # Cancelling is still allowed even though it's already linked -- and
    # never rewrites the Sowing that already happened.
    cancel_resp = client.post(
        f"/farms/{farm.id}/seeding-program-lines/{line['id']}/cancel", headers=headers,
        json={"client_command_id": str(uuid.uuid4())},
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    sowing_detail = client.get(
        f"/farms/{farm.id}/crop-batches/{batch['id']}/sowings/{sow_resp.json()['id']}", headers=headers
    ).json()
    assert sowing_detail["seeding_program_line_id"] == line["id"]

    line_detail = client.get(f"/farms/{farm.id}/seeding-program-lines/{line['id']}", headers=headers).json()
    assert line_detail["linked_sowing_count"] == 1
    assert line_detail["status"] == "cancelled"

    # Cancelled lines are excluded from active planned coverage.
    fulfillment = client.get(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}", headers=headers
    ).json()["fulfillment"]
    assert _d(fulfillment["planned_coverage_quantity"]) == Decimal("0")
    assert fulfillment["actual_sowings_count"] == 1


# === Sowing integration ===============================================================


@pytest.mark.integration
def test_unplanned_sowing_remains_valid(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    crop, variety, workflow_id, seed_lot = _build_sowable_workflow(client, headers, farm.id, suffix="adhoc")
    carrier = _make_carrier(client, headers, farm.id, code="ST-ADHOC-0001")
    batch = _make_batch(client, headers, farm.id, workflow_id, code="BATCH-ADHOC-0001")

    sow_resp = _sow(client, headers, farm.id, batch["id"], carrier["id"], seed_lot["id"])
    assert sow_resp.status_code == 201
    assert sow_resp.json()["seeding_program_line_id"] is None


@pytest.mark.integration
def test_multiple_actual_sowings_remain_separate_batches_under_one_plan_line(
    client, active_context_with_farm
) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    crop, variety, workflow_id, seed_lot = _build_sowable_workflow(client, headers, farm.id, suffix="multi")
    kg = _uom_id(client, headers, "kg")
    seed_uom = _uom_id(client, headers, "SEED")
    requirement = client.post(
        f"/farms/{farm.id}/production-requirements", headers=headers,
        json=_requirement_payload(crop["id"], variety["id"], kg),
    ).json()
    line = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/seeding-program-lines", headers=headers,
        json=_line_payload(crop["id"], variety["id"], seed_uom, kg),
    ).json()

    carrier_1 = _make_carrier(client, headers, farm.id, code="ST-MULTI-0001")
    batch_1 = _make_batch(client, headers, farm.id, workflow_id, code="BATCH-MULTI-0001")
    sow_1 = _sow(client, headers, farm.id, batch_1["id"], carrier_1["id"], seed_lot["id"], seeding_program_line_id=line["id"])
    assert sow_1.status_code == 201

    carrier_2 = _make_carrier(client, headers, farm.id, code="ST-MULTI-0002")
    batch_2 = _make_batch(client, headers, farm.id, workflow_id, code="BATCH-MULTI-0002")
    sow_2 = _sow(client, headers, farm.id, batch_2["id"], carrier_2["id"], seed_lot["id"], seeding_program_line_id=line["id"])
    assert sow_2.status_code == 201

    assert sow_1.json()["batch_id"] != sow_2.json()["batch_id"]
    assert sow_1.json()["id"] != sow_2.json()["id"]

    line_detail = client.get(f"/farms/{farm.id}/seeding-program-lines/{line['id']}", headers=headers).json()
    assert line_detail["linked_sowing_count"] == 2
    linked_batch_ids = {s["batch_id"] for s in line_detail["linked_sowings"]}
    assert linked_batch_ids == {batch_1["id"], batch_2["id"]}


@pytest.mark.integration
def test_sowing_link_rejects_cancelled_line_and_crop_mismatch(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    crop, variety, workflow_id, seed_lot = _build_sowable_workflow(client, headers, farm.id, suffix="reject")
    kg = _uom_id(client, headers, "kg")
    seed_uom = _uom_id(client, headers, "SEED")
    requirement = client.post(
        f"/farms/{farm.id}/production-requirements", headers=headers,
        json=_requirement_payload(crop["id"], variety["id"], kg),
    ).json()
    line = client.post(
        f"/farms/{farm.id}/production-requirements/{requirement['id']}/seeding-program-lines", headers=headers,
        json=_line_payload(crop["id"], variety["id"], seed_uom, kg),
    ).json()
    client.post(
        f"/farms/{farm.id}/seeding-program-lines/{line['id']}/cancel", headers=headers,
        json={"client_command_id": str(uuid.uuid4())},
    )

    carrier = _make_carrier(client, headers, farm.id, code="ST-REJECT-0001")
    batch = _make_batch(client, headers, farm.id, workflow_id, code="BATCH-REJECT-0001")
    cancelled_link = _sow(
        client, headers, farm.id, batch["id"], carrier["id"], seed_lot["id"], seeding_program_line_id=line["id"]
    )
    assert cancelled_link.status_code == 409

    # A different crop's workflow/batch cannot link to this line either.
    other_crop, other_variety, other_workflow_id, other_seed_lot = _build_sowable_workflow(
        client, headers, farm.id, suffix="reject2"
    )
    other_requirement = client.post(
        f"/farms/{farm.id}/production-requirements", headers=headers,
        json=_requirement_payload(other_crop["id"], other_variety["id"], kg),
    ).json()
    other_line = client.post(
        f"/farms/{farm.id}/production-requirements/{other_requirement['id']}/seeding-program-lines", headers=headers,
        json=_line_payload(other_crop["id"], other_variety["id"], seed_uom, kg),
    ).json()
    mismatched_carrier = _make_carrier(client, headers, farm.id, code="ST-REJECT-0002")
    mismatched_batch = _make_batch(client, headers, farm.id, workflow_id, code="BATCH-REJECT-0002")
    mismatched_link = _sow(
        client, headers, farm.id, mismatched_batch["id"], mismatched_carrier["id"], seed_lot["id"],
        seeding_program_line_id=other_line["id"],
    )
    assert mismatched_link.status_code == 422


# === Permissions =======================================================================


@pytest.mark.integration
def test_planning_permissions_by_role(client, active_context_with_farm, db_session) -> None:
    tenant, _admin_user, admin_headers, farm = active_context_with_farm
    crop = client.post(
        "/crops", headers=admin_headers, json={"code": "ice", "common_name": "Iceberg", "crop_category": "leafy_green"}
    ).json()
    kg = _uom_id(client, admin_headers, "kg")

    from app.services import user_service

    operator_user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject="op-user", email="op@example.com",
        display_name="Operator",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=operator_user.id, role_code="operator", actor_user_id=None
    )
    operator_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(operator_user.id)}

    supervisor_user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject="sup-user", email="sup@example.com",
        display_name="Supervisor",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=supervisor_user.id, role_code="production_supervisor",
        actor_user_id=None,
    )
    supervisor_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(supervisor_user.id)}

    payload = _requirement_payload(crop["id"], None, kg)

    operator_create = client.post(f"/farms/{farm.id}/production-requirements", headers=operator_headers, json=payload)
    assert operator_create.status_code == 403
    operator_list = client.get(f"/farms/{farm.id}/production-requirements", headers=operator_headers)
    assert operator_list.status_code == 403

    supervisor_list = client.get(f"/farms/{farm.id}/production-requirements", headers=supervisor_headers)
    assert supervisor_list.status_code == 200
    supervisor_create = client.post(
        f"/farms/{farm.id}/production-requirements", headers=supervisor_headers, json=payload
    )
    assert supervisor_create.status_code == 403

    admin_create = client.post(f"/farms/{farm.id}/production-requirements", headers=admin_headers, json=payload)
    assert admin_create.status_code == 201
