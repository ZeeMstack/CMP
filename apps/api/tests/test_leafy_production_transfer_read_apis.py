"""NURSERY-OPS-005B section 13-18/39-40: `list_available_leafy_production_
sources` (`GET /farms/{farm_id}/leafy-production/available-sources`) and
`list_available_production_plates` (`GET /farms/{farm_id}/leafy-production/
available-plates`) -- the narrow, read-only support for the Leafy
Production Transfer operator UI's source- and destination-Plate pickers.
Mirrors `test_intersalads_available_plates.py`'s exact structure/precedent
for the destination side; the source side additionally proves the
authoritative-population/restoration-lineage guarantees 005A's own unified
resolver provides (never a hand-summed reconstruction)."""

import uuid
from datetime import timedelta

import pytest

from app.services import carrier_service, carrier_specification_service, farm_service, tenant_service, transplant_correction_service, transplant_service
from app.services import leafy_production_transfer_service
from tests.test_leafy_production_transfer import (
    NURSERY_PLATE_TYPE,
    PRODUCTION_PLATE_TYPE,
    _leafy_setup,
    _nursery_plate_source_scenario,
    _production_plates,
    _simple_allocation,
    _simple_destination,
    _simple_source,
)

# =====================================================================
# Source read API
# =====================================================================


@pytest.mark.integration
def test_source_only_nursery_cultivation_plate_type_returned(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm)
    db_session.commit()

    result = leafy_production_transfer_service.list_available_leafy_production_sources(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert aids[0] in {r.source_assignment_id for r in result}
    for row in result:
        assert row.carrier.carrier_type.code == NURSERY_PLATE_TYPE


@pytest.mark.integration
def test_source_released_assignment_excluded(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)
    leafy_production_transfer_service.record_leafy_production_transfer(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=s["transfer_ready_time"] + timedelta(hours=1), note=None,
        source_lines=[_simple_source(aids[0])],
        destination_lines=[_simple_destination(plates[0].id, table_ids[0], count=200)],
        allocations=[_simple_allocation(aids[0], plates[0].id, 200)],
    )
    db_session.commit()

    result = leafy_production_transfer_service.list_available_leafy_production_sources(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert aids[0] not in {r.source_assignment_id for r in result}


@pytest.mark.integration
def test_source_zero_available_excluded(db_session, active_context_with_farm) -> None:
    """A source with a positive OPENING count but that has since been fully
    consumed by a partial-then-full sequence must never appear once its
    authoritative available count reaches zero -- proven distinctly from
    the "released" case above."""
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=100)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)
    leafy_production_transfer_service.record_leafy_production_transfer(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=s["transfer_ready_time"] + timedelta(hours=1), note=None,
        source_lines=[_simple_source(aids[0])],
        destination_lines=[_simple_destination(plates[0].id, table_ids[0], count=100)],
        allocations=[_simple_allocation(aids[0], plates[0].id, 100)],
    )
    db_session.commit()

    result = leafy_production_transfer_service.list_available_leafy_production_sources(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert aids[0] not in {r.source_assignment_id for r in result}


@pytest.mark.integration
def test_source_batch_filter(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s1, aids1 = _nursery_plate_source_scenario(db_session, tenant, user, farm, suffix="a")
    s2, aids2 = _nursery_plate_source_scenario(db_session, tenant, user, farm, suffix="b")
    db_session.commit()

    result = leafy_production_transfer_service.list_available_leafy_production_sources(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s1["batch_id"],
    )
    result_batch_ids = {r.batch_id for r in result}
    assert result_batch_ids == {s1["batch_id"]}
    assert aids2[0] not in {r.source_assignment_id for r in result}


@pytest.mark.integration
def test_source_tenant_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm)

    other_tenant = tenant_service.create_tenant(db_session, code=f"lp-other-{uuid.uuid4().hex[:8]}", name="Other")
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    db_session.commit()

    result = leafy_production_transfer_service.list_available_leafy_production_sources(
        db_session, tenant_id=other_tenant.id, farm_id=other_farm.id,
    )
    assert aids[0] not in {r.source_assignment_id for r in result}


@pytest.mark.integration
def test_source_farm_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"other-farm-{uuid.uuid4().hex[:6]}",
        name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    db_session.commit()

    result = leafy_production_transfer_service.list_available_leafy_production_sources(
        db_session, tenant_id=tenant.id, farm_id=other_farm.id,
    )
    assert aids[0] not in {r.source_assignment_id for r in result}


@pytest.mark.integration
def test_source_crop_variety_fields(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm)
    db_session.commit()

    result = leafy_production_transfer_service.list_available_leafy_production_sources(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    row = next(r for r in result if r.source_assignment_id == aids[0])
    assert row.crop.id == s["crop"].id
    assert row.variety is not None
    assert row.variety.id == s["variety"].id
    assert row.authoritative_available_count == 200


@pytest.mark.integration
def test_source_restored_current_generation_included_historical_excluded(db_session, active_context_with_farm) -> None:
    """005A restoration lineage: A exhausted -> correction restores B. Only
    B (the current, active generation) may ever appear -- A must never
    reappear even though it was once a valid source."""
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=1)
    target_event = leafy_production_transfer_service.record_leafy_production_transfer(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=s["transfer_ready_time"] + timedelta(hours=1), note=None,
        source_lines=[_simple_source(aids[0])],
        destination_lines=[_simple_destination(plates[0].id, table_ids[0], count=200)],
        allocations=[_simple_allocation(aids[0], plates[0].id, 200)],
    )
    db_session.commit()

    transplant_correction_service.correct_transplant(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        target_transplant_event_id=target_event.id, client_command_id=uuid.uuid4(), reason="test restoration",
        replacement=None,
    )
    db_session.commit()

    result = leafy_production_transfer_service.list_available_leafy_production_sources(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch_id"],
    )
    result_ids = {r.source_assignment_id for r in result}
    assert aids[0] not in result_ids
    assert len(result) == 1
    assert result[0].authoritative_available_count == 200


@pytest.mark.integration
def test_source_read_sufficient_via_http(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm)
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/leafy-production/available-sources", headers=headers)
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


@pytest.mark.integration
def test_source_role_without_transplant_read_denied_via_http(client, active_context_with_farm, db_session) -> None:
    from app.services import membership_service, user_service

    tenant, user, _headers, farm = active_context_with_farm
    storekeeper = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="lp-sources-sk", email="lp-sources-sk@example.com",
        display_name="Storekeeper",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=storekeeper.id, role_code="storekeeper", actor_user_id=None
    )
    db_session.commit()
    sk_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(storekeeper.id)}

    resp = client.get(f"/farms/{farm.id}/leafy-production/available-sources", headers=sk_headers)
    assert resp.status_code == 403, resp.text


# =====================================================================
# Destination (Production Plate) read API
# =====================================================================


def _register_production_spec(db_session, tenant, user, *, biological_position_count=200, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    return carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=PRODUCTION_PLATE_TYPE,
        code=f"PP-SPEC-{suffix}", name="200 Hole Production Plate", length_mm=600, width_mm=400, height_mm=80,
        biological_position_count=biological_position_count,
    )


def _register_production_plate(db_session, tenant, user, farm, *, spec, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    return carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code=f"PP-{suffix}", issued_date=None,
    )


@pytest.mark.integration
def test_destination_only_production_cultivation_plate_type_returned(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_production_spec(db_session, tenant, user)
    plate = _register_production_plate(db_session, tenant, user, farm, spec=spec)
    nursery_spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=NURSERY_PLATE_TYPE,
        code=f"NP-SPEC-{uuid.uuid4().hex[:8]}", name="Nursery Plate", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=200,
    )
    carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=nursery_spec.id, code=f"NP-{uuid.uuid4().hex[:8]}", issued_date=None,
    )
    db_session.commit()

    result = leafy_production_transfer_service.list_available_production_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert [r.id for r in result] == [plate.id]


@pytest.mark.integration
def test_destination_carrier_with_active_bca_excluded(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s, aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=200)
    table_ids = _leafy_setup(db_session, tenant, user, farm)
    plates, _spec = _production_plates(db_session, tenant, user, farm, count=2)
    leafy_production_transfer_service.record_leafy_production_transfer(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=s["transfer_ready_time"] + timedelta(hours=1), note=None,
        source_lines=[_simple_source(aids[0])],
        destination_lines=[_simple_destination(plates[0].id, table_ids[0], count=200)],
        allocations=[_simple_allocation(aids[0], plates[0].id, 200)],
    )
    db_session.commit()

    result = leafy_production_transfer_service.list_available_production_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    result_ids = {r.id for r in result}
    assert plates[0].id not in result_ids
    assert plates[1].id in result_ids


@pytest.mark.integration
def test_destination_tenant_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_production_spec(db_session, tenant, user)
    plate = _register_production_plate(db_session, tenant, user, farm, spec=spec)

    other_tenant = tenant_service.create_tenant(db_session, code=f"lp-other-{uuid.uuid4().hex[:8]}", name="Other")
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, code="other-farm", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_spec = _register_production_spec(db_session, other_tenant, user, suffix="other")
    other_plate = _register_production_plate(db_session, other_tenant, user, other_farm, spec=other_spec)
    db_session.commit()

    result = leafy_production_transfer_service.list_available_production_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    result_ids = {r.id for r in result}
    assert plate.id in result_ids
    assert other_plate.id not in result_ids


@pytest.mark.integration
def test_destination_farm_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_production_spec(db_session, tenant, user)
    plate = _register_production_plate(db_session, tenant, user, farm, spec=spec)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=None, code=f"other-farm-{uuid.uuid4().hex[:8]}",
        name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_plate = _register_production_plate(db_session, tenant, user, other_farm, spec=spec)
    db_session.commit()

    result = leafy_production_transfer_service.list_available_production_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    result_ids = {r.id for r in result}
    assert plate.id in result_ids
    assert other_plate.id not in result_ids


@pytest.mark.integration
def test_destination_response_exposes_capacity(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_production_spec(db_session, tenant, user, biological_position_count=175)
    plate = _register_production_plate(db_session, tenant, user, farm, spec=spec)
    db_session.commit()

    result = leafy_production_transfer_service.list_available_production_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    row = next(r for r in result if r.id == plate.id)
    assert row.specification is not None
    assert row.specification.biological_position_count == 175
    assert row.status == "active"


@pytest.mark.integration
def test_destination_read_sufficient_via_http(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    spec = _register_production_spec(db_session, tenant, user)
    _register_production_plate(db_session, tenant, user, farm, spec=spec)
    db_session.commit()

    resp = client.get(f"/farms/{farm.id}/leafy-production/available-plates", headers=headers)
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


@pytest.mark.integration
def test_destination_role_without_transplant_read_denied_via_http(client, active_context_with_farm, db_session) -> None:
    from app.services import membership_service, user_service

    tenant, user, _headers, farm = active_context_with_farm
    storekeeper = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="lp-plates-sk", email="lp-plates-sk@example.com",
        display_name="Storekeeper",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=storekeeper.id, role_code="storekeeper", actor_user_id=None
    )
    db_session.commit()
    sk_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(storekeeper.id)}

    resp = client.get(f"/farms/{farm.id}/leafy-production/available-plates", headers=sk_headers)
    assert resp.status_code == 403, resp.text
