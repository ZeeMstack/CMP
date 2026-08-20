"""NURSERY-OPS-004B.1: real two-connection concurrency tests for the
composite InterSalads Transplant command, mirroring
`test_transplant_concurrency.py`'s own established pattern (committed setup
via a dedicated connection, `threading.Barrier`-released racing workers on
independent connections/sessions, cleanup via `cleanup_traceability_scenario`).

Per this session's own prior finding (a barrier-released two-thread race is
inherently non-deterministic by construction, not merely occasionally flaky):
these tests assert the LEGAL outcome SET the transaction semantics guarantee
(e.g. "exactly one ok, one conflict"), never a specific thread winning, and
never use sleeps as the synchronization mechanism."""
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.services import (
    carrier_specification_service,
    farm_service,
    intersalads_transplant_service,
    membership_service,
    tenant_service,
    user_service,
)
from app.services.errors import (
    DestinationCarrierAlreadyAssignedError,
    InvalidTransplantEffectiveTimeError,
    SourceAssignmentAlreadyReleasedError,
    TargetOccupiedError,
)
from tests._traceability_scenario import cleanup_traceability_scenario
from tests._transplant_scenario import build_transplant_ready_scenario

DESTINATION_TYPE = "nursery_cultivation_plate"


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine, *, tray_count=4, intersalads_table_count=2, intersalads_table_capacity=4):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"ist-race-{suffix}", name="Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="ist-race", oidc_subject=suffix, email=f"ist-race-{suffix}@example.com",
        display_name="Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    spec = carrier_specification_service.register_carrier_specification(
        session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=DESTINATION_TYPE,
        code=f"NCP-{suffix}", name="Race Plate", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=200,
    )
    s = build_transplant_ready_scenario(
        session, tenant, user, farm, suffix=suffix, tray_count=tray_count,
        transplanting_required_type=DESTINATION_TYPE, destination_specification_id=spec.id,
        intersalads_table_count=intersalads_table_count, intersalads_table_capacity=intersalads_table_capacity,
    )
    session.commit()

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": s["batch_id"],
        "source_assignment_ids": s["source_assignment_ids"],
        "destination_carrier_ids": [c.id for c in s["destination_carriers"]],
        "intersalads_table_ids": s["intersalads_table_ids"],
        "entry_time": s["entry_time"],
    }
    session.close()
    conn.close()
    return result


def _one_to_one(source_id, dest_id, location_id, count=150):
    return (
        [{"source_assignment_id": source_id, "transplant_damage_count": 0, "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None}],
        [{"destination_carrier_id": dest_id, "assigned_plant_count": count, "destination_location_id": location_id, "note": None}],
        [{"source_assignment_id": source_id, "destination_carrier_id": dest_id, "allocated_plant_count": count}],
    )


@pytest.mark.integration
def test_concurrent_same_destination_plate_leaves_one_winner(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    dest_id = scenario["destination_carrier_ids"][0]
    table_id = scenario["intersalads_table_ids"][0]

    def worker(name: str, source_id) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            src, dst, alloc = _one_to_one(source_id, dest_id, table_id)
            result = intersalads_transplant_service.record_intersalads_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
            )
            results[name] = ("ok", result.id)
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
def test_concurrent_same_source_tray_leaves_one_winner(test_engine) -> None:
    """Two legitimate ways for the losing concurrent transplant against the
    same source to fail, both proving the same underlying guarantee (the
    source's balance is never double-spent): either it observes the
    assignment already released (`SourceAssignmentAlreadyReleasedError`), or
    -- when both commands share the exact same `effective_time`, as these
    two deliberately do -- it observes the winner's freshly-committed
    checkpoint and correctly refuses to backdate behind it
    (`InvalidTransplantEffectiveTimeError`). Both are the shared
    `_record_transplant_core`'s own existing, unmodified concurrency
    protection; the composite command adds no new locking here."""
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    source_id = scenario["source_assignment_ids"][0]

    def worker(name: str, dest_id, location_id) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            src, dst, alloc = _one_to_one(source_id, dest_id, location_id)
            result = intersalads_transplant_service.record_intersalads_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
            )
            results[name] = ("ok", result.id)
        except (SourceAssignmentAlreadyReleasedError, InvalidTransplantEffectiveTimeError) as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(
        target=worker, args=("a", scenario["destination_carrier_ids"][0], scenario["intersalads_table_ids"][0])
    )
    t_b = threading.Thread(
        target=worker, args=("b", scenario["destination_carrier_ids"][1], scenario["intersalads_table_ids"][1])
    )
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
def test_concurrent_opposite_order_multi_destination_commands_do_not_deadlock(test_engine) -> None:
    """Pre-commit audit finding (BLOCKER, fixed in this same change):
    two composite commands from two INDEPENDENT Crop Batches (so the
    CropBatch-row lock `_record_transplant_core` holds does NOT serialize
    them against each other) each place two Plates onto the SAME two
    InterSalads Tables, in OPPOSITE order:

        Command A: Plate A1 -> Table 1, Plate A2 -> Table 2
        Command B: Plate B1 -> Table 2, Plate B2 -> Table 1

    Proven directly (outside this test, via a minimal two-connection
    `SELECT ... FOR UPDATE` reproduction) that PostgreSQL raises
    `deadlock detected` (SQLSTATE 40P01) within ~1s for exactly this lock-
    order-inversion pattern, uncaught by any existing exception handling.
    `intersalads_transplant_service._lock_destination_locations_in_order`
    closes this by locking every distinct destination Location in
    deterministic (sorted) UUID order before any Movement call -- both
    commands must now serialize on that pre-lock step instead. There is no
    genuine domain conflict between A and B (different batches, different
    source Trays, different destination Plates, and each Table's capacity
    is 4, comfortably above the 1 occupant each receives), so with the fix
    both commands are expected to succeed; neither may raise an unmapped
    database-level error."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"ist-lock-{suffix}", name="Lock Order Tenant")
    user = user_service.create_user(
        session, oidc_issuer="ist-lock", oidc_subject=suffix, email=f"ist-lock-{suffix}@example.com",
        display_name="Lock Order User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Lock Order Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    spec = carrier_specification_service.register_carrier_specification(
        session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code=DESTINATION_TYPE,
        code=f"NCP-{suffix}", name="Lock Order Plate", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=200,
    )
    # Batch A also supplies the two shared InterSalads Tables both commands target.
    s_a = build_transplant_ready_scenario(
        session, tenant, user, farm, suffix=f"a-{suffix}", tray_count=2,
        transplanting_required_type=DESTINATION_TYPE, destination_specification_id=spec.id,
        intersalads_table_count=2, intersalads_table_capacity=4,
    )
    # Batch B is a fully independent CropBatch (its own crop/workflow/sowing
    # chain, its own trays/Plates) -- its own Tables are discarded; its
    # Plates target Batch A's Tables instead.
    s_b = build_transplant_ready_scenario(
        session, tenant, user, farm, suffix=f"b-{suffix}", tray_count=2,
        transplanting_required_type=DESTINATION_TYPE, destination_specification_id=spec.id,
        intersalads_table_count=2, intersalads_table_capacity=4,
    )
    session.commit()

    table_1, table_2 = s_a["intersalads_table_ids"][0], s_a["intersalads_table_ids"][1]
    effective_time = max(s_a["entry_time"], s_b["entry_time"]) + timedelta(hours=2)
    tenant_id, farm_id, user_id = tenant.id, farm.id, user.id
    a_batch_id, a_sources, a_plates = s_a["batch_id"], s_a["source_assignment_ids"][:2], [c.id for c in s_a["destination_carriers"][:2]]
    b_batch_id, b_sources, b_plates = s_b["batch_id"], s_b["source_assignment_ids"][:2], [c.id for c in s_b["destination_carriers"][:2]]
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def make_lines(source_ids, plate_ids, location_order):
        src = [
            {
                "source_assignment_id": aid, "transplant_damage_count": 0, "qc_rejection_count": 0,
                "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
            }
            for aid in source_ids
        ]
        dst = [
            {"destination_carrier_id": pid, "assigned_plant_count": 100, "destination_location_id": loc, "note": None}
            for pid, loc in zip(plate_ids, location_order)
        ]
        alloc = [
            {"source_assignment_id": aid, "destination_carrier_id": pid, "allocated_plant_count": 100}
            for aid, pid in zip(source_ids, plate_ids)
        ]
        return src, dst, alloc

    def worker(name, batch_id, source_ids, plate_ids, location_order):
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=30)
            src, dst, alloc = make_lines(source_ids, plate_ids, location_order)
            result = intersalads_transplant_service.record_intersalads_transplant(
                session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, batch_id=batch_id,
                client_command_id=uuid.uuid4(), effective_time=effective_time, note=None,
                source_lines=src, destination_lines=dst, allocations=alloc,
            )
            results[name] = ("ok", result.id)
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", type(exc).__name__, repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", a_batch_id, a_sources, a_plates, [table_1, table_2]))
    t_b = threading.Thread(target=worker, args=("b", b_batch_id, b_sources, b_plates, [table_2, table_1]))
    t_a.start()
    t_b.start()
    t_a.join(timeout=60)
    t_b.join(timeout=60)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), results
        assert results.get("a", ("missing",))[0] == "ok", results
        assert results.get("b", ("missing",))[0] == "ok", results
    finally:
        cleanup_traceability_scenario(test_engine, tenant.id)


@pytest.mark.integration
def test_concurrent_different_plates_racing_for_final_table_slot(test_engine) -> None:
    """Section 27.C: an InterSalads Table with capacity=1 -- two different
    Plates from two different source Trays race for its one slot. Movement's
    own existing target-row-lock-then-count guarantee (DOMAIN-FARM-002),
    reused unmodified, is what resolves this -- the composite adds no new
    locking of its own."""
    scenario = _build_committed_scenario(test_engine, intersalads_table_count=1, intersalads_table_capacity=1)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    table_id = scenario["intersalads_table_ids"][0]

    def worker(name: str, source_id, dest_id) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            src, dst, alloc = _one_to_one(source_id, dest_id, table_id)
            result = intersalads_transplant_service.record_intersalads_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
            )
            results[name] = ("ok", result.id)
        except TargetOccupiedError as exc:
            results[name] = ("conflict", str(exc))
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
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_identical_replay_both_resolve_to_same_result_no_duplicate_movement(test_engine) -> None:
    """Section 27.F: two threads submit the EXACT same composite command
    (same client_command_id, same payload) simultaneously. The transplant
    core's own three-tier idempotency (pre-lock check, post-lock check,
    IntegrityError-recovery) must serialize this correctly with zero
    duplicate TransplantEvent or Movement rows regardless of which thread's
    write physically lands first."""
    scenario = _build_committed_scenario(test_engine, tray_count=1)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)
    command_id = uuid.uuid4()
    source_id = scenario["source_assignment_ids"][0]
    dest_id = scenario["destination_carrier_ids"][0]
    table_id = scenario["intersalads_table_ids"][0]

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            src, dst, alloc = _one_to_one(source_id, dest_id, table_id)
            result = intersalads_transplant_service.record_intersalads_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=command_id,
                effective_time=effective_time, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
            )
            results[name] = ("ok", result.id, result.destination_lines[0].movement_id)
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
        outcomes = [results["a"], results["b"]]
        assert all(o[0] == "ok" for o in outcomes), results
        assert outcomes[0][1] == outcomes[1][1], "both replays must resolve to the same TransplantEvent id"
        assert outcomes[0][2] == outcomes[1][2], "both replays must resolve to the same Movement id"

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            from sqlalchemy import func, select

            from app.models.movement import Movement
            from app.models.transplant_event import TransplantEvent

            event_count = verify_session.execute(
                select(func.count()).select_from(TransplantEvent).where(
                    TransplantEvent.batch_id == scenario["batch_id"]
                )
            ).scalar_one()
            movement_count = verify_session.execute(
                select(func.count()).select_from(Movement).where(Movement.occupant_carrier_id == dest_id)
            ).scalar_one()
            assert event_count == 1
            assert movement_count == 1
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])
