"""Real two-connection concurrency tests for CMP-008 batch creation and
stage progression, mirroring test_movement_concurrency.py: committed setup
data via dedicated connections so two independent sessions can genuinely
race, with cleanup bypassing append-only/no-delete triggers via
`session_replication_role = replica`, scoped to this test only."""
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    crop_batch_service,
    crop_service,
    farm_service,
    membership_service,
    production_system_service,
    tenant_service,
    user_service,
    workflow_service,
)
from app.services.errors import (
    BatchCommandReusedWithDifferentPayloadError,
    DuplicateBatchCodeError,
    StageMismatchError,
)


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine, *, stage_codes=("SEEDING", "GERMINATION", "NURSERY")):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"batch-race-{suffix}", name="Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="race", oidc_subject=suffix, email=f"race-{suffix}@example.com", display_name="Race User"
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ps-{suffix}", name="Nursery Tray",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=None,
        production_system_id=ps.id, code=f"wf-{suffix}", name="Race Workflow",
    )
    version = workflow_service.create_draft_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    stages = []
    for i, code in enumerate(stage_codes):
        stage = workflow_service.add_stage(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            code=code, name=code.title(), display_order=i,
            stage_category=("seeding" if i == 0 else ("completed" if i == len(stage_codes) - 1 else "intermediate")),
            expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
            is_start=(i == 0), is_terminal=(i == len(stage_codes) - 1),
        )
        stages.append(stage)
    transitions = []
    for i in range(len(stages) - 1):
        t = workflow_service.add_transition(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=stages[i].id, to_stage_id=stages[i + 1].id, code=f"advance-{i}", name=f"Advance {i}",
        )
        transitions.append(t)
    workflow_service.publish_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "workflow_id": workflow.id,
        "stage_ids": [s.id for s in stages], "transition_ids": [t.id for t in transitions],
    }
    session.close()
    conn.close()
    return result


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM batch_stage_runs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crop_batches WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_stages WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_versions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflows WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM production_systems WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crops WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_concurrent_duplicate_batch_code_leaves_one_winner(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            batch = crop_batch_service.create_batch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), code="RACE-0001",
                workflow_id=scenario["workflow_id"], effective_time=effective_time,
            )
            results[name] = ("ok", batch.id)
        except DuplicateBatchCodeError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover - surfaced via assertion below
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
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_duplicate_creation_command_id_is_idempotent(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    shared_command_id = uuid.uuid4()
    effective_time = _now()

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            batch = crop_batch_service.create_batch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=shared_command_id, code="RACE-0002",
                workflow_id=scenario["workflow_id"], effective_time=effective_time,
            )
            results[name] = ("ok", batch.id)
        except BatchCommandReusedWithDifferentPayloadError as exc:
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
        assert results["a"][1] == results["b"][1], "both calls must resolve to the same batch"
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_transitions_against_one_batch_leave_one_winner(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)

    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    batch = crop_batch_service.create_batch(
        setup_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), code="RACE-0003",
        workflow_id=scenario["workflow_id"], effective_time=_now(),
    )
    batch_id = batch.id
    setup_session.close()
    setup_conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            transition = crop_batch_service.transition_stage(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=batch_id, client_command_id=uuid.uuid4(),
                configured_transition_id=scenario["transition_ids"][0], effective_time=effective_time, reason=None,
            )
            results[name] = ("ok", transition.id)
        except StageMismatchError as exc:
            results[name] = ("conflict", str(exc))
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
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])
# --- WORKFLOW-INTEGRITY-001: transition vs. concurrent biological writers ---------


def _build_committed_transplant_scenario(test_engine, *, tray_count=1):
    """A REAL Nursery scenario (sown -> Germination -> SeedlingEntry ->
    TRANSPLANTING stage), committed via a dedicated connection, so a
    genuinely separate connection can race `transition_stage` against it --
    mirrors `test_transplant_correction_concurrency.py`'s own identical
    pattern."""
    from tests._transplant_scenario import build_transplant_ready_scenario

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"wi-race-{suffix}", name="Workflow Integrity Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="wi-race", oidc_subject=suffix, email=f"wi-race-{suffix}@example.com",
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
        "entry_time": s["entry_time"], "transition_t2_id": s["transitions"]["t2"].id,
    }
    session.close()
    conn.close()
    return result


def _one_to_one_lines(source_id, dest_id, count):
    return (
        [{
            "source_assignment_id": source_id, "transplant_damage_count": 0, "qc_rejection_count": 0,
            "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
        }],
        [{"destination_carrier_id": dest_id, "assigned_plant_count": count, "note": None}],
        [{"source_assignment_id": source_id, "destination_carrier_id": dest_id, "allocated_plant_count": count}],
    )


@pytest.mark.integration
def test_transition_races_final_transplant_no_illegal_state(test_engine) -> None:
    """Section 19/26 A: a stage-exit attempt races the LAST Transplant that
    would resolve the final remainder. Both operations lock CropBatch first
    -- must serialize cleanly (no deadlock), and the surviving outcome must
    never be an illegal state (a committed transition coexisting with
    positive remainder)."""
    from datetime import timedelta

    from app.services import transplant_service

    scenario = _build_committed_transplant_scenario(test_engine, tray_count=1)
    et = scenario["entry_time"] + timedelta(hours=2)
    source_id = scenario["source_assignment_ids"][0]
    dest_id = scenario["destination_carrier_ids"][0]

    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    src, dst, alloc = _one_to_one_lines(source_id, dest_id, 170)  # 30 remain
    transplant_service.record_transplant(
        setup_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
        effective_time=et, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
    )
    setup_session.close()
    setup_conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    later_time = et + timedelta(hours=1)

    def transition_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            transition = crop_batch_service.transition_stage(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                configured_transition_id=scenario["transition_t2_id"], effective_time=later_time, reason=None,
            )
            results["transition"] = ("ok", transition.id)
        except Exception as exc:  # pragma: no cover -- includes the expected remainder rejection
            results["transition"] = ("rejected_or_error", repr(exc))
        finally:
            session.close()
            conn.close()

    def transplant_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            dest2_id = scenario["destination_carrier_ids"][1]
            src2, dst2, alloc2 = _one_to_one_lines(source_id, dest2_id, 30)  # resolves the remainder
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

    t_a = threading.Thread(target=transition_worker)
    t_b = threading.Thread(target=transplant_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=20)
    t_b.join(timeout=20)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        # Both legitimate serial orderings are acceptable: either the
        # transplant committed first (resolving the remainder), so the
        # transition legitimately succeeds; or the transition was evaluated
        # first (remainder still positive) and was legitimately rejected --
        # never a transition that committed while remainder was positive.
        assert results["transplant"][0] == "ok", results
        if results["transition"][0] == "ok":
            verify_conn = test_engine.connect()
            verify_session = Session(bind=verify_conn)
            from app.services import seedling_disposition_service

            count, total = seedling_disposition_service.get_unresolved_seedling_remainder(
                verify_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                batch_id=scenario["batch_id"], as_of=later_time,
            )
            assert count == 0 and total == 0, "a committed transition must never coexist with positive remainder"
            verify_session.close()
            verify_conn.close()
        else:
            assert "Unresolved" in results["transition"][1]
    finally:
        from tests._traceability_scenario import cleanup_traceability_scenario

        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_transition_races_correction_restoring_positive_remainder(test_engine) -> None:
    """Section 19/26 B: a stage-exit attempt races a Transplant correction
    that restores positive remainder for a Tray the target had (wrongly)
    recorded as fully resolved. The Batch must never escape TRANSPLANTING
    while restored biology remains unresolved."""
    from datetime import timedelta

    from app.services import transplant_correction_service, transplant_service

    scenario = _build_committed_transplant_scenario(test_engine, tray_count=1)
    et = scenario["entry_time"] + timedelta(hours=2)
    source_id = scenario["source_assignment_ids"][0]
    dest_id = scenario["destination_carrier_ids"][0]

    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    src, dst, alloc = _one_to_one_lines(source_id, dest_id, 200)  # (wrongly) recorded as fully resolved
    target = transplant_service.record_transplant(
        setup_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
        effective_time=et, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
    )
    target_id = target.id
    setup_session.close()
    setup_conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    later_time = et + timedelta(hours=1)

    def transition_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            transition = crop_batch_service.transition_stage(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                configured_transition_id=scenario["transition_t2_id"], effective_time=later_time, reason=None,
            )
            results["transition"] = ("ok", transition.id)
        except Exception as exc:  # pragma: no cover -- includes the expected remainder rejection
            results["transition"] = ("rejected_or_error", repr(exc))
        finally:
            session.close()
            conn.close()

    def correction_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            reversal = transplant_correction_service.correct_transplant(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"],
                target_transplant_event_id=target_id, client_command_id=uuid.uuid4(),
                reason="wrong quantity, void it", replacement=None,
            )
            results["correction"] = ("ok", reversal.id)
        except Exception as exc:  # pragma: no cover -- includes the expected stage-mismatch rejection
            results["correction"] = ("rejected_or_error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=transition_worker)
    t_b = threading.Thread(target=correction_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=20)
    t_b.join(timeout=20)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        # Both legitimate serial orderings are acceptable: either the
        # transition committed first (batch left TRANSPLANTING while
        # biology was still, at that moment, truthfully fully resolved),
        # in which case the correction legitimately fails on its OWN
        # stage-eligibility rule; or the correction committed first
        # (restoring 200 positive remainder), in which case the
        # transition legitimately fails on the biological guard. Never
        # both succeeding -- that would mean the batch left the stage
        # while restored biology remained unresolved.
        assert not (results["transition"][0] == "ok" and results["correction"][0] == "ok"), (
            "the batch must never escape TRANSPLANTING while a correction restores unresolved remainder", results
        )
        assert results["transition"][0] == "ok" or results["correction"][0] == "ok", (
            "at least one of the two racing operations must succeed", results
        )
    finally:
        from tests._traceability_scenario import cleanup_traceability_scenario

        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])
