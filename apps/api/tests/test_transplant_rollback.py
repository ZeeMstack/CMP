"""Proves that record_transplant rolls back every partial write when a
failure occurs after one or more flushes have already succeeded (using the
established before_flush / audit-monkeypatch techniques from
test_sowing_rollback.py / test_observation_quality_rollback.py), and
separately proves that the CMP-011 deferred reconciliation constraint
triggers genuinely fire at a real transaction commit boundary — not at
INSERT time — by committing on a dedicated connection and attempting a
direct-SQL mutation against an already-committed event."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.transplant_allocation import TransplantAllocation
from app.models.transplant_destination_line import TransplantDestinationLine
from app.models.transplant_event import TransplantEvent
from app.models.transplant_source_line import TransplantSourceLine
from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    production_system_service,
    sowing_service,
    transplant_service,
    workflow_service,
)


class _ForcedFailure(Exception):
    """Distinct marker exception so assertions can't accidentally match a
    real domain or database error."""


def _now():
    return datetime.now(timezone.utc)


def _fail_before_flushing(session, *, new_types=(), dirty_types=()):
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

    monkeypatch.setattr(transplant_service, "append_audit_event", _raise)


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
    transplanting = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="TRANSPLANTING", name="Transplanting", display_order=1, stage_category="transplanting",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="cultivation_plate", is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=transplanting.id, code="ADVANCE-1", name="Advance 1",
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=transplanting.id, to_stage_id=complete.id, code="ADVANCE-2", name="Advance 2",
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
    source_carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, 3)
    ]
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[
            {"carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 200, "seed_count": 200, "line_note": None}
            for c in source_carriers
        ],
    )
    assignments = sowing_service.list_batch_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assignment_by_carrier_code = {a.carrier.code: a.id for a in assignments}
    source_assignment_ids = [assignment_by_carrier_code[c.code] for c in source_carriers]

    crop_batch_service.transition_stage(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=_now(), reason=None,
    )
    destination_carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="cultivation_plate", code=f"CP-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, 3)
    ]
    return {"batch": batch, "source_assignment_ids": source_assignment_ids, "destination_carriers": destination_carriers}


def _lines(s):
    source_lines = [
        {"source_assignment_id": aid, "source_plant_count": 200, "discarded_plant_count": 0, "note": None}
        for aid in s["source_assignment_ids"]
    ]
    destination_lines = [
        {"destination_carrier_id": c.id, "assigned_plant_count": 200, "note": None} for c in s["destination_carriers"]
    ]
    allocations = [
        {"source_assignment_id": aid, "destination_carrier_id": c.id, "allocated_plant_count": 200}
        for aid, c in zip(s["source_assignment_ids"], s["destination_carriers"])
    ]
    return source_lines, destination_lines, allocations


def _run(db_session, tenant, farm, user, batch, source_lines, destination_lines, allocations, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
    )
    defaults.update(overrides)
    return transplant_service.record_transplant(
        db_session, source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        **defaults,
    )


def _assert_no_partial_writes(db_session, tenant, s) -> None:
    """Scoped to this test's own tenant/batch/assignments/carriers — never a
    bare table-wide count, which would be corrupted by committed rows any
    other test (in this file or elsewhere) has left in the shared database."""
    assert db_session.execute(
        select(func.count()).select_from(TransplantEvent).where(TransplantEvent.batch_id == s["batch"].id)
    ).scalar_one() == 0
    assert db_session.execute(
        select(func.count()).select_from(TransplantSourceLine).where(
            TransplantSourceLine.source_batch_carrier_assignment_id.in_(s["source_assignment_ids"])
        )
    ).scalar_one() == 0
    assert db_session.execute(
        select(func.count()).select_from(TransplantDestinationLine).where(
            TransplantDestinationLine.destination_carrier_id.in_([c.id for c in s["destination_carriers"]])
        )
    ).scalar_one() == 0
    assert db_session.execute(
        select(func.count()).select_from(TransplantAllocation).where(TransplantAllocation.tenant_id == tenant.id)
    ).scalar_one() == 0


def _assert_session_usable(db_session) -> None:
    db_session.execute(select(func.count()).select_from(TransplantEvent)).scalar_one()


# --- In-memory rollback (before_flush / audit monkeypatch) ---------------------------


@pytest.mark.integration
def test_rollback_after_event_insert_before_source_lines(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines, destination_lines, allocations = _lines(s)
    _fail_before_flushing(db_session, new_types=(TransplantSourceLine,))

    with pytest.raises(_ForcedFailure):
        _run(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    _assert_no_partial_writes(db_session, tenant, s)
    for aid in s["source_assignment_ids"]:
        assert db_session.get(BatchCarrierAssignment, aid).released_effective_time is None
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_rollback_after_source_release_before_destination_assignments(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines, destination_lines, allocations = _lines(s)
    # BatchCarrierAssignment appears both as a "dirty" object (source release)
    # and a "new" object (destination open) within this command; targeting
    # "new" fires strictly after the release update has already been flushed.
    _fail_before_flushing(db_session, new_types=(BatchCarrierAssignment,))

    with pytest.raises(_ForcedFailure):
        _run(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    _assert_no_partial_writes(db_session, tenant, s)
    for aid in s["source_assignment_ids"]:
        assert db_session.get(BatchCarrierAssignment, aid).released_effective_time is None
    assert db_session.execute(
        select(func.count()).select_from(BatchCarrierAssignment).where(
            BatchCarrierAssignment.carrier_id.in_([c.id for c in s["destination_carriers"]])
        )
    ).scalar_one() == 0
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_rollback_after_destination_assignments_before_destination_lines(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines, destination_lines, allocations = _lines(s)
    _fail_before_flushing(db_session, new_types=(TransplantDestinationLine,))

    with pytest.raises(_ForcedFailure):
        _run(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    _assert_no_partial_writes(db_session, tenant, s)
    for aid in s["source_assignment_ids"]:
        assert db_session.get(BatchCarrierAssignment, aid).released_effective_time is None
    assert db_session.execute(
        select(func.count()).select_from(BatchCarrierAssignment).where(
            BatchCarrierAssignment.carrier_id.in_([c.id for c in s["destination_carriers"]])
        )
    ).scalar_one() == 0
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_rollback_after_destination_lines_before_allocations(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines, destination_lines, allocations = _lines(s)
    _fail_before_flushing(db_session, new_types=(TransplantAllocation,))

    with pytest.raises(_ForcedFailure):
        _run(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    _assert_no_partial_writes(db_session, tenant, s)
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_rollback_after_allocations_before_audit(db_session, active_context_with_farm, monkeypatch) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines, destination_lines, allocations = _lines(s)
    _fail_audit_event(monkeypatch)

    with pytest.raises(_ForcedFailure):
        _run(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    _assert_no_partial_writes(db_session, tenant, s)
    for aid in s["source_assignment_ids"]:
        assert db_session.get(BatchCarrierAssignment, aid).released_effective_time is None
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_reused_integrity_error_rolls_back_before_requery(db_session, active_context_with_farm) -> None:
    """A duplicate client_command_id surfaces as an IntegrityError on the
    event's own flush; the handler must roll back before re-querying for
    the idempotent replay."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines, destination_lines, allocations = _lines(s)
    command_id = uuid.uuid4()
    first = _run(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        client_command_id=command_id,
    )
    replay = _run(
        db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations,
        client_command_id=command_id, effective_time=first.effective_time,
    )
    assert replay.id == first.id
    _assert_session_usable(db_session)


# --- Deferred reconciliation: real commit boundary ------------------------------------
#
# Both tests below build their scenario on a dedicated connection so
# record_transplant's internal commit is a genuine top-level commit — that's
# what lets the deferred constraint trigger fire at the real commit boundary
# they're testing. That commit is real and permanent (the append-only
# triggers reject a plain DELETE), so each test cleans up everything it
# committed, for its own tenant only, in a `finally` block using
# `session_replication_role = replica` — the same technique
# test_transplant_concurrency.py already uses. This keeps the test repeatable
# against the same database and keeps other tests (e.g. the CMP-011
# downgrade-guard proofs, or test_migrations.py's clean-downgrade cycle) from
# ever observing this test's committed workflow/sowing/transplant history.


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    """Deletes every row this test committed for its own tenant, bypassing
    the append-only/no-delete triggers via session_replication_role. Never
    relies on connection-close, rollback, or Postgres's transactional GUC
    behavior alone to restore session_replication_role — it is always
    explicitly reset to DEFAULT before the connection is released, on both
    the success and failure paths."""
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup (session_replication_role) against "
            f"database {current_db!r}; this cleanup is only permitted against 'cmp_test'"
        )

    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM transplant_allocations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_destination_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_event_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_carrier_assignments WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM seed_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_runs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crop_batches WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_stages WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_versions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflows WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM production_systems WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM varieties WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crops WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    except Exception:
        # The transaction is now aborted; Postgres rejects any further
        # statement (including SET ... = DEFAULT) until it is rolled back.
        # Roll back first, then explicitly restore DEFAULT as its own
        # statement and commit that restoration on its own — never rely on
        # rollback's GUC-reset behavior alone to undo replica mode.
        trans.rollback()
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        raise
    else:
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_deferred_trigger_rejects_direct_sql_extra_allocation_on_committed_event(test_engine) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant = tenant_service.create_tenant(session, code=f"tp-defer-{suffix}", name="Defer Tenant")
        tenant_id = tenant.id
        user = user_service.create_user(
            session, oidc_issuer="tp-defer", oidc_subject=suffix, email=f"tp-defer-{suffix}@example.com",
            display_name="Defer User",
        )
        membership_service.add_membership(
            session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
        )
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Defer Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        s = _build_scenario(session, tenant, user, farm)
        source_lines, destination_lines, allocations = _lines(s)
        event_row = _run(session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

        source_line_ids = list(
            session.execute(
                select(TransplantSourceLine.id)
                .where(TransplantSourceLine.transplant_event_id == event_row.id)
                .order_by(TransplantSourceLine.id)
            ).scalars()
        )
        destination_line_ids = list(
            session.execute(
                select(TransplantDestinationLine.id)
                .where(TransplantDestinationLine.transplant_event_id == event_row.id)
                .order_by(TransplantDestinationLine.id)
            ).scalars()
        )
        existing_pairs = set(
            session.execute(
                select(TransplantAllocation.source_line_id, TransplantAllocation.destination_line_id).where(
                    TransplantAllocation.transplant_event_id == event_row.id
                )
            ).all()
        )
        # Cross-pair a source line with a destination line that was NOT
        # already allocated together by the real command — determined by
        # explicitly checking transplant_allocations, not by guessing from
        # independent UUID sort order (two tables' UUIDs sort independently
        # of which source was originally zipped with which destination, so
        # an index-based guess can coincidentally land on an already-used
        # pair and fail with ux_transplant_allocations_pair instead of
        # reaching the deferred reconciliation check this test targets).
        # This still pushes both lines' totals over their own counts. The
        # INSERT itself succeeds (the deferred trigger doesn't run yet);
        # only the real commit — where the deferred constraint trigger
        # fires — must reject it.
        source_line_id, destination_line_id = next(
            (sid, did)
            for sid in source_line_ids
            for did in destination_line_ids
            if (sid, did) not in existing_pairs
        )
        session.execute(
            text(
                "INSERT INTO transplant_allocations (id, tenant_id, farm_id, transplant_event_id, source_line_id, "
                "destination_line_id, allocated_plant_count) VALUES "
                "(:id, :tenant_id, :farm_id, :event_id, :source_line_id, :destination_line_id, 50)"
            ),
            {
                "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id, "event_id": event_row.id,
                "source_line_id": source_line_id, "destination_line_id": destination_line_id,
            },
        )
        with pytest.raises(Exception, match="reconcile|does not reconcile|transplant event"):
            session.commit()
        session.rollback()
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_deferred_trigger_rejects_direct_sql_unmatched_destination_open(test_engine) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant = tenant_service.create_tenant(session, code=f"tp-defer2-{suffix}", name="Defer Tenant 2")
        tenant_id = tenant.id
        user = user_service.create_user(
            session, oidc_issuer="tp-defer2", oidc_subject=suffix, email=f"tp-defer2-{suffix}@example.com",
            display_name="Defer User 2",
        )
        membership_service.add_membership(
            session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
        )
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Defer Farm 2",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        s = _build_scenario(session, tenant, user, farm)
        source_lines, destination_lines, allocations = _lines(s)
        event_row = _run(session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

        active_run_id = session.execute(
            text("SELECT active_batch_stage_run_id FROM transplant_events WHERE id = :id"), {"id": event_row.id}
        ).scalar_one()
        extra_carrier = carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="cultivation_plate", code="CP-EXTRA-DEFER", issued_date=None,
        )
        # Opens a new transplant-origin assignment for this already-committed
        # event without ever inserting a matching transplant_destination_line.
        session.execute(
            text(
                "INSERT INTO batch_carrier_assignments (id, tenant_id, farm_id, batch_id, carrier_id, "
                "batch_stage_run_id, assigned_effective_time, opening_transplant_event_id, actor_user_id) "
                "VALUES (:id, :tenant_id, :farm_id, :batch_id, :carrier_id, :run_id, :eff, :event_id, :actor)"
            ),
            {
                "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id, "batch_id": s["batch"].id,
                "carrier_id": extra_carrier.id, "run_id": active_run_id, "eff": event_row.effective_time,
                "event_id": event_row.id, "actor": user.id,
            },
        )
        with pytest.raises(Exception, match="destination line|transplant event"):
            session.commit()
        session.rollback()
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup_scenario(test_engine, tenant_id)
