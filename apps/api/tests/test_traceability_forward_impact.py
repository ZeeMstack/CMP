"""CMP-019 forward recall-impact tests: crop-batch and harvested-produce-lot
impact, covering split/merge descendants, no-double-counting, partial and
multi-event dispatch, multi-location storage, and the ticket's explicit
no-proportional-attribution rule (a "potentially affected" downstream
quantity is always a finished-goods lot's own entire current quantity,
never a fraction of an upstream input)."""
import uuid
from decimal import Decimal

import pytest

from app.services import batch_derivation_service, traceability_service
from app.services.errors import CropBatchNotFoundError, FarmNotFoundError, HarvestedProduceLotNotFoundError
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
def test_batch_with_no_descendants_or_harvest(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            session.commit()
            farm_id, batch_id = farm.id, scaffold["batch"].id

        impact = traceability_service.get_crop_batch_impact(
            tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=batch_id, engine=test_engine
        )
        assert impact["harvest_events"] == []
        assert impact["produce_lots"] == []
        assert impact["finished_goods"] == []
        assert impact["summary"]["affected_finished_goods_lot_count"] == 0
        assert impact["summary"]["potentially_affected_available_weight_kg"] == Decimal("0")
        assert impact["completeness"]["trace_complete"] is True
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_direct_harvest_one_input_one_fg_lot(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()
            farm_id, batch_id = farm.id, scaffold["batch"].id

        impact = traceability_service.get_crop_batch_impact(
            tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=batch_id, engine=test_engine
        )
        assert len(impact["produce_lots"]) == 1
        assert len(impact["finished_goods"]) == 1
        fg = impact["finished_goods"][0]
        assert fg["finished_goods_lot_id"] == fg_lot_id
        assert fg["source_input_weight_kg"] == Decimal("5.000")
        assert fg["potentially_affected_available_weight_kg"] == Decimal("5.000")
        assert fg["potentially_affected_available_package_count"] == 5
        assert impact["summary"]["affected_finished_goods_lot_count"] == 1
        assert impact["summary"]["potentially_affected_available_weight_kg"] == Decimal("5.000")
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_split_descendants_forward(test_engine) -> None:
    """A -> split -> B, C. Both harvested+packed independently. Impact from
    A must reach FG lots from both B and C."""
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
            outputs = session.execute(
                select(CropBatch).where(CropBatch.created_by_batch_derivation_event_id == event.id).order_by(CropBatch.code)
            ).scalars().all()
            fg_lot_ids = set()
            for out_batch in outputs:
                assignment = session.execute(
                    select(BatchCarrierAssignment).where(BatchCarrierAssignment.batch_id == out_batch.id, BatchCarrierAssignment.released_effective_time.is_(None))
                ).scalars().first()
                _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=out_batch.id, assignment_ids=[assignment.id], suffix=out_batch.code)
                fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, suffix=out_batch.code)
                fg_lot_ids.add(fg_lot_id)
            session.commit()
            farm_id, source_batch_id = farm.id, scaffold["batch"].id

        impact = traceability_service.get_crop_batch_impact(
            tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=source_batch_id, engine=test_engine
        )
        assert {f["finished_goods_lot_id"] for f in impact["finished_goods"]} == fg_lot_ids
        assert impact["summary"]["affected_crop_batch_count"] == 3  # source + 2 outputs
        assert impact["summary"]["affected_finished_goods_lot_count"] == 2
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_merge_descendant_forward(test_engine) -> None:
    """s1, s2 -> merge -> M. Harvest+pack from M. Impact from s1 alone must
    still reach M's finished goods -- a merge output reached from the
    selected source is potentially affected even though the merge also
    combined an unrelated source (s2)."""
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
            farm_id, s1_batch_id = farm.id, s1["batch"].id

        impact = traceability_service.get_crop_batch_impact(
            tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=s1_batch_id, engine=test_engine
        )
        assert {f["finished_goods_lot_id"] for f in impact["finished_goods"]} == {fg_lot_id}
        assert impact["summary"]["affected_crop_batch_count"] == 2  # s1 + merged
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_multiple_affected_inputs_no_double_count_fg_lot(test_engine) -> None:
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
            farm_id, batch_id = farm.id, scaffold["batch"].id

        impact = traceability_service.get_crop_batch_impact(
            tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=batch_id, engine=test_engine
        )
        # Both produce lots are affected sources for the SAME fg lot -- it
        # must appear exactly once, with source_input summing both inputs.
        assert len(impact["finished_goods"]) == 1
        fg = impact["finished_goods"][0]
        assert fg["finished_goods_lot_id"] == fg_lot_id
        assert fg["source_input_weight_kg"] == Decimal("5.000")
        assert impact["summary"]["affected_finished_goods_lot_count"] == 1
        assert impact["summary"]["affected_harvested_produce_lot_count"] == 2
        assert impact["summary"]["potentially_affected_available_weight_kg"] == Decimal("5.000")
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_partial_dispatch_and_multi_event_dispatch_and_storage(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"], weight_per_line=Decimal("10.000"))
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("10.000"), package_count=10)
            session.commit()
            pos_a = create_cold_store_position(session, tenant, user, farm, suffix="a")
            pos_b = create_cold_store_position(session, tenant, user, farm, suffix="b")
            session.commit()
            place(session, tenant, user, farm, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_a.id, weight=Decimal("3.000"), count=3)
            session.commit()
            place(session, tenant, user, farm, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_b.id, weight=Decimal("2.000"), count=2)
            session.commit()
            dispatch(session, tenant, user, farm, finished_goods_lot_id=fg_lot_id, weight=Decimal("1.000"), count=1)
            session.commit()
            dispatch(session, tenant, user, farm, finished_goods_lot_id=fg_lot_id, weight=Decimal("2.000"), count=2)
            session.commit()
            farm_id, batch_id = farm.id, scaffold["batch"].id
            pos_a_id, pos_b_id = pos_a.id, pos_b.id

        impact = traceability_service.get_crop_batch_impact(
            tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=batch_id, engine=test_engine
        )
        fg = impact["finished_goods"][0]
        assert fg["potentially_affected_available_weight_kg"] == Decimal("7.000")
        assert fg["potentially_affected_dispatched_weight_kg"] == Decimal("3.000")
        assert fg["potentially_affected_placed_weight_kg"] == Decimal("5.000")
        assert fg["potentially_affected_unplaced_weight_kg"] == Decimal("2.000")
        assert len(impact["dispatches"]) == 2
        assert impact["summary"]["affected_dispatch_event_count"] == 2
        storage_locations = {s["location_id"] for s in impact["storage"]}
        assert storage_locations == {pos_a_id, pos_b_id}
        assert impact["summary"]["potentially_affected_dispatched_weight_kg"] == Decimal("3.000")
        assert impact["summary"]["potentially_affected_placed_weight_kg"] == Decimal("5.000")
        assert impact["summary"]["potentially_affected_unplaced_weight_kg"] == Decimal("2.000")
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_no_proportional_attribution_invented(test_engine) -> None:
    """FG lot = 5kg total, from a 3kg affected input + a 2kg unaffected
    input (packed from two different batches). Impact must report the
    entire 5kg as potentially affected, and the affected source input as
    exactly 3kg -- never a computed "3/5 of the lot" style figure."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            shared_scaffold = build_workflow_scaffold(session, tenant, user, farm)
            scaffold_a = sow_new_batch(session, tenant, user, farm, shared_scaffold, carrier_count=1, suffix="affected")
            scaffold_b = sow_new_batch(session, tenant, user, farm, shared_scaffold, carrier_count=1, suffix="other")
            _, lot_affected = harvest_all(session, tenant, user, farm, batch_id=scaffold_a["batch"].id, assignment_ids=scaffold_a["assignment_ids"], weight_per_line=Decimal("3.000"))
            _, lot_other = harvest_all(session, tenant, user, farm, batch_id=scaffold_b["batch"].id, assignment_ids=scaffold_b["assignment_ids"], weight_per_line=Decimal("2.000"))
            fg_lot_id, _ = pack_multi(session, tenant, user, farm, produce_lot_ids_and_weights=[(lot_affected, Decimal("3.000")), (lot_other, Decimal("2.000"))])
            session.commit()
            farm_id, affected_batch_id = farm.id, scaffold_a["batch"].id

        impact = traceability_service.get_crop_batch_impact(
            tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=affected_batch_id, engine=test_engine
        )
        assert len(impact["finished_goods"]) == 1
        fg = impact["finished_goods"][0]
        assert fg["source_input_weight_kg"] == Decimal("3.000")
        assert fg["potentially_affected_available_weight_kg"] == Decimal("5.000")
        # The unaffected co-input must still be visible as packing context...
        input_lot_ids = {p["harvested_produce_lot_id"] for p in impact["packing_inputs"]}
        assert lot_other in input_lot_ids
        # ...but never counted as an affected produce lot in its own right.
        assert impact["summary"]["affected_harvested_produce_lot_count"] == 1
        other_input = next(p for p in impact["packing_inputs"] if p["harvested_produce_lot_id"] == lot_other)
        assert other_input["is_affected_source"] is False
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_crop_batch_impact_tenant_farm_isolation_and_404(test_engine) -> None:
    tenant_id = None
    other_tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            session.commit()
            farm_id, batch_id = farm.id, scaffold["batch"].id

            other_tenant, other_user, other_farm = build_committed_tenant_farm(session)
            other_tenant_id = other_tenant.id
            session.commit()
            other_farm_id = other_farm.id

        with pytest.raises(CropBatchNotFoundError):
            traceability_service.get_crop_batch_impact(tenant_id=other_tenant_id, farm_id=other_farm_id, crop_batch_id=batch_id, engine=test_engine)
        with pytest.raises(CropBatchNotFoundError):
            traceability_service.get_crop_batch_impact(tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=uuid.uuid4(), engine=test_engine)
        with pytest.raises(FarmNotFoundError):
            traceability_service.get_crop_batch_impact(tenant_id=tenant_id, farm_id=uuid.uuid4(), crop_batch_id=batch_id, engine=test_engine)
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
        if other_tenant_id is not None:
            cleanup_traceability_scenario(test_engine, other_tenant_id)


# --- Harvested-produce-lot impact (thin reuse of the same downstream engine) --


@pytest.mark.integration
def test_produce_lot_impact_unused_lot(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            session.commit()
            farm_id = farm.id

        impact = traceability_service.get_harvested_produce_lot_impact(
            tenant_id=tenant_id, farm_id=farm_id, harvested_produce_lot_id=produce_lot_id, engine=test_engine
        )
        assert impact["finished_goods"] == []
        assert impact["summary"]["affected_finished_goods_lot_count"] == 0
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_produce_lot_impact_partially_and_fully_consumed(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"], weight_per_line=Decimal("10.000"))
            # partial consumption: only 4kg of the 10kg produce lot is packed
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("4.000"), package_count=4)
            session.commit()
            farm_id = farm.id

        impact = traceability_service.get_harvested_produce_lot_impact(
            tenant_id=tenant_id, farm_id=farm_id, harvested_produce_lot_id=produce_lot_id, engine=test_engine
        )
        assert len(impact["finished_goods"]) == 1
        assert impact["finished_goods"][0]["source_input_weight_kg"] == Decimal("4.000")
        assert impact["finished_goods"][0]["potentially_affected_available_weight_kg"] == Decimal("4.000")
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_produce_lot_impact_does_not_include_unrelated_sibling(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2)
            _, lot_a = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"][:1], suffix="a")
            _, lot_b = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"][1:], suffix="b")
            fg_a, _ = pack_lot(session, tenant, user, farm, produce_lot_id=lot_a, weight=Decimal("3.000"), package_count=3, suffix="a")
            fg_b, _ = pack_lot(session, tenant, user, farm, produce_lot_id=lot_b, weight=Decimal("2.000"), package_count=2, suffix="b")
            session.commit()
            farm_id = farm.id

        impact = traceability_service.get_harvested_produce_lot_impact(
            tenant_id=tenant_id, farm_id=farm_id, harvested_produce_lot_id=lot_a, engine=test_engine
        )
        fg_ids = {f["finished_goods_lot_id"] for f in impact["finished_goods"]}
        assert fg_ids == {fg_a}
        assert fg_b not in fg_ids
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_produce_lot_impact_tenant_farm_isolation_and_404(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            session.commit()
            farm_id = farm.id

        with pytest.raises(HarvestedProduceLotNotFoundError):
            traceability_service.get_harvested_produce_lot_impact(
                tenant_id=tenant_id, farm_id=farm_id, harvested_produce_lot_id=uuid.uuid4(), engine=test_engine
            )
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
