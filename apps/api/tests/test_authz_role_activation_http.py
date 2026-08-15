"""AUTHZ-002B2 representative HTTP-level authorization proofs for the
now-ACTIVE Imperial Pilot role policy.

Unlike AUTHZ-002B1's HTTP tests (which had to monkeypatch a temporary
grant onto a real role, since no non-admin role had any active permission
yet), every test in this file uses a real, DB-approved role_code with its
genuinely active `ROLE_PERMISSIONS` grant -- no monkeypatching anywhere.
This proves the activation itself, not merely the mechanism.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.finished_goods_storage_movement import FinishedGoodsStorageMovement
from app.models.membership import TenantMembership
from app.models.observation_definition import ObservationDefinition
from app.services import (
    farm_service,
    membership_service,
    tenant_service,
    user_service,
)
from tests._dispatch_scenario import pack_one
from tests._packing_scenario import build_committed_scenario, cleanup_scenario
from tests._storage_scenario import create_cold_store, create_cold_store_position
from tests.test_observation import _build_scenario as _build_observation_scenario


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture
def _scenario_cleanup(test_engine):
    """Registers `cleanup_scenario` to run AFTER `db_session`'s own
    transaction has rolled back. `build_committed_scenario` commits
    directly via `test_engine`, but each test's HTTP-auth role membership
    row is inserted through `db_session`'s still-open outer transaction
    (so the same request-scoped session used by `client` can see it) --
    that open transaction holds a lock on the scenario's tenant row
    (acquired implicitly by the FK reference from the membership insert)
    until it ends. Running `cleanup_scenario`'s `DELETE FROM tenants`
    while that lock is still held (e.g. in the test's own `finally`,
    before `db_session` tears down) is a lock-wait hang, not a test
    failure -- this fixture must be listed BEFORE `client`/`db_session` in
    each test's signature so pytest tears it down LAST, after that
    transaction has already rolled back and released the lock."""
    tenant_ids: list[uuid.UUID] = []
    yield tenant_ids
    for tenant_id in tenant_ids:
        cleanup_scenario(test_engine, tenant_id)


def _role_headers(db_session, *, tenant_id, role_code: str) -> dict[str, str]:
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"b2-role-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Role Activation Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}


def _observation_definition_payload(code: str) -> dict:
    return {
        "code": code, "name": "Leaf color score", "description": None,
        "value_type": "decimal", "unit": None, "target_scope": "either",
        "min_value": None, "max_value": None,
    }


def _observation_entry_payload(assignment_id) -> dict:
    return {
        "client_command_id": str(uuid.uuid4()),
        "effective_time": _now().isoformat(),
        "note": None,
        "values": [],
        "germination_checks": [
            {
                "batch_carrier_assignment_id": str(assignment_id),
                "inspected_site_count": 200,
                "normal_germinated_site_count": 180,
                "abnormal_germinated_site_count": 10,
                "failed_site_count": 10,
                "note": None,
            }
        ],
    }


# --- head_grower --------------------------------------------------------------


@pytest.mark.integration
def test_head_grower_can_mutate_master_data_and_define_observations(
    client, db_session, active_context_with_farm
) -> None:
    tenant, _user, _admin_headers, _farm = active_context_with_farm
    headers = _role_headers(db_session, tenant_id=tenant.id, role_code="head_grower")

    crop_response = client.post("/crops", json={
        "code": f"HG-{uuid.uuid4().hex[:8]}", "common_name": "Lettuce", "scientific_name": None,
        "crop_category": "leafy_green",
    }, headers=headers)
    assert crop_response.status_code == 201

    definition_response = client.post(
        "/observation-definitions", json=_observation_definition_payload(f"DEF-HG-{uuid.uuid4().hex[:8]}"),
        headers=headers,
    )
    assert definition_response.status_code == 201


# --- production_supervisor -----------------------------------------------------


@pytest.mark.integration
def test_production_supervisor_can_record_observation_but_not_define(
    client, db_session, active_context_with_farm
) -> None:
    tenant, user, _admin_headers, farm = active_context_with_farm
    scenario = _build_observation_scenario(db_session, tenant, user, farm)
    headers = _role_headers(db_session, tenant_id=tenant.id, role_code="production_supervisor")

    entry_response = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/observations",
        json=_observation_entry_payload(scenario["assignment_ids"][0]),
        headers=headers,
    )
    assert entry_response.status_code == 201

    denied_code = f"DEF-PS-{uuid.uuid4().hex[:8]}"
    definitions_before = db_session.scalar(
        select(func.count()).select_from(ObservationDefinition).where(ObservationDefinition.tenant_id == tenant.id)
    )
    audit_before = db_session.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id, AuditEvent.entity_type == "observation_definition"
        )
    )

    definition_response = client.post(
        "/observation-definitions", json=_observation_definition_payload(denied_code), headers=headers,
    )
    assert definition_response.status_code == 403

    # AUTHZ-002B2 ticket section 15: a production-configuration denial must
    # have zero business side effect, not merely a 403 status code.
    assert (
        db_session.scalar(
            select(func.count()).select_from(ObservationDefinition).where(
                ObservationDefinition.tenant_id == tenant.id
            )
        )
        == definitions_before
    )
    assert db_session.scalar(select(ObservationDefinition).where(ObservationDefinition.code == denied_code)) is None
    assert (
        db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.tenant_id == tenant.id, AuditEvent.entity_type == "observation_definition"
            )
        )
        == audit_before
    )


# --- operator --------------------------------------------------------------------


@pytest.mark.integration
def test_operator_can_execute_routine_mutations_but_not_configuration(
    client, db_session, active_context_with_farm, placed_trolley_and_tray
) -> None:
    tenant, user, _admin_headers, farm = active_context_with_farm
    scenario = _build_observation_scenario(db_session, tenant, user, farm)
    headers = _role_headers(db_session, tenant_id=tenant.id, role_code="operator")

    # One approved routine operational mutation: relocate the trolley.
    movement_response = client.post(f"/farms/{farm.id}/movements", json={
        "client_command_id": str(uuid.uuid4()),
        "effective_time": _now().isoformat(),
        "occupant": {"kind": "asset", "id": str(placed_trolley_and_tray["trolley"].id)},
        "destination": {"kind": "location", "id": str(placed_trolley_and_tray["chambers"]["GC-02"].id)},
        "reason": None,
    }, headers=headers)
    assert movement_response.status_code == 201

    entry_response = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/observations",
        json=_observation_entry_payload(scenario["assignment_ids"][0]),
        headers=headers,
    )
    assert entry_response.status_code == 201

    crop_response = client.post("/crops", json={
        "code": f"OP-{uuid.uuid4().hex[:8]}", "common_name": "Lettuce", "scientific_name": None,
        "crop_category": "leafy_green",
    }, headers=headers)
    assert crop_response.status_code == 403


# --- qc_officer ------------------------------------------------------------------


@pytest.mark.integration
def test_qc_officer_can_record_observation_and_place_hold_but_not_recall(
    client, db_session, active_context_with_farm
) -> None:
    tenant, user, _admin_headers, farm = active_context_with_farm
    scenario = _build_observation_scenario(db_session, tenant, user, farm)
    headers = _role_headers(db_session, tenant_id=tenant.id, role_code="qc_officer")

    entry_response = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/observations",
        json=_observation_entry_payload(scenario["assignment_ids"][0]),
        headers=headers,
    )
    assert entry_response.status_code == 201

    hold_response = client.post(
        f"/farms/{farm.id}/crop-batches/{scenario['batch'].id}/quality-holds",
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now().isoformat(),
            "source_observation_event_id": None, "reason_code": "PEST_SIGHTING",
            "reason_text": "Aphids observed on tray 2.",
        },
        headers=headers,
    )
    assert hold_response.status_code == 201

    recall_response = client.post(f"/farms/{farm.id}/recall-cases", json={
        "client_command_id": str(uuid.uuid4()), "effective_time": _now().isoformat(),
        "code": f"RC-{uuid.uuid4().hex[:8]}", "crop_batch_id": str(scenario["batch"].id),
        "harvested_produce_lot_id": None, "finished_goods_lot_id": None,
        "reason_code": "CONTAMINATION", "reason_text": "Precautionary.",
    }, headers=headers)
    assert recall_response.status_code == 403


# --- packing_supervisor / cold_store_supervisor / dispatch_officer --------------


@pytest.mark.integration
def test_packing_supervisor_can_pack_but_not_manage_storage(_scenario_cleanup, client, db_session, test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None, lot_b_count=None)
    _scenario_cleanup.append(scenario["tenant_id"])
    headers = _role_headers(db_session, tenant_id=scenario["tenant_id"], role_code="packing_supervisor")

    pack_response = client.post(f"/farms/{scenario['farm_id']}/packing-events", json={
        "client_command_id": str(uuid.uuid4()), "effective_time": _now().isoformat(),
        "finished_goods_lot_code": f"FG-PK-{scenario['suffix']}", "package_count": 5,
        "packed_output_weight_kg": "4.000", "process_loss_weight_kg": "0",
        "rejected_weight_kg": "0", "note": None,
        "input_lines": [{
            "harvested_produce_lot_id": str(scenario["lot_a_id"]), "consumed_weight_kg": "4.000",
            "consumed_whole_unit_count": None, "note": None,
        }],
    }, headers=headers)
    assert pack_response.status_code == 201
    fg_lot_id = pack_response.json()["finished_goods_lot"]["id"]

    movements_before = db_session.scalar(
        select(func.count()).select_from(FinishedGoodsStorageMovement).where(
            FinishedGoodsStorageMovement.tenant_id == scenario["tenant_id"]
        )
    )
    audit_before = db_session.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.tenant_id == scenario["tenant_id"],
            AuditEvent.entity_type == "finished_goods_storage_movement",
        )
    )

    storage_response = client.post(f"/farms/{scenario['farm_id']}/finished-goods-storage-movements", json={
        "client_command_id": str(uuid.uuid4()), "effective_time": _now().isoformat(),
        "finished_goods_lot_id": fg_lot_id, "movement_kind": "place",
        "source_location_id": None, "destination_location_id": str(uuid.uuid4()),
        "moved_weight_kg": "1.000", "moved_package_count": 1,
    }, headers=headers)
    assert storage_response.status_code == 403

    # AUTHZ-002B2 ticket section 15: a logistics cross-stage denial
    # (packing_supervisor attempting finished_goods_storage.manage)
    # must have zero business side effect.
    assert (
        db_session.scalar(
            select(func.count()).select_from(FinishedGoodsStorageMovement).where(
                FinishedGoodsStorageMovement.tenant_id == scenario["tenant_id"]
            )
        )
        == movements_before
    )
    assert (
        db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.tenant_id == scenario["tenant_id"],
                AuditEvent.entity_type == "finished_goods_storage_movement",
            )
        )
        == audit_before
    )


@pytest.mark.integration
def test_cold_store_supervisor_can_manage_storage_but_not_dispatch(
    _scenario_cleanup, client, db_session, test_engine
) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None, lot_b_count=None)
    _scenario_cleanup.append(scenario["tenant_id"])
    fg_lot_id, _event_id = pack_one(scenario, db_session, lot_key="lot_a_id", code_suffix="-CS")
    cold_store = create_cold_store(scenario, db_session, code_suffix="-CS")
    position = create_cold_store_position(scenario, db_session, cold_store_id=cold_store.id, code_suffix="-CS")

    headers = _role_headers(db_session, tenant_id=scenario["tenant_id"], role_code="cold_store_supervisor")

    storage_response = client.post(f"/farms/{scenario['farm_id']}/finished-goods-storage-movements", json={
        "client_command_id": str(uuid.uuid4()), "effective_time": _now().isoformat(),
        "finished_goods_lot_id": str(fg_lot_id), "movement_kind": "place",
        "source_location_id": None, "destination_location_id": str(position.id),
        "moved_weight_kg": "2.000", "moved_package_count": 2,
    }, headers=headers)
    assert storage_response.status_code == 201

    dispatch_response = client.post(f"/farms/{scenario['farm_id']}/dispatches", json={
        "client_command_id": str(uuid.uuid4()), "effective_time": _now().isoformat(),
        "code": f"DS-{uuid.uuid4().hex[:8]}", "external_reference": None, "note": None,
        "lines": [{
            "finished_goods_lot_id": str(fg_lot_id), "dispatched_weight_kg": "1.000",
            "dispatched_package_count": 1,
        }],
    }, headers=headers)
    assert dispatch_response.status_code == 403


@pytest.mark.integration
def test_dispatch_officer_can_dispatch_but_not_pack(_scenario_cleanup, client, db_session, test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None, lot_b_count=None)
    _scenario_cleanup.append(scenario["tenant_id"])
    # A separate lot (lot_b, default weight 5.000kg), left unplaced, so
    # dispatch can consume it (dispatch draws from unplaced quantity only).
    fg_lot_id, _event_id = pack_one(
        scenario, db_session, lot_key="lot_b_id", code_suffix="-DO", packed_output_weight_kg=Decimal("4.000")
    )

    headers = _role_headers(db_session, tenant_id=scenario["tenant_id"], role_code="dispatch_officer")

    dispatch_response = client.post(f"/farms/{scenario['farm_id']}/dispatches", json={
        "client_command_id": str(uuid.uuid4()), "effective_time": _now().isoformat(),
        "code": f"DS-{uuid.uuid4().hex[:8]}", "external_reference": None, "note": None,
        "lines": [{
            "finished_goods_lot_id": str(fg_lot_id), "dispatched_weight_kg": "1.000",
            "dispatched_package_count": 1,
        }],
    }, headers=headers)
    assert dispatch_response.status_code == 201

    pack_response = client.post(f"/farms/{scenario['farm_id']}/packing-events", json={
        "client_command_id": str(uuid.uuid4()), "effective_time": _now().isoformat(),
        "finished_goods_lot_code": f"FG-DO-{scenario['suffix']}", "package_count": 5,
        "packed_output_weight_kg": "1.000", "process_loss_weight_kg": "0",
        "rejected_weight_kg": "0", "note": None,
        "input_lines": [{
            "harvested_produce_lot_id": str(scenario["lot_a_id"]), "consumed_weight_kg": "1.000",
            "consumed_whole_unit_count": None, "note": None,
        }],
    }, headers=headers)
    assert pack_response.status_code == 403


# --- read_only / auditor ----------------------------------------------------------


@pytest.mark.integration
def test_read_only_can_read_but_not_mutate(client, db_session, active_context_with_farm) -> None:
    tenant, _user, _admin_headers, farm = active_context_with_farm
    headers = _role_headers(db_session, tenant_id=tenant.id, role_code="read_only")

    assert client.get(f"/farms/{farm.id}/crop-batches", headers=headers).status_code == 200
    assert client.post("/crops", json={
        "code": f"RO-{uuid.uuid4().hex[:8]}", "common_name": "Lettuce", "scientific_name": None,
        "crop_category": "leafy_green",
    }, headers=headers).status_code == 403


@pytest.mark.integration
def test_auditor_can_read_but_not_mutate(client, db_session, active_context_with_farm) -> None:
    tenant, _user, _admin_headers, farm = active_context_with_farm
    headers = _role_headers(db_session, tenant_id=tenant.id, role_code="auditor")

    assert client.get(f"/farms/{farm.id}/crop-batches", headers=headers).status_code == 200
    assert client.post("/crops", json={
        "code": f"AU-{uuid.uuid4().hex[:8]}", "common_name": "Lettuce", "scientific_name": None,
        "crop_category": "leafy_green",
    }, headers=headers).status_code == 403


# --- farm_manager (minimum policy) ------------------------------------------------


@pytest.mark.integration
def test_farm_manager_minimum_policy(client, db_session, active_context_with_farm) -> None:
    tenant, _user, _admin_headers, farm = active_context_with_farm
    headers = _role_headers(db_session, tenant_id=tenant.id, role_code="farm_manager")

    location_response = client.post(f"/farms/{farm.id}/locations", json={
        "location_type_code": "greenhouse", "code": f"FM-{uuid.uuid4().hex[:8]}", "name": "FM Greenhouse",
        "parent_location_id": None, "greenhouse_classification": "leafy_greens", "occupiable": None,
    }, headers=headers)
    assert location_response.status_code == 201

    denied_user_id = str(uuid.uuid4())
    memberships_before = db_session.scalar(
        select(func.count()).select_from(TenantMembership).where(TenantMembership.tenant_id == tenant.id)
    )
    audit_before = db_session.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id, AuditEvent.entity_type == "tenant_membership"
        )
    )

    membership_response = client.post("/memberships", json={
        "user_id": denied_user_id, "role_code": "operator",
    }, headers=headers)
    assert membership_response.status_code == 403

    # AUTHZ-002B2 ticket section 15: a tenant-membership administration
    # denial (farm_manager attempting tenant.members.manage) must have
    # zero business side effect.
    assert (
        db_session.scalar(
            select(func.count()).select_from(TenantMembership).where(TenantMembership.tenant_id == tenant.id)
        )
        == memberships_before
    )
    assert (
        db_session.scalar(select(TenantMembership).where(TenantMembership.user_id == denied_user_id)) is None
    )
    assert (
        db_session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.tenant_id == tenant.id, AuditEvent.entity_type == "tenant_membership"
            )
        )
        == audit_before
    )

    dispatch_response = client.post(f"/farms/{farm.id}/dispatches", json={
        "client_command_id": str(uuid.uuid4()), "effective_time": _now().isoformat(),
        "code": f"DS-{uuid.uuid4().hex[:8]}", "external_reference": None, "note": None,
        "lines": [{
            "finished_goods_lot_id": str(uuid.uuid4()), "dispatched_weight_kg": "1.000",
            "dispatched_package_count": 1,
        }],
    }, headers=headers)
    assert dispatch_response.status_code == 403


# --- tenant-specific role proof (ticket section 14) -------------------------------


@pytest.mark.integration
def test_same_user_farm_manager_in_one_tenant_read_only_in_another(
    client, db_session, active_context_with_farm
) -> None:
    """One CMP user, two ACTIVE memberships with genuinely different
    roles: farm_manager in Tenant A, read_only in Tenant B. A management
    mutation (LOCATION_MANAGE) must succeed in A and be denied in B for
    the identical action -- proving the role evaluated is always the
    ACTIVE membership's role_code for the tenant selected by the request
    header, never a role held elsewhere or cached across requests. Then
    the reverse: an allowed read (CROP_BATCH_READ, which both roles hold)
    must succeed in BOTH tenants, confirming tenant context -- not just
    role -- is independently respected on every request."""
    tenant_a, _admin_user, _admin_headers, farm_a = active_context_with_farm
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"b2-tenant-specific-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Tenant Specific Role User",
    )

    tenant_b = tenant_service.create_tenant(db_session, code=f"t-b2-b-{uuid.uuid4().hex[:8]}", name="B2 Tenant B")
    farm_b = farm_service.create_farm(
        db_session, tenant_id=tenant_b.id, actor_user_id=None, code="b2-farm-b", name="B2 Farm B",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_a.id, user_id=user.id, role_code="farm_manager", actor_user_id=None
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user.id, role_code="read_only", actor_user_id=None
    )
    headers_a = {"X-Dev-Tenant-Id": str(tenant_a.id), "X-Dev-User-Id": str(user.id)}
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user.id)}

    location_payload_a = {
        "location_type_code": "greenhouse", "code": f"B2-A-{uuid.uuid4().hex[:8]}", "name": "B2 Tenant A Greenhouse",
        "parent_location_id": None, "greenhouse_classification": "leafy_greens", "occupiable": None,
    }
    assert client.post(f"/farms/{farm_a.id}/locations", json=location_payload_a, headers=headers_a).status_code == 201

    location_payload_b = {
        "location_type_code": "greenhouse", "code": f"B2-B-{uuid.uuid4().hex[:8]}", "name": "B2 Tenant B Greenhouse",
        "parent_location_id": None, "greenhouse_classification": "leafy_greens", "occupiable": None,
    }
    assert client.post(f"/farms/{farm_b.id}/locations", json=location_payload_b, headers=headers_b).status_code == 403

    # Reverse: a read both roles hold succeeds independently in each tenant.
    assert client.get(f"/farms/{farm_a.id}/crop-batches", headers=headers_a).status_code == 200
    assert client.get(f"/farms/{farm_b.id}/crop-batches", headers=headers_b).status_code == 200
