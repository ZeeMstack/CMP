"""CMP-018 database-level integrity verification: proves the storage
movement insert-integrity trigger, the append-only triggers, and the
amended (v3) finished-goods ledger insert-integrity trigger are all
independently enforced by the database against direct SQL, not only by
the Python service layer. A module-scoped fixture packs one 20kg/20-count
lot, places 10kg/10 into one active position (leaving a real overdraw
target) and 3kg/3 into a second position that is then deactivated
(leaving a real inactive-source-with-balance target), and provides a
third active position (untouched) plus a non-eligible greenhouse
location. Every test rolls its own connection back afterward so the
shared baseline is never mutated between tests."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    farm_service,
    harvest_service,
    location_service,
    membership_service,
    packing_service,
    production_system_service,
    sowing_service,
    tenant_service,
    user_service,
    workflow_service,
)
from tests._dispatch_scenario import pack_one
from tests._packing_scenario import build_committed_scenario, build_packing_scaffold, cleanup_scenario, now, require_cmp_test
from tests._storage_scenario import create_cold_store, create_cold_store_position, place_one
from tests.conftest import ensure_seed_tray_specification


def _build_scenario_ready_to_harvest(session: Session, *, t_batch, t_sow, t_transition):
    """Builds a committed tenant/farm/crop/variety/workflow/batch, sown and
    transitioned into its harvesting stage, using caller-supplied,
    fully-deterministic `effective_time` values throughout -- never the
    real wall clock. Returns a dict with everything a caller needs to then
    call `harvest_service.record_harvest` (and later
    `packing_service.record_packing`) at its own chosen, deterministic
    times. Used only by the cross-ledger chronology tests below, which
    need a real, unambiguous gap between a lot's harvest/packing time and
    a later dispatch/storage-movement time without ever sleeping to
    manufacture it."""
    suffix = uuid.uuid4().hex[:10]
    tenant = tenant_service.create_tenant(session, code=f"chron-{suffix}", name="Chronology Tenant")
    user = user_service.create_user(
        session, oidc_issuer="chron", oidc_subject=suffix, email=f"chron-{suffix}@example.com",
        display_name="Chronology User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Chronology Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"var-{suffix}",
        name="Variety", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ps-{suffix}", name="System", description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"wf-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    harvesting = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="HARVESTING", name="Harvesting", display_order=1, stage_category="harvesting",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=harvesting.id, code="ADV-1", name="Advance 1",
    )
    workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=harvesting.id, to_stage_id=complete.id, code="ADV-2", name="Advance 2",
    )
    workflow_service.publish_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"batch-{suffix}", workflow_id=workflow.id, effective_time=t_batch,
    )
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"lot-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier = carrier_service.register_carrier(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, specification_id=seed_tray_spec.id,
        code=f"tray-{suffix}", issued_date=None,
    )
    sowing_service.sow_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=t_sow, note=None,
        lines=[{"carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": 20, "seed_count": 20, "line_note": None}],
    )
    assignment = sowing_service.list_batch_carriers(session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)[0]
    crop_batch_service.transition_stage(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=t_transition, reason=None,
    )
    return {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "suffix": suffix, "batch_id": batch.id,
        "assignment_id": assignment.id,
    }


def _harvest_and_pack_at(session: Session, scenario, *, t_harvest, t_pack, weight=Decimal("10.000")):
    """Harvests, grades (POSTHARVEST-OPS-001E: at the same effective_time
    as the harvest -- the chronology rule is inclusive, `>=`, not `>`),
    then packs the full weight at the caller's own explicit, deterministic
    times. Returns the finished_goods_lot_id."""
    from app.models.farm import Farm
    from app.models.tenant import Tenant
    from app.models.user import User

    harvest = harvest_service.record_harvest(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=t_harvest,
        produce_lot_code=f"HLOT-{scenario['suffix']}", note=None,
        source_lines=[{"batch_carrier_assignment_id": scenario["assignment_id"], "harvested_weight_kg": weight, "whole_unit_count": None, "note": None}],
    )
    lot_id = session.execute(
        text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": harvest.id}
    ).scalar_one()
    crop_id = session.execute(
        text("SELECT crop_id FROM harvested_produce_lots WHERE id = :lid"), {"lid": lot_id}
    ).scalar_one()
    tenant_obj = session.get(Tenant, scenario["tenant_id"])
    user_obj = session.get(User, scenario["user_id"])
    farm_obj = session.get(Farm, scenario["farm_id"])
    pack_scaffold = build_packing_scaffold(
        session, tenant_obj, user_obj, farm_obj, crop_id=crop_id, suffix=scenario["suffix"]
    )
    # grade_entire_lot always uses now() (the real wall clock) as its own
    # effective_time -- unusable here, since t_harvest/t_pack are both
    # deliberately in the deterministic past (see this module's own
    # docstring), and Packing's own chronology check would then reject
    # t_pack for preceding the GPL's real-now() effective_time. Grading is
    # called directly instead, at t_harvest (the chronology rule is
    # inclusive, `>=`, not `>`, against its own source HPL).
    from app.services import grading_service

    grading_event = grading_service.record_grading(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), source_harvested_produce_lot_id=lot_id,
        processing_hall_location_id=pack_scaffold["packing_hall_location_id"], effective_time=t_harvest, note=None,
        input_presented_weight_kg=weight, input_presented_whole_unit_count=None,
        rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
        loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
        sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
        remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=None,
        outputs=[
            {
                "grade_definition_version_id": pack_scaffold["grade_definition_version_id"],
                "code": f"GPL-{scenario['suffix']}", "output_weight_kg": weight, "output_whole_unit_count": None,
            }
        ],
    )
    gpl_id = session.execute(
        text("SELECT id FROM graded_produce_lots WHERE grading_event_id = :eid"), {"eid": grading_event.id}
    ).scalar_one()
    event = packing_service.record_packing(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), pack_specification_version_id=pack_scaffold["pack_specification_version_id"],
        effective_time=t_pack, finished_goods_lot_code=f"FG-{scenario['suffix']}",
        package_count=10, packed_output_weight_kg=weight, process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"graded_produce_lot_id": gpl_id, "consumed_weight_kg": weight, "consumed_whole_unit_count": None, "note": None}],
    )
    detail = packing_service.get_packing_event(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=event.id
    )
    return detail.finished_goods_lot.id


@pytest.fixture(scope="module")
def scenario(test_engine):
    s = build_committed_scenario(test_engine, lot_a_weight="20.000", lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)

    fg_lot_id, _ = pack_one(s, session, package_count=20, packed_output_weight_kg=Decimal("20.000"))
    cold_store = create_cold_store(s, session)
    pos_a = create_cold_store_position(s, session, cold_store_id=cold_store.id, code_suffix="-A")
    pos_b = create_cold_store_position(s, session, cold_store_id=cold_store.id, code_suffix="-B")
    pos_evacuated = create_cold_store_position(s, session, cold_store_id=cold_store.id, code_suffix="-EVAC")
    greenhouse = location_service.create_location(
        session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], actor_user_id=s["user_id"],
        location_type_code="greenhouse", code=f"GH-{s['suffix']}", name="Greenhouse", parent_location_id=None,
        greenhouse_classification="leafy_greens", occupiable=None,
    )
    session.commit()

    pos_a_id, pos_b_id, pos_evacuated_id, greenhouse_id = pos_a.id, pos_b.id, pos_evacuated.id, greenhouse.id

    place_one(s, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_a_id, moved_weight_kg=Decimal("10.000"), moved_package_count=10)
    place_one(s, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_evacuated_id, moved_weight_kg=Decimal("3.000"), moved_package_count=3)
    session.commit()
    session.close()
    conn.close()

    require_cmp_test(test_engine)
    bypass_conn = test_engine.connect()
    trans = bypass_conn.begin()
    bypass_conn.execute(text("UPDATE locations SET status = 'inactive' WHERE id = :id"), {"id": pos_evacuated_id})
    trans.commit()
    bypass_conn.close()

    s["fg_lot_id"] = fg_lot_id
    s["pos_a_id"] = pos_a_id
    s["pos_b_id"] = pos_b_id
    s["pos_evacuated_id"] = pos_evacuated_id
    s["greenhouse_id"] = greenhouse_id
    yield s
    cleanup_scenario(test_engine, s["tenant_id"])


def _insert_movement(conn, params, *, match):
    with pytest.raises(Exception, match=match):
        conn.execute(
            text(
                "INSERT INTO finished_goods_storage_movements "
                "(id, tenant_id, farm_id, finished_goods_lot_id, movement_kind, source_location_id, "
                "destination_location_id, moved_weight_kg, moved_package_count, effective_time, actor_user_id, "
                "client_command_id, request_fingerprint, note) "
                "VALUES (:id, :tid, :fid, :lot, :kind, :src, :dest, :weight, :count, :eff, :actor, :ccid, 'fp', NULL)"
            ),
            params,
        )


def _base_params(scenario, **overrides):
    params = {
        "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "lot": scenario["fg_lot_id"],
        "kind": "place", "src": None, "dest": scenario["pos_b_id"], "weight": Decimal("1.000"), "count": 1,
        "eff": now(), "actor": scenario["user_id"], "ccid": uuid.uuid4(),
    }
    params.update(overrides)
    return params


@pytest.mark.integration
def test_direct_sql_place_beyond_unplaced_weight_rejected(scenario, test_engine) -> None:
    # 20kg available, 13kg already placed (10 + 3) -> 7kg unplaced.
    params = _base_params(scenario, weight=Decimal("7.001"), count=1)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="exceed unplaced weight")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_place_beyond_unplaced_package_count_rejected(scenario, test_engine) -> None:
    params = _base_params(scenario, weight=Decimal("1.000"), count=8)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="exceed unplaced package count")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_transfer_beyond_source_weight_rejected(scenario, test_engine) -> None:
    params = _base_params(scenario, kind="transfer", src=scenario["pos_a_id"], dest=scenario["pos_b_id"], weight=Decimal("10.001"), count=1)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="negative weight")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_transfer_beyond_source_package_count_rejected(scenario, test_engine) -> None:
    params = _base_params(scenario, kind="transfer", src=scenario["pos_a_id"], dest=scenario["pos_b_id"], weight=Decimal("1.000"), count=11)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="negative package count")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_release_beyond_source_weight_rejected(scenario, test_engine) -> None:
    params = _base_params(scenario, kind="release", src=scenario["pos_a_id"], dest=None, weight=Decimal("10.001"), count=1)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="negative weight")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_release_beyond_source_package_count_rejected(scenario, test_engine) -> None:
    params = _base_params(scenario, kind="release", src=scenario["pos_a_id"], dest=None, weight=Decimal("1.000"), count=11)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="negative package count")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_wrong_tenant_rejected(scenario, test_engine) -> None:
    params = _base_params(scenario, tid=uuid.uuid4())
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="tenant/farm does not match|violates foreign key")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_invalid_destination_type_rejected(scenario, test_engine) -> None:
    params = _base_params(scenario, dest=scenario["greenhouse_id"])
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="not a storage-eligible cold-store position")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_inactive_destination_rejected(scenario, test_engine) -> None:
    params = _base_params(scenario, dest=scenario["pos_evacuated_id"])
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="destination location is not active")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_inactive_source_transfer_permitted(scenario, test_engine) -> None:
    """CMP-018 deliberately does not require an active source: the
    evacuated position still holds a real 3kg/3 balance from the module
    fixture, and a transfer off of it must still succeed."""
    params = _base_params(
        scenario, kind="transfer", src=scenario["pos_evacuated_id"], dest=scenario["pos_b_id"],
        weight=Decimal("1.000"), count=1,
    )
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(
            text(
                "INSERT INTO finished_goods_storage_movements "
                "(id, tenant_id, farm_id, finished_goods_lot_id, movement_kind, source_location_id, "
                "destination_location_id, moved_weight_kg, moved_package_count, effective_time, actor_user_id, "
                "client_command_id, request_fingerprint, note) "
                "VALUES (:id, :tid, :fid, :lot, :kind, :src, :dest, :weight, :count, :eff, :actor, :ccid, 'fp', NULL)"
            ),
            params,
        )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_release_from_inactive_source_permitted(scenario, test_engine) -> None:
    """Same asymmetry as the transfer case above, proven for `release`
    too: releasing off the evacuated (inactive) position must succeed."""
    params = _base_params(
        scenario, kind="release", src=scenario["pos_evacuated_id"], dest=None, weight=Decimal("1.000"), count=1,
    )
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(
            text(
                "INSERT INTO finished_goods_storage_movements "
                "(id, tenant_id, farm_id, finished_goods_lot_id, movement_kind, source_location_id, "
                "destination_location_id, moved_weight_kg, moved_package_count, effective_time, actor_user_id, "
                "client_command_id, request_fingerprint, note) "
                "VALUES (:id, :tid, :fid, :lot, :kind, :src, :dest, :weight, :count, :eff, :actor, :ccid, 'fp', NULL)"
            ),
            params,
        )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_transfer_into_inactive_destination_rejected(scenario, test_engine) -> None:
    """The active-destination rule applies to `transfer`, not only `place`."""
    params = _base_params(
        scenario, kind="transfer", src=scenario["pos_a_id"], dest=scenario["pos_evacuated_id"],
        weight=Decimal("1.000"), count=1,
    )
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="destination location is not active")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_ineligible_source_type_rejected(scenario, test_engine) -> None:
    """A non-`cold_store_position` source (the fixture's own greenhouse)
    must be rejected on type, independent of the destination-type check
    already proven by test_direct_sql_invalid_destination_type_rejected."""
    params = _base_params(
        scenario, kind="transfer", src=scenario["greenhouse_id"], dest=scenario["pos_b_id"],
        weight=Decimal("1.000"), count=1,
    )
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="source location is not a storage-eligible cold-store position")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_source_wrong_tenant_farm_rejected(scenario, test_engine) -> None:
    """A source location belonging to a genuinely different tenant/farm
    (not merely a fabricated tenant id on the movement row itself, which
    test_direct_sql_wrong_tenant_rejected already proves trips the lot-
    level check first) must be rejected specifically on the source-
    location tenant/farm match, once the movement's own tenant/farm
    agrees with the finished-goods lot's."""
    from app.services import farm_service, tenant_service, user_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    other_tenant_id = None
    try:
        other_suffix = uuid.uuid4().hex[:8]
        other_tenant = tenant_service.create_tenant(session, code=f"other-{other_suffix}", name="Other Tenant")
        other_tenant_id = other_tenant.id
        other_user = user_service.create_user(
            session, oidc_issuer="other", oidc_subject=other_suffix, email=f"other-{other_suffix}@example.com",
            display_name="Other User",
        )
        other_farm = farm_service.create_farm(
            session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code=f"farm-{other_suffix}",
            name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        other_cold_store = create_cold_store({"tenant_id": other_tenant.id, "farm_id": other_farm.id, "user_id": other_user.id, "suffix": other_suffix}, session)
        other_pos = create_cold_store_position(
            {"tenant_id": other_tenant.id, "farm_id": other_farm.id, "user_id": other_user.id, "suffix": other_suffix},
            session, cold_store_id=other_cold_store.id,
        )
        other_pos_id = other_pos.id
        session.commit()

        params = _base_params(scenario, kind="transfer", src=other_pos_id, dest=scenario["pos_b_id"], weight=Decimal("1.000"), count=1)
        _insert_movement(conn, params, match="storage movement tenant/farm does not match the source location")
        conn.rollback()
    finally:
        session.close()
        conn.close()
        if other_tenant_id is not None:
            require_cmp_test(test_engine)
            cleanup_scenario(test_engine, other_tenant_id)


@pytest.mark.integration
def test_direct_sql_same_source_destination_transfer_rejected(scenario, test_engine) -> None:
    params = _base_params(scenario, kind="transfer", src=scenario["pos_a_id"], dest=scenario["pos_a_id"], weight=Decimal("1.000"), count=1)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="ck_finished_goods_storage_movements_shape")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_malformed_shape_rejected(scenario, test_engine) -> None:
    """place with a non-null source_location_id violates the shape CHECK."""
    params = _base_params(scenario, kind="place", src=scenario["pos_a_id"], dest=scenario["pos_b_id"])
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_movement(conn, params, match="ck_finished_goods_storage_movements_shape")
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_movement_update_rejected(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="append-only"):
            conn.execute(
                text("UPDATE finished_goods_storage_movements SET moved_weight_kg = 99 WHERE finished_goods_lot_id = :lot"),
                {"lot": scenario["fg_lot_id"]},
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_movement_delete_rejected(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="hard-deleted|not permitted"):
            conn.execute(
                text("DELETE FROM finished_goods_storage_movements WHERE finished_goods_lot_id = :lot"),
                {"lot": scenario["fg_lot_id"]},
            )
    finally:
        trans.rollback()
        conn.close()


# --- v3 ledger trigger: dispatch cannot reduce available below placed --------


def _insert_dispatch_issue(conn, *, scenario, fg_lot_id, weight: Decimal, count: int, effective_time):
    event_id = uuid.uuid4()
    line_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO dispatch_events (id, tenant_id, farm_id, code, effective_time, actor_user_id, "
            "client_command_id, request_fingerprint, external_reference, note) "
            "VALUES (:id, :tid, :fid, :code, :eff, :uid, :ccid, 'fp', NULL, NULL)"
        ),
        {
            "id": event_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
            "code": f"DIRECT-{uuid.uuid4().hex[:8]}", "eff": effective_time, "uid": scenario["user_id"],
            "ccid": uuid.uuid4(),
        },
    )
    conn.execute(
        text(
            "INSERT INTO dispatch_lines (id, tenant_id, farm_id, dispatch_event_id, finished_goods_lot_id, "
            "dispatched_weight_kg, dispatched_package_count) VALUES (:id, :tid, :fid, :eid, :lid, :weight, :count)"
        ),
        {
            "id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "eid": event_id,
            "lid": fg_lot_id, "weight": weight, "count": count,
        },
    )
    recorded_time = conn.execute(
        text("SELECT recorded_time FROM dispatch_events WHERE id = :id"), {"id": event_id}
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO finished_goods_ledger_entries "
            "(id, tenant_id, farm_id, finished_goods_lot_id, dispatch_line_id, entry_kind, weight_delta_kg, "
            "package_count_delta, effective_time, recorded_time, actor_user_id, note) "
            "VALUES (:id, :tid, :fid, :lid, :line_id, 'dispatch_issue', :neg_weight, :neg_count, :eff, :rec, :uid, NULL)"
        ),
        {
            "id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "lid": fg_lot_id,
            "line_id": line_id, "neg_weight": -weight, "neg_count": -count, "eff": effective_time,
            "rec": recorded_time, "uid": scenario["user_id"],
        },
    )


@pytest.mark.integration
def test_direct_sql_dispatch_cannot_reduce_available_below_placed(scenario, test_engine) -> None:
    """20kg available, 13kg placed (10 + 3). Dispatching 8kg would leave
    available at 12kg -- below the 13kg physically placed -- and must be
    rejected by the v3 ledger trigger independently of the service."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="available weight below physically placed quantity"):
            _insert_dispatch_issue(
                conn, scenario=scenario, fg_lot_id=scenario["fg_lot_id"], weight=Decimal("8.000"), count=1,
                effective_time=now(),
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_dispatch_within_unplaced_still_succeeds(scenario, test_engine) -> None:
    """7kg is currently unplaced (20 - 13); dispatching exactly that much
    must still succeed even under the new v3 check."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        _insert_dispatch_issue(
            conn, scenario=scenario, fg_lot_id=scenario["fg_lot_id"], weight=Decimal("7.000"), count=7,
            effective_time=now(),
        )
    finally:
        trans.rollback()
        conn.close()


# --- cross-ledger chronology --------------------------------------------------
#
# Every test below builds its own scenario with fully deterministic,
# explicit `effective_time` values derived from one base time safely in
# the past (never the real wall clock, never a sleep): T_base, T_base+1m,
# T_base+2m, ... . Since every intervening command (batch creation,
# sowing, stage transition, harvest, packing) also requires a monotonic,
# non-future `effective_time` of its own, the whole scenario is built at
# T_base and forward from there, leaving a full minute of unambiguous
# separation between any two steps whose relative order a test cares
# about -- no dependency on scheduler speed or wall-clock advancement.


@pytest.mark.integration
def test_storage_movement_before_latest_ledger_entry_rejected(test_engine) -> None:
    """A dispatch issue posts at T1 (after the T0 packing receipt); a
    storage movement effective between T0 and T1 must be rejected for
    preceding the lot's *latest ledger entry*, not merely its own T0. The
    scenario's own session/connection is always closed before the outer
    `finally` hands off to `cleanup_scenario`, so a mid-test exception
    here can never leave an open transaction to block cleanup's own
    DELETEs."""
    t_base = now() - timedelta(minutes=30)
    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant_id = None
    try:
        try:
            s = _build_scenario_ready_to_harvest(
                session, t_batch=t_base, t_sow=t_base + timedelta(minutes=1),
                t_transition=t_base + timedelta(minutes=2),
            )
            tenant_id = s["tenant_id"]
            t0 = t_base + timedelta(minutes=4)
            fg_lot_id = _harvest_and_pack_at(session, s, t_harvest=t_base + timedelta(minutes=3), t_pack=t0)
            cold_store = create_cold_store(s, session)
            pos = create_cold_store_position(s, session, cold_store_id=cold_store.id)
            pos_id = pos.id
            session.commit()

            from app.services import dispatch_service

            t1 = t_base + timedelta(minutes=5)
            dispatch_service.record_dispatch(
                session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], actor_user_id=s["user_id"],
                client_command_id=uuid.uuid4(), effective_time=t1, code=f"DISP-{s['suffix']}",
                external_reference=None, note=None, dispatch_temperature_c=Decimal("4.0"),
                lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("2.000"), "dispatched_package_count": 2}],
            )
            session.commit()
        finally:
            session.close()
            conn.close()

        conn2 = test_engine.connect()
        trans2 = conn2.begin()
        try:
            with pytest.raises(Exception, match="latest ledger entry"):
                conn2.execute(
                    text(
                        "INSERT INTO finished_goods_storage_movements "
                        "(id, tenant_id, farm_id, finished_goods_lot_id, movement_kind, source_location_id, "
                        "destination_location_id, moved_weight_kg, moved_package_count, effective_time, "
                        "actor_user_id, client_command_id, request_fingerprint, note) "
                        "VALUES (:id, :tid, :fid, :lot, 'place', NULL, :dest, 1.000, 1, :eff, :actor, :ccid, 'fp', NULL)"
                    ),
                    {
                        "id": uuid.uuid4(), "tid": s["tenant_id"], "fid": s["farm_id"], "lot": fg_lot_id,
                        "dest": pos_id, "eff": t0 + timedelta(seconds=30), "actor": s["user_id"],
                        "ccid": uuid.uuid4(),
                    },
                )
        finally:
            trans2.rollback()
            conn2.close()
    finally:
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_dispatch_before_latest_storage_movement_rejected(test_engine) -> None:
    """A place posts at T2 (after the T0 packing receipt); a dispatch
    effective between T0 and T2 must be rejected for preceding the lot's
    latest storage movement."""
    t_base = now() - timedelta(minutes=30)
    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant_id = None
    try:
        try:
            s = _build_scenario_ready_to_harvest(
                session, t_batch=t_base, t_sow=t_base + timedelta(minutes=1),
                t_transition=t_base + timedelta(minutes=2),
            )
            tenant_id = s["tenant_id"]
            t0 = t_base + timedelta(minutes=4)
            fg_lot_id = _harvest_and_pack_at(session, s, t_harvest=t_base + timedelta(minutes=3), t_pack=t0)
            cold_store = create_cold_store(s, session)
            pos = create_cold_store_position(s, session, cold_store_id=cold_store.id)
            session.commit()

            t2 = t_base + timedelta(minutes=5)
            place_one(s, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos.id, moved_weight_kg=Decimal("2.000"), moved_package_count=2, effective_time=t2)
            session.commit()
        finally:
            session.close()
            conn.close()

        conn2 = test_engine.connect()
        trans2 = conn2.begin()
        try:
            with pytest.raises(Exception, match="latest storage movement"):
                _insert_dispatch_issue(
                    conn2, scenario=s, fg_lot_id=fg_lot_id, weight=Decimal("1.000"), count=1,
                    effective_time=t0 + timedelta(seconds=30),
                )
        finally:
            trans2.rollback()
            conn2.close()
    finally:
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_release_then_earlier_dispatch_rejected(test_engine) -> None:
    """A release posts at T (after an earlier place); a dispatch attempted
    exactly one second before T must be rejected for preceding the lot's
    latest storage movement, even though it is still after the earlier
    place -- proving the check compares against the *latest* movement,
    not merely *any* prior one."""
    t_base = now() - timedelta(minutes=30)
    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant_id = None
    try:
        try:
            s = _build_scenario_ready_to_harvest(
                session, t_batch=t_base, t_sow=t_base + timedelta(minutes=1),
                t_transition=t_base + timedelta(minutes=2),
            )
            tenant_id = s["tenant_id"]
            fg_lot_id = _harvest_and_pack_at(
                session, s, t_harvest=t_base + timedelta(minutes=3), t_pack=t_base + timedelta(minutes=4),
            )
            cold_store = create_cold_store(s, session)
            pos = create_cold_store_position(s, session, cold_store_id=cold_store.id)
            session.commit()

            from tests._storage_scenario import release_one

            t_place = t_base + timedelta(minutes=5)
            place_one(s, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos.id, moved_weight_kg=Decimal("10.000"), moved_package_count=10, effective_time=t_place)
            session.commit()

            t_release = t_base + timedelta(minutes=6)
            release_one(s, session, finished_goods_lot_id=fg_lot_id, source_location_id=pos.id, moved_weight_kg=Decimal("5.000"), moved_package_count=5, effective_time=t_release)
            session.commit()
        finally:
            session.close()
            conn.close()

        conn2 = test_engine.connect()
        trans2 = conn2.begin()
        try:
            with pytest.raises(Exception, match="latest storage movement"):
                _insert_dispatch_issue(
                    conn2, scenario=s, fg_lot_id=fg_lot_id, weight=Decimal("1.000"), count=1,
                    effective_time=t_release - timedelta(seconds=1),
                )
        finally:
            trans2.rollback()
            conn2.close()
    finally:
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_dispatch_then_earlier_storage_movement_rejected(test_engine) -> None:
    """A dispatch posts at T; a storage movement attempted exactly one
    second before T must be rejected for preceding the lot's latest
    ledger entry."""
    t_base = now() - timedelta(minutes=30)
    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant_id = None
    try:
        try:
            s = _build_scenario_ready_to_harvest(
                session, t_batch=t_base, t_sow=t_base + timedelta(minutes=1),
                t_transition=t_base + timedelta(minutes=2),
            )
            tenant_id = s["tenant_id"]
            fg_lot_id = _harvest_and_pack_at(
                session, s, t_harvest=t_base + timedelta(minutes=3), t_pack=t_base + timedelta(minutes=4),
            )
            cold_store = create_cold_store(s, session)
            pos = create_cold_store_position(s, session, cold_store_id=cold_store.id)
            pos_id = pos.id
            session.commit()

            from app.services import dispatch_service

            t_dispatch = t_base + timedelta(minutes=5)
            dispatch_service.record_dispatch(
                session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], actor_user_id=s["user_id"],
                client_command_id=uuid.uuid4(), effective_time=t_dispatch, code=f"DISP-{s['suffix']}",
                external_reference=None, note=None, dispatch_temperature_c=Decimal("4.0"),
                lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("2.000"), "dispatched_package_count": 2}],
            )
            session.commit()
        finally:
            session.close()
            conn.close()

        conn2 = test_engine.connect()
        trans2 = conn2.begin()
        try:
            with pytest.raises(Exception, match="latest ledger entry"):
                conn2.execute(
                    text(
                        "INSERT INTO finished_goods_storage_movements "
                        "(id, tenant_id, farm_id, finished_goods_lot_id, movement_kind, source_location_id, "
                        "destination_location_id, moved_weight_kg, moved_package_count, effective_time, "
                        "actor_user_id, client_command_id, request_fingerprint, note) "
                        "VALUES (:id, :tid, :fid, :lot, 'place', NULL, :dest, 1.000, 1, :eff, :actor, :ccid, 'fp', NULL)"
                    ),
                    {
                        "id": uuid.uuid4(), "tid": s["tenant_id"], "fid": s["farm_id"], "lot": fg_lot_id,
                        "dest": pos_id, "eff": t_dispatch - timedelta(seconds=1), "actor": s["user_id"],
                        "ccid": uuid.uuid4(),
                    },
                )
        finally:
            trans2.rollback()
            conn2.close()
    finally:
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_release_then_dispatch_at_exact_same_time_allowed(test_engine) -> None:
    s = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(s, session, package_count=10, packed_output_weight_kg=Decimal("10.000"))
        cold_store = create_cold_store(s, session)
        pos = create_cold_store_position(s, session, cold_store_id=cold_store.id)
        session.commit()

        from app.services import dispatch_service
        from tests._storage_scenario import release_one

        place_one(s, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos.id, moved_weight_kg=Decimal("5.000"), moved_package_count=5)
        t = now()
        release_one(s, session, finished_goods_lot_id=fg_lot_id, source_location_id=pos.id, moved_weight_kg=Decimal("5.000"), moved_package_count=5, effective_time=t)

        # dispatch at the exact same instant as the release must be allowed
        # (strict-less-than rejection convention -- equal timestamps are fine).
        dispatch_service.record_dispatch(
            session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], actor_user_id=s["user_id"],
            client_command_id=uuid.uuid4(), effective_time=t, code=f"DISP-{s['suffix']}",
            external_reference=None, note=None, dispatch_temperature_c=Decimal("4.0"),
            lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("5.000"), "dispatched_package_count": 5}],
        )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, s["tenant_id"])
