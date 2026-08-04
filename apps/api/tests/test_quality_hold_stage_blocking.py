"""CMP-010: proves that an open quality hold blocks CMP-008 stage
progression at both the service layer (crop_batch_service.transition_stage)
and the database layer (a trigger on the existing batch_stage_transitions
table), that an exact replay of an already-successful transition is
unaffected by a hold placed afterward, and that releasing only some of
several open holds still blocks progression."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.models.batch_stage_run import BatchStageRun
from app.models.batch_stage_transition import BatchStageTransition
from app.services import (
    crop_batch_service,
    crop_service,
    production_system_service,
    quality_hold_service,
    workflow_service,
)
from app.services.errors import QualityHoldOpenError


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(db_session, tenant, user, farm, *, suffix=None, stage_codes=("SEEDING", "GERMINATION", "COMPLETE")):
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg", scientific_name=None, crop_category="leafy_green",
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=None,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    stages = []
    for i, code in enumerate(stage_codes):
        stage = workflow_service.add_stage(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            code=code, name=code.title(), display_order=i,
            stage_category=("seeding" if i == 0 else ("completed" if i == len(stage_codes) - 1 else "intermediate")),
            expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
            is_start=(i == 0), is_terminal=(i == len(stage_codes) - 1),
        )
        stages.append(stage)
    transitions = []
    for i in range(len(stages) - 1):
        t = workflow_service.add_transition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=stages[i].id, to_stage_id=stages[i + 1].id, code=f"ADVANCE-{i}", name=f"Advance {i}",
        )
        transitions.append(t)
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    return {"batch": batch, "stages": stages, "transitions": transitions}


def _place_hold(db_session, tenant, user, farm, batch, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), source_observation_event_id=None,
        reason_code="LOW-GERMINATION", reason_text="Below threshold",
    )
    defaults.update(overrides)
    return quality_hold_service.place_quality_hold(db_session, **defaults)


def _release_hold(db_session, tenant, user, farm, batch, hold_id, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id, hold_id=hold_id,
        client_command_id=uuid.uuid4(), effective_time=_now(), release_reason="Reinspected",
    )
    defaults.update(overrides)
    return quality_hold_service.release_quality_hold(db_session, **defaults)


def _transition(db_session, tenant, user, farm, batch, configured_transition_id, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=configured_transition_id,
        effective_time=_now(), reason=None,
    )
    defaults.update(overrides)
    return crop_batch_service.transition_stage(db_session, **defaults)


@pytest.mark.integration
def test_open_hold_blocks_new_transition(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _place_hold(db_session, tenant, user, farm, s["batch"])
    with pytest.raises(QualityHoldOpenError):
        _transition(db_session, tenant, user, farm, s["batch"], s["transitions"][0].id)


@pytest.mark.integration
def test_blocked_transition_leaves_no_partial_data(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _place_hold(db_session, tenant, user, farm, s["batch"])
    with pytest.raises(QualityHoldOpenError):
        _transition(db_session, tenant, user, farm, s["batch"], s["transitions"][0].id)

    transitions_count = db_session.execute(
        select(func.count()).select_from(BatchStageTransition).where(
            BatchStageTransition.batch_id == s["batch"].id, BatchStageTransition.command_kind == "stage_transition"
        )
    ).scalar_one()
    assert transitions_count == 0
    active_run = db_session.execute(
        select(BatchStageRun).where(BatchStageRun.batch_id == s["batch"].id, BatchStageRun.exited_effective_time.is_(None))
    ).scalar_one()
    assert active_run.workflow_stage_id == s["stages"][0].id
    audit_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.stage_transitioned", AuditEvent.entity_id == s["batch"].id
        )
    ).scalar_one()
    assert audit_count == 0
    # Session must remain usable after the rejected command.
    db_session.execute(select(func.count()).select_from(BatchStageTransition)).scalar_one()


@pytest.mark.integration
def test_transition_succeeds_after_hold_released(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold = _place_hold(db_session, tenant, user, farm, s["batch"])
    _release_hold(db_session, tenant, user, farm, s["batch"], hold.id)
    transition = _transition(db_session, tenant, user, farm, s["batch"], s["transitions"][0].id)
    assert transition.destination_stage_id == s["stages"][1].id


@pytest.mark.integration
def test_releasing_one_of_several_holds_still_blocks(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold_a = _place_hold(db_session, tenant, user, farm, s["batch"], reason_code="A")
    _place_hold(db_session, tenant, user, farm, s["batch"], reason_code="B")
    _release_hold(db_session, tenant, user, farm, s["batch"], hold_a.id)
    with pytest.raises(QualityHoldOpenError):
        _transition(db_session, tenant, user, farm, s["batch"], s["transitions"][0].id)


@pytest.mark.integration
def test_releasing_all_holds_permits_progression(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold_a = _place_hold(db_session, tenant, user, farm, s["batch"], reason_code="A")
    hold_b = _place_hold(db_session, tenant, user, farm, s["batch"], reason_code="B")
    _release_hold(db_session, tenant, user, farm, s["batch"], hold_a.id)
    _release_hold(db_session, tenant, user, farm, s["batch"], hold_b.id)
    transition = _transition(db_session, tenant, user, farm, s["batch"], s["transitions"][0].id)
    assert transition.destination_stage_id == s["stages"][1].id


@pytest.mark.integration
def test_exact_transition_replay_succeeds_despite_later_hold(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    command_id = uuid.uuid4()
    effective_time = _now()
    original = _transition(
        db_session, tenant, user, farm, s["batch"], s["transitions"][0].id, client_command_id=command_id,
        effective_time=effective_time,
    )
    _place_hold(db_session, tenant, user, farm, s["batch"])
    replay = _transition(
        db_session, tenant, user, farm, s["batch"], s["transitions"][0].id, client_command_id=command_id,
        effective_time=effective_time,
    )
    assert replay.id == original.id


@pytest.mark.integration
def test_db_level_stage_transition_insert_rejected_while_hold_open(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _place_hold(db_session, tenant, user, farm, s["batch"])
    active_run = db_session.execute(
        select(BatchStageRun).where(BatchStageRun.batch_id == s["batch"].id, BatchStageRun.exited_effective_time.is_(None))
    ).scalar_one()

    with pytest.raises(DBAPIError) as exc_info:
        db_session.execute(
            text(
                "INSERT INTO batch_stage_transitions (id, tenant_id, farm_id, batch_id, workflow_version_id, "
                "command_kind, source_stage_id, destination_stage_id, configured_transition_id, "
                "effective_time, actor_user_id, client_command_id, request_fingerprint) VALUES "
                "(:id, :tenant_id, :farm_id, :batch_id, :wv_id, 'stage_transition', :src, :dst, :ct, "
                "now(), :actor, :cmd, 'fp')"
            ),
            {
                "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id, "batch_id": s["batch"].id,
                "wv_id": s["batch"].workflow_version_id, "src": s["stages"][0].id, "dst": s["stages"][1].id,
                "ct": s["transitions"][0].id, "actor": user.id, "cmd": uuid.uuid4(),
            },
        )
        db_session.flush()
    assert "open quality hold" in str(exc_info.value)
    db_session.rollback()


@pytest.mark.integration
def test_db_level_initial_entry_insert_not_blocked_by_hold_trigger(db_session, active_context_with_farm) -> None:
    """Proves the trigger's WHEN clause genuinely excludes command_kind =
    'initial_entry' — the attempted row here fails for an unrelated reason
    (the partial unique index capping one initial_entry per batch), not
    because the hold-block trigger fired."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _place_hold(db_session, tenant, user, farm, s["batch"])

    with pytest.raises(DBAPIError) as exc_info:
        db_session.execute(
            text(
                "INSERT INTO batch_stage_transitions (id, tenant_id, farm_id, batch_id, workflow_version_id, "
                "command_kind, source_stage_id, destination_stage_id, configured_transition_id, "
                "effective_time, actor_user_id, client_command_id, request_fingerprint) VALUES "
                "(:id, :tenant_id, :farm_id, :batch_id, :wv_id, 'initial_entry', NULL, :dst, NULL, "
                "now(), :actor, :cmd, 'fp')"
            ),
            {
                "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id, "batch_id": s["batch"].id,
                "wv_id": s["batch"].workflow_version_id, "dst": s["stages"][0].id, "actor": user.id,
                "cmd": uuid.uuid4(),
            },
        )
        db_session.flush()
    assert "open quality hold" not in str(exc_info.value)
    db_session.rollback()


@pytest.mark.integration
def test_terminal_transition_blocked_by_open_hold(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm, stage_codes=("SEEDING", "DONE"))
    _place_hold(db_session, tenant, user, farm, s["batch"])
    with pytest.raises(QualityHoldOpenError):
        _transition(db_session, tenant, user, farm, s["batch"], s["transitions"][0].id)
    db_session.refresh(s["batch"])
    assert s["batch"].state == "active"
