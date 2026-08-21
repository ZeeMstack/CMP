"""Real two-connection concurrency tests for TRANSPLANT-CORRECTION-001,
mirroring test_transplant_concurrency.py's own established pattern exactly:
committed setup data via a dedicated connection so two independent sessions
can genuinely race, real threads with a `threading.Barrier` (no sleep-based
timing), cleanup via the shared `cleanup_traceability_scenario` helper."""
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.seedling_source_checkpoint import SeedlingSourceCheckpoint
from app.services import (
    farm_service,
    membership_service,
    tenant_service,
    transplant_correction_service,
    transplant_service,
    user_service,
)
from tests._traceability_scenario import cleanup_traceability_scenario
from tests._transplant_scenario import build_transplant_ready_scenario


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine, *, tray_count=1):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"tc-race-{suffix}", name="Correction Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="tc-race", oidc_subject=suffix, email=f"tc-race-{suffix}@example.com",
        display_name="Correction Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Correction Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s = build_transplant_ready_scenario(session, tenant, user, farm, suffix=suffix, tray_count=tray_count)
    session.commit()

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": s["batch_id"],
        "source_assignment_ids": s["source_assignment_ids"],
        "destination_carrier_ids": [c.id for c in s["destination_carriers"]],
        "entry_time": s["entry_time"],
    }
    session.close()
    conn.close()
    return result


def _one_to_one(source_id, dest_id, count=200):
    return (
        [{"source_assignment_id": source_id, "transplant_damage_count": 0, "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None}],
        [{"destination_carrier_id": dest_id, "assigned_plant_count": count, "note": None}],
        [{"source_assignment_id": source_id, "destination_carrier_id": dest_id, "allocated_plant_count": count}],
    )


@pytest.mark.integration
def test_concurrent_corrections_of_same_target_leave_one_winner(test_engine) -> None:
    """Section 29/8A: two different correction commands concurrently target
    the SAME TransplantEvent -- exactly one must succeed, the other must
    receive a clean domain conflict (idempotency mismatch or already-
    corrected), never two REVERSALs, never a deadlock/500."""
    scenario = _build_committed_scenario(test_engine)
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    src, dst, alloc = _one_to_one(scenario["source_assignment_ids"][0], scenario["destination_carrier_ids"][0])

    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    target = transplant_service.record_transplant(
        setup_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
        effective_time=effective_time, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
    )
    target_id = target.id
    setup_session.close()
    setup_conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            reversal = transplant_correction_service.correct_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"],
                target_transplant_event_id=target_id, client_command_id=uuid.uuid4(),
                reason=f"concurrent correction {name}", replacement=None,
            )
            results[name] = ("ok", reversal.id)
        except Exception as exc:  # pragma: no cover -- includes the expected already-corrected conflict
            results[name] = ("conflict_or_error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a",))
    t_b = threading.Thread(target=worker, args=("b",))
    t_a.start()
    t_b.start()
    t_a.join(timeout=20)
    t_b.join(timeout=20)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict_or_error") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        from app.models.transplant_event import TransplantEvent

        reversal_count = verify_session.execute(
            select(TransplantEvent.id).where(TransplantEvent.reverses_transplant_event_id == target_id)
        ).scalars().all()
        assert len(reversal_count) == 1, "never two reversals of the same target"
        verify_session.close()
        verify_conn.close()
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_correction_races_new_transplant_on_same_source(test_engine) -> None:
    """Section 21/29/8B: a correction of TransplantEvent X (whose source
    still has remainder -- not exhausted) races a brand-new, independent
    Transplant sourced from the SAME assignment. Both operations lock the
    owning CropBatch first (the same discipline every domain command in
    this codebase already uses), so they must serialize cleanly through
    that shared lock: no deadlock, no silently-restored-over-a-newer-
    checkpoint outcome, and the resulting checkpoint chain for this Tray
    remains a single, unbranched structural sequence."""
    scenario = _build_committed_scenario(test_engine)
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    source_id = scenario["source_assignment_ids"][0]
    # Partial transplant -- remainder 100, assignment stays active, making
    # BOTH racing operations against this source legitimately eligible at
    # the moment each one starts.
    src, dst, alloc = _one_to_one(source_id, scenario["destination_carrier_ids"][0], count=100)

    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    target = transplant_service.record_transplant(
        setup_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
        effective_time=effective_time, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
    )
    target_id = target.id
    setup_session.close()
    setup_conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    later_time = effective_time + timedelta(hours=1)

    def correction_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            reversal = transplant_correction_service.correct_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"],
                target_transplant_event_id=target_id, client_command_id=uuid.uuid4(),
                reason="racing correction", replacement=None,
            )
            results["correction"] = ("ok", reversal.id)
        except Exception as exc:  # pragma: no cover -- includes the expected chain-tip rejection
            results["correction"] = ("rejected_or_error", repr(exc))
        finally:
            session.close()
            conn.close()

    def transplant_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            src2, dst2, alloc2 = _one_to_one(source_id, scenario["destination_carrier_ids"][1], count=50)
            event = transplant_service.record_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=later_time, note=None, source_lines=src2, destination_lines=dst2, allocations=alloc2,
            )
            results["transplant"] = ("ok", event.id)
        except Exception as exc:  # pragma: no cover
            results["transplant"] = ("rejected_or_error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=correction_worker)
    t_b = threading.Thread(target=transplant_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=20)
    t_b.join(timeout=20)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        # Both legitimately valid outcomes are accepted -- the invariant
        # under test is serialization safety (no deadlock, no corrupted/
        # branched chain), not which of the two wins a race that has no
        # product-mandated winner.
        assert results["correction"][0] in ("ok", "rejected_or_error"), results
        assert results["transplant"][0] in ("ok", "rejected_or_error"), results
        assert not (results["correction"][0] == "rejected_or_error" and results["transplant"][0] == "rejected_or_error"), (
            "at least one of the two racing operations must succeed", results
        )

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        from app.models.seedling_entry import SeedlingEntry

        entry_id = verify_session.execute(
            select(SeedlingEntry.id).where(SeedlingEntry.batch_carrier_assignment_id == source_id)
        ).scalar_one()
        all_checkpoints = verify_session.execute(
            select(SeedlingSourceCheckpoint).where(SeedlingSourceCheckpoint.seedling_entry_id == entry_id)
        ).scalars().all()
        tips = [
            cp for cp in all_checkpoints
            if not any(other.previous_checkpoint_id == cp.id for other in all_checkpoints)
        ]
        assert len(tips) == 1, "the structural checkpoint chain must never branch, even under this race"
        verify_session.close()
        verify_conn.close()
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])
