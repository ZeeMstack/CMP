"""CMP-020 containment gate tests: the four write-path boundaries (batch
derivation, packing, finished-goods storage release, dispatch), quality-
hold independence, closure lifting containment, and the frozen-scope
versus live-state distinction under otherwise-permitted operations."""
import uuid
from decimal import Decimal

import pytest

from app.services import (
    batch_derivation_service,
    dispatch_service,
    finished_goods_storage_service,
    packing_service,
    quality_hold_service,
    recall_service,
)
from app.services.errors import RecallContainmentOpenError
from tests._recall_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    build_workflow_scaffold,
    cleanup_recall_scenario,
    close_case,
    committed_connection,
    create_cold_store_position,
    dispatch,
    harvest_all,
    now,
    open_case,
    pack_lot,
    sow_new_batch,
)


@pytest.mark.integration
def test_derivation_blocked_from_contained_batch(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2)
            session.commit()
            batch_id = scaffold["batch"].id
            open_case(session, tenant, farm, user, crop_batch_id=batch_id)
            session.commit()

            with pytest.raises(RecallContainmentOpenError):
                batch_derivation_service.split_batch(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
                    client_command_id=uuid.uuid4(), effective_time=now(), note=None,
                    outputs=[
                        {"output_batch_code": "SIDE-1", "source_assignment_ids": scaffold["assignment_ids"][:1]},
                        {"output_batch_code": "SIDE-2", "source_assignment_ids": scaffold["assignment_ids"][1:]},
                    ],
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_packing_blocked_by_contained_produce_lot(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            session.commit()
            open_case(session, tenant, farm, user, harvested_produce_lot_id=produce_lot_id)
            session.commit()

            with pytest.raises(RecallContainmentOpenError):
                packing_service.record_packing(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                    effective_time=now(), finished_goods_lot_code=f"FG-{uuid.uuid4().hex[:8]}", package_count=5,
                    packed_output_weight_kg=Decimal("5.000"), process_loss_weight_kg=Decimal("0"),
                    rejected_weight_kg=Decimal("0"), note=None,
                    input_lines=[{"harvested_produce_lot_id": produce_lot_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_packing_blocked_by_contained_batch(test_engine) -> None:
    """The produce lot itself is not individually scoped, but its crop
    batch is (batch-source recall) -- packing must still be rejected."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            session.commit()
            batch_id = scaffold["batch"].id
            open_case(session, tenant, farm, user, crop_batch_id=batch_id)
            session.commit()

            with pytest.raises(RecallContainmentOpenError):
                packing_service.record_packing(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                    effective_time=now(), finished_goods_lot_code=f"FG-{uuid.uuid4().hex[:8]}", package_count=5,
                    packed_output_weight_kg=Decimal("5.000"), process_loss_weight_kg=Decimal("0"),
                    rejected_weight_kg=Decimal("0"), note=None,
                    input_lines=[{"harvested_produce_lot_id": produce_lot_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_place_and_transfer_allowed_but_release_blocked_for_recalled_lot(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            pos1 = create_cold_store_position(session, tenant, user, farm, suffix="p1")
            pos2 = create_cold_store_position(session, tenant, user, farm, suffix="p2")
            session.commit()
            pos1_id, pos2_id = pos1.id, pos2.id

            open_case(session, tenant, farm, user, finished_goods_lot_id=fg_lot_id)
            session.commit()

            # place: allowed (segregation into quarantine).
            finished_goods_storage_service.record_movement(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                effective_time=now(), finished_goods_lot_id=fg_lot_id, movement_kind="place",
                source_location_id=None, destination_location_id=pos1_id, moved_weight_kg=Decimal("5.000"),
                moved_package_count=5, note=None,
            )
            # transfer: allowed.
            finished_goods_storage_service.record_movement(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                effective_time=now(), finished_goods_lot_id=fg_lot_id, movement_kind="transfer",
                source_location_id=pos1_id, destination_location_id=pos2_id, moved_weight_kg=Decimal("5.000"),
                moved_package_count=5, note=None,
            )
            # release: blocked.
            with pytest.raises(RecallContainmentOpenError):
                finished_goods_storage_service.record_movement(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                    effective_time=now(), finished_goods_lot_id=fg_lot_id, movement_kind="release",
                    source_location_id=pos2_id, destination_location_id=None, moved_weight_kg=Decimal("5.000"),
                    moved_package_count=5, note=None,
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_dispatch_blocked_for_recalled_lot(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()
            open_case(session, tenant, farm, user, finished_goods_lot_id=fg_lot_id)
            session.commit()

            with pytest.raises(RecallContainmentOpenError):
                dispatch_service.record_dispatch(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                    effective_time=now(), code=f"DISP-{uuid.uuid4().hex[:8]}", external_reference=None, note=None,
                    lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1}],
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_dispatch_resumes_after_close(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()
            case = open_case(session, tenant, farm, user, finished_goods_lot_id=fg_lot_id)
            session.commit()
            case_id = case.id

            with pytest.raises(RecallContainmentOpenError):
                dispatch_service.record_dispatch(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                    effective_time=now(), code=f"DISP-{uuid.uuid4().hex[:8]}", external_reference=None, note=None,
                    lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1}],
                )

            close_case(session, tenant, farm, user, recall_case_id=case_id)
            session.commit()

            event = dispatch_service.record_dispatch(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                effective_time=now(), code=f"DISP-{uuid.uuid4().hex[:8]}", external_reference=None, note=None,
                lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1}],
            )
            assert event.id is not None
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_quality_hold_and_recall_containment_are_independent(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()
            batch_id = scaffold["batch"].id

            # 1. Recall containment blocks dispatch with NO quality hold present.
            case = open_case(session, tenant, farm, user, finished_goods_lot_id=fg_lot_id)
            session.commit()
            case_id = case.id
            with pytest.raises(RecallContainmentOpenError):
                dispatch_service.record_dispatch(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                    effective_time=now(), code=f"DISP-{uuid.uuid4().hex[:8]}", external_reference=None, note=None,
                    lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1}],
                )

            # 2. Close containment; place a quality hold on the source batch
            # independently. Quality hold still blocks dispatch on its own.
            close_case(session, tenant, farm, user, recall_case_id=case_id)
            session.commit()
            hold = quality_hold_service.place_quality_hold(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
                client_command_id=uuid.uuid4(), effective_time=now(), source_observation_event_id=None,
                reason_code="quality_defect", reason_text="unrelated quality issue",
            )
            session.commit()
            from app.services.errors import QualityHoldOpenError
            with pytest.raises(QualityHoldOpenError):
                dispatch_service.record_dispatch(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                    effective_time=now(), code=f"DISP-{uuid.uuid4().hex[:8]}", external_reference=None, note=None,
                    lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1}],
                )

            # 3. Closing the recall did not touch the (still-open) quality hold;
            # releasing the quality hold does not touch (re-open) the recall.
            assert quality_hold_service.has_open_quality_hold(session, batch_id=batch_id) is True
            quality_hold_service.release_quality_hold(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
                hold_id=hold.id, client_command_id=uuid.uuid4(), effective_time=now(), release_reason="resolved",
            )
            session.commit()
            assert recall_service.has_open_finished_goods_recall(session, tenant_id=tenant.id, farm_id=farm.id, finished_goods_lot_id=fg_lot_id) is False

            # Dispatch now succeeds -- neither gate blocks it anymore.
            event = dispatch_service.record_dispatch(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                effective_time=now(), code=f"DISP-{uuid.uuid4().hex[:8]}", external_reference=None, note=None,
                lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1}],
            )
            assert event.id is not None
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_frozen_scope_unchanged_by_permitted_live_state_changes(test_engine) -> None:
    """Opening a case, then placing/transferring the recalled stock
    (permitted operations), must never mutate the frozen scope ID lists --
    only live_state may change."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            pos = create_cold_store_position(session, tenant, user, farm)
            session.commit()
            pos_id = pos.id
            batch_id = scaffold["batch"].id
            user_id = user.id

            case = open_case(session, tenant, farm, user, crop_batch_id=batch_id)
            session.commit()
            case_id = case.id

        before = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
        assert before["live_state"]["finished_goods_lots"][0]["placed_weight_kg"] == Decimal("0.000")

        with committed_connection(test_engine) as session2:
            finished_goods_storage_service.record_movement(
                session2, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
                effective_time=now(), finished_goods_lot_id=fg_lot_id, movement_kind="place",
                source_location_id=None, destination_location_id=pos_id, moved_weight_kg=Decimal("5.000"),
                moved_package_count=5, note=None,
            )
            session2.commit()

        after = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
        assert after["frozen_scope"] == before["frozen_scope"]
        assert after["live_state"]["finished_goods_lots"][0]["placed_weight_kg"] == Decimal("5.000")
        assert after["live_state"]["finished_goods_lots"][0]["unplaced_weight_kg"] == Decimal("0.000")
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)
