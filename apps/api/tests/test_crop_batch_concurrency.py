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
