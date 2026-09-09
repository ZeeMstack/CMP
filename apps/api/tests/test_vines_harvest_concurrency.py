"""VINES-OPS-003: real two-connection concurrency proofs for Vines Harvest,
mirroring `test_production_disposition_concurrency.py`'s own established
pattern. Vine Harvest is REPEATABLE by design -- these proofs deliberately
do NOT test "two harvests of the same living plants race", since that is
legitimate, expected, concurrent-safe behavior (never blocked). Instead:

A/D. two operators race an EXACT replay (same client_command_id, same
     payload) of the same Vines Harvest command -> exactly one HarvestEvent/
     HarvestedProduceLot pair is ever created; the other returns the exact
     same one.
B. two operators race the same client_command_id with DIFFERENT payloads ->
   exactly one succeeds; the other is rejected as a payload mismatch, never
   silently applies the wrong one.
C. two operators race a correction against the SAME original HarvestSourceLine
   -> exactly one succeeds; the other is rejected as stale (already
   superseded), never both applied."""
import threading
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.harvest_event import HarvestEvent
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.services import harvest_service


def _build_committed_scenario(test_engine, **scenario_kwargs):
    from app.services import farm_service, membership_service, tenant_service, user_service

    from tests._vines_harvest_scenario import build_vines_harvest_ready_scenario

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"vh-race-{suffix}", name="Vines Harvest Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="vh-race", oidc_subject=suffix, email=f"vh-race-{suffix}@example.com",
        display_name="Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s = build_vines_harvest_ready_scenario(session, tenant, user, farm, suffix=suffix, **scenario_kwargs)
    session.commit()

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": s["batch"].id,
        "gutter_id": s["grow_gutter_id"], "harvest_time": s["harvest_time"],
    }
    session.close()
    conn.close()
    return result


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    from tests._traceability_scenario import cleanup_traceability_scenario

    cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
@pytest.mark.parametrize("attempt", range(5))
def test_proof_a_d_concurrent_exact_replay_creates_exactly_one_lot(test_engine, attempt) -> None:
    scenario = _build_committed_scenario(test_engine, intervines_plant_count=2, grow_bag_count=1, grow_bag_capacity=2)
    try:
        client_command_id = uuid.uuid4()
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def worker(name: str) -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                event = harvest_service.record_vines_harvest(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"],
                    client_command_id=client_command_id, effective_time=scenario["harvest_time"],
                    produce_lot_code="LOT-RACE", note=None,
                    source_lines=[
                        {
                            "source_location_id": scenario["gutter_id"], "harvested_weight_kg": Decimal("10.000"),
                            "whole_unit_count": None, "note": None,
                        }
                    ],
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
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["a"], results["b"]]
        assert all(o[0] == "ok" for o in outcomes), results
        assert outcomes[0][1] == outcomes[1][1]  # the exact same HarvestEvent id

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            events = verify_session.execute(
                select(HarvestEvent).where(HarvestEvent.tenant_id == scenario["tenant_id"], HarvestEvent.batch_id == scenario["batch_id"])
            ).scalars().all()
            assert len(events) == 1
            lots = verify_session.execute(
                select(HarvestedProduceLot).where(HarvestedProduceLot.harvest_event_id == events[0].id)
            ).scalars().all()
            assert len(lots) == 1
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])


@pytest.mark.integration
@pytest.mark.parametrize("attempt", range(3))
def test_proof_b_concurrent_same_command_id_different_payload_exactly_one_succeeds(test_engine, attempt) -> None:
    scenario = _build_committed_scenario(test_engine, intervines_plant_count=2, grow_bag_count=1, grow_bag_capacity=2)
    try:
        client_command_id = uuid.uuid4()
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def worker(name: str, weight: str) -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                event = harvest_service.record_vines_harvest(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"],
                    client_command_id=client_command_id, effective_time=scenario["harvest_time"],
                    produce_lot_code="LOT-RACE-B", note=None,
                    source_lines=[
                        {
                            "source_location_id": scenario["gutter_id"], "harvested_weight_kg": Decimal(weight),
                            "whole_unit_count": None, "note": None,
                        }
                    ],
                )
                results[name] = ("ok", event.id)
            except Exception as exc:  # pragma: no cover -- includes expected payload-mismatch rejection
                results[name] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=worker, args=("a", "10.000"))
        t_b = threading.Thread(target=worker, args=("b", "12.000"))
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("error") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            events = verify_session.execute(
                select(HarvestEvent).where(HarvestEvent.tenant_id == scenario["tenant_id"], HarvestEvent.batch_id == scenario["batch_id"])
            ).scalars().all()
            assert len(events) == 1  # only the winner's own event ever persists
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])


@pytest.mark.integration
@pytest.mark.parametrize("attempt", range(5))
def test_proof_c_concurrent_correction_of_same_line_exactly_one_succeeds(test_engine, attempt) -> None:
    # Everything that can raise (including the setup harvest itself) lives
    # inside this try/finally -- a mid-setup failure must never skip
    # `_cleanup` and leak committed scenario data into later tests.
    scenario = _build_committed_scenario(test_engine, intervines_plant_count=2, grow_bag_count=1, grow_bag_capacity=2)
    try:
        conn0 = test_engine.connect()
        session0 = Session(bind=conn0)
        event = harvest_service.record_vines_harvest(
            session0, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=scenario["harvest_time"],
            produce_lot_code="LOT-RACE-C", note=None,
            source_lines=[
                {
                    "source_location_id": scenario["gutter_id"], "harvested_weight_kg": Decimal("10.000"),
                    "whole_unit_count": None, "note": None,
                }
            ],
        )
        event_id = event.id
        detail = harvest_service.get_vines_harvest_event(
            session0, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], harvest_event_id=event_id
        )
        line_id = detail.source_lines[0].id
        session0.commit()
        session0.close()
        conn0.close()
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def worker(name: str, weight: str) -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                correction = harvest_service.correct_vines_harvest_source_line(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    harvest_event_id=event_id, harvest_source_line_id=line_id, actor_user_id=scenario["user_id"],
                    client_command_id=uuid.uuid4(), supersedes_correction_id=None, is_void=False,
                    corrected_harvested_weight_kg=Decimal(weight), reason_code="scale_error", note="reweighed",
                )
                results[name] = ("ok", correction.id)
            except Exception as exc:  # pragma: no cover -- includes expected stale-supersede rejection
                results[name] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=worker, args=("a", "9.000"))
        t_b = threading.Thread(target=worker, args=("b", "8.500"))
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("error") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            from app.models.harvest_source_line_correction import HarvestSourceLineCorrection

            corrections = verify_session.execute(
                select(HarvestSourceLineCorrection).where(HarvestSourceLineCorrection.harvest_source_line_id == line_id)
            ).scalars().all()
            assert len(corrections) == 1  # exactly one correction ever committed
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])
