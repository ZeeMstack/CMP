"""NURSERY-OPS-004B.0: proves the `_record_transplant_core` / `record_transplant`
split itself -- not domain behavior (already exhaustively covered by
test_transplant.py/test_transplant_acceptance.py/test_transplant_concurrency.py/
test_transplant_rollback.py/test_transplant_downgrade_guard.py/
test_seedling_source_checkpoint.py, all of which stay green, unmodified, after
this refactor). Specifically:

1. `_record_transplant_core` does NOT commit -- its writes are visible within
   the same session before any commit, and vanish entirely on an explicit
   `db.rollback()` at the caller's own discretion.
2. A caller can compose the core's writes with its OWN additional write in the
   same transaction and commit both together in one call -- proving the
   composition a future NURSERY-OPS-004B InterSalads orchestration will need
   is genuinely possible today, without building any InterSalads scaffolding
   here (per the ticket's own explicit instruction not to).
3. The public `record_transplant` wrapper still commits exactly as before,
   provable from a second, independent connection."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.seedling_source_checkpoint import SeedlingSourceCheckpoint
from app.models.transplant_event import TransplantEvent
from app.services import transplant_service
from app.services.audit import append_audit_event
from tests._traceability_scenario import cleanup_traceability_scenario
from tests._transplant_scenario import build_transplant_ready_scenario


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(db_session, tenant, user, farm):
    return build_transplant_ready_scenario(db_session, tenant, user, farm, tray_count=1)


def _lines(s):
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    source_lines = [
        {
            "source_assignment_id": aid, "transplant_damage_count": 0, "qc_rejection_count": 0,
            "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
        }
    ]
    destination_lines = [{"destination_carrier_id": dest.id, "assigned_plant_count": s["starting"], "note": None}]
    allocations = [
        {"source_assignment_id": aid, "destination_carrier_id": dest.id, "allocated_plant_count": s["starting"]}
    ]
    return source_lines, destination_lines, allocations


def _event_row_count(db_session, event_id) -> int:
    return db_session.execute(
        select(func.count()).select_from(TransplantEvent).where(TransplantEvent.id == event_id)
    ).scalar_one()


def _checkpoint_count_for_batch(db_session, batch_id) -> int:
    return db_session.execute(
        select(func.count()).select_from(SeedlingSourceCheckpoint).where(SeedlingSourceCheckpoint.batch_id == batch_id)
    ).scalar_one()


@pytest.mark.integration
def test_core_writes_visible_in_session_but_not_committed(db_session, active_context_with_farm) -> None:
    """Section 16: the core's writes are readable within the SAME session
    immediately after it returns (proving it actually wrote and flushed),
    but an explicit `db.rollback()` at the caller's own discretion discards
    every one of them -- proving the core itself never committed."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines, destination_lines, allocations = _lines(s)
    aid = s["source_assignment_ids"][0]

    event, is_new = transplant_service._record_transplant_core(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
    )
    assert is_new is True
    event_id = event.id

    # Visible within this same, still-uncommitted session/transaction.
    assert _event_row_count(db_session, event_id) == 1
    assert _checkpoint_count_for_batch(db_session, s["batch"].id) == 1
    assert db_session.get(BatchCarrierAssignment, aid).released_effective_time is not None

    db_session.rollback()

    # Nothing survives -- the core itself never called db.commit().
    assert _event_row_count(db_session, event_id) == 0
    assert _checkpoint_count_for_batch(db_session, s["batch"].id) == 0
    # The source assignment row itself predates this test (created by the
    # scenario builder's own earlier, separate flush) and so still exists,
    # but its release must have rolled back along with everything else.
    assert db_session.get(BatchCarrierAssignment, aid).released_effective_time is None


@pytest.mark.integration
def test_caller_can_compose_core_with_its_own_write_under_one_commit(db_session, active_context_with_farm) -> None:
    """Section 17: proves the exact composition NURSERY-OPS-004B needs --
    a caller invokes `_record_transplant_core`, then performs its OWN
    additional domain write (here, a second, independent audit event -- a
    stand-in for a future orchestration's own destination-placement write,
    without building any InterSalads scaffolding), then commits ONCE. Both
    the core's writes and the caller's own write must survive together."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    source_lines, destination_lines, allocations = _lines(s)

    event, is_new = transplant_service._record_transplant_core(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
    )
    assert is_new is True

    # The caller's own additional composable write, in the SAME transaction
    # the core just wrote into -- nothing here has been committed yet.
    caller_audit = append_audit_event(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, action="test.caller_composed_write",
        entity_type="transplant_event", entity_id=event.id, event_data={"proof": "composition"},
    )
    db_session.flush()
    caller_audit_id = caller_audit.id

    db_session.commit()
    db_session.refresh(event)

    # Both survive the single, caller-owned commit.
    assert _event_row_count(db_session, event.id) == 1
    assert db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.id == caller_audit_id)
    ).scalar_one() == 1
    assert db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "crop_batch.transplanted", AuditEvent.entity_id == event.id
        )
    ).scalar_one() == 1


@pytest.mark.integration
def test_public_wrapper_still_commits_visible_from_second_connection(test_engine) -> None:
    """Section 18: the public `record_transplant` wrapper must still commit
    exactly as before this refactor -- proven from a genuinely independent
    second connection/session, not merely the same session's own read."""
    from app.services import farm_service, membership_service, tenant_service, user_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant = tenant_service.create_tenant(session, code=f"tp-core-{suffix}", name="Core Tenant")
        tenant_id = tenant.id
        user = user_service.create_user(
            session, oidc_issuer="tp-core", oidc_subject=suffix, email=f"tp-core-{suffix}@example.com",
            display_name="Core User",
        )
        membership_service.add_membership(
            session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
        )
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Core Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        s = build_transplant_ready_scenario(session, tenant, user, farm, suffix=suffix, tray_count=1)
        session.commit()
        source_lines, destination_lines, allocations = _lines(s)

        event = transplant_service.record_transplant(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
            source_lines=source_lines, destination_lines=destination_lines, allocations=allocations,
        )
        event_id = event.id

        with test_engine.connect() as verify_conn:
            second_session = Session(bind=verify_conn)
            try:
                assert _event_row_count(second_session, event_id) == 1
                assert _checkpoint_count_for_batch(second_session, s["batch"].id) == 1
            finally:
                second_session.close()
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
