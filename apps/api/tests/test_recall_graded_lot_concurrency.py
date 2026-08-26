"""POSTHARVEST-OPS-001D concurrency race tests: real two-connection races
(same `threading.Barrier` pattern `test_recall_concurrency.py` already
uses), proving (A) a duplicate graded-produce-lot-source open command
resolves to exactly one logical case with no duplicate scope, and (B) a
harvested-produce-lot-source recall opening races a concurrent
`GradingEvent` attempt against the same produce lot with no deadlock and
exactly one coherent serial outcome -- proving the new GradedProduceLot
lock tier (inserted between HarvestedProduceLot and FinishedGoodsLot)
introduces no lock-order inversion with grading's own
CropBatch-before-HarvestedProduceLot lock order."""
import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import grading_service, recall_service
from app.services.errors import RecallContainmentOpenError
from tests._recall_graded_lot_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    build_grading_scaffold,
    cleanup_recall_graded_lot_scenario,
    committed_connection,
    harvest_all,
    now,
)
from tests.test_recall_graded_lot_case_opening import _build_graded_pair, _crop_id_for_lot


@pytest.mark.integration
def test_duplicate_graded_produce_lot_source_open_command_race_one_logical_case(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
            user_id = user.id

        client_command_id = uuid.uuid4()
        effective_time = now()
        code = f"RC-GPL-DUP-{uuid.uuid4().hex[:8]}"
        barrier = threading.Barrier(2)
        results: dict[str, tuple] = {}

        def worker(name: str) -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                case = recall_service.open_recall_case(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
                    client_command_id=client_command_id, effective_time=effective_time,
                    code=code, crop_batch_id=None, harvested_produce_lot_id=None,
                    graded_produce_lot_id=gpl_a_id, finished_goods_lot_id=None,
                    reason_code="contamination_suspected", reason_text="duplicate race",
                )
                session.commit()
                results[name] = ("ok", case.id)
            except Exception as exc:
                session.rollback()
                results[name] = ("error", exc)
            finally:
                session.close()
                conn.close()

        t1 = threading.Thread(target=worker, args=("one",))
        t2 = threading.Thread(target=worker, args=("two",))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert not t1.is_alive() and not t2.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        assert results["one"][0] == "ok" and results["two"][0] == "ok", results
        assert results["one"][1] == results["two"][1], "identical client_command_id must resolve to one logical case"

        with test_engine.connect() as conn:
            case_count = conn.execute(
                text("SELECT count(*) FROM recall_cases WHERE tenant_id = :tid AND client_command_id = :ccid"),
                {"tid": tenant_id, "ccid": client_command_id},
            ).scalar_one()
            scope_count = conn.execute(
                text("SELECT count(*) FROM recall_scope_graded_produce_lots WHERE recall_case_id = :cid"),
                {"cid": results["one"][1]},
            ).scalar_one()
        assert case_count == 1
        assert scope_count == 1
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_open_produce_lot_source_vs_grading_one_serial_truth(test_engine) -> None:
    """No lock-order inversion between the new GradedProduceLot tier and
    grading's own CropBatch-before-HarvestedProduceLot order: a
    harvested-produce-lot-source recall opening (which locks the produce
    lot, then derives/locks its graded descendants) races a concurrent
    `GradingEvent` attempt against the same produce lot (which locks the
    batch, then the same produce lot, before creating any new
    GradedProduceLot)."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            user_id = user.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(
                session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"],
                weight_per_line=Decimal("5.000"),
            )
            session.commit()
            crop_id = _crop_id_for_lot(session, produce_lot_id)
            grading_scaffold = build_grading_scaffold(session, tenant, user, farm, crop_id=crop_id)
            session.commit()
            hall_id = grading_scaffold["packing_hall_location_id"]
            grade_a_id = grading_scaffold["grade_a_version_id"]

        barrier = threading.Barrier(2)
        results: dict[str, tuple] = {}
        effective_time = now()

        def recall_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                case = recall_service.open_recall_case(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
                    client_command_id=uuid.uuid4(), effective_time=effective_time,
                    code=f"RC-GPL-RACE-{uuid.uuid4().hex[:8]}", crop_batch_id=None,
                    harvested_produce_lot_id=produce_lot_id, graded_produce_lot_id=None,
                    finished_goods_lot_id=None, reason_code="contamination_suspected", reason_text="race",
                )
                session.commit()
                results["recall"] = ("ok", case.id)
            except Exception as exc:
                session.rollback()
                results["recall"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        def grading_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                event = grading_service.record_grading(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
                    client_command_id=uuid.uuid4(), source_harvested_produce_lot_id=produce_lot_id,
                    processing_hall_location_id=hall_id, effective_time=effective_time, note=None,
                    input_presented_weight_kg=Decimal("5.000"), input_presented_whole_unit_count=None,
                    rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
                    loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
                    sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
                    remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=None,
                    outputs=[
                        {
                            "grade_definition_version_id": grade_a_id, "code": f"GPL-RACE-{uuid.uuid4().hex[:8]}",
                            "output_weight_kg": Decimal("5.000"), "output_whole_unit_count": None,
                        },
                    ],
                )
                session.commit()
                results["grading"] = ("ok", event.id)
            except Exception as exc:
                session.rollback()
                results["grading"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        t_recall = threading.Thread(target=recall_worker)
        t_grading = threading.Thread(target=grading_worker)
        t_recall.start()
        t_grading.start()
        t_recall.join(timeout=15)
        t_grading.join(timeout=15)

        assert not t_recall.is_alive() and not t_grading.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        assert results["recall"][0] == "ok", results
        recall_outcome, grading_outcome = results["recall"][0], results["grading"][0]
        assert (recall_outcome, grading_outcome) in {("ok", "ok"), ("ok", "error")}, results

        if grading_outcome == "ok":
            # A. grading committed first -> the new GradedProduceLot it
            # created must appear in the recall's frozen scope (which
            # necessarily opened afterward, having waited on the same
            # produce-lot lock).
            case_id = results["recall"][1]
            detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
            assert len(detail["frozen_scope"]["graded_produce_lot_ids"]) == 1
        else:
            # B. recall committed first -> grading, resuming after the
            # produce-lot lock freed, must see the now-open containment.
            assert isinstance(results["grading"][1], RecallContainmentOpenError), results["grading"]
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)
