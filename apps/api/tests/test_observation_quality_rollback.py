"""Proves that record_observation, place_quality_hold, and
release_quality_hold each roll back every partial write when a failure
occurs after one or more flushes have already succeeded, and that the same
Session remains usable afterward — the same discipline CMP-008/009
established (test_crop_batch_rollback.py, test_sowing_rollback.py)."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, func, select

from app.models.audit_event import AuditEvent
from app.models.germination_check import GerminationCheck
from app.models.observation_event import ObservationEvent
from app.models.observation_value import ObservationValue
from app.models.quality_hold import QualityHold
from app.models.quality_hold_release import QualityHoldRelease
from app.services import (
    crop_batch_service,
    crop_service,
    observation_service,
    production_system_service,
    quality_hold_service,
    workflow_service,
)


class _ForcedFailure(Exception):
    """Distinct marker exception so assertions can't accidentally match a
    real domain or database error."""


def _now():
    return datetime.now(timezone.utc)


def _fail_before_flushing(session, *, new_types=()):
    def handler(sess, _flush_context, _instances):
        if any(isinstance(obj, new_types) for obj in sess.new):
            raise _ForcedFailure(f"forced failure before flushing new {new_types}")

    event.listen(session, "before_flush", handler)
    return handler


def _fail_audit_event(monkeypatch, module) -> None:
    def _raise(*args, **kwargs):
        raise _ForcedFailure("forced failure during audit event creation")

    monkeypatch.setattr(module, "append_audit_event", _raise)


def _build_scenario(db_session, tenant, user, farm):
    suffix = uuid.uuid4().hex[:8]
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
    seeding = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=True, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=complete.id, code="ADVANCE", name="Advance",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    definition = observation_service.register_observation_definition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"DEF-{suffix}", name="Metric",
        description=None, value_type="text", unit=None, target_scope="crop_batch", min_value=None, max_value=None,
    )
    return {"batch": batch, "definition": definition, "stage": seeding}


def _assert_session_usable(db_session) -> None:
    db_session.execute(select(func.count()).select_from(ObservationEvent)).scalar_one()


def _audit_count(db_session, action: str) -> int:
    return db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)
    ).scalar_one()


# --- Observation rollback -----------------------------------------------------------


@pytest.mark.integration
def test_observation_rollback_after_event_insert_before_values(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _fail_before_flushing(db_session, new_types=(ObservationValue, GerminationCheck))

    with pytest.raises(_ForcedFailure):
        observation_service.record_observation(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
            values=[{"observation_definition_id": s["definition"].id, "value_text": "ok"}],
            germination_checks=[],
        )

    assert db_session.execute(select(func.count()).select_from(ObservationEvent)).scalar_one() == 0
    assert db_session.execute(select(func.count()).select_from(ObservationValue)).scalar_one() == 0
    assert _audit_count(db_session, "crop_batch.observation_recorded") == 0
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_observation_rollback_after_values_insert_before_audit(
    db_session, active_context_with_farm, monkeypatch
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _fail_audit_event(monkeypatch, observation_service)

    with pytest.raises(_ForcedFailure):
        observation_service.record_observation(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
            values=[{"observation_definition_id": s["definition"].id, "value_text": "ok"}],
            germination_checks=[],
        )

    assert db_session.execute(select(func.count()).select_from(ObservationEvent)).scalar_one() == 0
    assert db_session.execute(select(func.count()).select_from(ObservationValue)).scalar_one() == 0
    assert _audit_count(db_session, "crop_batch.observation_recorded") == 0
    _assert_session_usable(db_session)


# --- Quality-hold rollback ------------------------------------------------------------


@pytest.mark.integration
def test_hold_rollback_after_insert_before_audit(db_session, active_context_with_farm, monkeypatch) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _fail_audit_event(monkeypatch, quality_hold_service)

    with pytest.raises(_ForcedFailure):
        quality_hold_service.place_quality_hold(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), source_observation_event_id=None,
            reason_code="X", reason_text="x",
        )

    assert db_session.execute(select(func.count()).select_from(QualityHold)).scalar_one() == 0
    assert _audit_count(db_session, "crop_batch.quality_hold_placed") == 0
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_release_rollback_after_insert_before_audit(db_session, active_context_with_farm, monkeypatch) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    hold = quality_hold_service.place_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), source_observation_event_id=None,
        reason_code="X", reason_text="x",
    )
    _fail_audit_event(monkeypatch, quality_hold_service)

    with pytest.raises(_ForcedFailure):
        quality_hold_service.release_quality_hold(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            hold_id=hold.id, client_command_id=uuid.uuid4(), effective_time=_now(), release_reason="cleared",
        )

    assert db_session.execute(select(func.count()).select_from(QualityHoldRelease)).scalar_one() == 0
    assert _audit_count(db_session, "crop_batch.quality_hold_released") == 0
    # The hold placed before the rollback-triggering release attempt must
    # remain intact and still open.
    assert db_session.execute(select(func.count()).select_from(QualityHold)).scalar_one() == 1
    read = quality_hold_service.get_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, hold_id=hold.id
    )
    assert read.is_open is True
    _assert_session_usable(db_session)
