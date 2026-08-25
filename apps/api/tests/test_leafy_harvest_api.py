"""HARVEST-OPS-001 SLICE 2: HTTP-level tests for the operator-facing Leafy
Harvest API surface (`app/api/leafy_harvest.py`) -- harvestable Plates,
Record, History, and line-level Correction. Reuses the exact real-service
scenario helpers already proven by Slice 1's own test suite (`_plate_
scenario`, `_two_plate_scenario`, `_nursery_plate_source_scenario`) so every
setup is a genuine committed-via-`db_session` fact the `client` fixture's
shared connection can see, never fabricated rows."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.services import membership_service, quality_hold_service, user_service
from tests.test_leafy_harvest import _harvest, _line, _two_plate_scenario
from tests.test_leafy_harvest_correction import _correct
from tests.test_production_disposition import _plate_scenario

pytestmark = pytest.mark.integration


def _membership_headers(db_session, *, tenant_id, role_code: str) -> dict[str, str]:
    user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"lh-api-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com", display_name="Leafy Harvest API Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}


def _record_payload(batch_id, lines, *, effective_time, produce_lot_code=None, note=None) -> dict:
    return {
        "client_command_id": str(uuid.uuid4()), "batch_id": str(batch_id),
        "effective_time": effective_time.isoformat(), "produce_lot_code": produce_lot_code or f"HL-{uuid.uuid4().hex[:8]}",
        "note": note,
        "source_lines": [
            {
                "batch_carrier_assignment_id": str(aid), "whole_unit_count": count,
                "harvested_weight_kg": weight, "note": line_note,
            }
            for aid, count, weight, line_note in lines
        ],
    }


def _correct_payload(
    *, supersedes_correction_id=None, is_void=False, corrected_weight=None, corrected_count=None,
    reason_code="miscounted", note="test correction",
) -> dict:
    return {
        "client_command_id": str(uuid.uuid4()),
        "supersedes_correction_id": str(supersedes_correction_id) if supersedes_correction_id else None,
        "is_void": is_void, "corrected_harvested_weight_kg": corrected_weight,
        "corrected_whole_unit_count": corrected_count, "reason_code": reason_code, "note": note,
    }


# =====================================================================
# HARVESTABLE PLATES READ
# =====================================================================


@pytest.mark.integration
def test_harvestable_plates_only_production_cultivation_plate(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, _t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    resp = client.get(f"/farms/{farm.id}/leafy-production/harvestable-plates", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert row["current_batch_carrier_assignment_id"] == str(root_id)
    assert row["batch_id"] == str(batch.id)
    assert row["current_living_heads"] == 10
    assert row["quality_hold_open"] is False
    assert "population_root_batch_carrier_assignment_id" not in row


@pytest.mark.integration
def test_harvestable_plates_excludes_nursery_plate(client, db_session, active_context_with_farm) -> None:
    from tests.test_leafy_production_transfer import _nursery_plate_source_scenario

    tenant, user, headers, farm = active_context_with_farm
    _s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=20)
    _batch, root_id, _t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    resp = client.get(f"/farms/{farm.id}/leafy-production/harvestable-plates", headers=headers)
    assert resp.status_code == 200
    ids = {row["current_batch_carrier_assignment_id"] for row in resp.json()}
    assert str(aids[0]) not in ids
    assert str(root_id) in ids


@pytest.mark.integration
def test_harvestable_plates_excludes_zero_exhausted_and_includes_partial(
    client, db_session, active_context_with_farm
) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_ids, t0 = _two_plate_scenario(db_session, tenant, user, farm, counts=(5, 8))
    _harvest(
        db_session, tenant, farm, user, batch.id,
        [_line(root_ids[0], 5, "2.500"), _line(root_ids[1], 3, "1.500")], effective_time=t0 + timedelta(hours=1),
    )
    resp = client.get(f"/farms/{farm.id}/leafy-production/harvestable-plates", headers=headers)
    assert resp.status_code == 200
    by_id = {row["current_batch_carrier_assignment_id"]: row for row in resp.json()}
    assert str(root_ids[0]) not in by_id
    assert str(root_ids[1]) in by_id
    assert by_id[str(root_ids[1])]["current_living_heads"] == 5


@pytest.mark.integration
def test_harvestable_plates_quality_held_plate_visible_and_flagged(
    client, db_session, active_context_with_farm
) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    quality_hold_service.place_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=t0 + timedelta(minutes=5),
        source_observation_event_id=None, reason_code="OTHER", reason_text="test hold",
    )
    resp = client.get(f"/farms/{farm.id}/leafy-production/harvestable-plates", headers=headers)
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["quality_hold_open"] is True


@pytest.mark.integration
def test_harvestable_plates_tenant_farm_isolation(client, db_session, active_context_with_farm) -> None:
    from app.services import farm_service, membership_service as _ms, tenant_service, user_service as _us

    tenant, user, headers, farm = active_context_with_farm
    _plate_scenario(db_session, tenant, user, farm, opening_count=10)

    other_tenant = tenant_service.create_tenant(db_session, code="other-lh-tenant", name="Other Tenant")
    other_user = _us.create_user(
        db_session, oidc_issuer="other", oidc_subject="other-lh", email="other-lh@example.com", display_name="Other",
    )
    _ms.add_membership(
        db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None
    )
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_headers = {"X-Dev-Tenant-Id": str(other_tenant.id), "X-Dev-User-Id": str(other_user.id)}

    resp = client.get(f"/farms/{other_farm.id}/leafy-production/harvestable-plates", headers=other_headers)
    assert resp.status_code == 200
    assert resp.json() == []

    cross_resp = client.get(f"/farms/{farm.id}/leafy-production/harvestable-plates", headers=other_headers)
    assert cross_resp.status_code == 404


@pytest.mark.integration
def test_harvestable_plates_requires_harvest_read(client, db_session, active_context_with_farm) -> None:
    tenant, user, _admin_headers, farm = active_context_with_farm
    _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="storekeeper")
    resp = client.get(f"/farms/{farm.id}/leafy-production/harvestable-plates", headers=headers)
    assert resp.status_code == 403


# =====================================================================
# RECORD HTTP
# =====================================================================


@pytest.mark.integration
def test_record_partial_harvest(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    resp = client.post(
        f"/farms/{farm.id}/leafy-production/harvests",
        json=_record_payload(batch.id, [(root_id, 4, "2.000", None)], effective_time=t0 + timedelta(hours=1)),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["current_total_whole_unit_count"] == 4
    assert body["current_total_harvested_weight_kg"] == "2"
    assert body["original_total_whole_unit_count"] == 4
    assert len(body["source_lines"]) == 1
    assert body["source_lines"][0]["state"] == "ACTIVE"


@pytest.mark.integration
def test_record_exact_zero_harvest(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=6)
    resp = client.post(
        f"/farms/{farm.id}/leafy-production/harvests",
        json=_record_payload(batch.id, [(root_id, 6, "3.000", None)], effective_time=t0 + timedelta(hours=1)),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    plates_resp = client.get(f"/farms/{farm.id}/leafy-production/harvestable-plates", headers=headers)
    assert all(row["current_batch_carrier_assignment_id"] != str(root_id) for row in plates_resp.json())
    history_resp = client.get(f"/farms/{farm.id}/leafy-production/harvests", headers=headers)
    assert any(e["id"] == resp.json()["id"] for e in history_resp.json())


@pytest.mark.integration
def test_record_multi_plate_same_batch(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_ids, t0 = _two_plate_scenario(db_session, tenant, user, farm, counts=(5, 8))
    resp = client.post(
        f"/farms/{farm.id}/leafy-production/harvests",
        json=_record_payload(
            batch.id, [(root_ids[0], 5, "2.500", None), (root_ids[1], 3, "1.500", "second plate")],
            effective_time=t0 + timedelta(hours=1),
        ),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["current_total_whole_unit_count"] == 8
    assert len(body["source_lines"]) == 2


@pytest.mark.integration
def test_record_cross_batch_rejected(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch_a, root_a, t0a = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    batch_b, root_b, _t0b = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    resp = client.post(
        f"/farms/{farm.id}/leafy-production/harvests",
        json=_record_payload(
            batch_a.id, [(root_a, 4, "2.000", None), (root_b, 3, "1.500", None)], effective_time=t0a + timedelta(hours=1)
        ),
        headers=headers,
    )
    assert resp.status_code in (404, 422)


@pytest.mark.integration
def test_record_requires_harvest_manage(client, db_session, active_context_with_farm) -> None:
    tenant, user, _admin_headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="qc_officer")
    resp = client.post(
        f"/farms/{farm.id}/leafy-production/harvests",
        json=_record_payload(batch.id, [(root_id, 4, "2.000", None)], effective_time=t0 + timedelta(hours=1)),
        headers=headers,
    )
    assert resp.status_code == 403


@pytest.mark.integration
def test_record_blocked_by_quality_hold(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    quality_hold_service.place_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=t0 + timedelta(minutes=5),
        source_observation_event_id=None, reason_code="OTHER", reason_text="test hold",
    )
    resp = client.post(
        f"/farms/{farm.id}/leafy-production/harvests",
        json=_record_payload(batch.id, [(root_id, 4, "2.000", None)], effective_time=t0 + timedelta(hours=1)),
        headers=headers,
    )
    assert resp.status_code == 409


@pytest.mark.integration
def test_record_response_returns_lot_identity_and_totals(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    resp = client.post(
        f"/farms/{farm.id}/leafy-production/harvests",
        json=_record_payload(
            batch.id, [(root_id, 4, "2.000", None)], effective_time=t0 + timedelta(hours=1), produce_lot_code="HL-XYZ",
        ),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["produce_lot_code"] == "HL-XYZ"
    assert body["available_balance_whole_unit_count"] == 4
    assert body["available_balance_weight_kg"] == "2"


@pytest.mark.integration
def test_record_idempotent_replay(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    payload = _record_payload(batch.id, [(root_id, 4, "2.000", None)], effective_time=t0 + timedelta(hours=1))
    resp1 = client.post(f"/farms/{farm.id}/leafy-production/harvests", json=payload, headers=headers)
    resp2 = client.post(f"/farms/{farm.id}/leafy-production/harvests", json=payload, headers=headers)
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["id"] == resp2.json()["id"]
    history_resp = client.get(f"/farms/{farm.id}/leafy-production/harvests?batch_id={batch.id}", headers=headers)
    assert len(history_resp.json()) == 1


# =====================================================================
# HISTORY
# =====================================================================


@pytest.mark.integration
def test_history_original_and_current_effective_values(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    from tests.test_leafy_harvest_correction import _only_source_line

    line = _only_source_line(db_session, event)
    _correct(
        db_session, tenant, farm, user, line.id, corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
    )
    resp = client.get(f"/farms/{farm.id}/leafy-production/harvests/{event.id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    source_line = body["source_lines"][0]
    assert source_line["original_whole_unit_count"] == 5
    assert source_line["original_harvested_weight_kg"] == "2.5"
    assert source_line["current_whole_unit_count"] == 4
    assert source_line["current_harvested_weight_kg"] == "2"
    assert source_line["state"] == "ACTIVE"
    assert len(source_line["correction_history"]) == 1
    assert body["original_total_whole_unit_count"] == 5
    assert body["current_total_whole_unit_count"] == 4


@pytest.mark.integration
def test_history_void_state(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    from tests.test_leafy_harvest_correction import _only_source_line

    line = _only_source_line(db_session, event)
    _correct(db_session, tenant, farm, user, line.id, is_void=True)
    resp = client.get(f"/farms/{farm.id}/leafy-production/harvests/{event.id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    source_line = body["source_lines"][0]
    assert source_line["state"] == "VOID"
    assert source_line["current_whole_unit_count"] == 0
    assert source_line["current_harvested_weight_kg"] == "0"
    assert body["current_total_whole_unit_count"] == 0


@pytest.mark.integration
def test_history_current_totals_aggregate_offsetting_per_line_changes(
    client, db_session, active_context_with_farm
) -> None:
    """Plate A: original 5 -> current 4. Plate B: original 7 -> current 8.
    Original lot total 12, current corrected lot total also 12 -- but each
    Plate's own change must remain independently visible in `source_lines`."""
    tenant, user, headers, farm = active_context_with_farm
    batch, root_ids, t0 = _two_plate_scenario(db_session, tenant, user, farm, counts=(10, 10))
    event = _harvest(
        db_session, tenant, farm, user, batch.id,
        [_line(root_ids[0], 5, "2.500"), _line(root_ids[1], 7, "3.500")], effective_time=t0 + timedelta(hours=1),
    )
    from sqlalchemy import select

    from app.models.harvest_source_line import HarvestSourceLine

    source_lines = db_session.execute(
        select(HarvestSourceLine).where(HarvestSourceLine.harvest_event_id == event.id)
    ).scalars().all()
    line_a = next(sl for sl in source_lines if sl.batch_carrier_assignment_id == root_ids[0])
    line_b = next(sl for sl in source_lines if sl.batch_carrier_assignment_id == root_ids[1])

    _correct(db_session, tenant, farm, user, line_a.id, corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4)
    _correct(db_session, tenant, farm, user, line_b.id, corrected_harvested_weight_kg=Decimal("4.000"), corrected_whole_unit_count=8)

    resp = client.get(f"/farms/{farm.id}/leafy-production/harvests/{event.id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["original_total_whole_unit_count"] == 12
    assert body["current_total_whole_unit_count"] == 12
    by_root = {sl["batch_carrier_assignment_id"]: sl for sl in body["source_lines"]}
    assert by_root[str(root_ids[0])]["current_whole_unit_count"] == 4
    assert by_root[str(root_ids[1])]["current_whole_unit_count"] == 8


# =====================================================================
# CORRECTION HTTP
# =====================================================================


def _correct_url(farm_id, event_id, line_id) -> str:
    return f"/farms/{farm_id}/leafy-production/harvests/{event_id}/source-lines/{line_id}/correct"


@pytest.mark.integration
def test_correct_first_replacement(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    from tests.test_leafy_harvest_correction import _only_source_line

    line = _only_source_line(db_session, event)
    resp = client.post(
        _correct_url(farm.id, event.id, line.id),
        json=_correct_payload(corrected_weight="2.000", corrected_count=4),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    source_line = resp.json()["source_lines"][0]
    assert source_line["current_whole_unit_count"] == 4
    assert source_line["correction_tip_id"] is not None


@pytest.mark.integration
def test_correct_pure_void(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    from tests.test_leafy_harvest_correction import _only_source_line

    line = _only_source_line(db_session, event)
    resp = client.post(_correct_url(farm.id, event.id, line.id), json=_correct_payload(is_void=True), headers=headers)
    assert resp.status_code == 201, resp.text
    source_line = resp.json()["source_lines"][0]
    assert source_line["state"] == "VOID"


@pytest.mark.integration
def test_correct_a_void_uses_same_action(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    from tests.test_leafy_harvest_correction import _only_source_line

    line = _only_source_line(db_session, event)
    void_resp = client.post(_correct_url(farm.id, event.id, line.id), json=_correct_payload(is_void=True), headers=headers)
    tip_id = void_resp.json()["source_lines"][0]["correction_tip_id"]
    resp = client.post(
        _correct_url(farm.id, event.id, line.id),
        json=_correct_payload(supersedes_correction_id=tip_id, corrected_weight="1.000", corrected_count=2),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    source_line = resp.json()["source_lines"][0]
    assert source_line["state"] == "ACTIVE"
    assert source_line["current_whole_unit_count"] == 2


@pytest.mark.integration
def test_correct_stale_predecessor_409(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    from tests.test_leafy_harvest_correction import _only_source_line

    line = _only_source_line(db_session, event)
    _correct(db_session, tenant, farm, user, line.id, corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4)
    resp = client.post(
        _correct_url(farm.id, event.id, line.id),
        json=_correct_payload(supersedes_correction_id=None, corrected_weight="1.000", corrected_count=2),
        headers=headers,
    )
    assert resp.status_code == 409


@pytest.mark.integration
def test_correct_negative_available_balance_409(client, db_session, active_context_with_farm) -> None:
    from app.services import packing_service

    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 10, "5.000")], effective_time=t0 + timedelta(hours=1))
    from tests.test_leafy_harvest_correction import _lot_for, _only_source_line

    line = _only_source_line(db_session, event)
    lot = _lot_for(db_session, event)
    packing_service.record_packing(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=t0 + timedelta(hours=2), finished_goods_lot_code=f"FG-{uuid.uuid4().hex[:8]}", package_count=1,
        packed_output_weight_kg=Decimal("4.000"), process_loss_weight_kg=Decimal("0.000"),
        rejected_weight_kg=Decimal("0.000"), note=None,
        input_lines=[
            {"harvested_produce_lot_id": lot.id, "consumed_weight_kg": Decimal("4.000"), "consumed_whole_unit_count": 8, "note": None}
        ],
    )
    resp = client.post(
        _correct_url(farm.id, event.id, line.id),
        json=_correct_payload(corrected_weight="2.500", corrected_count=5),
        headers=headers,
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "packing" in detail["message"].lower()


@pytest.mark.integration
def test_correct_requires_harvest_manage(client, db_session, active_context_with_farm) -> None:
    tenant, user, _admin_headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    from tests.test_leafy_harvest_correction import _only_source_line

    line = _only_source_line(db_session, event)
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="qc_officer")
    resp = client.post(
        _correct_url(farm.id, event.id, line.id),
        json=_correct_payload(corrected_weight="2.000", corrected_count=4),
        headers=headers,
    )
    assert resp.status_code == 403


@pytest.mark.integration
def test_correct_source_line_must_belong_to_event(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_ids, t0 = _two_plate_scenario(db_session, tenant, user, farm, counts=(10, 10))
    event_a = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_ids[0], 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    event_b = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_ids[1], 3, "1.500")], effective_time=t0 + timedelta(hours=2))
    from tests.test_leafy_harvest_correction import _only_source_line

    line_b = _only_source_line(db_session, event_b)
    resp = client.post(
        _correct_url(farm.id, event_a.id, line_b.id),
        json=_correct_payload(corrected_weight="1.000", corrected_count=2),
        headers=headers,
    )
    assert resp.status_code == 404


@pytest.mark.integration
def test_correct_idempotent_replay(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    from tests.test_leafy_harvest_correction import _only_source_line

    line = _only_source_line(db_session, event)
    payload = _correct_payload(corrected_weight="2.000", corrected_count=4)
    resp1 = client.post(_correct_url(farm.id, event.id, line.id), json=payload, headers=headers)
    resp2 = client.post(_correct_url(farm.id, event.id, line.id), json=payload, headers=headers)
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["source_lines"][0]["correction_tip_id"] == resp2.json()["source_lines"][0]["correction_tip_id"]


# =====================================================================
# HARVEST-OPS-001 SLICE 2 CORRECTION 1, Finding 1: Harvest source-line
# location must be HISTORICAL (as of HarvestEvent.effective_time), never
# current -- a later Movement must never rewrite Harvest History's own
# traceability fact. Harvestable Plates (operational, current-state) is
# explicitly proven UNCHANGED by the same scenario.
# =====================================================================


def _plate_scenario_with_tables(db_session, tenant, user, farm, *, opening_count=10):
    """Like `_plate_scenario`, but also returns the Production Plate's
    Carrier id and every Leafy Table id `_leafy_setup` created (only
    `table_ids[0]` is used for the initial placement) -- so a test can
    later move the same Plate to a second real Table."""
    from tests.test_leafy_production_transfer import (
        _leafy_setup, _nursery_plate_source_scenario, _production_plates, _record, _simple_allocation,
        _simple_destination, _simple_source,
    )

    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=opening_count)
    table_ids = _leafy_setup(db_session, tenant, user, farm, table_count=2)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)
    result = _record(
        db_session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=opening_count)],
        [_simple_allocation(aids[0], plates[0].id, opening_count)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )
    root_id = result.destination_lines[0].destination_batch_carrier_assignment_id
    t0 = s["transfer_ready_time"] + timedelta(hours=1)
    return s["batch"], root_id, plates[0].id, table_ids, t0


@pytest.mark.integration
def test_harvest_history_location_is_as_of_harvest_time_not_current(
    client, db_session, active_context_with_farm
) -> None:
    """1. Plate starts at TA01 (table_ids[0]). 2. Harvest occurs. 3. A later
    Movement moves the Plate to TA02 (table_ids[1]). 4. Harvest detail still
    reports TA01. 5. The current Harvestable Plates read reports TA02."""
    from app.services import movement_service

    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, carrier_id, table_ids, t0 = _plate_scenario_with_tables(db_session, tenant, user, farm, opening_count=10)
    harvest_time = t0 + timedelta(hours=1)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 4, "2.000")], effective_time=harvest_time)

    # 3. Later Movement to a second real Table.
    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=harvest_time + timedelta(hours=5), occupant_kind="carrier", occupant_id=carrier_id,
        destination_kind="location", destination_id=table_ids[1], reason=None,
    )

    # 4. Harvest detail must still report TA01 (the harvest-time location).
    detail_resp = client.get(f"/farms/{farm.id}/leafy-production/harvests/{event.id}", headers=headers)
    assert detail_resp.status_code == 200
    line = detail_resp.json()["source_lines"][0]
    assert line["harvest_location"]["grow_table"]["id"] == str(table_ids[0])
    assert line["harvest_location"]["grow_table"]["id"] != str(table_ids[1])

    # 5. The Harvestable Plates read (operational, current-state) must
    # report TA02 -- proving this screen was correctly left unchanged.
    plates_resp = client.get(f"/farms/{farm.id}/leafy-production/harvestable-plates", headers=headers)
    assert plates_resp.status_code == 200
    row = next(r for r in plates_resp.json() if r["current_batch_carrier_assignment_id"] == str(root_id))
    assert row["location"]["grow_table"]["id"] == str(table_ids[1])


@pytest.mark.integration
def test_released_historical_harvest_lineage_still_resolves_harvest_time_location(
    client, db_session, active_context_with_farm
) -> None:
    """A fully zero-harvested (released) Plate disappears from Harvestable
    Plates but its Harvest History must still resolve to exactly where it
    was physically located at the moment of that Harvest."""
    from app.services import movement_service

    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, carrier_id, table_ids, t0 = _plate_scenario_with_tables(db_session, tenant, user, farm, opening_count=6)
    harvest_time = t0 + timedelta(hours=1)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 6, "3.000")], effective_time=harvest_time)

    movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=harvest_time + timedelta(hours=5), occupant_kind="carrier", occupant_id=carrier_id,
        destination_kind="location", destination_id=table_ids[1], reason=None,
    )

    plates_resp = client.get(f"/farms/{farm.id}/leafy-production/harvestable-plates", headers=headers)
    assert all(r["current_batch_carrier_assignment_id"] != str(root_id) for r in plates_resp.json())

    detail_resp = client.get(f"/farms/{farm.id}/leafy-production/harvests/{event.id}", headers=headers)
    assert detail_resp.status_code == 200
    line = detail_resp.json()["source_lines"][0]
    assert line["harvest_location"]["grow_table"]["id"] == str(table_ids[0])


def test_carrier_location_as_of_returns_none_when_no_occupancy_interval_contains_it(
    db_session, active_context_with_farm
) -> None:
    """Service-level proof of the resolver's own explicit-unavailable
    contract: a Carrier that has never been placed anywhere (registered,
    but no Occupancy row ever opened for it -- a real, if exceptional,
    state Harvest's own effective_time guards make otherwise unreachable
    end-to-end, since a Plate must be transplanted+placed together before
    any Harvest against it is even possible) must resolve to `None` for
    any `as_of`, never a fabricated/fallback location."""
    from datetime import datetime, timezone

    from app.services import movement_service
    from tests.test_leafy_production_transfer import _production_plates

    tenant, user, _headers, farm = active_context_with_farm
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)
    resolved = movement_service.get_carrier_location_as_of(
        db_session, carrier_id=plates[0].id, as_of=datetime.now(timezone.utc)
    )
    assert resolved is None


# =====================================================================
# HARVEST-OPS-001 SLICE 2 CORRECTION 1, Finding 2: 409 conflicts carry a
# stable, machine-readable `code` in `detail`, never classified by the
# frontend via message shape/text.
# =====================================================================


@pytest.mark.integration
def test_stale_predecessor_409_carries_stable_code(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    from tests.test_leafy_harvest_correction import _only_source_line

    line = _only_source_line(db_session, event)
    _correct(db_session, tenant, farm, user, line.id, corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4)
    resp = client.post(
        _correct_url(farm.id, event.id, line.id),
        json=_correct_payload(supersedes_correction_id=None, corrected_weight="1.000", corrected_count=2),
        headers=headers,
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["code"] == "HARVEST_CORRECTION_STALE"


@pytest.mark.integration
def test_negative_available_balance_409_carries_stable_code(client, db_session, active_context_with_farm) -> None:
    from app.services import packing_service

    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 10, "5.000")], effective_time=t0 + timedelta(hours=1))
    from tests.test_leafy_harvest_correction import _lot_for, _only_source_line

    line = _only_source_line(db_session, event)
    lot = _lot_for(db_session, event)
    packing_service.record_packing(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=t0 + timedelta(hours=2), finished_goods_lot_code=f"FG-{uuid.uuid4().hex[:8]}", package_count=1,
        packed_output_weight_kg=Decimal("4.000"), process_loss_weight_kg=Decimal("0.000"),
        rejected_weight_kg=Decimal("0.000"), note=None,
        input_lines=[
            {"harvested_produce_lot_id": lot.id, "consumed_weight_kg": Decimal("4.000"), "consumed_whole_unit_count": 8, "note": None}
        ],
    )
    resp = client.post(
        _correct_url(farm.id, event.id, line.id),
        json=_correct_payload(corrected_weight="2.500", corrected_count=5),
        headers=headers,
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["code"] == "HARVEST_NEGATIVE_LOT_BALANCE"
    assert "already been consumed in packing" in detail["message"]


@pytest.mark.integration
def test_quality_hold_409_on_record_carries_stable_code(client, db_session, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    quality_hold_service.place_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=t0 + timedelta(minutes=5),
        source_observation_event_id=None, reason_code="OTHER", reason_text="test hold",
    )
    resp = client.post(
        f"/farms/{farm.id}/leafy-production/harvests",
        json=_record_payload(batch.id, [(root_id, 4, "2.000", None)], effective_time=t0 + timedelta(hours=1)),
        headers=headers,
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["code"] == "HARVEST_QUALITY_HOLD"


@pytest.mark.integration
def test_idempotency_replay_conflict_keeps_plain_string_detail(client, db_session, active_context_with_farm) -> None:
    """Not every 409 gets a code -- only the 5 named Harvest conflict
    types. An idempotency replay-mismatch (a pre-existing, unrelated
    conflict class) must keep its plain-string `detail` exactly as
    before, proving this change is additive, never a blanket rewrite of
    every conflict response's shape."""
    tenant, user, headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=10)
    same_command_id = str(uuid.uuid4())
    payload_a = _record_payload(batch.id, [(root_id, 4, "2.000", None)], effective_time=t0 + timedelta(hours=1))
    payload_a["client_command_id"] = same_command_id
    payload_b = _record_payload(batch.id, [(root_id, 3, "1.500", None)], effective_time=t0 + timedelta(hours=1))
    payload_b["client_command_id"] = same_command_id

    resp1 = client.post(f"/farms/{farm.id}/leafy-production/harvests", json=payload_a, headers=headers)
    assert resp1.status_code == 201
    resp2 = client.post(f"/farms/{farm.id}/leafy-production/harvests", json=payload_b, headers=headers)
    assert resp2.status_code == 409
    assert isinstance(resp2.json()["detail"], str)
