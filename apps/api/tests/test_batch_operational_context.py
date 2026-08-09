"""CMP-FE-002A tests for the shared batch operational read model
(`operational_read_service.get_batch_operational_contexts`, plus its
`resolve_batch_ids_by_state` companion): sowing-origin resolution across
derivation ancestry (direct, split-inherited, merge same/differing
effective_time), structured placement facts (unplaced/placed/partial/
shared-branch/scattered), open quality-hold aggregation, active-vs-all
state filtering, tenant/farm isolation, and snapshot consistency under a
concurrent write. Exercises the service directly against a dedicated
`_snapshot_connection`, exactly as the two new routes do -- consistent
with how CMP-019/CMP-020's own snapshot-connection-dependent code is
tested elsewhere in this codebase (see test_traceability_concurrency.py)."""
import threading
import uuid
from datetime import timedelta

import pytest

from app.services import operational_read_service
from app.services.lineage_traversal import _snapshot_connection
from tests._operational_read_scenario import (
    batch_id_by_code,
    build_committed_tenant_farm,
    build_direct_placement_workflow_scaffold,
    build_transplant_workflow_scaffold,
    committed_connection,
    merge,
    minutes_after,
    now,
    open_hold,
    place_carrier,
    release_hold,
    sow_batch,
    sow_second_carrier,
    split,
    transition,
    transplant_to_plate,
)
from tests._traceability_scenario import cleanup_traceability_scenario


@pytest.mark.integration
def test_direct_sown_batch_resolves_single_sowing_origin(test_engine) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0)
            session.commit()
            batch_id, farm_id = sown["batch"].id, farm.id

        with _snapshot_connection(test_engine) as conn:
            [ctx] = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[batch_id]
            )
        assert len(ctx.sowing_origins) == 1
        assert ctx.sowing_origins[0].source_batch_id == batch_id
        assert ctx.sown_effective_time == t0
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_split_child_inherits_sowing_origin_from_parent(test_engine) -> None:
    """`_seed_origins_for_batches` (reused verbatim from lineage_traversal)
    returns one row per sowing-opened assignment, and split requires >= 2
    non-empty outputs, so a splittable parent necessarily has >= 2
    assignments/origins -- the child therefore provably traces back to
    *all* of the parent's origins (batch-level ancestry, honest about what
    it can prove), not just the one assignment it happened to receive.
    What matters for the derived batch is that those origins still resolve
    to one unambiguous `sown_effective_time` when they share a sowing
    event/time -- exactly the multi-origin-but-unambiguous case a real
    split-derived batch (e.g. PILOT-LOT-007A/007B) needs."""
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0)
            second = sow_second_carrier(
                session, tenant, user, farm, batch_id=sown["batch"].id, seed_lot_id=sown["seed_lot"].id,
                effective_time=t0,
            )
            session.commit()
            parent_id, farm_id = sown["batch"].id, farm.id
            assignment_id, sibling_assignment_id = sown["assignment_id"], second["assignment_id"]

            output_code = f"CHILD-{uuid.uuid4().hex[:8]}"
            sibling_code = f"SIBLING-{uuid.uuid4().hex[:8]}"
            split(
                session, tenant, user, farm, batch_id=parent_id, output_codes=[output_code, sibling_code],
                source_assignment_ids=[assignment_id, sibling_assignment_id], effective_time=minutes_after(t0, 5),
            )
            session.commit()
            child_id = batch_id_by_code(session, tenant, code=output_code)

        with _snapshot_connection(test_engine) as conn:
            [ctx] = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[child_id]
            )
        assert len(ctx.sowing_origins) == 2
        assert {o.source_batch_id for o in ctx.sowing_origins} == {parent_id}
        assert ctx.sown_effective_time == t0
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_merge_with_same_effective_time_yields_unambiguous_sown_effective_time(test_engine) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)
            s1 = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, code_suffix="a")
            s2 = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, code_suffix="b")
            session.commit()
            farm_id = farm.id
            s1_batch_id, s2_batch_id = s1["batch"].id, s2["batch"].id

            output_code = f"MERGED-{uuid.uuid4().hex[:8]}"
            merge(
                session, tenant, user, farm, source_batch_ids=[s1_batch_id, s2_batch_id],
                output_code=output_code, effective_time=minutes_after(t0, 5),
            )
            session.commit()
            merged_id = batch_id_by_code(session, tenant, code=output_code)

        with _snapshot_connection(test_engine) as conn:
            [ctx] = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[merged_id]
            )
        assert len(ctx.sowing_origins) == 2
        assert {o.source_batch_id for o in ctx.sowing_origins} == {s1_batch_id, s2_batch_id}
        assert ctx.sown_effective_time == t0
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_merge_with_differing_effective_time_yields_null_sown_effective_time(test_engine) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30) - timedelta(days=2)
        t1 = now() - timedelta(days=1)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)
            s1 = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, code_suffix="a")
            s2 = sow_batch(session, tenant, user, farm, scaffold, effective_time=t1, code_suffix="b")
            session.commit()
            farm_id = farm.id

            output_code = f"MERGED-{uuid.uuid4().hex[:8]}"
            merge(
                session, tenant, user, farm, source_batch_ids=[s1["batch"].id, s2["batch"].id],
                output_code=output_code, effective_time=now(),
            )
            session.commit()
            merged_id = batch_id_by_code(session, tenant, code=output_code)

        with _snapshot_connection(test_engine) as conn:
            [ctx] = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[merged_id]
            )
        assert len(ctx.sowing_origins) == 2
        assert {o.effective_time for o in ctx.sowing_origins} == {t0, t1}
        assert ctx.sown_effective_time is None
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_zero_active_carriers_on_fully_split_source_batch(test_engine) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0)
            second = sow_second_carrier(
                session, tenant, user, farm, batch_id=sown["batch"].id, seed_lot_id=sown["seed_lot"].id,
                effective_time=minutes_after(t0, 1),
            )
            session.commit()
            parent_id, farm_id = sown["batch"].id, farm.id
            assignment_id, sibling_assignment_id = sown["assignment_id"], second["assignment_id"]

            split(
                session, tenant, user, farm, batch_id=parent_id,
                output_codes=[f"CHILD-{uuid.uuid4().hex[:8]}", f"SIBLING-{uuid.uuid4().hex[:8]}"],
                source_assignment_ids=[assignment_id, sibling_assignment_id], effective_time=minutes_after(t0, 5),
            )
            session.commit()

        with _snapshot_connection(test_engine) as conn:
            [ctx] = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[parent_id]
            )
        assert ctx.state == "superseded"
        assert ctx.placement.active_carrier_count == 0
        assert ctx.placement.placed_carrier_count == 0
        assert ctx.placement.unplaced_carrier_count == 0
        assert ctx.placement.placements == []
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_active_carrier_never_placed_counts_as_unplaced(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=now())
            session.commit()
            batch_id, farm_id = sown["batch"].id, farm.id

        with _snapshot_connection(test_engine) as conn:
            [ctx] = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[batch_id]
            )
        assert ctx.placement.active_carrier_count == 1
        assert ctx.placement.placed_carrier_count == 0
        assert ctx.placement.unplaced_carrier_count == 1
        assert ctx.placement.placements == []
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_single_placement_reports_full_path(test_engine) -> None:
    from tests._operational_read_scenario import build_greenhouse_tree

    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_direct_placement_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=now(), carrier_type_code="cultivation_plate")
            tree = build_greenhouse_tree(session, tenant, user, farm)
            position = tree["positions"][0]
            place_carrier(
                session, tenant, user, farm, carrier_id=sown["tray"].id, location_id=position.id,
                effective_time=now(),
            )
            session.commit()
            batch_id, farm_id = sown["batch"].id, farm.id
            gh_id, zone_id, span_id, table_id, position_id = (
                tree["greenhouse"].id, tree["zone"].id, tree["span"].id, tree["table"].id, position.id,
            )

        with _snapshot_connection(test_engine) as conn:
            [ctx] = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[batch_id]
            )
        assert ctx.placement.active_carrier_count == 1
        assert ctx.placement.placed_carrier_count == 1
        assert ctx.placement.unplaced_carrier_count == 0
        [placement] = ctx.placement.placements
        assert placement.location_id == position_id
        assert [seg.id for seg in placement.path] == [gh_id, zone_id, span_id, table_id, position_id]
        assert ctx.placement.common_ancestor_path == placement.path
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_transplant_releases_source_assignment_and_places_destination(test_engine) -> None:
    """Not a "partial" case (the source assignment is released by the
    transplant itself, per `transplant_service.record_transplant`, so only
    the destination carrier remains active) -- included to prove placement
    resolution follows the currently-active assignment, not stale ones.
    The genuine mixed-placement case (two concurrently active carriers,
    only one placed) is exercised separately below."""
    from tests._operational_read_scenario import build_greenhouse_tree

    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0)
            transition(
                session, tenant, user, farm, batch_id=sown["batch"].id,
                configured_transition_id=scaffold["t_seed_to_transplant"].id, effective_time=minutes_after(t0, 1),
            )
            transplanted = transplant_to_plate(
                session, tenant, user, farm, batch_id=sown["batch"].id,
                source_assignment_id=sown["assignment_id"], effective_time=minutes_after(t0, 2),
            )
            tree = build_greenhouse_tree(session, tenant, user, farm, position_count=1)
            place_carrier(
                session, tenant, user, farm, carrier_id=transplanted["plate"].id,
                location_id=tree["positions"][0].id, effective_time=minutes_after(t0, 3),
            )
            session.commit()
            batch_id, farm_id = sown["batch"].id, farm.id

        with _snapshot_connection(test_engine) as conn:
            [ctx] = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[batch_id]
            )
        # The source seed_tray assignment was released by the transplant;
        # only the destination cultivation_plate assignment remains active,
        # and it is placed -- so this batch is now fully (not partially)
        # placed. The partial case instead needs two concurrently active
        # carriers with only one placed, exercised below.
        assert ctx.placement.active_carrier_count == 1
        assert ctx.placement.placed_carrier_count == 1
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_two_active_carriers_with_only_one_placed_is_partial(test_engine) -> None:
    from tests._operational_read_scenario import build_greenhouse_tree

    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_direct_placement_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, site_count=20, carrier_type_code="cultivation_plate")
            tree = build_greenhouse_tree(session, tenant, user, farm, position_count=1)

            # Split the single sown assignment's carrier into two batches is
            # not what's wanted here (that changes batch identity); instead
            # give the batch a second independent carrier by transplanting
            # only half the sown assignment's plants isn't supported either
            # (transplant reconciliation requires the whole source line to
            # resolve). Simplest true two-active-carrier case for one batch:
            # sow with two carriers directly.
            from app.services import carrier_service, sowing_service

            tray2 = carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code="cultivation_plate", code=f"TRAY2-{uuid.uuid4().hex[:8]}", issued_date=None,
            )
            sowing_service.sow_batch(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=sown["batch"].id,
                client_command_id=uuid.uuid4(), effective_time=minutes_after(t0, 1), note=None,
                lines=[{"carrier_id": tray2.id, "seed_lot_id": sown["seed_lot"].id, "sown_site_count": 10, "seed_count": 10, "line_note": None}],
            )
            place_carrier(
                session, tenant, user, farm, carrier_id=sown["tray"].id, location_id=tree["positions"][0].id,
                effective_time=minutes_after(t0, 2),
            )
            session.commit()
            batch_id, farm_id = sown["batch"].id, farm.id

        with _snapshot_connection(test_engine) as conn:
            [ctx] = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[batch_id]
            )
        assert ctx.placement.active_carrier_count == 2
        assert ctx.placement.placed_carrier_count == 1
        assert ctx.placement.unplaced_carrier_count == 1
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_multiple_placements_shared_branch_yields_common_ancestor_path(test_engine) -> None:
    from app.services import carrier_service, sowing_service

    from tests._operational_read_scenario import build_greenhouse_tree

    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_direct_placement_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, carrier_type_code="cultivation_plate")
            tree = build_greenhouse_tree(session, tenant, user, farm, position_count=2)

            tray2 = carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code="cultivation_plate", code=f"TRAY2-{uuid.uuid4().hex[:8]}", issued_date=None,
            )
            sowing_service.sow_batch(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=sown["batch"].id,
                client_command_id=uuid.uuid4(), effective_time=minutes_after(t0, 1), note=None,
                lines=[{"carrier_id": tray2.id, "seed_lot_id": sown["seed_lot"].id, "sown_site_count": 10, "seed_count": 10, "line_note": None}],
            )
            place_carrier(
                session, tenant, user, farm, carrier_id=sown["tray"].id, location_id=tree["positions"][0].id,
                effective_time=minutes_after(t0, 2),
            )
            place_carrier(
                session, tenant, user, farm, carrier_id=tray2.id, location_id=tree["positions"][1].id,
                effective_time=minutes_after(t0, 3),
            )
            session.commit()
            batch_id, farm_id = sown["batch"].id, farm.id
            gh_id, zone_id, span_id, table_id = tree["greenhouse"].id, tree["zone"].id, tree["span"].id, tree["table"].id

        with _snapshot_connection(test_engine) as conn:
            [ctx] = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[batch_id]
            )
        assert ctx.placement.placed_carrier_count == 2
        assert ctx.placement.common_ancestor_path is not None
        assert [seg.id for seg in ctx.placement.common_ancestor_path] == [gh_id, zone_id, span_id, table_id]
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_multiple_placements_separate_branches_yields_no_common_ancestor(test_engine) -> None:
    from app.services import carrier_service, sowing_service

    from tests._operational_read_scenario import build_greenhouse_tree

    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_direct_placement_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, carrier_type_code="cultivation_plate")
            tree_a = build_greenhouse_tree(session, tenant, user, farm, position_count=1)
            tree_b = build_greenhouse_tree(session, tenant, user, farm, position_count=1)

            tray2 = carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code="cultivation_plate", code=f"TRAY2-{uuid.uuid4().hex[:8]}", issued_date=None,
            )
            sowing_service.sow_batch(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=sown["batch"].id,
                client_command_id=uuid.uuid4(), effective_time=minutes_after(t0, 1), note=None,
                lines=[{"carrier_id": tray2.id, "seed_lot_id": sown["seed_lot"].id, "sown_site_count": 10, "seed_count": 10, "line_note": None}],
            )
            place_carrier(
                session, tenant, user, farm, carrier_id=sown["tray"].id, location_id=tree_a["positions"][0].id,
                effective_time=minutes_after(t0, 2),
            )
            place_carrier(
                session, tenant, user, farm, carrier_id=tray2.id, location_id=tree_b["positions"][0].id,
                effective_time=minutes_after(t0, 3),
            )
            session.commit()
            batch_id, farm_id = sown["batch"].id, farm.id

        with _snapshot_connection(test_engine) as conn:
            [ctx] = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[batch_id]
            )
        assert ctx.placement.placed_carrier_count == 2
        assert ctx.placement.common_ancestor_path is None
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
@pytest.mark.parametrize("hold_count,released_count,expected_open", [(0, 0, 0), (1, 0, 1), (2, 0, 2), (2, 1, 1)])
def test_open_quality_hold_count(test_engine, hold_count, released_count, expected_open) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0)
            hold_ids = []
            for i in range(hold_count):
                hold = open_hold(
                    session, tenant, user, farm, batch_id=sown["batch"].id, reason_code=f"REASON_{i}",
                    effective_time=minutes_after(t0, i + 1),
                )
                hold_ids.append(hold.id)
            for i in range(released_count):
                release_hold(
                    session, tenant, user, farm, batch_id=sown["batch"].id, hold_id=hold_ids[i],
                    effective_time=minutes_after(t0, 10 + i),
                )
            session.commit()
            batch_id, farm_id = sown["batch"].id, farm.id

        with _snapshot_connection(test_engine) as conn:
            [ctx] = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[batch_id]
            )
        assert ctx.open_quality_hold_count == expected_open
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_active_state_filter_excludes_closed_and_superseded(test_engine) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)

            active_batch = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, code_suffix="active")

            closing_batch = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, code_suffix="closing")
            transition(
                session, tenant, user, farm, batch_id=closing_batch["batch"].id,
                configured_transition_id=scaffold["t_seed_to_transplant"].id, effective_time=minutes_after(t0, 1),
            )
            transition(
                session, tenant, user, farm, batch_id=closing_batch["batch"].id,
                configured_transition_id=scaffold["t_transplant_to_growing"].id, effective_time=minutes_after(t0, 2),
            )
            transition(
                session, tenant, user, farm, batch_id=closing_batch["batch"].id,
                configured_transition_id=scaffold["t_growing_to_complete"].id, effective_time=minutes_after(t0, 3),
            )

            superseding_parent = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, code_suffix="parent")
            superseding_sibling = sow_second_carrier(
                session, tenant, user, farm, batch_id=superseding_parent["batch"].id,
                seed_lot_id=superseding_parent["seed_lot"].id, effective_time=minutes_after(t0, 1),
            )
            split(
                session, tenant, user, farm, batch_id=superseding_parent["batch"].id,
                output_codes=[f"CHILD-{uuid.uuid4().hex[:8]}", f"SIBLING-{uuid.uuid4().hex[:8]}"],
                source_assignment_ids=[superseding_parent["assignment_id"], superseding_sibling["assignment_id"]],
                effective_time=minutes_after(t0, 4),
            )
            session.commit()
            farm_id = farm.id
            active_batch_id, closing_batch_id, superseding_parent_id = (
                active_batch["batch"].id, closing_batch["batch"].id, superseding_parent["batch"].id,
            )

        with _snapshot_connection(test_engine) as conn:
            active_ids = operational_read_service.resolve_batch_ids_by_state(
                conn, tenant_id=tenant_id, farm_id=farm_id, state_filter="active"
            )
        assert active_batch_id in active_ids
        assert closing_batch_id not in active_ids
        assert superseding_parent_id not in active_ids
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_all_state_filter_includes_active_closed_and_superseded(test_engine) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)

            active_batch = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, code_suffix="active")

            closing_batch = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, code_suffix="closing")
            transition(
                session, tenant, user, farm, batch_id=closing_batch["batch"].id,
                configured_transition_id=scaffold["t_seed_to_transplant"].id, effective_time=minutes_after(t0, 1),
            )
            transition(
                session, tenant, user, farm, batch_id=closing_batch["batch"].id,
                configured_transition_id=scaffold["t_transplant_to_growing"].id, effective_time=minutes_after(t0, 2),
            )
            transition(
                session, tenant, user, farm, batch_id=closing_batch["batch"].id,
                configured_transition_id=scaffold["t_growing_to_complete"].id, effective_time=minutes_after(t0, 3),
            )

            superseding_parent = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, code_suffix="parent")
            superseding_sibling = sow_second_carrier(
                session, tenant, user, farm, batch_id=superseding_parent["batch"].id,
                seed_lot_id=superseding_parent["seed_lot"].id, effective_time=minutes_after(t0, 1),
            )
            split(
                session, tenant, user, farm, batch_id=superseding_parent["batch"].id,
                output_codes=[f"CHILD-{uuid.uuid4().hex[:8]}", f"SIBLING-{uuid.uuid4().hex[:8]}"],
                source_assignment_ids=[superseding_parent["assignment_id"], superseding_sibling["assignment_id"]],
                effective_time=minutes_after(t0, 4),
            )
            session.commit()
            farm_id = farm.id
            active_batch_id, closing_batch_id, superseding_parent_id = (
                active_batch["batch"].id, closing_batch["batch"].id, superseding_parent["batch"].id,
            )

        with _snapshot_connection(test_engine) as conn:
            all_ids = operational_read_service.resolve_batch_ids_by_state(
                conn, tenant_id=tenant_id, farm_id=farm_id, state_filter="all"
            )
            contexts = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=all_ids
            )
        states_by_id = {c.id: c.state for c in contexts}
        assert states_by_id[active_batch_id] == "active"
        assert states_by_id[closing_batch_id] == "closed"
        assert states_by_id[superseding_parent_id] == "superseded"
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_superseded_batch_resolves_via_single_batch_lookup(test_engine) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)
            parent = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0)
            sibling = sow_second_carrier(
                session, tenant, user, farm, batch_id=parent["batch"].id, seed_lot_id=parent["seed_lot"].id,
                effective_time=minutes_after(t0, 1),
            )
            split(
                session, tenant, user, farm, batch_id=parent["batch"].id,
                output_codes=[f"CHILD-{uuid.uuid4().hex[:8]}", f"SIBLING-{uuid.uuid4().hex[:8]}"],
                source_assignment_ids=[parent["assignment_id"], sibling["assignment_id"]],
                effective_time=minutes_after(t0, 2),
            )
            session.commit()
            parent_id, farm_id = parent["batch"].id, farm.id

        with _snapshot_connection(test_engine) as conn:
            results = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[parent_id]
            )
        assert len(results) == 1
        assert results[0].state == "superseded"
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_tenant_isolation_excludes_other_tenants_batch(test_engine) -> None:
    tenant_id = None
    other_tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=now())
            session.commit()
            batch_id, farm_id = sown["batch"].id, farm.id

        with committed_connection(test_engine) as session2:
            other_tenant, _other_user, other_farm = build_committed_tenant_farm(session2)
            session2.commit()
            other_tenant_id, other_farm_id = other_tenant.id, other_farm.id

        # The other tenant's own farm is legitimate (passes the farm check),
        # but `batch_id` belongs to the first tenant -- the batch lookup
        # itself must exclude it, proving isolation holds even when farm
        # ownership alone would not have caught the leak.
        with _snapshot_connection(test_engine) as conn:
            results = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=other_tenant_id, farm_id=other_farm_id, batch_ids=[batch_id]
            )
        assert results == []
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
        if other_tenant_id is not None:
            cleanup_traceability_scenario(test_engine, other_tenant_id)


@pytest.mark.integration
def test_farm_isolation_excludes_batch_from_other_farm(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            from app.services import farm_service

            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            other_farm = farm_service.create_farm(
                session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm2-{uuid.uuid4().hex[:8]}",
                name="Second Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
            )
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=now())
            session.commit()
            batch_id, other_farm_id = sown["batch"].id, other_farm.id

        with _snapshot_connection(test_engine) as conn:
            results = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=other_farm_id, batch_ids=[batch_id]
            )
        assert results == []
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_missing_batch_id_is_simply_absent(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            session.commit()
            farm_id = farm.id

        with _snapshot_connection(test_engine) as conn:
            results = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[uuid.uuid4()]
            )
        assert results == []
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_snapshot_is_never_mixed_across_a_concurrent_hold_commit(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_transplant_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=now())
            session.commit()
            batch_id, farm_id, user_id = sown["batch"].id, farm.id, user.id

        snapshot_ready = threading.Event()
        mutation_committed = threading.Event()
        results: dict[str, object] = {}

        def read_thread() -> None:
            with _snapshot_connection(test_engine) as conn:
                before = operational_read_service.get_batch_operational_contexts(
                    conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[batch_id]
                )
                results["before"] = before[0].open_quality_hold_count
                snapshot_ready.set()
                assert mutation_committed.wait(timeout=10), "the concurrent hold must commit within the timeout"
                after = operational_read_service.get_batch_operational_contexts(
                    conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[batch_id]
                )
                results["after_same_snapshot"] = after[0].open_quality_hold_count

        t = threading.Thread(target=read_thread)
        t.start()
        assert snapshot_ready.wait(timeout=10), "the read thread must establish its snapshot before this test proceeds"

        from app.services import quality_hold_service

        with committed_connection(test_engine) as mutate_session:
            quality_hold_service.place_quality_hold(
                mutate_session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, batch_id=batch_id,
                client_command_id=uuid.uuid4(), effective_time=now(), source_observation_event_id=None,
                reason_code="CONCURRENT", reason_text="Concurrent hold.",
            )
            mutate_session.commit()
        mutation_committed.set()

        t.join(timeout=15)
        assert not t.is_alive(), "the read thread must finish within the bounded join timeout"

        assert results["before"] == 0
        assert results["after_same_snapshot"] == 0, (
            "a REPEATABLE READ snapshot must not observe a commit that happened after it was established"
        )

        with _snapshot_connection(test_engine) as conn:
            fresh = operational_read_service.get_batch_operational_contexts(
                conn, tenant_id=tenant_id, farm_id=farm_id, batch_ids=[batch_id]
            )
        assert fresh[0].open_quality_hold_count == 1
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
