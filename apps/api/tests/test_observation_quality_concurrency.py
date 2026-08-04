"""Real two-connection concurrency tests for CMP-010 observations, quality
holds, and hold-vs-transition interaction, mirroring
test_sowing_concurrency.py / test_crop_batch_concurrency.py: committed setup
data via a dedicated connection so two independent sessions can genuinely
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
    observation_service,
    production_system_service,
    quality_hold_service,
    tenant_service,
    user_service,
    workflow_service,
)
from app.services.errors import (
    ObservationCommandReusedWithDifferentPayloadError,
    QualityHoldAlreadyReleasedError,
    QualityHoldCommandReusedWithDifferentPayloadError,
    QualityHoldOpenError,
)


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"obsq-race-{suffix}", name="Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="obsq-race", oidc_subject=suffix, email=f"obsq-race-{suffix}@example.com",
        display_name="Race User",
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
    seeding = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=True, is_terminal=False,
    )
    germination = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="GERMINATION", name="Germination", display_order=1, stage_category="germination",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    transition = workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=germination.id, code="ADVANCE", name="Advance",
    )
    workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=germination.id, to_stage_id=complete.id, code="ADVANCE-2", name="Advance 2",
    )
    workflow_service.publish_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    definition = observation_service.register_observation_definition(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"DEF-{suffix}", name="Metric",
        description=None, value_type="text", unit=None, target_scope="crop_batch", min_value=None, max_value=None,
    )

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": batch.id,
        "transition_id": transition.id, "definition_id": definition.id, "stage_seeding_id": seeding.id,
    }
    session.close()
    conn.close()
    return result


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM quality_hold_releases WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM quality_holds WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM observation_values WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM germination_checks WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM observation_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM observation_definitions WHERE tenant_id = :tid"), {"tid": tenant_id})
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
def test_concurrent_hold_placement_and_transition(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()

    def hold_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            hold = quality_hold_service.place_quality_hold(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, source_observation_event_id=None, reason_code="RACE",
                reason_text="race hold",
            )
            results["hold"] = ("ok", hold.id)
        except Exception as exc:  # pragma: no cover
            results["hold"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def transition_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            t = crop_batch_service.transition_stage(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                configured_transition_id=scenario["transition_id"], effective_time=effective_time, reason=None,
            )
            results["transition"] = ("ok", t.id)
        except QualityHoldOpenError:
            results["transition"] = ("blocked", None)
        except Exception as exc:  # pragma: no cover
            results["transition"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=hold_worker)
    t_b = threading.Thread(target=transition_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        assert results["hold"][0] == "ok", results
        assert results["transition"][0] in ("ok", "blocked"), results
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_hold_release_and_transition(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)

    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    hold = quality_hold_service.place_quality_hold(
        setup_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
        effective_time=_now(), source_observation_event_id=None, reason_code="PRE", reason_text="pre-existing",
    )
    hold_id = hold.id
    setup_session.close()
    setup_conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()

    def release_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            release = quality_hold_service.release_quality_hold(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], hold_id=hold_id,
                client_command_id=uuid.uuid4(), effective_time=effective_time, release_reason="cleared",
            )
            results["release"] = ("ok", release.id)
        except Exception as exc:  # pragma: no cover
            results["release"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def transition_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            t = crop_batch_service.transition_stage(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                configured_transition_id=scenario["transition_id"], effective_time=effective_time, reason=None,
            )
            results["transition"] = ("ok", t.id)
        except QualityHoldOpenError:
            results["transition"] = ("blocked", None)
        except Exception as exc:  # pragma: no cover
            results["transition"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=release_worker)
    t_b = threading.Thread(target=transition_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        assert results["release"][0] == "ok", results
        assert results["transition"][0] in ("ok", "blocked"), results
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_hold_placements_both_succeed(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            hold = quality_hold_service.place_quality_hold(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, source_observation_event_id=None, reason_code=name,
                reason_text=f"reason {name}",
            )
            results[name] = ("ok", hold.id)
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
        assert results["a"][1] != results["b"][1]
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_release_of_same_hold_leaves_one_winner(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)

    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    hold = quality_hold_service.place_quality_hold(
        setup_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
        effective_time=_now(), source_observation_event_id=None, reason_code="PRE", reason_text="pre-existing",
    )
    hold_id = hold.id
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
            release = quality_hold_service.release_quality_hold(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], hold_id=hold_id,
                client_command_id=uuid.uuid4(), effective_time=effective_time, release_reason=f"reason {name}",
            )
            results[name] = ("ok", release.id)
        except QualityHoldAlreadyReleasedError:
            results[name] = ("conflict", None)
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


@pytest.mark.integration
def test_concurrent_duplicate_observation_command_is_idempotent(test_engine) -> None:
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
            event = observation_service.record_observation(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"],
                client_command_id=shared_command_id, effective_time=effective_time, note=None,
                values=[{"observation_definition_id": scenario["definition_id"], "value_text": "race"}],
                germination_checks=[],
            )
            results[name] = ("ok", event.id)
        except ObservationCommandReusedWithDifferentPayloadError as exc:
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
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_duplicate_hold_command_is_idempotent(test_engine) -> None:
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
            hold = quality_hold_service.place_quality_hold(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"],
                client_command_id=shared_command_id, effective_time=effective_time,
                source_observation_event_id=None, reason_code="RACE", reason_text="race hold",
            )
            results[name] = ("ok", hold.id)
        except QualityHoldCommandReusedWithDifferentPayloadError as exc:
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
        _cleanup_scenario(test_engine, scenario["tenant_id"])
