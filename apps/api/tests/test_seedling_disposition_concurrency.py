"""SEEDLING-DISPOSITION-LIFECYCLE-001: real two-connection concurrency
proofs for the Carrier latest-assignment pointer / correction-restoration
races, mirroring `test_crop_batch_concurrency.py`'s established pattern:
committed setup data via a dedicated connection, `threading.Barrier(2)`,
two worker threads each with their OWN `test_engine.connect()`/`Session`."""
import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.seedling_disposition_event import SeedlingDispositionEvent
from app.services import seedling_disposition_service

pytestmark = pytest.mark.integration


def _build_committed_exhausted_scenario(test_engine, *, tray_count=1, normal=20):
    from app.services import farm_service, membership_service, tenant_service, user_service
    from tests._transplant_scenario import build_transplant_ready_scenario

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"wi-sd-race-{suffix}", name="Disposition Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="wi-sd-race", oidc_subject=suffix, email=f"wi-sd-race-{suffix}@example.com",
        display_name="Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s = build_transplant_ready_scenario(
        session, tenant, user, farm, suffix=suffix, tray_count=tray_count, normal=normal, abnormal=0,
        transplanting_required_type="cultivation_plate",
    )
    aid = s["source_assignment_ids"][0]
    a = session.execute(select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == aid)).scalar_one()
    carrier_id = a.carrier_id
    et = s["entry_time"] + timedelta(hours=2)
    record_command = seedling_disposition_service.record_disposition(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=aid, quantity=normal, reason_code="WEAK_SEEDLING", effective_time=et, note=None,
    )
    x = session.execute(
        select(SeedlingDispositionEvent).where(SeedlingDispositionEvent.command_id == record_command.id)
    ).scalar_one()
    session.commit()

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": s["batch_id"],
        "assignment_id": aid, "carrier_id": carrier_id, "target_event_id": x.id, "et": et, "seed_lot_id": s["seed_lot"].id,
    }
    session.close()
    conn.close()
    return result


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    from tests._traceability_scenario import cleanup_traceability_scenario

    cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.parametrize("attempt", range(5))
def test_correction_restoration_vs_new_sowing_same_carrier_race(test_engine, attempt) -> None:
    """A exhausted and released. Race: correction attempting restoration vs
    a completely unrelated new Sowing claiming the same physical Carrier.
    Both serialize on Carrier FOR UPDATE. Legal outcomes: correction wins
    (restoration B created, Carrier pointer now B) OR the new Sowing wins
    (Carrier pointer moves to Z, correction then correctly rejects with
    SeedlingDispositionCarrierReusedError). Illegal: old biology restored
    after the Carrier has already been claimed by the new Sowing."""
    from app.services.errors import SeedlingDispositionCarrierReusedError

    scenario = _build_committed_exhausted_scenario(test_engine)
    try:
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def correction_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                command = seedling_disposition_service.correct_disposition(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    target_event_id=scenario["target_event_id"], corrected=None,
                )
                results["correction"] = ("ok", command.id)
            except SeedlingDispositionCarrierReusedError as exc:
                results["correction"] = ("reused", repr(exc))
            except Exception as exc:  # pragma: no cover
                results["correction"] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        def sowing_worker() -> None:
            from app.services import nursery_service, sowing_service

            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                # A minimal, genuinely independent reuse-sowing infra --
                # reuses the SAME seed_lot (different batch), same Carrier.
                seeding_station_id = session.execute(
                    text(
                        "SELECT l.id FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
                        "WHERE l.tenant_id = :tid AND l.farm_id = :fid AND lt.code = 'seeding_station' LIMIT 1"
                    ),
                    {"tid": scenario["tenant_id"], "fid": scenario["farm_id"]},
                ).scalar_one_or_none()
                if seeding_station_id is None:
                    results["sowing"] = ("skipped-no-station", None)
                    return
                event = nursery_service.sow_new_batch(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    seed_lot_id=scenario["seed_lot_id"], seeding_station_id=seeding_station_id,
                    seeding_machine_id=None, effective_time=scenario["et"] + timedelta(hours=1), note=None,
                    trays=[{"carrier_id": scenario["carrier_id"], "sown_site_count": 10, "seeds_sown": 10}],
                )
                assignments = sowing_service.list_batch_carriers(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], batch_id=event.batch_id
                )
                results["sowing"] = ("ok", assignments[0].id)
            except Exception as exc:  # pragma: no cover -- includes expected serialization outcomes
                results["sowing"] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=correction_worker)
        t_b = threading.Thread(target=sowing_worker)
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            pointer = verify_session.execute(
                select(Carrier.latest_batch_carrier_assignment_id).where(Carrier.id == scenario["carrier_id"])
            ).scalar_one()
            if results.get("correction", (None,))[0] == "ok":
                # Correction won -- the pointer must point to the
                # restoration it created, never to a Sowing that raced in.
                restored = verify_session.execute(
                    select(BatchCarrierAssignment).where(
                        BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == scenario["assignment_id"]
                    )
                ).scalar_one()
                assert pointer == restored.id, "old biology restored but Carrier pointer does not agree"
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])


@pytest.mark.parametrize("attempt", range(5))
def test_two_corrections_of_same_target_race(test_engine, attempt) -> None:
    """Two concurrent CORRECT commands targeting the exact same exhausting
    REDUCTION -- must never both succeed (ux_seedling_disposition_events_
    reverses_once backstops it even under a race); exactly one restoration
    assignment must ever exist for this target."""
    scenario = _build_committed_exhausted_scenario(test_engine)
    try:
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def worker(name: str) -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                command = seedling_disposition_service.correct_disposition(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    target_event_id=scenario["target_event_id"], corrected=None,
                )
                results[name] = ("ok", command.id)
            except Exception as exc:  # pragma: no cover -- includes expected already-corrected rejection
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
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            restored_count = verify_session.execute(
                select(BatchCarrierAssignment).where(
                    BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == scenario["assignment_id"]
                )
            ).scalars().all()
            assert len(restored_count) == 1
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])
