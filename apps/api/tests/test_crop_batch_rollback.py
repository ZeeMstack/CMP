"""Proves that create_batch and transition_stage roll back every partial
write when a failure occurs after one or more flushes have already
succeeded, and that the same Session remains usable afterward — the defect
the CMP-008 verification report incorrectly described as a non-issue."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, func, select

from app.models.audit_event import AuditEvent
from app.models.batch_stage_run import BatchStageRun
from app.models.batch_stage_transition import BatchStageTransition
from app.models.crop_batch import CropBatch
from app.services import crop_batch_service, crop_service, production_system_service, workflow_service


class _ForcedFailure(Exception):
    """Distinct marker exception so assertions can't accidentally match a
    real domain or database error."""


def _now():
    return datetime.now(timezone.utc)


def _fail_before_flushing(session, *, new_types=(), dirty_types=()):
    """Raises the instant a pending object of one of the given types is about
    to be flushed — new objects via `session.new`, modified ones via
    `session.dirty`. This targets the exact write, unlike counting raw
    `flush()` calls: the test session (unlike the app's `SessionLocal`) uses
    SQLAlchemy's default `autoflush=True`, so plain SELECTs issue their own
    flush() calls and any call-counting scheme silently drifts out of sync
    with which object is actually about to be persisted."""

    def handler(sess, _flush_context, _instances):
        if new_types and any(isinstance(obj, new_types) for obj in sess.new):
            raise _ForcedFailure(f"forced failure before flushing new {new_types}")
        if dirty_types and any(isinstance(obj, dirty_types) for obj in sess.dirty):
            raise _ForcedFailure(f"forced failure before flushing dirty {dirty_types}")

    event.listen(session, "before_flush", handler)
    return handler


def _fail_audit_event(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise _ForcedFailure("forced failure during audit event creation")

    monkeypatch.setattr(crop_batch_service, "append_audit_event", _raise)


def _build_scenario(db_session, tenant, *, stage_codes=("SEEDING", "GERMINATION", "NURSERY")):
    suffix = uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code=f"ICE-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=None, code=f"PS-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=None, crop_id=crop.id, variety_id=None,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id
    )
    stages = []
    for i, code in enumerate(stage_codes):
        stage = workflow_service.add_stage(
            db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
            code=code, name=code.title(), display_order=i,
            stage_category=("seeding" if i == 0 else ("completed" if i == len(stage_codes) - 1 else "intermediate")),
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
    return {"workflow": workflow, "version": published, "stages": stages, "transitions": transitions}


def _assert_session_usable(db_session) -> None:
    # A session left in a failed-transaction state raises PendingRollbackError
    # (or similar) on the very next query — this must not happen.
    db_session.execute(select(func.count()).select_from(CropBatch)).scalar_one()


def _audit_count(db_session, action: str) -> int:
    return db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)
    ).scalar_one()


# --- Creation rollback ---------------------------------------------------------------


@pytest.mark.integration
def test_creation_rollback_after_batch_insert(db_session, active_context_with_farm, monkeypatch) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    # Fires the instant the initial-entry transition is about to be flushed —
    # i.e. strictly after the batch row has already been persisted for real.
    _fail_before_flushing(db_session, new_types=(BatchStageTransition,))

    with pytest.raises(_ForcedFailure):
        crop_batch_service.create_batch(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), code="ROLLBACK-1", workflow_id=scenario["workflow"].id,
            effective_time=_now(),
        )

    assert db_session.execute(select(func.count()).select_from(CropBatch)).scalar_one() == 0
    assert db_session.execute(select(func.count()).select_from(BatchStageTransition)).scalar_one() == 0
    assert db_session.execute(select(func.count()).select_from(BatchStageRun)).scalar_one() == 0
    assert _audit_count(db_session, "crop_batch.created") == 0
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_creation_rollback_after_initial_transition_insert(db_session, active_context_with_farm, monkeypatch) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    # Fires the instant the initial stage run is about to be flushed — i.e.
    # strictly after both the batch and its initial-entry transition are
    # already persisted for real.
    _fail_before_flushing(db_session, new_types=(BatchStageRun,))

    with pytest.raises(_ForcedFailure):
        crop_batch_service.create_batch(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), code="ROLLBACK-2", workflow_id=scenario["workflow"].id,
            effective_time=_now(),
        )

    assert db_session.execute(select(func.count()).select_from(CropBatch)).scalar_one() == 0
    assert db_session.execute(select(func.count()).select_from(BatchStageTransition)).scalar_one() == 0
    assert db_session.execute(select(func.count()).select_from(BatchStageRun)).scalar_one() == 0
    assert _audit_count(db_session, "crop_batch.created") == 0
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_creation_rollback_after_stage_run_insert(db_session, active_context_with_farm, monkeypatch) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    _fail_audit_event(monkeypatch)  # fires after batch + transition + run are all flushed

    with pytest.raises(_ForcedFailure):
        crop_batch_service.create_batch(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), code="ROLLBACK-3", workflow_id=scenario["workflow"].id,
            effective_time=_now(),
        )

    assert db_session.execute(select(func.count()).select_from(CropBatch)).scalar_one() == 0
    assert db_session.execute(select(func.count()).select_from(BatchStageTransition)).scalar_one() == 0
    assert db_session.execute(select(func.count()).select_from(BatchStageRun)).scalar_one() == 0
    assert _audit_count(db_session, "crop_batch.created") == 0
    _assert_session_usable(db_session)


# --- Stage progression rollback ------------------------------------------------------


def _create_batch(db_session, tenant, user, farm, workflow, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code="BASE-0001", workflow_id=workflow.id, effective_time=_now(),
    )
    defaults.update(overrides)
    return crop_batch_service.create_batch(db_session, **defaults)


@pytest.mark.integration
def test_progression_rollback_after_transition_insert(db_session, active_context_with_farm, monkeypatch) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    original_run_id = db_session.execute(
        select(BatchStageRun.id).where(BatchStageRun.batch_id == batch.id)
    ).scalar_one()

    # Fires the instant the active run's closure (a dirty-object flush) is
    # about to happen — i.e. strictly after the progression transition row
    # has already been persisted for real.
    _fail_before_flushing(db_session, dirty_types=(BatchStageRun,))
    with pytest.raises(_ForcedFailure):
        crop_batch_service.transition_stage(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), configured_transition_id=scenario["transitions"][0].id,
            effective_time=_now(), reason=None,
        )

    db_session.refresh(batch)
    assert batch.state == "active"
    active_run = db_session.execute(
        select(BatchStageRun).where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
    ).scalar_one()
    assert active_run.id == original_run_id
    assert db_session.execute(select(func.count()).select_from(BatchStageRun).where(BatchStageRun.batch_id == batch.id)).scalar_one() == 1
    assert db_session.execute(
        select(func.count()).select_from(BatchStageTransition).where(BatchStageTransition.command_kind == "stage_transition")
    ).scalar_one() == 0
    assert _audit_count(db_session, "crop_batch.stage_transitioned") == 0
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_progression_rollback_after_old_run_closed(db_session, active_context_with_farm, monkeypatch) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    original_run_id = db_session.execute(
        select(BatchStageRun.id).where(BatchStageRun.batch_id == batch.id)
    ).scalar_one()

    # Fires the instant the new destination run (a new-object flush) is about
    # to happen — i.e. strictly after the transition row and the old run's
    # closure have already been persisted for real.
    _fail_before_flushing(db_session, new_types=(BatchStageRun,))
    with pytest.raises(_ForcedFailure):
        crop_batch_service.transition_stage(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), configured_transition_id=scenario["transitions"][0].id,
            effective_time=_now(), reason=None,
        )

    db_session.refresh(batch)
    assert batch.state == "active"
    active_run = db_session.execute(
        select(BatchStageRun).where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
    ).scalar_one()
    assert active_run.id == original_run_id, "the original run must remain active, not left half-closed"
    assert db_session.execute(select(func.count()).select_from(BatchStageRun).where(BatchStageRun.batch_id == batch.id)).scalar_one() == 1
    assert db_session.execute(
        select(func.count()).select_from(BatchStageTransition).where(BatchStageTransition.command_kind == "stage_transition")
    ).scalar_one() == 0
    assert _audit_count(db_session, "crop_batch.stage_transitioned") == 0
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_progression_rollback_after_destination_run_insert(db_session, active_context_with_farm, monkeypatch) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant)
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    original_run_id = db_session.execute(
        select(BatchStageRun.id).where(BatchStageRun.batch_id == batch.id)
    ).scalar_one()

    _fail_audit_event(monkeypatch)  # fires after transition + closure + destination run are all flushed
    with pytest.raises(_ForcedFailure):
        crop_batch_service.transition_stage(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), configured_transition_id=scenario["transitions"][0].id,
            effective_time=_now(), reason=None,
        )

    db_session.refresh(batch)
    assert batch.state == "active"
    active_run = db_session.execute(
        select(BatchStageRun).where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
    ).scalar_one()
    assert active_run.id == original_run_id
    assert db_session.execute(select(func.count()).select_from(BatchStageRun).where(BatchStageRun.batch_id == batch.id)).scalar_one() == 1
    assert db_session.execute(
        select(func.count()).select_from(BatchStageTransition).where(BatchStageTransition.command_kind == "stage_transition")
    ).scalar_one() == 0
    assert _audit_count(db_session, "crop_batch.stage_transitioned") == 0
    _assert_session_usable(db_session)


# --- Terminal progression rollback ---------------------------------------------------


@pytest.mark.integration
def test_terminal_progression_rollback_leaves_batch_active(db_session, active_context_with_farm, monkeypatch) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, stage_codes=("SEEDING", "DONE"))
    batch = _create_batch(db_session, tenant, user, farm, scenario["workflow"])
    original_run_id = db_session.execute(
        select(BatchStageRun.id).where(BatchStageRun.batch_id == batch.id)
    ).scalar_one()

    # Fires after the transition, the old run's closure, the new (terminal) run's
    # insertion, and the batch's own closing flush have all succeeded — only the
    # audit event and commit remain.
    _fail_audit_event(monkeypatch)
    with pytest.raises(_ForcedFailure):
        crop_batch_service.transition_stage(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), configured_transition_id=scenario["transitions"][0].id,
            effective_time=_now(), reason=None,
        )

    db_session.refresh(batch)
    assert batch.state == "active", "the batch must not remain closed after a rolled-back closure"
    assert batch.closed_effective_time is None
    active_run = db_session.execute(
        select(BatchStageRun).where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
    ).scalar_one()
    assert active_run.id == original_run_id, "the SEEDING run must remain active, not the terminal one"
    assert db_session.execute(select(func.count()).select_from(BatchStageRun).where(BatchStageRun.batch_id == batch.id)).scalar_one() == 1
    assert db_session.execute(
        select(func.count()).select_from(BatchStageTransition).where(BatchStageTransition.command_kind == "stage_transition")
    ).scalar_one() == 0
    assert _audit_count(db_session, "crop_batch.closed") == 0
    _assert_session_usable(db_session)
