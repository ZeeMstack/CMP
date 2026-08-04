import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.schemas.crop_batch import CropBatchCreate
from app.services import crop_batch_service, crop_service, production_system_service, workflow_service
from app.services.errors import (
    BatchCommandReusedWithDifferentPayloadError,
    BatchCreationValidationError,
    DuplicateBatchCodeError,
    InvalidBatchEffectiveTimeError,
    WorkflowHasNoPublishedVersionError,
    WorkflowInactiveError,
    WorkflowNotFoundError,
)

# --- Application-level (Pydantic) validation — no DB required ---


def test_batch_code_trimmed_and_uppercased() -> None:
    payload = CropBatchCreate(
        code="  ice-0001  ", workflow_id=uuid.uuid4(), client_command_id=uuid.uuid4(),
        effective_time=datetime.now(timezone.utc),
    )
    assert payload.code == "ICE-0001"


def test_batch_blank_code_rejected() -> None:
    with pytest.raises(ValueError):
        CropBatchCreate(
            code="   ", workflow_id=uuid.uuid4(), client_command_id=uuid.uuid4(),
            effective_time=datetime.now(timezone.utc),
        )


def test_batch_naive_effective_time_rejected() -> None:
    with pytest.raises(ValueError):
        CropBatchCreate(
            code="ICE-0001", workflow_id=uuid.uuid4(), client_command_id=uuid.uuid4(),
            effective_time=datetime.now(),
        )


def test_batch_create_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        CropBatchCreate(
            code="ICE-0001", workflow_id=uuid.uuid4(), client_command_id=uuid.uuid4(),
            effective_time=datetime.now(timezone.utc), workflow_version_id=uuid.uuid4(),
        )


# --- Integration (DB) helpers ---


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(db_session, tenant, *, stage_codes=("SEEDING", "GERMINATION", "NURSERY", "COMPLETE")):
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="ICE", common_name="Iceberg Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=None, crop_id=crop.id, code="MAM",
        name="Mamutik RZ", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="NURSERY-TRAY", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=None, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code="ICE-NURSERY", name="Iceberg Nursery Workflow",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id
    )
    categories = {"SEEDING": "seeding", "GERMINATION": "germination", "NURSERY": "nursery", "COMPLETE": "completed"}
    stages = []
    for i, code in enumerate(stage_codes):
        stage = workflow_service.add_stage(
            db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
            code=code, name=code.title(), display_order=i, stage_category=categories.get(code, "intermediate"),
            expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
            is_start=(i == 0), is_terminal=(i == len(stage_codes) - 1),
        )
        stages.append(stage)
    transitions = []
    for i in range(len(stages) - 1):
        t = workflow_service.add_transition(
            db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=stages[i].id, to_stage_id=stages[i + 1].id, code=f"ADVANCE-{i}", name=f"Advance {i}",
        )
        transitions.append(t)
    published = workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id
    )
    return {
        "crop": crop, "variety": variety, "production_system": ps, "workflow": workflow,
        "version": published, "stages": stages, "transitions": transitions,
    }


def _create_batch(db_session, tenant, user, farm, workflow, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code="ICE-0001", workflow_id=workflow.id, effective_time=_now(),
    )
    defaults.update(overrides)
    return crop_batch_service.create_batch(db_session, **defaults)


@pytest.mark.integration
def test_batch_creation_binds_to_published_version(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    assert batch.workflow_version_id == scenario["version"].id
    assert batch.state == "active"
    assert batch.created_by_user_id == user.id


@pytest.mark.integration
def test_batch_code_tenant_scoped_case_insensitive_uniqueness(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    _create_batch(db_session, tenant, user, farm, scenario["workflow"], code="ICE-0001")
    with pytest.raises(DuplicateBatchCodeError):
        _create_batch(db_session, tenant, user, farm, scenario["workflow"], code="ice-0001")


@pytest.mark.integration
def test_same_batch_code_allowed_in_different_tenant(db_session, active_context_with_farm) -> None:
    from app.services import farm_service, tenant_service

    tenant_a, user_a, _headers, farm_a = active_context_with_farm
    scenario_a = _build_scenario(db_session, tenant_a)
    batch_a = _create_batch(db_session, tenant_a, user_a, farm_a, scenario_a["workflow"], code="ICE-0001")

    tenant_b = tenant_service.create_tenant(db_session, code="batch-tenant-b", name="Tenant B")
    farm_b = farm_service.create_farm(
        db_session, tenant_id=tenant_b.id, actor_user_id=None, code="farm-b", name="Farm B",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    scenario_b = _build_scenario(db_session, tenant_b)
    batch_b = _create_batch(db_session, tenant_b, user_a, farm_b, scenario_b["workflow"], code="ICE-0001")
    assert batch_a.code == batch_b.code
    assert batch_a.tenant_id != batch_b.tenant_id


@pytest.mark.integration
def test_creation_without_published_version_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="ICE", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="NURSERY-TRAY", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=None, crop_id=crop.id, variety_id=None,
        production_system_id=ps.id, code="ICE-NURSERY", name="Iceberg Nursery",
    )
    # draft version only, never published
    workflow_service.create_draft_version(db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id)
    with pytest.raises(WorkflowHasNoPublishedVersionError):
        _create_batch(db_session, tenant, user, farm, workflow)


@pytest.mark.integration
def test_creation_with_only_retired_version_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, stage_codes=("ONLY",))
    workflow = scenario["workflow"]
    # Retire the only published version directly (a legitimate published -> retired
    # transition per the CMP-007 lifecycle trigger), leaving no published version at all.
    db_session.execute(
        text("UPDATE workflow_versions SET state = 'retired', retired_at = :retired_at WHERE id = :id"),
        {"id": scenario["version"].id, "retired_at": _now()},
    )
    db_session.flush()
    with pytest.raises(WorkflowHasNoPublishedVersionError):
        _create_batch(db_session, tenant, user, farm, workflow)


@pytest.mark.integration
def test_inactive_workflow_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    workflow = scenario["workflow"]
    workflow.status = "inactive"
    db_session.flush()
    with pytest.raises(WorkflowInactiveError):
        _create_batch(db_session, tenant, user, farm, workflow)


@pytest.mark.integration
def test_inactive_crop_rejected_at_batch_creation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    scenario["crop"].status = "inactive"
    db_session.flush()
    with pytest.raises(BatchCreationValidationError):
        _create_batch(db_session, tenant, user, farm, scenario["workflow"])


@pytest.mark.integration
def test_inactive_variety_rejected_at_batch_creation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    scenario["variety"].status = "inactive"
    db_session.flush()
    with pytest.raises(BatchCreationValidationError):
        _create_batch(db_session, tenant, user, farm, scenario["workflow"])


@pytest.mark.integration
def test_inactive_production_system_rejected_at_batch_creation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    scenario["production_system"].status = "inactive"
    db_session.flush()
    with pytest.raises(BatchCreationValidationError):
        _create_batch(db_session, tenant, user, farm, scenario["workflow"])


@pytest.mark.integration
def test_initial_start_stage_run_created_atomically(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    batch_row, run, stage = crop_batch_service.get_current_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assert stage.code == "SEEDING"
    assert run.exited_effective_time is None


@pytest.mark.integration
def test_exactly_one_active_stage_run(db_session, active_context_with_farm) -> None:
    from app.models.batch_stage_run import BatchStageRun

    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    count = db_session.execute(
        select(func.count()).select_from(BatchStageRun).where(
            BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None)
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.integration
def test_batch_stores_creation_command_id_and_fingerprint(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    command_id = uuid.uuid4()
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"], client_command_id=command_id)
    assert batch.client_command_id == command_id
    assert batch.request_fingerprint


@pytest.mark.integration
def test_future_creation_effective_time_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    with pytest.raises(InvalidBatchEffectiveTimeError):
        _create_batch(
            db_session, tenant, user, farm, scenario["workflow"],
            effective_time=_now() + timedelta(days=1),
        )


@pytest.mark.integration
def test_terminal_start_stage_closes_batch_atomically(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, stage_codes=("ONLY",))
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    assert batch.state == "closed"
    assert batch.closed_effective_time == batch.created_effective_time

    batch_row, run, stage = crop_batch_service.get_current_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assert stage.code == "ONLY"
    assert run.exited_effective_time is None, "terminal run must remain the active current stage"

    count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.created", AuditEvent.entity_id == batch.id
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.integration
def test_idempotent_batch_creation_returns_original(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    command_id = uuid.uuid4()
    effective_time = _now()
    batch_1 = _create_batch(
        db_session, tenant, user, farm, scenario["workflow"], client_command_id=command_id,
        effective_time=effective_time,
    )
    batch_2 = _create_batch(
        db_session, tenant, user, farm, scenario["workflow"], client_command_id=command_id,
        effective_time=effective_time,
    )
    assert batch_1.id == batch_2.id


@pytest.mark.integration
def test_reused_creation_command_id_with_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    command_id = uuid.uuid4()
    _create_batch(db_session, tenant, user, farm, scenario["workflow"], client_command_id=command_id, code="ICE-0001")
    with pytest.raises(BatchCommandReusedWithDifferentPayloadError):
        _create_batch(db_session, tenant, user, farm, scenario["workflow"], client_command_id=command_id, code="ICE-0002")


@pytest.mark.integration
def test_idempotent_retry_succeeds_after_newer_version_published(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    workflow = scenario["workflow"]
    command_id = uuid.uuid4()
    effective_time = _now()
    batch_1 = _create_batch(
        db_session, tenant, user, farm, workflow, client_command_id=command_id, effective_time=effective_time,
    )

    v2 = workflow_service.create_draft_version(db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id)
    workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=v2.id,
        code="ONLY", name="Only", display_order=0, stage_category="completed", expected_duration_minutes=None,
        permitted_location_type_code=None, required_carrier_type_code=None, is_start=True, is_terminal=True,
    )
    workflow_service.publish_version(db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=v2.id)

    batch_2 = _create_batch(
        db_session, tenant, user, farm, workflow, client_command_id=command_id, effective_time=effective_time,
    )
    assert batch_2.id == batch_1.id
    assert batch_2.workflow_version_id == scenario["version"].id, "retry must still bind to the original version"


@pytest.mark.integration
def test_created_by_user_id_cannot_be_null_at_db_level(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO crop_batches "
                    "(id, tenant_id, farm_id, code, workflow_id, workflow_version_id, "
                    "created_effective_time, created_by_user_id, client_command_id, request_fingerprint) "
                    "VALUES (:id, :tenant_id, :farm_id, 'BAD', :workflow_id, :version_id, now(), NULL, :cmd, 'fp')"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id,
                    "workflow_id": scenario["workflow"].id, "version_id": scenario["version"].id,
                    "cmd": uuid.uuid4(),
                },
            )


@pytest.mark.integration
def test_batch_identity_fields_immutable_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("UPDATE crop_batches SET code = 'CHANGED' WHERE id = :id"), {"id": batch.id})


@pytest.mark.integration
def test_batch_delete_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM crop_batches WHERE id = :id"), {"id": batch.id})


@pytest.mark.integration
def test_get_batch_via_api_returns_current_stage_and_crop_variety(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    response = client.get(f"/farms/{farm.id}/crop-batches/{batch.id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "ICE-0001"
    assert body["current_stage"]["code"] == "SEEDING"
    assert body["crop"]["code"] == "ICE"
    assert body["variety"]["code"] == "MAM"


@pytest.mark.integration
def test_unknown_batch_id_returns_404(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    response = client.get(f"/farms/{farm.id}/crop-batches/{uuid.uuid4()}", headers=headers)
    assert response.status_code == 404
