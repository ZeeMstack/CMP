"""POSTHARVEST-OPS-001C: real two-connection concurrency proofs -- grading
vs grading (double-spend prevention), grading vs an existing Harvest
correction, grading vs current direct Packing (both consume from the same
HarvestedProduceLot ledger), and a Quality Hold race vs grading. Same
committed-connection threading pattern as test_packing_concurrency.py and
test_observation_quality_concurrency.py."""
import threading
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import grading_service, quality_hold_service
from app.services.errors import (
    InsufficientHarvestedProduceLotBalanceError,
    QualityHoldOpenError,
)
from tests._grading_scenario import build_committed_scenario, cleanup_scenario, now
from tests.test_grading import _output


@pytest.mark.integration
def test_overlapping_concurrent_grading_cannot_overdraw(test_engine) -> None:
    """Two threads each present 7kg of a 10kg lot for grading at the same
    time -- at most one may succeed; the loser must fail with insufficient
    balance, never a negative-balance data corruption."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = grading_service.record_grading(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                source_harvested_produce_lot_id=scenario["lot_a_id"],
                processing_hall_location_id=scenario["packing_hall_location_id"], effective_time=effective_time,
                note=None, input_presented_weight_kg=Decimal("7.000"), input_presented_whole_unit_count=None,
                rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
                loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
                sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
                remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=None,
                outputs=[_output(scenario, weight="7.000", code=f"GPL-{name}")],
            )
            results[name] = ("ok", event.id)
        except InsufficientHarvestedProduceLotBalanceError as exc:
            results[name] = ("insufficient", str(exc))
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
        assert outcomes.count("insufficient") == 1, results
        with test_engine.connect() as verify_conn:
            balance = verify_conn.execute(
                text("SELECT COALESCE(sum(weight_delta_kg), 0) FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid"),
                {"lid": scenario["lot_a_id"]},
            ).scalar_one()
        assert balance >= 0, "the lot's balance must never go negative under concurrent grading"
        assert balance == Decimal("3.000") or balance == Decimal("3.000")
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_exact_duplicate_grading_command_race_creates_one_event(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()
    command_id = uuid.uuid4()
    fixed_output = _output(scenario, weight="5.000", code="GPL-RACE")

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = grading_service.record_grading(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=command_id,
                source_harvested_produce_lot_id=scenario["lot_a_id"],
                processing_hall_location_id=scenario["packing_hall_location_id"], effective_time=effective_time,
                note=None, input_presented_weight_kg=Decimal("5.000"), input_presented_whole_unit_count=None,
                rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
                loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
                sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
                remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=None,
                outputs=[fixed_output],
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
        assert results["a"][1] == results["b"][1]
        with test_engine.connect() as verify_conn:
            event_count = verify_conn.execute(
                text("SELECT count(*) FROM grading_events WHERE tenant_id = :tid"), {"tid": scenario["tenant_id"]}
            ).scalar_one()
            debit_count = verify_conn.execute(
                text(
                    "SELECT count(*) FROM produce_lot_ledger_entries "
                    "WHERE produce_lot_id = :lid AND entry_kind = 'grading_consumption'"
                ),
                {"lid": scenario["lot_a_id"]},
            ).scalar_one()
        assert event_count == 1
        assert debit_count == 1
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_grading_vs_harvest_correction_same_source_no_deadlock(test_engine) -> None:
    """Grading and a Harvest correction against the SAME source lot both
    lock the owning CropBatch first (the established shared lock-order
    convention) -- they must serialize cleanly with no deadlock, and the
    final ledger balance must reconcile correctly regardless of which one
    the database happened to run first."""
    from app.services import harvest_service, location_service
    from tests._traceability_scenario import cleanup_traceability_scenario
    from tests.test_leafy_harvest_concurrency import _build_committed_plate_scenario

    plate_scenario = _build_committed_plate_scenario(test_engine, opening_count=15)
    conn0 = test_engine.connect()
    session0 = Session(bind=conn0)
    try:
        harvest_event = harvest_service.record_leafy_harvest(
            session0, tenant_id=plate_scenario["tenant_id"], farm_id=plate_scenario["farm_id"],
            actor_user_id=plate_scenario["user_id"], batch_id=plate_scenario["batch_id"],
            client_command_id=uuid.uuid4(), effective_time=plate_scenario["et"],
            produce_lot_code=f"HL-{uuid.uuid4().hex[:8]}", note=None,
            source_lines=[
                {
                    "batch_carrier_assignment_id": plate_scenario["root_id"], "whole_unit_count": 10,
                    "harvested_weight_kg": Decimal("10.000"), "note": None,
                }
            ],
        )
        harvest_source_line_id = session0.execute(
            text("SELECT id FROM harvest_source_lines WHERE harvest_event_id = :eid"), {"eid": harvest_event.id}
        ).scalar_one()
        lot_id, crop_id, variety_id = session0.execute(
            text("SELECT id, crop_id, variety_id FROM harvested_produce_lots WHERE harvest_event_id = :eid"),
            {"eid": harvest_event.id},
        ).one()
        hall = location_service.create_location(
            session0, tenant_id=plate_scenario["tenant_id"], farm_id=plate_scenario["farm_id"],
            actor_user_id=plate_scenario["user_id"], location_type_code="packing_hall",
            code=f"hall-{uuid.uuid4().hex[:8]}", name="Race Hall", parent_location_id=None,
            greenhouse_classification=None, occupiable=False,
        )
        from app.services import grade_definition_service

        grade_def = grade_definition_service.register_grade_definition(
            session0, tenant_id=plate_scenario["tenant_id"], actor_user_id=plate_scenario["user_id"],
            client_command_id=uuid.uuid4(), code=f"grade-{uuid.uuid4().hex[:8]}", name="Premium", crop_id=crop_id,
            variety_id=None, description=None,
        )
        grade_version = grade_definition_service.create_draft_version(
            session0, tenant_id=plate_scenario["tenant_id"], actor_user_id=plate_scenario["user_id"],
            client_command_id=uuid.uuid4(), grade_definition_id=grade_def.id, spec_notes=None,
        )
        grade_definition_service.activate_version(
            session0, tenant_id=plate_scenario["tenant_id"], actor_user_id=plate_scenario["user_id"],
            client_command_id=uuid.uuid4(), grade_definition_id=grade_def.id, version_id=grade_version.id,
            effective_time=plate_scenario["et"] - timedelta(days=1),
        )
        hall_id = hall.id
        grade_version_id = grade_version.id
        session0.commit()
    finally:
        session0.close()
        conn0.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = plate_scenario["et"] + timedelta(hours=1)

    def grading_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = grading_service.record_grading(
                session, tenant_id=plate_scenario["tenant_id"], farm_id=plate_scenario["farm_id"],
                actor_user_id=plate_scenario["user_id"], client_command_id=uuid.uuid4(),
                source_harvested_produce_lot_id=lot_id, processing_hall_location_id=hall_id,
                effective_time=effective_time, note=None, input_presented_weight_kg=Decimal("6.000"),
                input_presented_whole_unit_count=6, rejected_weight_kg=Decimal("0"),
                rejected_whole_unit_count=0, loss_weight_kg=Decimal("0"), loss_whole_unit_count=0,
                sample_weight_kg=Decimal("0"), sample_whole_unit_count=0, remainder_weight_kg=Decimal("0"),
                remainder_whole_unit_count=0,
                outputs=[
                    {
                        "grade_definition_version_id": grade_version_id, "code": "GPL-GRADE",
                        "output_weight_kg": Decimal("6.000"), "output_whole_unit_count": 6,
                    }
                ],
            )
            results["grading"] = ("ok", event.id)
        except Exception as exc:  # pragma: no cover -- includes expected balance rejection
            results["grading"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def correction_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            correction = harvest_service.correct_leafy_harvest(
                session, tenant_id=plate_scenario["tenant_id"], farm_id=plate_scenario["farm_id"],
                actor_user_id=plate_scenario["user_id"], client_command_id=uuid.uuid4(),
                harvest_source_line_id=harvest_source_line_id, supersedes_correction_id=None, is_void=False,
                corrected_harvested_weight_kg=Decimal("6.000"), corrected_whole_unit_count=6,
                reason_code="miscounted", note="concurrency race correction",
            )
            results["correction"] = ("ok", correction.id)
        except Exception as exc:  # pragma: no cover -- includes expected balance rejection
            results["correction"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=grading_worker)
    t_b = threading.Thread(target=correction_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        # Grading consumes 6/6 of the 10/10 lot; the correction's own delta
        # (10/10 -> 6/6, i.e. -4/-4) exactly matches what remains regardless
        # of which one the database serializes first through the shared
        # CropBatch lock -- both must succeed, leaving the lot at exactly
        # zero, proving the lock forces correct sequential re-evaluation
        # rather than either side acting on a stale pre-lock balance.
        assert results["grading"][0] == "ok", results
        assert results["correction"][0] == "ok", results
        with test_engine.connect() as verify_conn:
            balance = verify_conn.execute(
                text("SELECT COALESCE(sum(weight_delta_kg), 0) FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid"),
                {"lid": lot_id},
            ).scalar_one()
        assert balance >= 0, "the lot's balance must never go negative regardless of race order"
        assert balance == Decimal("0.000") or balance == Decimal("0")
    finally:
        # `cleanup_traceability_scenario` predates POSTHARVEST-OPS-001C and
        # does not know about the grading tables this scenario also wrote
        # to -- clean those up explicitly first (same tenant-scoped,
        # replica-mode pattern as `_grading_scenario.cleanup_scenario`)
        # before delegating the rest to the traceability helper.
        with test_engine.connect() as cleanup_conn:
            cleanup_trans = cleanup_conn.begin()
            try:
                cleanup_conn.execute(text("SET session_replication_role = replica"))
                cleanup_conn.execute(
                    text("DELETE FROM graded_produce_lot_ledger_entries WHERE tenant_id = :tid"),
                    {"tid": plate_scenario["tenant_id"]},
                )
                cleanup_conn.execute(
                    text("DELETE FROM graded_produce_lots WHERE tenant_id = :tid"),
                    {"tid": plate_scenario["tenant_id"]},
                )
                cleanup_conn.execute(
                    text("DELETE FROM grading_events WHERE tenant_id = :tid"), {"tid": plate_scenario["tenant_id"]}
                )
                cleanup_conn.execute(
                    text("DELETE FROM grade_definition_versions WHERE tenant_id = :tid"),
                    {"tid": plate_scenario["tenant_id"]},
                )
                cleanup_conn.execute(
                    text("DELETE FROM grade_definitions WHERE tenant_id = :tid"), {"tid": plate_scenario["tenant_id"]}
                )
                cleanup_conn.execute(text("SET session_replication_role = DEFAULT"))
                cleanup_trans.commit()
            except Exception:
                cleanup_trans.rollback()
                cleanup_conn.execute(text("SET session_replication_role = DEFAULT"))
                cleanup_conn.commit()
                raise
        cleanup_traceability_scenario(test_engine, plate_scenario["tenant_id"])


# POSTHARVEST-OPS-001E: `test_grading_vs_packing_same_source_serializes_safely`
# removed outright (not rewritten) -- it tested Grading racing a *direct*
# Harvest -> Packing consuming the same HarvestedProduceLot ledger row.
# That contract no longer exists: Packing now consumes exclusively from
# GradedProduceLot balance and never accepts a harvested_produce_lot_id at
# all, so there is no longer any shared-ledger race between the two to prove.


@pytest.mark.integration
def test_quality_hold_race_vs_grading(test_engine) -> None:
    """A Quality Hold placed on the same batch, racing against a Grading
    command -- both lock the owning CropBatch first, so regardless of
    which wins the race, the outcome must be consistent: either the hold
    commits first and grading is blocked, or grading commits first and the
    hold placement still succeeds afterward. No deadlock, no corruption."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()

    def hold_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            hold = quality_hold_service.place_quality_hold(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                effective_time=effective_time, source_observation_event_id=None, reason_code="RACE",
                reason_text="race hold vs grading",
            )
            results["hold"] = ("ok", hold.id)
        except Exception as exc:  # pragma: no cover
            results["hold"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def grading_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = grading_service.record_grading(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                source_harvested_produce_lot_id=scenario["lot_a_id"],
                processing_hall_location_id=scenario["packing_hall_location_id"], effective_time=effective_time,
                note=None, input_presented_weight_kg=Decimal("5.000"), input_presented_whole_unit_count=None,
                rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
                loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
                sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
                remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=None,
                outputs=[_output(scenario, weight="5.000", code="GPL-VS-HOLD")],
            )
            results["grading"] = ("ok", event.id)
        except QualityHoldOpenError:
            results["grading"] = ("blocked", None)
        except Exception as exc:  # pragma: no cover
            results["grading"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=hold_worker)
    t_b = threading.Thread(target=grading_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        assert results["hold"][0] == "ok", results
        assert results["grading"][0] in ("ok", "blocked"), results
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])
