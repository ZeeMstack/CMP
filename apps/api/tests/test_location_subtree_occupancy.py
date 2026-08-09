"""CMP-FE-002A tests for `operational_read_service.get_location_subtree_occupancy`:
bounded-by-root aggregation (never farm-wide), generic occupiable-location
semantics (an occupiable root counts itself; occupied roots count
themselves as occupied), nested aggregate correctness across four
structural levels, occupied-only reporting (empty leaves never listed),
occupant batch-context resolution (present, and honestly absent rather
than fabricated), sibling/outside-root exclusion, tenant/farm isolation,
and snapshot consistency under a concurrent write."""
import threading
import uuid
from datetime import timedelta

import pytest

from app.services import carrier_service, operational_read_service
from app.services.errors import LocationNotFoundError
from app.services.lineage_traversal import _snapshot_connection
from tests._operational_read_scenario import (
    build_committed_tenant_farm,
    build_direct_placement_workflow_scaffold,
    build_greenhouse_tree,
    committed_connection,
    now,
    place_carrier,
    sow_batch,
)
from tests._traceability_scenario import cleanup_traceability_scenario


@pytest.mark.integration
def test_empty_subtree_has_zero_counts_and_no_occupied_locations(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            from app.services import location_service

            empty_gh = location_service.create_location(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="greenhouse",
                code=f"EMPTY-GH-{uuid.uuid4().hex[:8]}", name="Empty Greenhouse", parent_location_id=None,
                greenhouse_classification="leafy_greens", occupiable=None,
            )
            session.commit()
            farm_id, empty_gh_id = farm.id, empty_gh.id

        with _snapshot_connection(test_engine) as conn:
            result = operational_read_service.get_location_subtree_occupancy(
                conn, tenant_id=tenant_id, farm_id=farm_id, root_location_id=empty_gh_id
            )
        assert result.root_location_id == empty_gh_id
        assert result.occupied_locations == []
        [agg] = result.aggregate_counts
        assert agg.location_id == empty_gh_id
        assert agg.occupiable_location_count == 0
        assert agg.occupied_location_count == 0
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_occupiable_root_counts_itself_when_unoccupied(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            tree = build_greenhouse_tree(session, tenant, user, farm, position_count=1)
            session.commit()
            farm_id, position_id = farm.id, tree["positions"][0].id

        with _snapshot_connection(test_engine) as conn:
            result = operational_read_service.get_location_subtree_occupancy(
                conn, tenant_id=tenant_id, farm_id=farm_id, root_location_id=position_id
            )
        assert result.occupied_locations == []
        [agg] = result.aggregate_counts
        assert agg.location_id == position_id
        assert agg.occupiable_location_count == 1
        assert agg.occupied_location_count == 0
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_occupied_occupiable_root_counts_itself_as_occupied(test_engine) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            tree = build_greenhouse_tree(session, tenant, user, farm, position_count=1)
            tray = carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code="cultivation_plate", code=f"TRAY-{uuid.uuid4().hex[:8]}", issued_date=None,
            )
            place_carrier(session, tenant, user, farm, carrier_id=tray.id, location_id=tree["positions"][0].id, effective_time=t0)
            session.commit()
            farm_id, position_id, tray_id = farm.id, tree["positions"][0].id, tray.id

        with _snapshot_connection(test_engine) as conn:
            result = operational_read_service.get_location_subtree_occupancy(
                conn, tenant_id=tenant_id, farm_id=farm_id, root_location_id=position_id
            )
        [agg] = result.aggregate_counts
        assert agg.location_id == position_id
        assert agg.occupiable_location_count == 1
        assert agg.occupied_location_count == 1
        [occ] = result.occupied_locations
        assert occ.location_id == position_id
        assert occ.occupant.kind == "carrier"
        assert occ.occupant.id == tray_id
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_nested_aggregate_counts_correct_across_levels(test_engine) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            tree = build_greenhouse_tree(session, tenant, user, farm, position_count=4)
            trays = [
                carrier_service.register_carrier(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                    carrier_type_code="cultivation_plate", code=f"TRAY-{uuid.uuid4().hex[:8]}", issued_date=None,
                )
                for _ in range(2)
            ]
            place_carrier(session, tenant, user, farm, carrier_id=trays[0].id, location_id=tree["positions"][0].id, effective_time=t0)
            place_carrier(session, tenant, user, farm, carrier_id=trays[1].id, location_id=tree["positions"][1].id, effective_time=t0)
            session.commit()
            farm_id = farm.id
            gh_id, zone_id, span_id, table_id = tree["greenhouse"].id, tree["zone"].id, tree["span"].id, tree["table"].id

        with _snapshot_connection(test_engine) as conn:
            result = operational_read_service.get_location_subtree_occupancy(
                conn, tenant_id=tenant_id, farm_id=farm_id, root_location_id=gh_id
            )
        by_id = {a.location_id: a for a in result.aggregate_counts}
        for node_id in (gh_id, zone_id, span_id, table_id):
            assert by_id[node_id].occupiable_location_count == 4
            assert by_id[node_id].occupied_location_count == 2
        assert len(result.occupied_locations) == 2
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_occupied_leaf_resolves_batch_context(test_engine) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_direct_placement_workflow_scaffold(session, tenant, user, farm)
            sown = sow_batch(session, tenant, user, farm, scaffold, effective_time=t0, carrier_type_code="cultivation_plate")
            tree = build_greenhouse_tree(session, tenant, user, farm, position_count=1)
            place_carrier(session, tenant, user, farm, carrier_id=sown["tray"].id, location_id=tree["positions"][0].id, effective_time=t0)
            session.commit()
            farm_id, position_id, batch_id = farm.id, tree["positions"][0].id, sown["batch"].id
            tray_code, batch_code = sown["tray"].code, sown["batch"].code

        with _snapshot_connection(test_engine) as conn:
            result = operational_read_service.get_location_subtree_occupancy(
                conn, tenant_id=tenant_id, farm_id=farm_id, root_location_id=position_id
            )
        [occ] = result.occupied_locations
        assert occ.occupant.kind == "carrier"
        assert occ.occupant.carrier_code == tray_code
        assert occ.occupant.batch is not None
        assert occ.occupant.batch.batch_id == batch_id
        assert occ.occupant.batch.batch_code == batch_code
        # CMP-FE-002A.1: subtree occupancy's occupant batch-context uses the
        # same operational stage schema, so it must expose the
        # authoritative stage_category too.
        assert occ.occupant.batch.current_stage.stage_category == "seeding"
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_occupied_leaf_without_batch_assignment_preserves_null_batch_context(test_engine) -> None:
    """A carrier can be physically placed without ever being sown/assigned
    to a batch -- the occupant itself must still be reported truthfully
    (kind, id, carrier_code), with `batch` honestly `null` rather than
    fabricated or the whole occupant collapsed away."""
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            tree = build_greenhouse_tree(session, tenant, user, farm, position_count=1)
            tray = carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code="cultivation_plate", code=f"TRAY-{uuid.uuid4().hex[:8]}", issued_date=None,
            )
            place_carrier(session, tenant, user, farm, carrier_id=tray.id, location_id=tree["positions"][0].id, effective_time=t0)
            session.commit()
            farm_id, position_id, tray_id, tray_code = farm.id, tree["positions"][0].id, tray.id, tray.code

        with _snapshot_connection(test_engine) as conn:
            result = operational_read_service.get_location_subtree_occupancy(
                conn, tenant_id=tenant_id, farm_id=farm_id, root_location_id=position_id
            )
        [occ] = result.occupied_locations
        assert occ.occupant.kind == "carrier"
        assert occ.occupant.id == tray_id
        assert occ.occupant.carrier_code == tray_code
        assert occ.occupant.batch is None
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_singular_occupant_reflects_only_the_currently_active_placement(test_engine) -> None:
    """Proves the cardinality rule backing `LocationOccupant` being a single
    object, not a list: moving carrier B into a location a first carrier A
    already occupied ends A's occupancy (enforced by
    `ux_occupancies_active_target_location`), so the location's occupant
    resolves to exactly B, never both."""
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            tree = build_greenhouse_tree(session, tenant, user, farm, position_count=1)
            tray_a = carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code="cultivation_plate", code=f"TRAY-A-{uuid.uuid4().hex[:8]}", issued_date=None,
            )
            tray_b = carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code="cultivation_plate", code=f"TRAY-B-{uuid.uuid4().hex[:8]}", issued_date=None,
            )
            position_id = tree["positions"][0].id
            place_carrier(session, tenant, user, farm, carrier_id=tray_a.id, location_id=position_id, effective_time=t0)
            from app.services import movement_service

            movement_service.execute_movement(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                effective_time=t0 + timedelta(minutes=1), occupant_kind="carrier", occupant_id=tray_a.id,
                destination_kind=None, destination_id=None, reason="vacate before re-occupying",
            )
            place_carrier(session, tenant, user, farm, carrier_id=tray_b.id, location_id=position_id, effective_time=t0 + timedelta(minutes=2))
            session.commit()
            farm_id, tray_b_id = farm.id, tray_b.id

        with _snapshot_connection(test_engine) as conn:
            result = operational_read_service.get_location_subtree_occupancy(
                conn, tenant_id=tenant_id, farm_id=farm_id, root_location_id=position_id
            )
        [occ] = result.occupied_locations
        assert occ.occupant.id == tray_b_id
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_sibling_and_outside_root_locations_excluded(test_engine) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            tree_a = build_greenhouse_tree(session, tenant, user, farm, position_count=1)
            tree_b = build_greenhouse_tree(session, tenant, user, farm, position_count=1)
            tray_a = carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code="cultivation_plate", code=f"TRAY-A-{uuid.uuid4().hex[:8]}", issued_date=None,
            )
            tray_b = carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code="cultivation_plate", code=f"TRAY-B-{uuid.uuid4().hex[:8]}", issued_date=None,
            )
            place_carrier(session, tenant, user, farm, carrier_id=tray_a.id, location_id=tree_a["positions"][0].id, effective_time=t0)
            place_carrier(session, tenant, user, farm, carrier_id=tray_b.id, location_id=tree_b["positions"][0].id, effective_time=t0)
            session.commit()
            farm_id, gh_a_id, gh_b_id = farm.id, tree_a["greenhouse"].id, tree_b["greenhouse"].id
            tree_b_ids = {gh_b_id, tree_b["zone"].id, tree_b["span"].id, tree_b["table"].id}
            position_a_id = tree_a["positions"][0].id

        with _snapshot_connection(test_engine) as conn:
            result = operational_read_service.get_location_subtree_occupancy(
                conn, tenant_id=tenant_id, farm_id=farm_id, root_location_id=gh_a_id
            )
        assert {a.location_id for a in result.aggregate_counts}.isdisjoint(tree_b_ids)
        assert result.occupied_locations[0].location_id == position_a_id
        assert len(result.occupied_locations) == 1
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_tenant_isolation_root_from_other_tenant_raises_not_found(test_engine) -> None:
    tenant_id = None
    other_tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            tree = build_greenhouse_tree(session, tenant, user, farm, position_count=1)
            session.commit()
            farm_id, gh_id = farm.id, tree["greenhouse"].id

        with committed_connection(test_engine) as session2:
            other_tenant, _u, other_farm = build_committed_tenant_farm(session2)
            session2.commit()
            other_tenant_id, other_farm_id = other_tenant.id, other_farm.id

        # The other tenant's own farm is legitimate (passes the farm check),
        # but `gh_id` belongs to the first tenant's farm -- the location
        # lookup itself must fail, proving isolation holds even when farm
        # ownership alone would not have caught the leak.
        with pytest.raises(LocationNotFoundError):
            with _snapshot_connection(test_engine) as conn:
                operational_read_service.get_location_subtree_occupancy(
                    conn, tenant_id=other_tenant_id, farm_id=other_farm_id, root_location_id=gh_id
                )
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
        if other_tenant_id is not None:
            cleanup_traceability_scenario(test_engine, other_tenant_id)


@pytest.mark.integration
def test_farm_isolation_root_from_other_farm_raises_not_found(test_engine) -> None:
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
            tree = build_greenhouse_tree(session, tenant, user, farm, position_count=1)
            session.commit()
            other_farm_id, gh_id = other_farm.id, tree["greenhouse"].id

        with pytest.raises(LocationNotFoundError):
            with _snapshot_connection(test_engine) as conn:
                operational_read_service.get_location_subtree_occupancy(
                    conn, tenant_id=tenant_id, farm_id=other_farm_id, root_location_id=gh_id
                )
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_missing_root_location_raises_not_found(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            session.commit()
            farm_id = farm.id

        with pytest.raises(LocationNotFoundError):
            with _snapshot_connection(test_engine) as conn:
                operational_read_service.get_location_subtree_occupancy(
                    conn, tenant_id=tenant_id, farm_id=farm_id, root_location_id=uuid.uuid4()
                )
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_snapshot_is_never_mixed_across_a_concurrent_placement_commit(test_engine) -> None:
    tenant_id = None
    try:
        t0 = now() - timedelta(minutes=30)
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            tree = build_greenhouse_tree(session, tenant, user, farm, position_count=1)
            tray = carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code="cultivation_plate", code=f"TRAY-{uuid.uuid4().hex[:8]}", issued_date=None,
            )
            session.commit()
            farm_id, gh_id, position_id, user_id, tray_id = (
                farm.id, tree["greenhouse"].id, tree["positions"][0].id, user.id, tray.id,
            )

        snapshot_ready = threading.Event()
        mutation_committed = threading.Event()
        results: dict[str, object] = {}

        def read_thread() -> None:
            with _snapshot_connection(test_engine) as conn:
                before = operational_read_service.get_location_subtree_occupancy(
                    conn, tenant_id=tenant_id, farm_id=farm_id, root_location_id=gh_id
                )
                results["before"] = len(before.occupied_locations)
                snapshot_ready.set()
                assert mutation_committed.wait(timeout=10), "the concurrent placement must commit within the timeout"
                after = operational_read_service.get_location_subtree_occupancy(
                    conn, tenant_id=tenant_id, farm_id=farm_id, root_location_id=gh_id
                )
                results["after_same_snapshot"] = len(after.occupied_locations)

        t = threading.Thread(target=read_thread)
        t.start()
        assert snapshot_ready.wait(timeout=10), "the read thread must establish its snapshot before this test proceeds"

        from app.services import movement_service

        with committed_connection(test_engine) as mutate_session:
            movement_service.execute_movement(
                mutate_session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
                client_command_id=uuid.uuid4(), effective_time=t0, occupant_kind="carrier", occupant_id=tray_id,
                destination_kind="location", destination_id=position_id, reason=None,
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
            fresh = operational_read_service.get_location_subtree_occupancy(
                conn, tenant_id=tenant_id, farm_id=farm_id, root_location_id=gh_id
            )
        assert len(fresh.occupied_locations) == 1
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
