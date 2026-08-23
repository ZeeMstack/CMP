"""NURSERY-OPS-005A concurrency proofs (ticket section 28).

Items A-D of the required matrix (two concurrent destination assignments to
one empty Carrier; record vs correct overlapping Carrier; record vs
split/merge overlap; Carrier reuse vs correction restoration) exercise
locking mechanisms this ticket did NOT change the order of (Carrier-first
creation locking, BCA-first existing-assignment locking) -- items A and B
are already proven, unaffected, by the pre-existing
test_concurrent_use_of_same_destination_carrier_leaves_one_winner and
test_correction_races_new_transplant_on_same_source (both still pass
unchanged against this branch). Item C (split/merge) touches a service this
ticket never modifies. This file adds dedicated coverage only for the two
items that exercise NEW NURSERY-OPS-005A mechanism specifically:

  D. Carrier reuse vs correction restoration race -- the NEW
     TransplantCorrectionCarrierReusedError check.
  E. Two concurrent Nursery Plate consumptions of the SAME source
     BatchCarrierAssignment -- the new unified source-authority resolver's
     own locking path, proving it serializes exactly like the pre-existing
     SeedlingEntry path and never creates two competing structural
     checkpoint chain tips.

Mirrors test_transplant_concurrency.py's conventions: committed setup via a
dedicated connection so two independent sessions can genuinely race,
cleanup via the shared `cleanup_traceability_scenario` helper."""

import threading
import uuid
from datetime import timedelta, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_carrier_population_checkpoint import BatchCarrierPopulationCheckpoint
from app.models.farm import Farm
from app.models.tenant import Tenant
from app.models.user import User
from app.services import (
    carrier_specification_service,
    farm_service,
    membership_service,
    tenant_service,
    transplant_correction_service,
    transplant_service,
    user_service,
)
from app.services.errors import SourceAssignmentAlreadyReleasedError, TransplantCorrectionCarrierReusedError
from tests._traceability_scenario import cleanup_traceability_scenario
from tests._transplant_scenario import build_transplant_ready_scenario


def _now():
    return datetime.now(timezone.utc)


def _one_to_one(source_id, dest_id, count):
    return (
        [{"source_assignment_id": source_id, "transplant_damage_count": 0, "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None}],
        [{"destination_carrier_id": dest_id, "assigned_plant_count": count, "note": None}],
        [{"source_assignment_id": source_id, "destination_carrier_id": dest_id, "allocated_plant_count": count}],
    )


def _build_nursery_plate_race_scenario(test_engine, *, suffix_prefix: str):
    """Commits: tenant/farm, a Seed Tray -> Plate1 (nursery_cultivation_
    plate, 200-strong, unreleased) real scenario. Returns everything needed
    for two independent connections to race consuming Plate1."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = f"{suffix_prefix}-{uuid.uuid4().hex[:8]}"

    tenant = tenant_service.create_tenant(session, code=f"npc-{suffix}", name="Nursery Plate Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="npc-race", oidc_subject=suffix, email=f"npc-race-{suffix}@example.com",
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
        session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="nursery_cultivation_plate",
        code=f"NP-SPEC-{suffix}", name=f"NP-SPEC-{suffix}", length_mm=300, width_mm=200, height_mm=50,
        biological_position_count=200,
    )
    s = build_transplant_ready_scenario(
        session, tenant, user, farm, suffix=suffix, tray_count=1, normal=200, abnormal=0,
        transplanting_required_type="nursery_cultivation_plate", destination_specification_id=spec.id,
    )
    source_assignment_id = s["source_assignment_ids"][0]
    plate1 = s["destination_carriers"][0]
    opening_event = transplant_service.record_transplant(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=1), note=None,
        source_lines=[
            {
                "source_assignment_id": source_assignment_id, "transplant_damage_count": 0,
                "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0, "other_loss_note": None,
                "note": None,
            }
        ],
        destination_lines=[{"destination_carrier_id": plate1.id, "assigned_plant_count": 200, "note": None}],
        allocations=[
            {
                "source_assignment_id": source_assignment_id, "destination_carrier_id": plate1.id,
                "allocated_plant_count": 200,
            }
        ],
    )
    session.commit()

    plate1_assignment_id = session.execute(
        select(BatchCarrierAssignment.id).where(BatchCarrierAssignment.opening_transplant_event_id == opening_event.id)
    ).scalar_one()

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": s["batch_id"],
        "plate1_id": plate1.id, "plate1_assignment_id": plate1_assignment_id,
        "entry_time": s["entry_time"], "seed_lot_id": s["seed_lot"].id,
    }
    session.close()
    conn.close()
    return result


@pytest.mark.integration
def test_concurrent_nursery_plate_consumptions_of_same_source_leave_one_winner_and_one_chain(test_engine) -> None:
    """Section 28 item E. Two connections race to fully consume the SAME
    Plate1 assignment (200/200) into two DIFFERENT destination Plates.
    Exactly one must win; the other must see the now-released assignment
    (SourceAssignmentAlreadyReleasedError, the same shape the pre-existing
    SeedlingEntry-backed race already proves) -- and afterward exactly one
    structural checkpoint chain tip must exist for Plate1's assignment, with
    no branch ever created (proving the BCA lock this unified resolver
    shares with the pre-existing path serializes correctly)."""
    scenario = _build_nursery_plate_race_scenario(test_engine, suffix_prefix="e")
    conn = test_engine.connect()
    session = Session(bind=conn)
    spec_a = carrier_specification_service.register_carrier_specification(
        session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        carrier_type_code="nursery_cultivation_plate", code="NP-DEST-A", name="NP-DEST-A", length_mm=300,
        width_mm=200, height_mm=50, biological_position_count=200,
    )
    spec_b = carrier_specification_service.register_carrier_specification(
        session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        carrier_type_code="nursery_cultivation_plate", code="NP-DEST-B", name="NP-DEST-B", length_mm=300,
        width_mm=200, height_mm=50, biological_position_count=200,
    )
    from app.services import carrier_service

    plate_a = carrier_service.register_carrier(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        carrier_type_code="nursery_cultivation_plate", code="NP-A", issued_date=None, specification_id=spec_a.id,
    )
    plate_b = carrier_service.register_carrier(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        carrier_type_code="nursery_cultivation_plate", code="NP-B", issued_date=None, specification_id=spec_b.id,
    )
    session.commit()
    # Captured as plain UUIDs before close -- both objects' attributes
    # expire on commit, and would raise DetachedInstanceError if accessed
    # after the session below closes.
    plate_a_id = plate_a.id
    plate_b_id = plate_b.id
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = scenario["entry_time"] + timedelta(hours=2)

    def worker(name: str, dest_id) -> None:
        wconn = test_engine.connect()
        wsession = Session(bind=wconn)
        try:
            barrier.wait(timeout=10)
            src, dst, alloc = _one_to_one(scenario["plate1_assignment_id"], dest_id, 200)
            event = transplant_service.record_transplant(
                wsession, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, source_lines=src, destination_lines=dst, allocations=alloc,
            )
            results[name] = ("ok", event.id)
        except SourceAssignmentAlreadyReleasedError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            wsession.close()
            wconn.close()

    t_a = threading.Thread(target=worker, args=("a", plate_a_id))
    t_b = threading.Thread(target=worker, args=("b", plate_b_id))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            chain_rows = list(
                verify_session.execute(
                    select(BatchCarrierPopulationCheckpoint).where(
                        BatchCarrierPopulationCheckpoint.batch_carrier_assignment_id
                        == scenario["plate1_assignment_id"]
                    )
                ).scalars()
            )
            assert len(chain_rows) == 1, "no branch: exactly one checkpoint must exist for Plate1's assignment"
            tips = [
                row for row in chain_rows
                if not any(other.previous_checkpoint_id == row.id for other in chain_rows)
            ]
            assert len(tips) == 1, "exactly one structural chain tip, never a branch"
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_carrier_reuse_vs_correction_restoration_race_is_safe(test_engine) -> None:
    """Section 28 item D. Sets up a released Plate1 (fully chained into
    Plate2) eligible for correction-restoration, then races two independent
    connections: one legitimately reuses Plate1's now-released physical
    Carrier for a completely unrelated fresh Batch's transplant (advancing
    Carrier.latest_batch_carrier_assignment_id via the real DB trigger),
    the other corrects/reverses the original chained consumption (which
    would restore a new assignment onto that same Carrier). No deadlock, no
    corrupted state: the reuse must always succeed (nothing legitimately
    blocks a physical Carrier reuse), and the correction must either
    (a) win the race and succeed, or (b) lose the race and be rejected with
    TransplantCorrectionCarrierReusedError -- never any other outcome."""
    scenario = _build_nursery_plate_race_scenario(test_engine, suffix_prefix="d")
    conn = test_engine.connect()
    session = Session(bind=conn)

    spec2 = carrier_specification_service.register_carrier_specification(
        session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        carrier_type_code="nursery_cultivation_plate", code="NP-DEST2", name="NP-DEST2", length_mm=300,
        width_mm=200, height_mm=50, biological_position_count=200,
    )
    from app.services import carrier_service

    plate2 = carrier_service.register_carrier(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        carrier_type_code="nursery_cultivation_plate", code="NP-DEST2-C", issued_date=None,
        specification_id=spec2.id,
    )
    chained_event = transplant_service.record_transplant(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
        effective_time=scenario["entry_time"] + timedelta(hours=2), note=None,
        source_lines=[
            {
                "source_assignment_id": scenario["plate1_assignment_id"], "transplant_damage_count": 0,
                "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0, "other_loss_note": None,
                "note": None,
            }
        ],
        destination_lines=[{"destination_carrier_id": plate2.id, "assigned_plant_count": 200, "note": None}],
        allocations=[
            {
                "source_assignment_id": scenario["plate1_assignment_id"], "destination_carrier_id": plate2.id,
                "allocated_plant_count": 200,
            }
        ],
    )
    session.commit()
    chained_event_id = chained_event.id

    # Independent second scenario for the REUSE worker: a completely
    # separate, fully-ready-for-transplant Seed Tray (own Batch, own
    # SeedlingEntry) -- Plate1 is nursery_cultivation_plate-typed, so its
    # legitimate physical reuse is another Transplant (Seed Tray -> Plate1),
    # exactly mirroring test_carrier_reuse_blocks_nursery_plate_restoration's
    # own reuse mechanism (a raw sow_new_batch would reject Plate1 outright:
    # sowing requires a seed_tray-typed Carrier).
    reuse_spec = carrier_specification_service.register_carrier_specification(
        session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        carrier_type_code="nursery_cultivation_plate", code="NP-REUSE-SPEC", name="NP-REUSE-SPEC", length_mm=300,
        width_mm=200, height_mm=50, biological_position_count=200,
    )
    s2 = build_transplant_ready_scenario(
        session, session.get(Tenant, scenario["tenant_id"]), session.get(User, scenario["user_id"]),
        session.get(Farm, scenario["farm_id"]), suffix=f"reuse-{uuid.uuid4().hex[:8]}", tray_count=1, normal=50,
        abnormal=0, transplanting_required_type="nursery_cultivation_plate",
        destination_specification_id=reuse_spec.id,
    )
    reuse_source_assignment_id = s2["source_assignment_ids"][0]
    reuse_entry_time = s2["entry_time"]
    session.commit()

    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def reuse_worker() -> None:
        wconn = test_engine.connect()
        wsession = Session(bind=wconn)
        try:
            barrier.wait(timeout=10)
            src, dst, alloc = _one_to_one(reuse_source_assignment_id, scenario["plate1_id"], 50)
            transplant_service.record_transplant(
                wsession, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=s2["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=reuse_entry_time + timedelta(hours=2), note=None, source_lines=src,
                destination_lines=dst, allocations=alloc,
            )
            wsession.commit()
            results["reuse"] = ("ok", None)
        except Exception as exc:  # pragma: no cover
            results["reuse"] = ("error", repr(exc))
        finally:
            wsession.close()
            wconn.close()

    def correct_worker() -> None:
        wconn = test_engine.connect()
        wsession = Session(bind=wconn)
        try:
            barrier.wait(timeout=10)
            transplant_correction_service.correct_transplant(
                wsession, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"],
                target_transplant_event_id=chained_event_id, client_command_id=uuid.uuid4(),
                reason="race-correction", replacement=None,
            )
            wsession.commit()
            results["correct"] = ("ok", None)
        except TransplantCorrectionCarrierReusedError as exc:
            results["correct"] = ("carrier_reused", str(exc))
        except Exception as exc:  # pragma: no cover
            results["correct"] = ("error", repr(exc))
        finally:
            wsession.close()
            wconn.close()

    t_reuse = threading.Thread(target=reuse_worker)
    t_correct = threading.Thread(target=correct_worker)
    t_reuse.start()
    t_correct.start()
    t_reuse.join(timeout=15)
    t_correct.join(timeout=15)

    try:
        assert not t_reuse.is_alive() and not t_correct.is_alive()
        assert results["reuse"][0] == "ok", results
        assert results["correct"][0] in ("ok", "carrier_reused"), results
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])
