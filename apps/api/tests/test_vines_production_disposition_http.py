"""VINES-OPS-002: focused HTTP-level coverage for the Vines Production
disposition routes -- one representative round trip proving the API wiring
(schemas, permission dependency, error mapping) end-to-end, plus one
representative permission-split check reusing the same real, DB-approved
roles `test_authz_disposition_correction_split_http.py` already established
for the sibling Leafy authority (`operator` = MANAGE only, `farm_manager` =
CORRECT only). Not a full role matrix -- the domain-level suite
(`test_vines_production_disposition.py`) already covers business logic;
this file only proves the route boundary itself."""

import uuid
from datetime import timedelta

import pytest

from app.services import membership_service, user_service, vines_production_transfer_service
from tests._vines_production_scenario import build_vines_production_ready_scenario

pytestmark = pytest.mark.integration


@pytest.fixture
def _dev_auth_enabled(monkeypatch):
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)


def _membership_headers(db_session, *, tenant_id, role_code: str) -> dict[str, str]:
    user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"vd-http-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com", display_name="Vines Disposition HTTP Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}


def _build_ready_bag(db_session, tenant, user, farm):
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, intervines_plant_count=1, grow_bag_capacity=1, grow_bag_count=1,
        gutter_bag_positions=1,
    )
    transfer = vines_production_transfer_service.record_vines_production_transfer(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
        source_intervines_table_id=s["intervines_table_id"], plant_count=1,
        destination_grow_gutter_id=s["grow_gutter_id"], grow_bag_specification_id=s["grow_bag_specification"].id,
    )
    return s, transfer


@pytest.mark.integration
def test_record_round_trip_via_api(client, db_session, active_context_with_farm, _dev_auth_enabled) -> None:
    tenant, user, admin_headers, farm = active_context_with_farm
    s, transfer = _build_ready_bag(db_session, tenant, user, farm)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id
    db_session.commit()

    payload = {
        "client_command_id": str(uuid.uuid4()),
        "batch_carrier_assignment_id": str(bag_assignment_id),
        "grow_cube_carrier_ids": [str(gc_id)],
        "reason_code": "dead",
        "effective_time": (s["entry_time"] + timedelta(hours=3)).isoformat(),
        "note": None,
    }
    response = client.post(f"/farms/{farm.id}/vines-production/dispositions", json=payload, headers=admin_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["resulting_living_population"] == 0
    assert body["assignment_released"] is True
    assert [c["id"] for c in body["event"]["grow_cubes"]] == [str(gc_id)]

    history_response = client.get(
        f"/farms/{farm.id}/vines-production/dispositions", params={"batch_id": str(s["batch"].id)},
        headers=admin_headers,
    )
    assert history_response.status_code == 200
    history = history_response.json()
    lineage = next(h for h in history if h["population_root_batch_carrier_assignment_id"] == str(bag_assignment_id))
    assert lineage["current_living_population"] == 0
    reduction = next(e for e in lineage["events"] if e["event_kind"] == "REDUCTION")
    assert [c["id"] for c in reduction["grow_cubes"]] == [str(gc_id)]

    correct_response = client.post(
        f"/farms/{farm.id}/vines-production/dispositions/{reduction['id']}/correct",
        json={"client_command_id": str(uuid.uuid4())},
        headers=admin_headers,
    )
    assert correct_response.status_code == 201, correct_response.text
    assert correct_response.json()["resulting_living_population"] == 1


@pytest.mark.integration
def test_operator_may_record_but_not_correct(client, db_session, active_context_with_farm, _dev_auth_enabled) -> None:
    tenant, user, _admin_headers, farm = active_context_with_farm
    s, transfer = _build_ready_bag(db_session, tenant, user, farm)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id
    db_session.commit()
    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="operator")
    db_session.commit()

    record_response = client.post(
        f"/farms/{farm.id}/vines-production/dispositions",
        json={
            "client_command_id": str(uuid.uuid4()), "batch_carrier_assignment_id": str(bag_assignment_id),
            "grow_cube_carrier_ids": [str(gc_id)], "reason_code": "dead",
            "effective_time": (s["entry_time"] + timedelta(hours=3)).isoformat(), "note": None,
        },
        headers=headers,
    )
    assert record_response.status_code == 201, record_response.text
    event_id = record_response.json()["event"]["id"]

    correct_response = client.post(
        f"/farms/{farm.id}/vines-production/dispositions/{event_id}/correct",
        json={"client_command_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert correct_response.status_code == 403


@pytest.mark.integration
def test_farm_manager_may_correct_but_not_record(client, db_session, active_context_with_farm, _dev_auth_enabled) -> None:
    tenant, user, admin_headers, farm = active_context_with_farm
    s, transfer = _build_ready_bag(db_session, tenant, user, farm)
    bag_assignment_id = transfer.grow_bags[0].destination_batch_carrier_assignment_id
    gc_id = transfer.source_grow_cubes[0].id
    db_session.commit()

    admin_record = client.post(
        f"/farms/{farm.id}/vines-production/dispositions",
        json={
            "client_command_id": str(uuid.uuid4()), "batch_carrier_assignment_id": str(bag_assignment_id),
            "grow_cube_carrier_ids": [str(gc_id)], "reason_code": "dead",
            "effective_time": (s["entry_time"] + timedelta(hours=3)).isoformat(), "note": None,
        },
        headers=admin_headers,
    )
    assert admin_record.status_code == 201, admin_record.text
    event_id = admin_record.json()["event"]["id"]

    headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="farm_manager")
    db_session.commit()

    record_response = client.post(
        f"/farms/{farm.id}/vines-production/dispositions",
        json={
            "client_command_id": str(uuid.uuid4()), "batch_carrier_assignment_id": str(bag_assignment_id),
            "grow_cube_carrier_ids": [str(gc_id)], "reason_code": "dead",
            "effective_time": (s["entry_time"] + timedelta(hours=4)).isoformat(), "note": None,
        },
        headers=headers,
    )
    assert record_response.status_code == 403

    correct_response = client.post(
        f"/farms/{farm.id}/vines-production/dispositions/{event_id}/correct",
        json={"client_command_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert correct_response.status_code == 201, correct_response.text
