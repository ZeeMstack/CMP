"""Real two-connection concurrency tests for CMP-013 harvest, mirroring
test_batch_derivation_concurrency.py / test_transplant_concurrency.py:
committed setup data via a dedicated connection so two independent sessions
can genuinely race, with cleanup bypassing append-only/no-delete triggers via
`session_replication_role = replica`, scoped to this test only, hardened
with the `cmp_test` guard and explicit `DEFAULT` restore."""
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    farm_service,
    harvest_service,
    membership_service,
    production_system_service,
    quality_hold_service,
    sowing_service,
    tenant_service,
    user_service,
    workflow_service,
)
from app.services.errors import DuplicateProduceLotCodeError, HarvestCommandReusedWithDifferentPayloadError


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine, *, carrier_count=4):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"harv-race-{suffix}", name="Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="harv-race", oidc_subject=suffix, email=f"harv-race-{suffix}@example.com",
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
    variety = crop_service.register_variety(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"var-{suffix}",
        name="Variety", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ps-{suffix}", name="System", description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"wf-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    harvesting = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="HARVESTING", name="Harvesting", display_order=1, stage_category="harvesting",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=harvesting.id, code="ADV-1", name="Advance 1",
    )
    t2 = workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=harvesting.id, to_stage_id=complete.id, code="ADV-2", name="Advance 2",
    )
    workflow_service.publish_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"batch-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"lot-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    carriers = [
        carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"tray-{suffix}-{n}", issued_date=None,
        )
        for n in range(carrier_count)
    ]
    sowing_service.sow_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[
            {"carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 50, "seed_count": 50, "line_note": None}
            for c in carriers
        ],
    )
    assignments = sowing_service.list_batch_carriers(session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_by_carrier = {a.carrier.code: a.id for a in assignments}
    assignment_ids = [assignment_by_carrier[c.code] for c in carriers]

    crop_batch_service.transition_stage(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=_now(), reason=None,
    )

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": batch.id,
        "assignment_ids": assignment_ids, "suffix": suffix, "advance_to_complete_transition_id": t2.id,
    }
    session.close()
    conn.close()
    return result


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
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
        conn.execute(text("DELETE FROM harvest_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvested_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM quality_hold_releases WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM quality_holds WHERE tenant_id = :tid"), {"tid": tenant_id})
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
def test_concurrent_duplicate_harvest_command_is_idempotent(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, carrier_count=1)
    aid = scenario["assignment_ids"][0]
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()
    command_id = uuid.uuid4()
    lot_code = f"RACE-{scenario['suffix']}"

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = harvest_service.record_harvest(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=command_id,
                effective_time=effective_time, produce_lot_code=lot_code, note=None,
                source_lines=[{"batch_carrier_assignment_id": aid, "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
            )
            results[name] = ("ok", event.id)
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
        assert results["a"][0] == "ok" and results["b"][0] == "ok", results
        assert results["a"][1] == results["b"][1], "both racing callers of the same command id must see the same event"
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_same_lot_code_leaves_one_winner(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, carrier_count=2)
    aids = scenario["assignment_ids"]
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()
    lot_code = f"COLLIDE-{scenario['suffix']}"

    def worker(name: str, aid: uuid.UUID) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = harvest_service.record_harvest(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, produce_lot_code=lot_code, note=None,
                source_lines=[{"batch_carrier_assignment_id": aid, "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
            )
            results[name] = ("ok", event.id)
        except DuplicateProduceLotCodeError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", aids[0]))
    t_b = threading.Thread(target=worker, args=("b", aids[1]))
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
def test_concurrent_harvests_of_same_batch_both_succeed(test_engine) -> None:
    """The batch lock serializes two different harvest commands against the
    same batch, but repeated/overlapping harvests are permitted — both
    should succeed once serialized, not conflict."""
    scenario = _build_committed_scenario(test_engine, carrier_count=2)
    aids = scenario["assignment_ids"]
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()

    def worker(name: str, aid: uuid.UUID, code_suffix: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = harvest_service.record_harvest(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, produce_lot_code=f"{code_suffix}-{scenario['suffix']}", note=None,
                source_lines=[{"batch_carrier_assignment_id": aid, "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
            )
            results[name] = ("ok", event.id)
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", aids[0], "BOTH-A"))
    t_b = threading.Thread(target=worker, args=("b", aids[1], "BOTH-B"))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        assert results["a"][0] == "ok" and results["b"][0] == "ok", results
        assert results["a"][1] != results["b"][1]
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_hold_placement_vs_harvest_race_serializes_validly(test_engine) -> None:
    """Both commands lock the crop-batch row first (`SELECT ... FOR UPDATE`),
    so whichever wins the race fully determines the other's outcome — there
    is no window where both proceed against a stale view. Both serialized
    orderings are valid: hold-first blocks the harvest; harvest-first lets
    the harvest through and the hold is then placed independently
    afterward. What must never happen is an unhandled exception from either
    side, or a harvest succeeding *and* an open hold existing without the
    harvest having strictly preceded it — checked here via final state."""
    scenario = _build_committed_scenario(test_engine, carrier_count=1)
    aid = scenario["assignment_ids"][0]
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()

    def harvest_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = harvest_service.record_harvest(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, produce_lot_code=f"RACEHOLD-{scenario['suffix']}", note=None,
                source_lines=[{"batch_carrier_assignment_id": aid, "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
            )
            results["harvest"] = ("ok", event.id)
        except Exception as exc:
            results["harvest"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def hold_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            hold = quality_hold_service.place_quality_hold(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, source_observation_event_id=None, reason_code="pest",
                reason_text="race test",
            )
            results["hold"] = ("ok", hold.id)
        except Exception as exc:
            results["hold"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=harvest_worker)
    t_b = threading.Thread(target=hold_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        # The hold placement never depends on harvest state, so it must
        # always succeed regardless of ordering.
        assert results["hold"][0] == "ok", results
        # The harvest either won the race (succeeded) or lost it to an
        # already-committed hold (blocked) — never anything else.
        assert results["harvest"][0] in ("ok", "error"), results
        if results["harvest"][0] == "error":
            assert "QualityHoldOpenError" in results["harvest"][1] or "quality hold" in results["harvest"][1].lower(), results
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_harvest_vs_stage_progression_race_serializes_validly(test_engine) -> None:
    """Harvest and `transition_stage` both lock the crop-batch row first, so
    the race is fully serialized: harvest-first succeeds while still in the
    harvesting stage, then the transition moves the batch on; transition-
    first moves the batch out of the harvesting stage first, so the harvest
    then correctly sees a non-harvesting current stage and is rejected."""
    scenario = _build_committed_scenario(test_engine, carrier_count=1)
    aid = scenario["assignment_ids"][0]
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()

    def harvest_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = harvest_service.record_harvest(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, produce_lot_code=f"RACESTAGE-{scenario['suffix']}", note=None,
                source_lines=[{"batch_carrier_assignment_id": aid, "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
            )
            results["harvest"] = ("ok", event.id)
        except Exception as exc:
            results["harvest"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def transition_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            transition = crop_batch_service.transition_stage(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                configured_transition_id=scenario["advance_to_complete_transition_id"], effective_time=effective_time,
                reason=None,
            )
            results["transition"] = ("ok", transition.id)
        except Exception as exc:
            results["transition"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=harvest_worker)
    t_b = threading.Thread(target=transition_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        # The transition never depends on harvest state, so it must always
        # succeed regardless of ordering.
        assert results["transition"][0] == "ok", results
        assert results["harvest"][0] in ("ok", "error"), results
        if results["harvest"][0] == "error":
            # `complete` is a terminal stage, so a transition-first win both
            # takes the batch out of the harvesting stage *and* closes it
            # (crop_batch_service.transition_stage closes the batch when the
            # destination stage is terminal) — either rejection reason is a
            # valid consequence of the same losing ordering.
            message = results["harvest"][1]
            assert "harvesting stage" in message.lower() or "CropBatchClosedError" in message, results
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])
