"""Proves that record_transplant rolls back every partial write when a
failure occurs after one or more flushes have already succeeded (using the
established before_flush / audit-monkeypatch techniques from
test_sowing_rollback.py / test_observation_quality_rollback.py), against
NURSERY-OPS-004A's actual write order -- TransplantEvent -> TransplantSourceLine(s)
-> destination BatchCarrierAssignment(s) -> TransplantDestinationLine(s) ->
TransplantAllocation(s) -> SeedlingSourceCheckpoint(s) -> conditional source
release (moved to the END, after checkpoint insertion, per the documented
write-order bug fix: releasing a source assignment before its own
checkpoint exists would trip the checkpoint insert-integrity trigger's own
"already released" guard against itself) -- and separately proves that the
CMP-011 deferred reconciliation constraint triggers genuinely fire at a real
transaction commit boundary -- not at INSERT time -- by committing on a
dedicated connection and attempting a direct-SQL mutation against an
already-committed event. Scenario setup uses the shared
`build_transplant_ready_scenario` helper (real sow -> Germination ->
SeedlingEntry pipeline), matching every other NURSERY-OPS-004A transplant
test file."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.seedling_source_checkpoint import SeedlingSourceCheckpoint
from app.models.transplant_allocation import TransplantAllocation
from app.models.transplant_destination_line import TransplantDestinationLine
from app.models.transplant_event import TransplantEvent
from app.models.transplant_source_line import TransplantSourceLine
from app.services import carrier_service, transplant_service
from tests._traceability_scenario import cleanup_traceability_scenario
from tests._transplant_scenario import build_transplant_ready_scenario


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
    return build_transplant_ready_scenario(db_session, tenant, user, farm, tray_count=2)


def _lines(s):
    dest = s["destination_carriers"][:2]
    source_lines = [
        {
            "source_assignment_id": aid, "transplant_damage_count": 0, "qc_rejection_count": 0,
            "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
        }
        for aid in s["source_assignment_ids"]
    ]
    destination_lines = [
        {"destination_carrier_id": c.id, "assigned_plant_count": s["starting"], "note": None} for c in dest
    ]
    allocations = [
        {"source_assignment_id": aid, "destination_carrier_id": c.id, "allocated_plant_count": s["starting"]}
        for aid, c in zip(s["source_assignment_ids"], dest)
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
    """Scoped to this test's own tenant/batch/assignments/carriers -- never a
    bare table-wide count, which would be corrupted by committed rows any
    other test (in this file or elsewhere) has left in the shared database."""
    assert db_session.execute(
        select(func.count()).select_from(TransplantEvent).where(TransplantEvent.batch_id == s["batch_id"])
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
    assert db_session.execute(
        select(func.count()).select_from(SeedlingSourceCheckpoint).where(
            SeedlingSourceCheckpoint.batch_id == s["batch_id"]
        )
    ).scalar_one() == 0


def _assert_no_destination_assignments(db_session, s) -> None:
    assert db_session.execute(
        select(func.count()).select_from(BatchCarrierAssignment).where(
            BatchCarrierAssignment.carrier_id.in_([c.id for c in s["destination_carriers"]])
        )
    ).scalar_one() == 0


def _assert_sources_not_released(db_session, s) -> None:
    for aid in s["source_assignment_ids"]:
        assert db_session.get(BatchCarrierAssignment, aid).released_effective_time is None


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
    _assert_sources_not_released(db_session, s)
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_rollback_after_source_lines_before_destination_assignments(db_session, active_context_with_farm) -> None:
    """NURSERY-OPS-004A's write order opens destination BatchCarrierAssignment
    rows immediately after the source lines -- well before source release,
    which is now the LAST write before the audit event. Targeting `new`
    BatchCarrierAssignment therefore fires exactly here, not at release."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines, destination_lines, allocations = _lines(s)
    _fail_before_flushing(db_session, new_types=(BatchCarrierAssignment,))

    with pytest.raises(_ForcedFailure):
        _run(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    _assert_no_partial_writes(db_session, tenant, s)
    _assert_sources_not_released(db_session, s)
    _assert_no_destination_assignments(db_session, s)
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
    _assert_sources_not_released(db_session, s)
    _assert_no_destination_assignments(db_session, s)
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
    _assert_sources_not_released(db_session, s)
    _assert_no_destination_assignments(db_session, s)
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_rollback_after_allocations_before_checkpoints(db_session, active_context_with_farm) -> None:
    """NURSERY-OPS-004A section 10/22: checkpoints are inserted last of all
    the "new row" writes, after allocations exist -- a failure here must
    still unwind the event, source lines, destination assignments,
    destination lines, and allocations together."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines, destination_lines, allocations = _lines(s)
    _fail_before_flushing(db_session, new_types=(SeedlingSourceCheckpoint,))

    with pytest.raises(_ForcedFailure):
        _run(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    _assert_no_partial_writes(db_session, tenant, s)
    _assert_sources_not_released(db_session, s)
    _assert_no_destination_assignments(db_session, s)
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_rollback_after_checkpoints_before_release(db_session, active_context_with_farm) -> None:
    """NURSERY-OPS-004A's own write-order bug fix: conditional source
    release is the LAST row-level write, strictly after its own checkpoint
    has already been inserted. A failure here must roll back the
    checkpoint(s) too, not just leave the release un-applied."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines, destination_lines, allocations = _lines(s)
    _fail_before_flushing(db_session, dirty_types=(BatchCarrierAssignment,))

    with pytest.raises(_ForcedFailure):
        _run(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    _assert_no_partial_writes(db_session, tenant, s)
    _assert_sources_not_released(db_session, s)
    _assert_no_destination_assignments(db_session, s)
    _assert_session_usable(db_session)


@pytest.mark.integration
def test_rollback_after_release_before_audit(db_session, active_context_with_farm, monkeypatch) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines, destination_lines, allocations = _lines(s)
    _fail_audit_event(monkeypatch)

    with pytest.raises(_ForcedFailure):
        _run(db_session, tenant, farm, user, s["batch"], source_lines, destination_lines, allocations)

    _assert_no_partial_writes(db_session, tenant, s)
    _assert_sources_not_released(db_session, s)
    _assert_no_destination_assignments(db_session, s)
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
# record_transplant's internal commit is a genuine top-level commit -- that's
# what lets the deferred constraint trigger fire at the real commit boundary
# they're testing. That commit is real and permanent (the append-only
# triggers reject a plain DELETE), so each test cleans up everything it
# committed, for its own tenant only, via the shared
# `cleanup_traceability_scenario` helper (bypasses append-only/no-delete
# triggers via session_replication_role) -- the same helper
# test_transplant_concurrency.py already uses, and the only one that knows
# how to unwind a real Nursery scenario's full table set (sowing,
# Germination, SeedlingEntry, SeedlingSourceCheckpoint, assets). This keeps
# the test repeatable against the same database and keeps other tests (e.g.
# the CMP-011 downgrade-guard proofs, or test_migrations.py's clean-downgrade
# cycle) from ever observing this test's committed workflow/sowing/transplant
# history.


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
        s = build_transplant_ready_scenario(session, tenant, user, farm, suffix=suffix, tray_count=2)
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
        # already allocated together by the real command -- determined by
        # explicitly checking transplant_allocations, not by guessing from
        # independent UUID sort order (two tables' UUIDs sort independently
        # of which source was originally zipped with which destination, so
        # an index-based guess can coincidentally land on an already-used
        # pair and fail with ux_transplant_allocations_pair instead of
        # reaching the deferred reconciliation check this test targets).
        # This still pushes both lines' totals over their own counts. The
        # INSERT itself succeeds (the deferred trigger doesn't run yet);
        # only the real commit -- where the deferred constraint trigger
        # fires -- must reject it.
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
            cleanup_traceability_scenario(test_engine, tenant_id)


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
        s = build_transplant_ready_scenario(session, tenant, user, farm, suffix=suffix, tray_count=2)
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
        new_assignment_id = uuid.uuid4()
        session.execute(
            text(
                "INSERT INTO batch_carrier_assignments (id, tenant_id, farm_id, batch_id, carrier_id, "
                "batch_stage_run_id, assigned_effective_time, opening_transplant_event_id, "
                "population_root_batch_carrier_assignment_id, actor_user_id) "
                "VALUES (:id, :tenant_id, :farm_id, :batch_id, :carrier_id, :run_id, :eff, :event_id, :id, :actor)"
            ),
            {
                "id": new_assignment_id, "tenant_id": tenant.id, "farm_id": farm.id, "batch_id": s["batch_id"],
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
            cleanup_traceability_scenario(test_engine, tenant_id)
