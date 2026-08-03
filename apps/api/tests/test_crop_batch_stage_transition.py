import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.models.batch_stage_run import BatchStageRun
from app.models.batch_stage_transition import BatchStageTransition
from app.schemas.batch_stage_transition import BatchStageTransitionCreate
from app.services import crop_batch_service, crop_service, production_system_service, workflow_service
from app.services.errors import (
    BatchCommandReusedWithDifferentPayloadError,
    ConfiguredTransitionNotFoundError,
    CropBatchClosedError,
    InvalidBatchEffectiveTimeError,
    StageMismatchError,
)


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(db_session, tenant, *, stage_codes=("SEEDING", "GERMINATION", "NURSERY", "COMPLETE")):
    suffix = uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code=f"ICE-{suffix}", common_name="Iceberg Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=None, code=f"NURSERY-TRAY-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=None, crop_id=crop.id, variety_id=None,
        production_system_id=ps.id, code=f"ICE-NURSERY-{suffix}", name="Iceberg Nursery Workflow",
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
        "crop": crop, "production_system": ps, "workflow": workflow,
        "version": published, "stages": stages, "transitions": transitions,
    }


def _create_batch(db_session, tenant, user, farm, workflow, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code="ICE-0001", workflow_id=workflow.id, effective_time=_now(),
    )
    defaults.update(overrides)
    return crop_batch_service.create_batch(db_session, **defaults)


def _transition(db_session, tenant, user, farm, batch, configured_transition, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=configured_transition.id,
        effective_time=_now(), reason=None,
    )
    defaults.update(overrides)
    return crop_batch_service.transition_stage(db_session, **defaults)


# --- Application-level (Pydantic) validation — no DB required ---


def test_stage_transition_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        BatchStageTransitionCreate(
            configured_transition_id=uuid.uuid4(), client_command_id=uuid.uuid4(),
            effective_time=_now(), source_stage_id=uuid.uuid4(),
        )


def test_stage_transition_reason_normalized_to_none_when_blank() -> None:
    payload = BatchStageTransitionCreate(
        configured_transition_id=uuid.uuid4(), client_command_id=uuid.uuid4(),
        effective_time=_now(), reason="   ",
    )
    assert payload.reason is None


# --- Integration (DB) ---


@pytest.mark.integration
def test_valid_stage_progression(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    transition = _transition(db_session, tenant, user, farm, batch, scenario["transitions"][0])
    assert transition.destination_stage_id == scenario["stages"][1].id
    _batch, run, stage = crop_batch_service.get_current_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assert stage.code == "GERMINATION"


@pytest.mark.integration
def test_wrong_source_stage_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    # transitions[1] goes GERMINATION -> NURSERY, but the batch is still at SEEDING.
    with pytest.raises(StageMismatchError):
        _transition(db_session, tenant, user, farm, batch, scenario["transitions"][1])


@pytest.mark.integration
def test_cross_version_transition_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    workflow = scenario["workflow"]
    batch = _create_batch(db_session, tenant, user, farm, workflow)

    v2 = workflow_service.create_draft_version(db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id)
    s1 = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=v2.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding", expected_duration_minutes=None,
        permitted_location_type_code=None, required_carrier_type_code=None, is_start=True, is_terminal=False,
    )
    s2 = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=v2.id,
        code="DONE", name="Done", display_order=1, stage_category="completed", expected_duration_minutes=None,
        permitted_location_type_code=None, required_carrier_type_code=None, is_start=False, is_terminal=True,
    )
    t_v2 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=v2.id,
        from_stage_id=s1.id, to_stage_id=s2.id, code="ADVANCE", name="Advance",
    )
    workflow_service.publish_version(db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=v2.id)

    # batch stays bound to v1; attempting a v2 transition must be rejected.
    with pytest.raises(ConfiguredTransitionNotFoundError):
        _transition(db_session, tenant, user, farm, batch, t_v2)


@pytest.mark.integration
def test_closed_batch_cannot_transition(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, stage_codes=("ONLY",))
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    assert batch.state == "closed"
    # No transitions exist for a one-stage workflow; simulate an attempt with a foreign
    # transition to prove the closed-batch check fires before transition lookup would matter.
    other_scenario = _build_scenario(db_session, tenant, stage_codes=("A", "B"))
    with pytest.raises(CropBatchClosedError):
        _transition(db_session, tenant, user, farm, batch, other_scenario["transitions"][0])


@pytest.mark.integration
def test_terminal_progression_closes_batch_with_one_audit_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, stage_codes=("SEEDING", "DONE"))
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    _transition(db_session, tenant, user, farm, batch, scenario["transitions"][0])

    db_session.refresh(batch)
    assert batch.state == "closed"

    stage_transitioned_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "crop_batch.stage_transitioned")
    ).scalar_one()
    closed_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "crop_batch.closed")
    ).scalar_one()
    assert stage_transitioned_count == 0, "a terminal command must not also emit stage_transitioned"
    assert closed_count == 1


@pytest.mark.integration
def test_non_terminal_progression_produces_one_stage_transitioned_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    _transition(db_session, tenant, user, farm, batch, scenario["transitions"][0])

    count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "crop_batch.stage_transitioned")
    ).scalar_one()
    assert count == 1


@pytest.mark.integration
def test_full_stage_history_ordering(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    for t in scenario["transitions"]:
        _transition(db_session, tenant, user, farm, batch, t)

    history = crop_batch_service.get_stage_history(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    codes = [stage.code for _run, stage in history]
    assert codes == ["SEEDING", "GERMINATION", "NURSERY", "COMPLETE"]
    for run, _stage in history[:-1]:
        assert run.exited_effective_time is not None
    assert history[-1][0].exited_effective_time is None


@pytest.mark.integration
def test_idempotent_stage_transition_retry(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    command_id = uuid.uuid4()
    effective_time = _now()
    t1 = _transition(
        db_session, tenant, user, farm, batch, scenario["transitions"][0],
        client_command_id=command_id, effective_time=effective_time,
    )
    t2 = _transition(
        db_session, tenant, user, farm, batch, scenario["transitions"][0],
        client_command_id=command_id, effective_time=effective_time,
    )
    assert t1.id == t2.id

    run_count = db_session.execute(
        select(func.count()).select_from(BatchStageRun).where(BatchStageRun.batch_id == batch.id)
    ).scalar_one()
    assert run_count == 2  # initial SEEDING run + GERMINATION run, no duplicate
    transition_count = db_session.execute(
        select(func.count()).select_from(BatchStageTransition).where(
            BatchStageTransition.batch_id == batch.id, BatchStageTransition.command_kind == "stage_transition"
        )
    ).scalar_one()
    assert transition_count == 1


@pytest.mark.integration
def test_reused_transition_command_id_with_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    command_id = uuid.uuid4()
    _transition(db_session, tenant, user, farm, batch, scenario["transitions"][0], client_command_id=command_id)
    # Retry with a different reason changes the fingerprint.
    with pytest.raises(BatchCommandReusedWithDifferentPayloadError):
        _transition(
            db_session, tenant, user, farm, batch, scenario["transitions"][0],
            client_command_id=command_id, reason="different",
        )


@pytest.mark.integration
def test_idempotent_retry_succeeds_after_batch_progressed_further(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    command_id = uuid.uuid4()
    effective_time = _now()
    t1 = _transition(
        db_session, tenant, user, farm, batch, scenario["transitions"][0],
        client_command_id=command_id, effective_time=effective_time,
    )
    _transition(db_session, tenant, user, farm, batch, scenario["transitions"][1])  # advance again

    t1_retry = _transition(
        db_session, tenant, user, farm, batch, scenario["transitions"][0],
        client_command_id=command_id, effective_time=effective_time,
    )
    assert t1_retry.id == t1.id


@pytest.mark.integration
def test_future_progression_effective_time_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    with pytest.raises(InvalidBatchEffectiveTimeError):
        _transition(
            db_session, tenant, user, farm, batch, scenario["transitions"][0],
            effective_time=_now() + timedelta(days=1),
        )


@pytest.mark.integration
def test_progression_before_current_stage_entry_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    entry_time = _now()
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"], effective_time=entry_time)
    with pytest.raises(InvalidBatchEffectiveTimeError):
        _transition(
            db_session, tenant, user, farm, batch, scenario["transitions"][0],
            effective_time=entry_time - timedelta(hours=1),
        )


@pytest.mark.integration
def test_failed_transition_preserves_active_run_and_creates_no_audit_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    with pytest.raises(StageMismatchError):
        _transition(db_session, tenant, user, farm, batch, scenario["transitions"][1])

    _batch, run, stage = crop_batch_service.get_current_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assert stage.code == "SEEDING"
    assert run.exited_effective_time is None

    count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action.in_(["crop_batch.stage_transitioned", "crop_batch.closed"])
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.integration
def test_cross_tenant_batch_transition_rejected(db_session, active_context_with_farm) -> None:
    from app.services import tenant_service

    tenant_a, user_a, _headers, farm_a = active_context_with_farm
    scenario = _build_scenario(db_session, tenant_a)
    batch = _create_batch(db_session, tenant_a, user_a, farm_a, scenario["workflow"])

    tenant_b = tenant_service.create_tenant(db_session, code="transition-tenant-b", name="Tenant B")
    from app.services.errors import FarmNotFoundError

    with pytest.raises(FarmNotFoundError):
        crop_batch_service.transition_stage(
            db_session, tenant_id=tenant_b.id, farm_id=farm_a.id, actor_user_id=user_a.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), configured_transition_id=scenario["transitions"][0].id,
            effective_time=_now(), reason=None,
        )


# --- Immutability / direct SQL ------------------------------------------------------


@pytest.mark.integration
def test_batch_stage_transition_update_and_delete_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    transition = _transition(db_session, tenant, user, farm, batch, scenario["transitions"][0])

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE batch_stage_transitions SET reason = 'x' WHERE id = :id"), {"id": transition.id}
            )
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM batch_stage_transitions WHERE id = :id"), {"id": transition.id})


@pytest.mark.integration
def test_closed_stage_run_cannot_reopen(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    _transition(db_session, tenant, user, farm, batch, scenario["transitions"][0])

    closed_run = db_session.execute(
        select(BatchStageRun).where(
            BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_not(None)
        )
    ).scalar_one()
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE batch_stage_runs SET exited_effective_time = NULL, closed_by_transition_id = NULL WHERE id = :id"),
                {"id": closed_run.id},
            )


@pytest.mark.integration
def test_stage_run_delete_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    run = db_session.execute(
        select(BatchStageRun).where(BatchStageRun.batch_id == batch.id)
    ).scalar_one()
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM batch_stage_runs WHERE id = :id"), {"id": run.id})


@pytest.mark.integration
def test_stage_run_with_mismatched_opening_transition_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    other_scenario = _build_scenario(db_session, tenant, stage_codes=("A", "B"))
    other_batch = _create_batch(db_session, tenant, user, farm, other_scenario["workflow"], code="OTHER-0001")
    unrelated_transition = db_session.execute(
        select(BatchStageTransition).where(BatchStageTransition.batch_id == other_batch.id)
    ).scalar_one()

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO batch_stage_runs "
                    "(id, tenant_id, farm_id, batch_id, workflow_version_id, workflow_stage_id, "
                    "entered_effective_time, opened_by_transition_id, actor_user_id) "
                    "VALUES (:id, :tenant_id, :farm_id, :batch_id, :version_id, :stage_id, now(), :opening_id, :actor_id)"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id, "batch_id": batch.id,
                    "version_id": scenario["version"].id, "stage_id": scenario["stages"][1].id,
                    "opening_id": unrelated_transition.id, "actor_id": user.id,
                },
            )


@pytest.mark.integration
def test_stage_run_closure_with_mismatched_transition_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    active_run = db_session.execute(
        select(BatchStageRun).where(
            BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None)
        )
    ).scalar_one()

    other_scenario = _build_scenario(db_session, tenant, stage_codes=("A", "B"))
    other_batch = _create_batch(db_session, tenant, user, farm, other_scenario["workflow"], code="OTHER-0002")
    unrelated_transition = db_session.execute(
        select(BatchStageTransition).where(BatchStageTransition.batch_id == other_batch.id)
    ).scalar_one()

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "UPDATE batch_stage_runs SET exited_effective_time = now(), closed_by_transition_id = :closing_id "
                    "WHERE id = :id"
                ),
                {"id": active_run.id, "closing_id": unrelated_transition.id},
            )
