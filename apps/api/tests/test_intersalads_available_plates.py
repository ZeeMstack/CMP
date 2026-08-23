"""NURSERY-OPS-004B.2 section 13/36: `list_available_intersalads_plates` --
the narrow, read-only support for the InterSalads Transplant operator UI's
destination-Plate picker (`GET /farms/{farm_id}/nursery/intersalads/
available-plates`). Not a generic Carrier-availability framework -- only
`nursery_cultivation_plate` eligibility, mirroring the exact eligibility
`transplant_service._record_transplant_core` itself enforces
(`carrier.status == "active"`, no currently-active
`BatchCarrierAssignment`)."""

import uuid
from datetime import timedelta

import pytest

from app.services import carrier_service, carrier_specification_service, farm_service, tenant_service
from app.services import intersalads_transplant_service
from tests.test_intersalads_transplant import _build_scenario, _simple_allocation, _simple_destination, _simple_source

DESTINATION_TYPE = "nursery_cultivation_plate"


def _register_plate(db_session, tenant, user, farm, *, spec, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    return carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code=f"NCP-{suffix}", issued_date=None,
    )


def _register_spec(db_session, tenant, user, *, biological_position_count=200, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    return carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=DESTINATION_TYPE,
        code=f"SPEC-{suffix}", name="200 Hole Nursery Plate", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=biological_position_count,
    )


@pytest.mark.integration
def test_only_nursery_cultivation_plate_type_returned(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    plate = _register_plate(db_session, tenant, user, farm, spec=spec)
    # A different carrier type (seed_tray) must never appear in the result.
    seed_tray_spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="seed_tray",
        code=f"ST-SPEC-{uuid.uuid4().hex[:8]}", name="Standard Tray", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=200,
    )
    carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code=f"ST-{uuid.uuid4().hex[:8]}", issued_date=None,
    )
    db_session.commit()

    result = intersalads_transplant_service.list_available_intersalads_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert [r.id for r in result] == [plate.id]


@pytest.mark.integration
def test_free_plate_included(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    plate = _register_plate(db_session, tenant, user, farm, spec=spec)
    db_session.commit()

    result = intersalads_transplant_service.list_available_intersalads_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert plate.id in {r.id for r in result}


@pytest.mark.integration
def test_carrier_with_active_batch_carrier_assignment_excluded(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, _spec = _build_scenario(db_session, tenant, user, farm, tray_count=1)
    db_session.commit()
    plate = s["destination_carriers"][0]
    still_free_plate = s["destination_carriers"][1]
    aid = s["source_assignment_ids"][0]
    table_id = s["intersalads_table_ids"][0]

    intersalads_transplant_service.record_intersalads_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
        source_lines=[_simple_source(aid)],
        destination_lines=[_simple_destination(plate.id, table_id, count=150)],
        allocations=[_simple_allocation(aid, plate.id, count=150)],
    )
    db_session.commit()

    result = intersalads_transplant_service.list_available_intersalads_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    result_ids = {r.id for r in result}
    assert plate.id not in result_ids
    assert still_free_plate.id in result_ids


@pytest.mark.integration
def test_tenant_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    plate = _register_plate(db_session, tenant, user, farm, spec=spec)

    other_tenant = tenant_service.create_tenant(db_session, code=f"isalads-other-{uuid.uuid4().hex[:8]}", name="Other Tenant")
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_spec = _register_spec(db_session, other_tenant, user, suffix="other")
    other_plate = _register_plate(db_session, other_tenant, user, other_farm, spec=other_spec)
    db_session.commit()

    result = intersalads_transplant_service.list_available_intersalads_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    result_ids = {r.id for r in result}
    assert plate.id in result_ids
    assert other_plate.id not in result_ids


@pytest.mark.integration
def test_farm_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    plate = _register_plate(db_session, tenant, user, farm, spec=spec)

    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=None, code=f"other-farm-{uuid.uuid4().hex[:8]}",
        name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_plate = _register_plate(db_session, tenant, user, other_farm, spec=spec)
    db_session.commit()

    result = intersalads_transplant_service.list_available_intersalads_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    result_ids = {r.id for r in result}
    assert plate.id in result_ids
    assert other_plate.id not in result_ids


@pytest.mark.integration
def test_inactive_carrier_status_excluded(db_session, active_context_with_farm) -> None:
    """Mirrors the exact eligibility `transplant_service._record_transplant_
    core` itself enforces (`carrier.status != "active"` is rejected) --
    reproduced here read-only."""
    from sqlalchemy import text

    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    plate = _register_plate(db_session, tenant, user, farm, spec=spec)
    db_session.execute(
        text("UPDATE carriers SET status = 'retired', retired_date = CURRENT_DATE WHERE id = :cid"),
        {"cid": plate.id},
    )
    db_session.commit()

    result = intersalads_transplant_service.list_available_intersalads_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert plate.id not in {r.id for r in result}


@pytest.mark.integration
def test_response_exposes_biological_position_count(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user, biological_position_count=175)
    plate = _register_plate(db_session, tenant, user, farm, spec=spec)
    db_session.commit()

    result = intersalads_transplant_service.list_available_intersalads_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    row = next(r for r in result if r.id == plate.id)
    assert row.specification is not None
    assert row.specification.biological_position_count == 175
    assert row.specification.code == spec.code
    assert row.status == "active"


@pytest.mark.integration
def test_transplant_read_sufficient_via_http(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    _register_plate(db_session, tenant, user, farm, spec=spec)
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/nursery/intersalads/available-plates", headers=headers)
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


@pytest.mark.integration
def test_role_without_transplant_read_denied_via_http(client, active_context_with_farm, db_session) -> None:
    from app.services import membership_service, user_service

    tenant, user, _headers, farm = active_context_with_farm
    storekeeper = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="isalads-plates-sk", email="isalads-plates-sk@example.com",
        display_name="Storekeeper",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=storekeeper.id, role_code="storekeeper", actor_user_id=None
    )
    db_session.commit()
    sk_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(storekeeper.id)}

    resp = client.get(f"/farms/{farm.id}/nursery/intersalads/available-plates", headers=sk_headers)
    assert resp.status_code == 403, resp.text
