"""CMP-019 backward traceability tests: finished-goods lot -> packing ->
harvest -> crop-batch lineage -> seed origin, plus current storage/dispatch/
quality state. All scenarios are built via committed connections (the
traceability service owns its own dedicated snapshot connection, which
cannot see another session's uncommitted work). Every scenario-building
step runs inside `committed_connection`, which always closes its session
before the outer `finally: cleanup_traceability_scenario(...)` runs --
a mid-scenario exception can never leave an open transaction behind to
block that cleanup."""
import uuid
from decimal import Decimal

import pytest

from app.services import batch_derivation_service, quality_hold_service, traceability_service
from app.services.errors import FarmNotFoundError, FinishedGoodsLotNotFoundError
from tests._traceability_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    build_workflow_scaffold,
    cleanup_traceability_scenario,
    committed_connection,
    create_cold_store_position,
    dispatch,
    harvest_all,
    now,
    pack_lot,
    pack_multi,
    place,
    sow_new_batch,
)


@pytest.mark.integration
def test_simple_chain_seed_to_finished_goods(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id)
            session.commit()
            farm_id, batch_id, seed_lot_id = farm.id, scaffold["batch"].id, scaffold["seed_lot"].id

        trace = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
        )
        assert trace["subject"]["finished_goods_lot_id"] == fg_lot_id
        assert len(trace["packing_inputs"]) == 1
        assert len(trace["produce_lots"]) == 1
        assert trace["produce_lots"][0]["harvested_produce_lot_id"] == produce_lot_id
        assert len(trace["lineage"]["batches"]) == 1
        assert trace["lineage"]["batches"][0]["batch_id"] == batch_id
        assert trace["lineage"]["batches"][0]["transformation_type"] == "sown"
        assert trace["lineage"]["edges"] == []
        assert len(trace["seed_origins"]) == 1
        assert trace["seed_origins"][0]["seed_lot_id"] == seed_lot_id
        assert trace["completeness"]["trace_complete"] is True
        assert trace["completeness"]["limitations"] == []
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_finished_goods_lot_with_multiple_produce_lots_stays_visibly_mixed(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2)
            _, lot_a = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"][:1], suffix="a")
            _, lot_b = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"][1:], suffix="b")
            fg_lot_id, _ = pack_multi(session, tenant, user, farm, produce_lot_ids_and_weights=[(lot_a, Decimal("3.000")), (lot_b, Decimal("2.000"))])
            session.commit()
            farm_id = farm.id

        trace = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
        )
        assert len(trace["packing_inputs"]) == 2
        assert {p["harvested_produce_lot_id"] for p in trace["packing_inputs"]} == {lot_a, lot_b}
        assert len(trace["produce_lots"]) == 2
        # Both harvest lines came from the same batch -- one lineage node.
        assert len(trace["lineage"]["batches"]) == 1
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_split_ancestry_backward(test_engine) -> None:
    """A -> split -> B, C. Harvest+pack from C. Backward trace must reach
    both C (direct) and A (ancestor via the split edge)."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            from sqlalchemy import select
            from app.models.batch_carrier_assignment import BatchCarrierAssignment
            from app.models.crop_batch import CropBatch

            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2)
            suffix = uuid.uuid4().hex[:6]
            event = batch_derivation_service.split_batch(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scaffold["batch"].id,
                client_command_id=uuid.uuid4(), effective_time=now(), note=None,
                outputs=[
                    {"output_batch_code": f"OUT-B-{suffix}", "source_assignment_ids": scaffold["assignment_ids"][:1]},
                    {"output_batch_code": f"OUT-C-{suffix}", "source_assignment_ids": scaffold["assignment_ids"][1:]},
                ],
            )
            session.commit()
            batch_c = session.execute(
                select(CropBatch).where(CropBatch.created_by_batch_derivation_event_id == event.id, CropBatch.code == f"OUT-C-{suffix}")
            ).scalar_one()
            assignment_c = session.execute(
                select(BatchCarrierAssignment).where(BatchCarrierAssignment.batch_id == batch_c.id, BatchCarrierAssignment.released_effective_time.is_(None))
            ).scalars().first()
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=batch_c.id, assignment_ids=[assignment_c.id])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id)
            session.commit()
            batch_c_id = batch_c.id
            source_batch_id = scaffold["batch"].id
            farm_id = farm.id

        trace = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
        )
        batch_ids_in_lineage = {b["batch_id"] for b in trace["lineage"]["batches"]}
        assert batch_c_id in batch_ids_in_lineage
        assert source_batch_id in batch_ids_in_lineage
        assert len(trace["lineage"]["edges"]) == 1
        edge = trace["lineage"]["edges"][0]
        assert edge["parent_batch_id"] == source_batch_id
        assert edge["child_batch_id"] == batch_c_id
        assert edge["derivation_kind"] == "split"
        nodes_by_id = {b["batch_id"]: b for b in trace["lineage"]["batches"]}
        assert nodes_by_id[source_batch_id]["transformation_type"] == "sown"
        assert nodes_by_id[batch_c_id]["transformation_type"] == "split"
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_merge_ancestry_backward_multiple_seed_origins(test_engine) -> None:
    """Two independently-sown batches merge into one; harvest+pack from the
    merged batch must reach both original ancestors and both distinct seed
    origins, without collapsing them."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            from sqlalchemy import select
            from app.models.batch_carrier_assignment import BatchCarrierAssignment
            from app.models.crop_batch import CropBatch

            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            shared_scaffold = build_workflow_scaffold(session, tenant, user, farm)
            s1 = sow_new_batch(session, tenant, user, farm, shared_scaffold, carrier_count=1, suffix="s1")
            s2 = sow_new_batch(session, tenant, user, farm, shared_scaffold, carrier_count=1, suffix="s2")
            session.commit()
            suffix = uuid.uuid4().hex[:6]
            merge_event = batch_derivation_service.merge_batches(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                source_batch_ids=[s1["batch"].id, s2["batch"].id], client_command_id=uuid.uuid4(), effective_time=now(),
                note=None, output_batch_code=f"MERGED-{suffix}",
            )
            session.commit()
            merged = session.execute(
                select(CropBatch).where(CropBatch.created_by_batch_derivation_event_id == merge_event.id)
            ).scalar_one()
            merged_assignments = session.execute(
                select(BatchCarrierAssignment).where(BatchCarrierAssignment.batch_id == merged.id, BatchCarrierAssignment.released_effective_time.is_(None))
            ).scalars().all()

            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=merged.id, assignment_ids=[a.id for a in merged_assignments])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id)
            session.commit()
            merged_id = merged.id
            s1_batch_id, s1_seed_lot_id = s1["batch"].id, s1["seed_lot"].id
            s2_batch_id, s2_seed_lot_id = s2["batch"].id, s2["seed_lot"].id
            farm_id = farm.id

        trace = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
        )
        batch_ids = {b["batch_id"] for b in trace["lineage"]["batches"]}
        assert {s1_batch_id, s2_batch_id, merged_id} <= batch_ids
        assert len(trace["lineage"]["edges"]) == 2
        seed_lot_ids = {o["seed_lot_id"] for o in trace["seed_origins"]}
        assert seed_lot_ids == {s1_seed_lot_id, s2_seed_lot_id}
        assert len(trace["seed_origins"]) == 2
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_storage_dispatch_and_quality_included(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()
            pos = create_cold_store_position(session, tenant, user, farm)
            session.commit()
            place(session, tenant, user, farm, finished_goods_lot_id=fg_lot_id, destination_location_id=pos.id, weight=Decimal("3.000"), count=3)
            session.commit()
            dispatch(session, tenant, user, farm, finished_goods_lot_id=fg_lot_id, weight=Decimal("1.000"), count=1)
            session.commit()
            hold = quality_hold_service.place_quality_hold(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scaffold["batch"].id,
                client_command_id=uuid.uuid4(), effective_time=now(), source_observation_event_id=None,
                reason_code="pest", reason_text="Aphids observed",
            )
            session.commit()
            hold_id = hold.id
            farm_id = farm.id

        trace = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
        )
        assert trace["subject"]["available_weight_kg"] == Decimal("4.000")
        assert trace["subject"]["placed_weight_kg"] == Decimal("3.000")
        assert trace["subject"]["unplaced_weight_kg"] == Decimal("1.000")
        assert len(trace["storage_movements"]) == 1
        assert len(trace["dispatches"]) == 1
        assert trace["dispatches"][0]["dispatched_weight_kg"] == Decimal("1.000")
        assert len(trace["quality"]) == 1
        assert trace["quality"][0]["quality_hold_id"] == hold_id
        assert trace["quality"][0]["is_open"] is True
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_tenant_farm_isolation_and_404(test_engine) -> None:
    tenant_id = None
    other_tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id)
            session.commit()
            farm_id = farm.id

            other_tenant, other_user, other_farm = build_committed_tenant_farm(session)
            other_tenant_id = other_tenant.id
            session.commit()
            other_farm_id = other_farm.id

        with pytest.raises(FinishedGoodsLotNotFoundError):
            traceability_service.get_finished_goods_lot_trace(
                tenant_id=other_tenant_id, farm_id=other_farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
            )
        with pytest.raises(FinishedGoodsLotNotFoundError):
            traceability_service.get_finished_goods_lot_trace(
                tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=uuid.uuid4(), engine=test_engine
            )
        with pytest.raises(FarmNotFoundError):
            traceability_service.get_finished_goods_lot_trace(
                tenant_id=tenant_id, farm_id=uuid.uuid4(), finished_goods_lot_id=fg_lot_id, engine=test_engine
            )
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
        if other_tenant_id is not None:
            cleanup_traceability_scenario(test_engine, other_tenant_id)


@pytest.mark.integration
def test_deterministic_ordering(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2)
            _, lot_a = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"][:1], suffix="a")
            _, lot_b = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"][1:], suffix="b")
            fg_lot_id, _ = pack_multi(session, tenant, user, farm, produce_lot_ids_and_weights=[(lot_a, Decimal("3.000")), (lot_b, Decimal("2.000"))])
            session.commit()
            farm_id = farm.id

        for _ in range(3):
            trace = traceability_service.get_finished_goods_lot_trace(
                tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
            )
            effective_times = [p["effective_time"] for p in trace["produce_lots"]]
            assert effective_times == sorted(effective_times)
            packing_input_ids = [p["harvested_produce_lot_id"] for p in trace["packing_inputs"]]
            assert packing_input_ids == sorted(packing_input_ids)
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
