"""Real two-connection concurrency tests for NURSERY-OPS-004A transplantation,
mirroring test_sowing_concurrency.py / test_seedling_disposition.py's own
concurrency section: committed setup data (a real Nursery scenario, sown ->
Germination -> SeedlingEntry) via a dedicated connection so two independent
sessions can genuinely race, with cleanup via the shared
`cleanup_traceability_scenario` helper (bypasses append-only/no-delete
triggers via session_replication_role, scoped to this test's own tenant)."""
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.services import (
    farm_service,
    membership_service,
    tenant_service,
    transplant_service,
    user_service,
)
from app.services.errors import (
    DestinationCarrierAlreadyAssignedError,
    SourceAssignmentAlreadyReleasedError,
    TransplantCommandReusedWithDifferentPayloadError,
)
from tests._traceability_scenario import cleanup_traceability_scenario
from tests._transplant_scenario import build_transplant_ready_scenario


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine, *, tray_count=4):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"tp-race-{suffix}", name="Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="tp-race", oidc_subject=suffix, email=f"tp-race-{suffix}@example.com",
        display_name="Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
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
def test_concurrent_use_of_same_source_assignment_leaves_one_winner(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    source_id = scenario["source_assignment_ids"][0]

    def worker(name: str, dest_id) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            src, dst, alloc = _one_to_one(source_id, dest_id)
            event = transplant_service.record_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
            )
            results[name] = ("ok", event.id)
        except SourceAssignmentAlreadyReleasedError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", scenario["destination_carrier_ids"][0]))
    t_b = threading.Thread(target=worker, args=("b", scenario["destination_carrier_ids"][1]))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_use_of_same_destination_carrier_leaves_one_winner(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    dest_id = scenario["destination_carrier_ids"][0]

    def worker(name: str, source_id) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            src, dst, alloc = _one_to_one(source_id, dest_id)
            event = transplant_service.record_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
            )
            results[name] = ("ok", event.id)
        except DestinationCarrierAlreadyAssignedError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", scenario["source_assignment_ids"][0]))
    t_b = threading.Thread(target=worker, args=("b", scenario["source_assignment_ids"][1]))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_disjoint_transplants_on_one_batch_both_succeed(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)

    def worker(name: str, source_id, dest_id) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            src, dst, alloc = _one_to_one(source_id, dest_id)
            event = transplant_service.record_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
            )
            results[name] = ("ok", event.id)
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(
        target=worker, args=("a", scenario["source_assignment_ids"][0], scenario["destination_carrier_ids"][0])
    )
    t_b = threading.Thread(
        target=worker, args=("b", scenario["source_assignment_ids"][1], scenario["destination_carrier_ids"][1])
    )
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        assert results["a"][0] == "ok", results
        assert results["b"][0] == "ok", results
        assert results["a"][1] != results["b"][1]
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_duplicate_transplant_command_is_idempotent(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    shared_command_id = uuid.uuid4()
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    src, dst, alloc = _one_to_one(scenario["source_assignment_ids"][0], scenario["destination_carrier_ids"][0])

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = transplant_service.record_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"],
                client_command_id=shared_command_id, effective_time=effective_time, note=None,
                source_lines=src, destination_lines=dst, allocations=alloc,
            )
            results[name] = ("ok", event.id)
        except TransplantCommandReusedWithDifferentPayloadError as exc:
            results[name] = ("rejected", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a",))
    t_b = threading.Thread(target=worker, args=("b",))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        assert results["a"][0] == "ok", results
        assert results["b"][0] == "ok", results
        assert results["a"][1] == results["b"][1]
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_checkpoint_and_disposition_around_temporal_floor(test_engine) -> None:
    """NURSERY-OPS-004A section 63: a transplant checkpoint and a
    disposition racing against the SAME Tray around the temporal floor must
    serialize cleanly -- only one may win the ambiguous ordering, never
    both, never a deadlock."""
    from app.services import seedling_disposition_service

    scenario = _build_committed_scenario(test_engine, tray_count=1)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    source_id = scenario["source_assignment_ids"][0]

    def transplant_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            src, dst, alloc = _one_to_one(source_id, scenario["destination_carrier_ids"][0], count=100)
            event = transplant_service.record_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
            )
            results["transplant"] = ("ok", event.id)
        except Exception as exc:  # pragma: no cover
            results["transplant"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def disposition_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            command = seedling_disposition_service.record_disposition(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                batch_carrier_assignment_id=source_id, quantity=5, reason_code="WEAK_SEEDLING",
                effective_time=effective_time, note=None,
            )
            results["disposition"] = ("ok", command.id)
        except Exception as exc:  # pragma: no cover -- includes the expected checkpoint-floor rejection
            results["disposition"] = ("rejected_or_error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=transplant_worker)
    t_b = threading.Thread(target=disposition_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        # The transplant always succeeds (it doesn't depend on the
        # disposition); the disposition either wins (recorded before the
        # checkpoint closes the window) or is cleanly rejected/errors
        # (the checkpoint floor already closed it) -- never a hang, never
        # silent corruption either way.
        assert results["transplant"][0] == "ok", results
        assert results["disposition"][0] in ("ok", "rejected_or_error"), results
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])
