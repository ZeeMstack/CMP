"""Proves that sow_batch rolls back every partial write when a failure
occurs after one or more flushes have already succeeded, and that the same
Session remains usable afterward — the same discipline CMP-008 established
for crop_batch_service (test_crop_batch_rollback.py)."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, func, select

from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.sowing_event import SowingEvent
from app.models.sowing_event_line import SowingEventLine
from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    production_system_service,
    sowing_service,
    workflow_service,
)
from tests.conftest import ensure_seed_tray_specification


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


def _fail_audit_event(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise _ForcedFailure("forced failure during audit event creation")

    monkeypatch.setattr(sowing_service, "append_audit_event", _raise)


def _build_scenario(db_session, tenant, user, farm):
    suffix = uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg", scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code=None, is_start=False, is_terminal=True,
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
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id, code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, 3)
    ]
    return {"batch": batch, "seed_lot": seed_lot, "carriers": carriers}


def _lines(scenario):
    return [
        {
            "carrier_id": c.id, "seed_lot_id": scenario["seed_lot"].id, "sown_site_count": 200,
            "seed_count": 200, "line_note": None,
        }
        for c in scenario["carriers"]
    ]


def _assert_no_partial_writes(db_session, tenant, s) -> None:
    """Scoped to this test's own tenant/batch — never a bare table-wide
    count, which would be corrupted by committed rows any other test (e.g.
    CMP-011's dedicated-connection scenarios, which also call sow_batch) has
    left in the shared database."""
    assert db_session.execute(
        select(func.count()).select_from(SowingEvent).where(SowingEvent.batch_id == s["batch"].id)
    ).scalar_one() == 0
    assert db_session.execute(
        select(func.count()).select_from(BatchCarrierAssignment).where(
            BatchCarrierAssignment.batch_id == s["batch"].id
        )
    ).scalar_one() == 0
    assert db_session.execute(
        select(func.count()).select_from(SowingEventLine).where(SowingEventLine.tenant_id == tenant.id)
    ).scalar_one() == 0
    assert (
        db_session.execute(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "crop_batch.sown", AuditEvent.tenant_id == tenant.id
            )
        ).scalar_one()
        == 0
    )


def _assert_session_usable(db_session) -> None:
    db_session.execute(select(func.count()).select_from(SowingEvent)).scalar_one()


@pytest.mark.integration
def test_rollback_after_event_insert_before_assignments(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _fail_before_flushing(db_session, new_types=(BatchCarrierAssignment,))

    with pytest.raises(_ForcedFailure):
        sowing_service.sow_batch(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None, lines=_lines(s),
        )

    _assert_no_partial_writes(db_session, tenant, s)
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_rollback_after_assignments_insert_before_lines(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _fail_before_flushing(db_session, new_types=(SowingEventLine,))

    with pytest.raises(_ForcedFailure):
        sowing_service.sow_batch(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None, lines=_lines(s),
        )

    _assert_no_partial_writes(db_session, tenant, s)
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_rollback_after_lines_insert_before_audit_and_commit(db_session, active_context_with_farm, monkeypatch) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _fail_audit_event(monkeypatch)  # fires after event + assignments + lines are all flushed

    with pytest.raises(_ForcedFailure):
        sowing_service.sow_batch(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None, lines=_lines(s),
        )

    _assert_no_partial_writes(db_session, tenant, s)
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_rollback_leaves_carriers_unassigned_and_batch_unchanged(db_session, active_context_with_farm, monkeypatch) -> None:
    from app.models.batch_stage_run import BatchStageRun
    from app.models.carrier import Carrier

    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    original_run = db_session.execute(
        select(BatchStageRun).where(BatchStageRun.batch_id == s["batch"].id)
    ).scalar_one()
    _fail_audit_event(monkeypatch)

    with pytest.raises(_ForcedFailure):
        sowing_service.sow_batch(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None, lines=_lines(s),
        )

    db_session.refresh(s["batch"])
    assert s["batch"].state == "active"
    active_run = db_session.execute(
        select(BatchStageRun).where(BatchStageRun.batch_id == s["batch"].id, BatchStageRun.exited_effective_time.is_(None))
    ).scalar_one()
    assert active_run.id == original_run.id
    for carrier in s["carriers"]:
        db_session.refresh(db_session.get(Carrier, carrier.id))
    assert db_session.execute(
        select(func.count()).select_from(BatchCarrierAssignment).where(
            BatchCarrierAssignment.batch_id == s["batch"].id
        )
    ).scalar_one() == 0
    _assert_session_usable(db_session)
