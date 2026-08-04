"""Core CMP-010 acceptance flow: farm -> crop/variety/workflow -> active
batch -> sow four seed-tray carriers -> generic observation definition ->
one observation event with generic values and four germination checks ->
sowing quantities and occupancy/movement counts unchanged -> derived (not
stored) germination percentage -> quality hold referencing the observation
-> blocked stage progression -> idempotent hold retry -> a second
independent hold -> partial release still blocks -> full release unblocks
-> successful progression -> idempotent observation and release retries
after progression -> no duplicate records -> rejected cross-tenant access.
All via the API."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.batch_stage_transition import BatchStageTransition
from app.models.germination_check import GerminationCheck
from app.models.movement import Movement
from app.models.observation_event import ObservationEvent
from app.models.observation_value import ObservationValue
from app.models.occupancy import Occupancy
from app.models.quality_hold import QualityHold
from app.models.quality_hold_release import QualityHoldRelease
from app.models.sowing_event_line import SowingEventLine


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.mark.integration
def test_core_observation_quality_acceptance_flow(client, active_context, db_session) -> None:
    _tenant, _user, headers = active_context

    # 1. Create an active farm, crop, variety, workflow, and active batch.
    farm = client.post(
        "/farms", headers=headers,
        json={"code": "obsq-farm", "name": "Observation Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    ).json()
    farm_id = farm["id"]
    crop = client.post(
        "/crops", headers=headers,
        json={"code": "iceberg-obsq", "common_name": "Iceberg Lettuce", "crop_category": "leafy_green"},
    ).json()
    variety = client.post(
        f"/crops/{crop['id']}/varieties", headers=headers, json={"code": "mamutik-obsq", "name": "Mamutik RZ"}
    ).json()
    production_system = client.post(
        "/production-systems", headers=headers, json={"code": "obsq-ps", "name": "Nursery Tray"}
    ).json()
    workflow = client.post(
        "/workflows", headers=headers,
        json={
            "crop_id": crop["id"], "variety_id": variety["id"], "production_system_id": production_system["id"],
            "code": "obsq-workflow", "name": "Iceberg Nursery",
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
    germination_stage = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={
            "code": "GERMINATION", "name": "Germination", "display_order": 1, "stage_category": "germination",
            "is_start": False, "is_terminal": False,
        },
    ).json()
    complete_stage = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={
            "code": "COMPLETE", "name": "Complete", "display_order": 2, "stage_category": "completed",
            "is_start": False, "is_terminal": True,
        },
    ).json()
    transition_1 = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
        json={
            "from_stage_id": seeding_stage["id"], "to_stage_id": germination_stage["id"],
            "code": "ADVANCE-1", "name": "Advance to Germination",
        },
    ).json()
    client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
        json={
            "from_stage_id": germination_stage["id"], "to_stage_id": complete_stage["id"],
            "code": "ADVANCE-2", "name": "Advance to Complete",
        },
    )
    client.post(f"/workflows/{workflow['id']}/versions/{version['id']}/publish", headers=headers)
    batch = client.post(
        f"/farms/{farm_id}/crop-batches", headers=headers,
        json={
            "code": "ICE-OBSQ-0001", "workflow_id": workflow["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    ).json()

    # 2. Register and sow four seed-tray carriers.
    seed_lot = client.post(
        f"/farms/{farm_id}/seed-lots", headers=headers,
        json={"crop_id": crop["id"], "variety_id": variety["id"], "code": "LOT-OBSQ-0001"},
    ).json()
    carriers = [
        client.post(
            f"/farms/{farm_id}/carriers", headers=headers,
            json={"carrier_type_code": "seed_tray", "code": f"ST-OBSQ-{n:04d}"},
        ).json()
        for n in range(1, 5)
    ]
    sow_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/sowings", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "lines": [
                {"carrier_id": c["id"], "seed_lot_id": seed_lot["id"], "sown_site_count": 200, "seed_count": 200}
                for c in carriers
            ],
        },
    )
    assert sow_resp.status_code == 201
    carrier_assignments = client.get(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/carriers", headers=headers
    ).json()
    assignment_by_carrier_code = {a["carrier"]["code"]: a["id"] for a in carrier_assignments}
    assignment_ids = [assignment_by_carrier_code[c["code"]] for c in carriers]

    occupancy_before = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    movement_before = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()

    # 3. Create at least one ordinary observation definition.
    definition = client.post(
        "/observation-definitions", headers=headers,
        json={"code": "TRAY-TEMP", "name": "Tray Temperature", "value_type": "decimal", "target_scope": "either"},
    ).json()

    # 4. Record one observation event with generic values and four germination checks.
    observation_command_id = str(uuid.uuid4())
    observation_effective_time = _now_iso()
    observation_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/observations", headers=headers,
        json={
            "client_command_id": observation_command_id, "effective_time": observation_effective_time,
            "values": [{"observation_definition_id": definition["id"], "value_decimal": "21.5"}],
            "germination_checks": [
                {
                    "batch_carrier_assignment_id": aid, "inspected_site_count": 200,
                    "normal_germinated_site_count": 180, "abnormal_germinated_site_count": 10,
                    "failed_site_count": 5,
                }
                for aid in assignment_ids
            ],
        },
    )
    assert observation_resp.status_code == 201
    observation_event = observation_resp.json()
    assert len(observation_event["germination_checks"]) == 4

    # 5. Confirm original CMP-009 sowing quantities remain unchanged.
    sowing_lines = db_session.execute(
        select(SowingEventLine).where(SowingEventLine.batch_carrier_assignment_id.in_(assignment_ids))
    ).scalars().all()
    assert len(sowing_lines) == 4
    assert all(line.sown_site_count == 200 and line.seed_count == 200 for line in sowing_lines)

    # 6. Confirm no occupancy or movement records change.
    occupancy_after = db_session.execute(select(func.count()).select_from(Occupancy)).scalar_one()
    movement_after = db_session.execute(select(func.count()).select_from(Movement)).scalar_one()
    assert occupancy_after == occupancy_before
    assert movement_after == movement_before

    # 7. Confirm germination percentages are derived (not a stored column —
    # test_germination_check.py separately proves the column doesn't exist).
    for check in observation_event["germination_checks"]:
        assert float(check["germination_percentage"]) == 95.0

    # 8. Place a quality hold referencing the observation event.
    hold_command_id = str(uuid.uuid4())
    hold_effective_time = _now_iso()
    hold_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/quality-holds", headers=headers,
        json={
            "client_command_id": hold_command_id, "effective_time": hold_effective_time,
            "source_observation_event_id": observation_event["id"], "reason_code": "low-germination",
            "reason_text": "Germination check flagged low viability",
        },
    )
    assert hold_resp.status_code == 201
    hold = hold_resp.json()
    assert hold["is_open"] is True

    # 9. Attempt stage progression and reject it.
    blocked_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": transition_1["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    assert blocked_resp.status_code == 409

    # 10. Confirm no transition, stage-run change, or audit event was created.
    transitions_count = db_session.execute(
        select(func.count()).select_from(BatchStageTransition).where(
            BatchStageTransition.batch_id == uuid.UUID(batch["id"]),
            BatchStageTransition.command_kind == "stage_transition",
        )
    ).scalar_one()
    assert transitions_count == 0
    current_stage = client.get(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/current-stage", headers=headers
    ).json()
    assert current_stage["current_stage"]["code"] == "SEEDING"
    stage_transitioned_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.stage_transitioned", AuditEvent.entity_id == uuid.UUID(batch["id"])
        )
    ).scalar_one()
    assert stage_transitioned_count == 0

    # 11. Retry the hold command and return the original hold.
    hold_retry_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/quality-holds", headers=headers,
        json={
            "client_command_id": hold_command_id, "effective_time": hold_effective_time,
            "source_observation_event_id": observation_event["id"], "reason_code": "low-germination",
            "reason_text": "Germination check flagged low viability",
        },
    )
    assert hold_retry_resp.status_code == 201
    assert hold_retry_resp.json()["id"] == hold["id"]

    # 12. Place a second independent hold.
    second_hold_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/quality-holds", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "reason_code": "manual-check",
            "reason_text": "Manual visual inspection pending",
        },
    )
    assert second_hold_resp.status_code == 201
    second_hold = second_hold_resp.json()

    # 13. Release only the first hold.
    first_release_command_id = str(uuid.uuid4())
    first_release_effective_time = _now_iso()
    first_release_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/quality-holds/{hold['id']}/release", headers=headers,
        json={
            "client_command_id": first_release_command_id, "effective_time": first_release_effective_time,
            "release_reason": "Reinspected and passed",
        },
    )
    assert first_release_resp.status_code == 201
    assert first_release_resp.json()["is_open"] is False

    # 14. Confirm progression remains blocked (second hold still open).
    still_blocked_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": transition_1["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    assert still_blocked_resp.status_code == 409

    # 15. Release the second hold.
    second_release_command_id = str(uuid.uuid4())
    second_release_effective_time = _now_iso()
    second_release_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/quality-holds/{second_hold['id']}/release", headers=headers,
        json={
            "client_command_id": second_release_command_id, "effective_time": second_release_effective_time,
            "release_reason": "Visual inspection passed",
        },
    )
    assert second_release_resp.status_code == 201
    assert second_release_resp.json()["is_open"] is False

    # 16. Progress the batch successfully.
    progress_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/stage-transitions", headers=headers,
        json={
            "configured_transition_id": transition_1["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    assert progress_resp.status_code == 201
    current_stage_after = client.get(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/current-stage", headers=headers
    ).json()
    assert current_stage_after["current_stage"]["code"] == "GERMINATION"

    # 17. Retry the original observation command after progression.
    observation_retry_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/observations", headers=headers,
        json={
            "client_command_id": observation_command_id, "effective_time": observation_effective_time,
            "values": [{"observation_definition_id": definition["id"], "value_decimal": "21.5"}],
            "germination_checks": [
                {
                    "batch_carrier_assignment_id": aid, "inspected_site_count": 200,
                    "normal_germinated_site_count": 180, "abnormal_germinated_site_count": 10,
                    "failed_site_count": 5,
                }
                for aid in assignment_ids
            ],
        },
    )
    assert observation_retry_resp.status_code == 201
    assert observation_retry_resp.json()["id"] == observation_event["id"]

    # 18. Retry both hold-release commands and return the original releases.
    first_release_retry_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/quality-holds/{hold['id']}/release", headers=headers,
        json={
            "client_command_id": first_release_command_id, "effective_time": first_release_effective_time,
            "release_reason": "Reinspected and passed",
        },
    )
    assert first_release_retry_resp.status_code == 201
    second_release_retry_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/quality-holds/{second_hold['id']}/release", headers=headers,
        json={
            "client_command_id": second_release_command_id, "effective_time": second_release_effective_time,
            "release_reason": "Visual inspection passed",
        },
    )
    assert second_release_retry_resp.status_code == 201

    # 19. Confirm no duplicate observation, hold, release, transition, value, germination, or audit records.
    assert db_session.execute(select(func.count()).select_from(ObservationEvent)).scalar_one() == 1
    assert db_session.execute(select(func.count()).select_from(ObservationValue)).scalar_one() == 1
    assert db_session.execute(select(func.count()).select_from(GerminationCheck)).scalar_one() == 4
    assert db_session.execute(select(func.count()).select_from(QualityHold)).scalar_one() == 2
    assert db_session.execute(select(func.count()).select_from(QualityHoldRelease)).scalar_one() == 2
    assert db_session.execute(
        select(func.count()).select_from(BatchStageTransition).where(
            BatchStageTransition.command_kind == "stage_transition"
        )
    ).scalar_one() == 1
    assert db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "crop_batch.observation_recorded")
    ).scalar_one() == 1
    assert db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "crop_batch.quality_hold_placed")
    ).scalar_one() == 2
    assert db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "crop_batch.quality_hold_released")
    ).scalar_one() == 2

    # 20. Reject cross-tenant access.
    from app.services import membership_service, tenant_service, user_service

    tenant_b = tenant_service.create_tenant(db_session, code="obsq-acceptance-tenant-b", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="obsq-acceptance-b", email="obsqaccb@example.com",
        display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    cross_tenant_resp = client.get(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/observations/{observation_event['id']}", headers=headers_b
    )
    assert cross_tenant_resp.status_code == 404
