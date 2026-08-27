"""POSTHARVEST-OPS-001F: GradedProduceLot as a first-class public
traceability entity. Covers backward trace (FG -> GPL -> GradingEvent ->
HPL), forward impact (Batch/HPL -> GPL -> FG), multi-GPL packing, distinct
GPLs graded from one HPL (sibling-grade isolation), and no cross-lineage
leakage -- extending the same committed-scenario style
`test_traceability_backward.py`/`test_traceability_forward_impact.py`
already use."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services import grade_definition_service, grading_service, harvest_service, packing_service, traceability_service
from tests._traceability_scenario import (
    _build_packing_scaffold,
    build_batch_with_assignments,
    build_committed_tenant_farm,
    build_workflow_scaffold,
    cleanup_traceability_scenario,
    committed_connection,
    dispatch,
    harvest_all,
    now,
    pack_lot,
    pack_multi,
    sow_new_batch,
)


@pytest.mark.integration
def test_backward_trace_fg_one_gpl_one_hpl(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(
                session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"]
            )
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id)
            session.commit()
            farm_id = farm.id

        trace = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
        )
        assert len(trace["graded_produce_lots"]) == 1
        assert len(trace["grading_events"]) == 1
        gpl = trace["graded_produce_lots"][0]
        grading_event = trace["grading_events"][0]
        assert gpl["grading_event_id"] == grading_event["grading_event_id"]
        assert grading_event["source_harvested_produce_lot_id"] == produce_lot_id
        # Packing inputs must expose GPL identity directly, not just HPL.
        assert len(trace["packing_inputs"]) == 1
        assert trace["packing_inputs"][0]["graded_produce_lot_id"] == gpl["graded_produce_lot_id"]
        assert trace["packing_inputs"][0]["harvested_produce_lot_id"] == produce_lot_id
        assert len(trace["produce_lots"]) == 1
        assert trace["produce_lots"][0]["harvested_produce_lot_id"] == produce_lot_id
        # POSTHARVEST-OPS-001F correction: weight-only grading (the source
        # HPL here does not track count -- harvest_all always passes
        # whole_unit_count=None) must leave every grading count quantity
        # null, never a fabricated zero or a partial count.
        assert grading_event["input_presented_whole_unit_count"] is None
        assert grading_event["rejected_whole_unit_count"] is None
        assert grading_event["loss_whole_unit_count"] is None
        assert grading_event["sample_whole_unit_count"] is None
        assert grading_event["remainder_whole_unit_count"] is None
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_backward_trace_count_bearing_grading_event_returns_count_quantities(test_engine) -> None:
    """POSTHARVEST-OPS-001F correction: a count-tracked source HPL forces
    count-mode grading (all count fields populated, per
    `ck_grading_events_count_mode_shape`) -- the backward trace's
    `grading_events` entry must surface every one of those existing count
    quantities (input presented/rejected/loss/sample/remainder), mirroring
    the weight breakdown it already returns."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            suffix = uuid.uuid4().hex[:8]
            harvest_event = harvest_service.record_harvest(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scaffold["batch"].id,
                client_command_id=uuid.uuid4(), effective_time=now(), produce_lot_code=f"HLOT-{suffix}", note=None,
                source_lines=[
                    {
                        "batch_carrier_assignment_id": aid, "harvested_weight_kg": Decimal("10.000"),
                        "whole_unit_count": 100, "note": None,
                    }
                    for aid in scaffold["assignment_ids"]
                ],
            )
            produce_lot_id = session.execute(
                text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": harvest_event.id}
            ).scalar_one()

            crop_id, variety_id = session.execute(
                text("SELECT crop_id, variety_id FROM harvested_produce_lots WHERE id = :id"), {"id": produce_lot_id}
            ).one()
            pack_scaffold = _build_packing_scaffold(session, tenant, user, farm, crop_id=crop_id, suffix=suffix)

            grading_event = grading_service.record_grading(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                source_harvested_produce_lot_id=produce_lot_id,
                processing_hall_location_id=pack_scaffold["packing_hall_location_id"], effective_time=now(),
                note=None,
                input_presented_weight_kg=Decimal("10.000"), input_presented_whole_unit_count=100,
                rejected_weight_kg=Decimal("1.000"), rejected_whole_unit_count=10,
                loss_weight_kg=Decimal("0.500"), loss_whole_unit_count=5,
                sample_weight_kg=Decimal("0.500"), sample_whole_unit_count=5,
                remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=0,
                outputs=[
                    {
                        "grade_definition_version_id": pack_scaffold["grade_version_id"], "code": f"GPL-{suffix}",
                        "output_weight_kg": Decimal("8.000"), "output_whole_unit_count": 80,
                    }
                ],
            )
            gpl_id = session.execute(
                text("SELECT id FROM graded_produce_lots WHERE grading_event_id = :eid"), {"eid": grading_event.id}
            ).scalar_one()
            event = packing_service.record_packing(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                pack_specification_version_id=pack_scaffold["pack_specification_version_id"], effective_time=now(),
                finished_goods_lot_code=f"FG-{suffix}", package_count=8, packed_output_weight_kg=Decimal("8.000"),
                process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[
                    {
                        "graded_produce_lot_id": gpl_id, "consumed_weight_kg": Decimal("8.000"),
                        "consumed_whole_unit_count": 80, "note": None,
                    }
                ],
            )
            session.commit()
            fg_lot_id = packing_service.get_packing_event(
                session, tenant_id=tenant.id, farm_id=farm.id, packing_event_id=event.id
            ).finished_goods_lot.id
            farm_id = farm.id

        trace = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
        )
        assert len(trace["grading_events"]) == 1
        ge = trace["grading_events"][0]
        assert ge["input_presented_whole_unit_count"] == 100
        assert ge["rejected_whole_unit_count"] == 10
        assert ge["loss_whole_unit_count"] == 5
        assert ge["sample_whole_unit_count"] == 5
        assert ge["remainder_whole_unit_count"] == 0
        # Weight breakdown must still be present alongside the counts.
        assert ge["input_presented_weight_kg"] == Decimal("10.000")
        assert ge["rejected_weight_kg"] == Decimal("1.000")
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_backward_trace_fg_multiple_gpls_from_different_hpls(test_engine) -> None:
    """One FG lot packed from two GPLs, each graded from its own,
    independent HPL (different harvest events) -- both GPLs and both HPLs
    must appear, never collapsed into one."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2)
            _, lot_a = harvest_all(
                session, tenant, user, farm, batch_id=scaffold["batch"].id,
                assignment_ids=scaffold["assignment_ids"][:1], suffix="a",
            )
            _, lot_b = harvest_all(
                session, tenant, user, farm, batch_id=scaffold["batch"].id,
                assignment_ids=scaffold["assignment_ids"][1:], suffix="b",
            )
            fg_lot_id, _ = pack_multi(
                session, tenant, user, farm,
                produce_lot_ids_and_weights=[(lot_a, Decimal("3.000")), (lot_b, Decimal("2.000"))],
            )
            session.commit()
            farm_id = farm.id

        trace = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
        )
        assert len(trace["graded_produce_lots"]) == 2
        assert len(trace["grading_events"]) == 2
        source_hpl_ids = {ge["source_harvested_produce_lot_id"] for ge in trace["grading_events"]}
        assert source_hpl_ids == {lot_a, lot_b}
        assert len(trace["packing_inputs"]) == 2
        packing_gpl_ids = {p["graded_produce_lot_id"] for p in trace["packing_inputs"]}
        assert packing_gpl_ids == {g["graded_produce_lot_id"] for g in trace["graded_produce_lots"]}
        assert {p["harvested_produce_lot_id"] for p in trace["packing_inputs"]} == {lot_a, lot_b}
        assert len(trace["produce_lots"]) == 2
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_backward_trace_sibling_gpls_from_same_hpl_are_isolated(test_engine) -> None:
    """One HPL graded by one GradingEvent into two distinct GPLs (Grade A,
    Grade B), each packed into its own FG lot. Tracing FG-A backward must
    return only GPL-A -- never GPL-B, even though they share one
    GradingEvent -- mirroring the recall model's own sibling-grade
    isolation rule (docs/domain/RECALL_CONTAINMENT_MODEL.md)."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(
                session, tenant, user, farm, batch_id=scaffold["batch"].id,
                assignment_ids=scaffold["assignment_ids"], weight_per_line=Decimal("10.000"),
            )
            crop_id, variety_id = session.execute(
                text("SELECT crop_id, variety_id FROM harvested_produce_lots WHERE id = :id"), {"id": produce_lot_id}
            ).one()
            suffix = uuid.uuid4().hex[:8]
            pack_scaffold = _build_packing_scaffold(session, tenant, user, farm, crop_id=crop_id, suffix=suffix)

            second_grade_definition = grade_definition_service.register_grade_definition(
                session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                code=f"grade2-{suffix}", name="Second Grade", crop_id=crop_id, variety_id=None, description=None,
            )
            second_grade_version = grade_definition_service.create_draft_version(
                session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                grade_definition_id=second_grade_definition.id, spec_notes=None,
            )
            grade_definition_service.activate_version(
                session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                grade_definition_id=second_grade_definition.id, version_id=second_grade_version.id,
                effective_time=now(),
            )

            grading_event = grading_service.record_grading(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                source_harvested_produce_lot_id=produce_lot_id,
                processing_hall_location_id=pack_scaffold["packing_hall_location_id"], effective_time=now(),
                note=None,
                input_presented_weight_kg=Decimal("10.000"), input_presented_whole_unit_count=None,
                rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
                loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
                sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
                remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=None,
                outputs=[
                    {
                        "grade_definition_version_id": pack_scaffold["grade_version_id"], "code": f"GPL-A-{suffix}",
                        "output_weight_kg": Decimal("6.000"), "output_whole_unit_count": None,
                    },
                    {
                        "grade_definition_version_id": second_grade_version.id, "code": f"GPL-B-{suffix}",
                        "output_weight_kg": Decimal("4.000"), "output_whole_unit_count": None,
                    },
                ],
            )
            gpl_a_id, gpl_b_id = session.execute(
                text(
                    "SELECT id FROM graded_produce_lots WHERE grading_event_id = :eid ORDER BY code"
                ),
                {"eid": grading_event.id},
            ).scalars().all()

            event_a = packing_service.record_packing(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                pack_specification_version_id=pack_scaffold["pack_specification_version_id"], effective_time=now(),
                finished_goods_lot_code=f"FG-A-{suffix}", package_count=6, packed_output_weight_kg=Decimal("6.000"),
                process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[
                    {
                        "graded_produce_lot_id": gpl_a_id, "consumed_weight_kg": Decimal("6.000"),
                        "consumed_whole_unit_count": None, "note": None,
                    }
                ],
            )
            event_b = packing_service.record_packing(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                pack_specification_version_id=pack_scaffold["pack_specification_version_id"], effective_time=now(),
                finished_goods_lot_code=f"FG-B-{suffix}", package_count=4, packed_output_weight_kg=Decimal("4.000"),
                process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[
                    {
                        "graded_produce_lot_id": gpl_b_id, "consumed_weight_kg": Decimal("4.000"),
                        "consumed_whole_unit_count": None, "note": None,
                    }
                ],
            )
            session.commit()
            fg_a_id = packing_service.get_packing_event(
                session, tenant_id=tenant.id, farm_id=farm.id, packing_event_id=event_a.id
            ).finished_goods_lot.id
            fg_b_id = packing_service.get_packing_event(
                session, tenant_id=tenant.id, farm_id=farm.id, packing_event_id=event_b.id
            ).finished_goods_lot.id
            farm_id = farm.id
            grading_event_id = grading_event.id

        trace_a = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_a_id, engine=test_engine
        )
        assert len(trace_a["graded_produce_lots"]) == 1
        assert trace_a["graded_produce_lots"][0]["graded_produce_lot_id"] == gpl_a_id
        # The shared GradingEvent still resolves, but never pulls in GPL-B.
        assert len(trace_a["grading_events"]) == 1
        assert trace_a["grading_events"][0]["grading_event_id"] == grading_event_id
        gpl_ids_in_trace_a = {g["graded_produce_lot_id"] for g in trace_a["graded_produce_lots"]}
        assert gpl_b_id not in gpl_ids_in_trace_a

        trace_b = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_b_id, engine=test_engine
        )
        assert len(trace_b["graded_produce_lots"]) == 1
        assert trace_b["graded_produce_lots"][0]["graded_produce_lot_id"] == gpl_b_id
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_backward_trace_no_foreign_lineage_leakage(test_engine) -> None:
    """Two independently sown/harvested/graded/packed batches. Tracing one
    FG lot backward must never surface the other batch's GPL, HPL, or seed
    lot."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold_a = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1, suffix="a")
            scaffold_b = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1, suffix="b")
            _, lot_a = harvest_all(
                session, tenant, user, farm, batch_id=scaffold_a["batch"].id,
                assignment_ids=scaffold_a["assignment_ids"], suffix="a",
            )
            _, lot_b = harvest_all(
                session, tenant, user, farm, batch_id=scaffold_b["batch"].id,
                assignment_ids=scaffold_b["assignment_ids"], suffix="b",
            )
            fg_a, _ = pack_lot(session, tenant, user, farm, produce_lot_id=lot_a, suffix="a")
            fg_b, _ = pack_lot(session, tenant, user, farm, produce_lot_id=lot_b, suffix="b")
            session.commit()
            farm_id = farm.id
            seed_lot_a_id, seed_lot_b_id = scaffold_a["seed_lot"].id, scaffold_b["seed_lot"].id
            batch_a_id, batch_b_id = scaffold_a["batch"].id, scaffold_b["batch"].id

        trace_a = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_a, engine=test_engine
        )
        assert {p["harvested_produce_lot_id"] for p in trace_a["packing_inputs"]} == {lot_a}
        assert lot_b not in {p["harvested_produce_lot_id"] for p in trace_a["packing_inputs"]}
        assert {b["batch_id"] for b in trace_a["lineage"]["batches"]} == {batch_a_id}
        assert batch_b_id not in {b["batch_id"] for b in trace_a["lineage"]["batches"]}
        assert {o["seed_lot_id"] for o in trace_a["seed_origins"]} == {seed_lot_a_id}
        assert seed_lot_b_id not in {o["seed_lot_id"] for o in trace_a["seed_origins"]}
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_backward_trace_fg_to_dispatch_with_gpl_identity(test_engine) -> None:
    """Full chain: seed -> batch -> harvest -> grade -> pack -> dispatch.
    Confirms GPL identity and dispatch history are both present in one
    consistent snapshot."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(
                session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"],
                weight_per_line=Decimal("5.000"),
            )
            fg_lot_id, _ = pack_lot(
                session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5,
            )
            session.commit()
            dispatch(session, tenant, user, farm, finished_goods_lot_id=fg_lot_id, weight=Decimal("2.000"), count=2)
            session.commit()
            farm_id = farm.id

        trace = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
        )
        assert len(trace["graded_produce_lots"]) == 1
        assert len(trace["dispatches"]) == 1
        assert trace["dispatches"][0]["dispatched_weight_kg"] == Decimal("2.000")
        assert trace["dispatches"][0]["finished_goods_lot_id"] == fg_lot_id
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_forward_impact_crop_batch_includes_graded_produce_lot_identity(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(
                session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"],
                weight_per_line=Decimal("5.000"),
            )
            fg_lot_id, _ = pack_lot(
                session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5,
            )
            session.commit()
            farm_id, batch_id = farm.id, scaffold["batch"].id

        impact = traceability_service.get_crop_batch_impact(
            tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=batch_id, engine=test_engine
        )
        assert len(impact["graded_produce_lots"]) == 1
        gpl = impact["graded_produce_lots"][0]
        assert gpl["is_affected_source"] is True
        assert impact["summary"]["affected_graded_produce_lot_count"] == 1
        assert {p["graded_produce_lot_id"] for p in impact["packing_inputs"]} == {gpl["graded_produce_lot_id"]}
        assert len(impact["finished_goods"]) == 1
        assert impact["finished_goods"][0]["finished_goods_lot_id"] == fg_lot_id
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_forward_impact_harvested_produce_lot_includes_graded_produce_lot_identity(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(
                session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"],
                weight_per_line=Decimal("5.000"),
            )
            fg_lot_id, _ = pack_lot(
                session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5,
            )
            session.commit()
            farm_id = farm.id

        impact = traceability_service.get_harvested_produce_lot_impact(
            tenant_id=tenant_id, farm_id=farm_id, harvested_produce_lot_id=produce_lot_id, engine=test_engine
        )
        assert len(impact["graded_produce_lots"]) == 1
        assert impact["graded_produce_lots"][0]["is_affected_source"] is True
        assert impact["summary"]["affected_graded_produce_lot_count"] == 1
        assert impact["finished_goods"][0]["finished_goods_lot_id"] == fg_lot_id
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_forward_impact_unaffected_co_input_gpl_never_promoted(test_engine) -> None:
    """FG lot packed from an affected GPL (from the traced batch) and an
    unaffected co-input GPL (from an unrelated batch). Both GPLs appear as
    context, but only the affected one is flagged `is_affected_source` and
    counted in the summary -- mirroring the packing-input-line rule this
    ticket extends one lineage hop further out."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            shared_scaffold = build_workflow_scaffold(session, tenant, user, farm)
            scaffold_affected = sow_new_batch(session, tenant, user, farm, shared_scaffold, carrier_count=1, suffix="affected")
            scaffold_other = sow_new_batch(session, tenant, user, farm, shared_scaffold, carrier_count=1, suffix="other")
            _, lot_affected = harvest_all(
                session, tenant, user, farm, batch_id=scaffold_affected["batch"].id,
                assignment_ids=scaffold_affected["assignment_ids"], weight_per_line=Decimal("3.000"),
            )
            _, lot_other = harvest_all(
                session, tenant, user, farm, batch_id=scaffold_other["batch"].id,
                assignment_ids=scaffold_other["assignment_ids"], weight_per_line=Decimal("2.000"),
            )
            fg_lot_id, _ = pack_multi(
                session, tenant, user, farm,
                produce_lot_ids_and_weights=[(lot_affected, Decimal("3.000")), (lot_other, Decimal("2.000"))],
            )
            session.commit()
            farm_id, affected_batch_id = farm.id, scaffold_affected["batch"].id

        impact = traceability_service.get_crop_batch_impact(
            tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=affected_batch_id, engine=test_engine
        )
        assert len(impact["graded_produce_lots"]) == 2
        affected = [g for g in impact["graded_produce_lots"] if g["is_affected_source"]]
        unaffected = [g for g in impact["graded_produce_lots"] if not g["is_affected_source"]]
        assert len(affected) == 1
        assert len(unaffected) == 1
        assert impact["summary"]["affected_graded_produce_lot_count"] == 1
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
