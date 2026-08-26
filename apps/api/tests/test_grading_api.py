"""POSTHARVEST-OPS-001C: HTTP-level authorization, tenant-isolation, and
farm-isolation proofs for the grading-events/graded-produce-lots API,
reusing packing.read/packing.manage exactly. Mirrors
test_authz_role_activation_http.py's own committed-scenario + role-header
bridging pattern for HTTP tests against `test_engine`-committed data."""
import uuid
from datetime import datetime, timezone

import pytest

from app.models.membership import TenantMembership
from app.services import membership_service, user_service
from tests._grading_scenario import build_committed_scenario, cleanup_scenario


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _role_headers(db_session, *, tenant_id, role_code: str):
    user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"grading-role-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com", display_name="Grading Role Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}, user


@pytest.fixture
def _scenario_cleanup(test_engine):
    tenant_ids: list[uuid.UUID] = []
    yield tenant_ids
    for tenant_id in tenant_ids:
        cleanup_scenario(test_engine, tenant_id)


def _grading_payload(scenario, *, code="GPL-API") -> dict:
    return {
        "client_command_id": str(uuid.uuid4()),
        "source_harvested_produce_lot_id": str(scenario["lot_a_id"]),
        "processing_hall_location_id": str(scenario["packing_hall_location_id"]),
        "effective_time": _now_iso(), "note": None,
        "input_presented_weight_kg": "10.000", "input_presented_whole_unit_count": None,
        "rejected_weight_kg": "0", "rejected_whole_unit_count": None,
        "loss_weight_kg": "0", "loss_whole_unit_count": None,
        "sample_weight_kg": "0", "sample_whole_unit_count": None,
        "remainder_weight_kg": "0", "remainder_whole_unit_count": None,
        "outputs": [
            {
                "grade_definition_version_id": str(scenario["grade_definition_version_id"]), "code": code,
                "output_weight_kg": "10.000", "output_whole_unit_count": None,
            }
        ],
    }


@pytest.mark.integration
def test_packing_read_can_read_but_not_mutate(_scenario_cleanup, client, db_session, test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    _scenario_cleanup.append(scenario["tenant_id"])
    headers, _user = _role_headers(db_session, tenant_id=scenario["tenant_id"], role_code="qc_officer")

    list_response = client.get(f"/farms/{scenario['farm_id']}/grading-events", headers=headers)
    assert list_response.status_code == 200

    lots_response = client.get(f"/farms/{scenario['farm_id']}/graded-produce-lots", headers=headers)
    assert lots_response.status_code == 200

    create_response = client.post(
        f"/farms/{scenario['farm_id']}/grading-events", json=_grading_payload(scenario), headers=headers
    )
    assert create_response.status_code == 403


@pytest.mark.integration
def test_packing_manage_can_mutate(_scenario_cleanup, client, db_session, test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    _scenario_cleanup.append(scenario["tenant_id"])
    headers, _user = _role_headers(db_session, tenant_id=scenario["tenant_id"], role_code="packing_supervisor")

    create_response = client.post(
        f"/farms/{scenario['farm_id']}/grading-events", json=_grading_payload(scenario), headers=headers
    )
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["processed_weight_kg"] == "10"
    assert len(body["outputs"]) == 1

    graded_lot_id = body["outputs"][0]["id"]
    balance_response = client.get(
        f"/farms/{scenario['farm_id']}/graded-produce-lots/{graded_lot_id}/balance", headers=headers
    )
    assert balance_response.status_code == 200
    assert balance_response.json()["available_weight_kg"] == "10"

    ledger_response = client.get(
        f"/farms/{scenario['farm_id']}/graded-produce-lots/{graded_lot_id}/ledger", headers=headers
    )
    assert ledger_response.status_code == 200
    assert len(ledger_response.json()) == 1


@pytest.mark.integration
def test_cross_tenant_api_access_returns_404(_scenario_cleanup, client, db_session, test_engine) -> None:
    scenario_a = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    scenario_b = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    _scenario_cleanup.append(scenario_a["tenant_id"])
    _scenario_cleanup.append(scenario_b["tenant_id"])
    headers_a, _ = _role_headers(db_session, tenant_id=scenario_a["tenant_id"], role_code="packing_supervisor")

    create_response = client.post(
        f"/farms/{scenario_a['farm_id']}/grading-events", json=_grading_payload(scenario_a), headers=headers_a
    )
    assert create_response.status_code == 201
    event_id = create_response.json()["id"]

    headers_b, _ = _role_headers(db_session, tenant_id=scenario_b["tenant_id"], role_code="packing_supervisor")
    response = client.get(f"/farms/{scenario_a['farm_id']}/grading-events/{event_id}", headers=headers_b)
    assert response.status_code == 404


@pytest.mark.integration
def test_farm_isolation(_scenario_cleanup, client, db_session, test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    _scenario_cleanup.append(scenario["tenant_id"])
    headers, _user = _role_headers(db_session, tenant_id=scenario["tenant_id"], role_code="packing_supervisor")

    create_response = client.post(
        f"/farms/{scenario['farm_id']}/grading-events", json=_grading_payload(scenario), headers=headers
    )
    assert create_response.status_code == 201
    event_id = create_response.json()["id"]

    from app.services import farm_service

    other_farm = farm_service.create_farm(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=None, code=f"farm-iso-{scenario['suffix']}",
        name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    db_session.commit()
    response = client.get(f"/farms/{other_farm.id}/grading-events/{event_id}", headers=headers)
    assert response.status_code == 404


@pytest.mark.integration
def test_inactive_membership_denied(_scenario_cleanup, client, db_session, test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    _scenario_cleanup.append(scenario["tenant_id"])
    headers, user = _role_headers(db_session, tenant_id=scenario["tenant_id"], role_code="packing_supervisor")

    membership = db_session.query(TenantMembership).filter_by(tenant_id=scenario["tenant_id"], user_id=user.id).one()
    membership.status = "removed"
    db_session.flush()

    response = client.get(f"/farms/{scenario['farm_id']}/grading-events", headers=headers)
    assert response.status_code == 403
