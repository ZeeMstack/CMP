"""Unit/integration coverage for CMP-018 finished-goods physical storage:
location-model reuse, place/transfer/release shape, unplaced-quantity
derivation, per-location balance, Decimal precision, BIGINT bounds, and
confirmation that packing creates no fake placement. Direct-SQL/db-trigger
enforcement lives in test_finished_goods_storage_integrity.py."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services import finished_goods_storage_service, location_service
from app.services.errors import (
    IneligibleStorageLocationError,
    InsufficientStorageLocationBalanceError,
    InsufficientUnplacedQuantityError,
    StorageLocationNotFoundError,
    StorageMovementValidationError,
)
from tests._dispatch_scenario import pack_one
from tests._packing_scenario import build_committed_scenario, cleanup_scenario
from tests._storage_scenario import create_cold_store, create_cold_store_position, now, place_one, release_one, transfer_one

MAX_WHOLE_UNIT_COUNT = 9223372036854775807


@pytest.mark.integration
def test_location_model_reuse_cold_store_position(test_engine) -> None:
    """CMP-018 needs no location/hierarchy schema change -- the existing
    cold_store -> cold_store_position farm-root hierarchy (CMP-004) is
    directly reusable."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cold_store = create_cold_store(scenario, session)
        position = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
        session.commit()
        assert position.parent_location_id == cold_store.id
        assert cold_store.parent_location_id is None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_historical_lot_begins_fully_unplaced(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
        placement = finished_goods_storage_service.get_placement(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        assert placement.available_weight_kg == Decimal("8.000")
        assert placement.total_placed_weight_kg == Decimal("0")
        assert placement.unplaced_weight_kg == Decimal("8.000")
        assert placement.available_package_count == 10
        assert placement.total_placed_package_count == 0
        assert placement.unplaced_package_count == 10
        assert placement.locations == []
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_packing_creates_no_fake_placement(test_engine) -> None:
    """Packing must never create a storage movement -- confirmed directly
    against the table, not just the derived placement view."""
    from sqlalchemy import func, select

    from app.models.finished_goods_storage_movement import FinishedGoodsStorageMovement

    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        pack_one(scenario, session, package_count=5, packed_output_weight_kg=Decimal("4.000"))
        count = session.execute(
            select(func.count()).select_from(FinishedGoodsStorageMovement)
            .where(FinishedGoodsStorageMovement.tenant_id == scenario["tenant_id"])
        ).scalar_one()
        assert count == 0
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_place_partial_and_multi_location_split(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("10.000"))
        cold_store = create_cold_store(scenario, session)
        pos_a = create_cold_store_position(scenario, session, cold_store_id=cold_store.id, code_suffix="-A")
        pos_b = create_cold_store_position(scenario, session, cold_store_id=cold_store.id, code_suffix="-B")
        session.commit()

        place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_a.id, moved_weight_kg=Decimal("4.000"), moved_package_count=4)
        place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_b.id, moved_weight_kg=Decimal("3.000"), moved_package_count=3)

        placement = finished_goods_storage_service.get_placement(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        assert placement.total_placed_weight_kg == Decimal("7.000")
        assert placement.total_placed_package_count == 7
        assert placement.unplaced_weight_kg == Decimal("3.000")
        assert placement.unplaced_package_count == 3
        balances = {loc.location_id: loc for loc in placement.locations}
        assert balances[pos_a.id].weight_kg == Decimal("4.000")
        assert balances[pos_b.id].weight_kg == Decimal("3.000")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_transfer_partial_and_source_balance_decreases(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("10.000"))
        cold_store = create_cold_store(scenario, session)
        pos_a = create_cold_store_position(scenario, session, cold_store_id=cold_store.id, code_suffix="-A")
        pos_b = create_cold_store_position(scenario, session, cold_store_id=cold_store.id, code_suffix="-B")
        session.commit()

        place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_a.id, moved_weight_kg=Decimal("6.000"), moved_package_count=6)
        transfer_one(scenario, session, finished_goods_lot_id=fg_lot_id, source_location_id=pos_a.id, destination_location_id=pos_b.id, moved_weight_kg=Decimal("2.000"), moved_package_count=2)

        placement = finished_goods_storage_service.get_placement(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        # A transfer must leave total placed unchanged -- only relocated.
        assert placement.total_placed_weight_kg == Decimal("6.000")
        balances = {loc.location_id: loc for loc in placement.locations}
        assert balances[pos_a.id].weight_kg == Decimal("4.000")
        assert balances[pos_b.id].weight_kg == Decimal("2.000")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_release_partial_and_exact_zero_source_balance(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("10.000"))
        cold_store = create_cold_store(scenario, session)
        pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
        session.commit()

        place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos.id, moved_weight_kg=Decimal("5.000"), moved_package_count=5)
        release_one(scenario, session, finished_goods_lot_id=fg_lot_id, source_location_id=pos.id, moved_weight_kg=Decimal("2.000"), moved_package_count=2)

        placement = finished_goods_storage_service.get_placement(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        assert placement.total_placed_weight_kg == Decimal("3.000")
        assert placement.unplaced_weight_kg == Decimal("7.000")

        # Release the exact remainder -- exact-zero source balance is valid.
        release_one(scenario, session, finished_goods_lot_id=fg_lot_id, source_location_id=pos.id, moved_weight_kg=Decimal("3.000"), moved_package_count=3)
        final_placement = finished_goods_storage_service.get_placement(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        assert final_placement.total_placed_weight_kg == Decimal("0")
        assert final_placement.unplaced_weight_kg == Decimal("10.000")
        assert final_placement.locations == []
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_placement_cannot_exceed_unplaced_weight(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=5, packed_output_weight_kg=Decimal("5.000"))
        cold_store = create_cold_store(scenario, session)
        pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
        session.commit()
        with pytest.raises(InsufficientUnplacedQuantityError):
            place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos.id, moved_weight_kg=Decimal("5.001"), moved_package_count=1)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_placement_cannot_exceed_unplaced_package_count(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=5, packed_output_weight_kg=Decimal("5.000"))
        cold_store = create_cold_store(scenario, session)
        pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
        session.commit()
        with pytest.raises(InsufficientUnplacedQuantityError):
            place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos.id, moved_weight_kg=Decimal("1.000"), moved_package_count=6)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_source_weight_cannot_go_negative(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=5, packed_output_weight_kg=Decimal("5.000"))
        cold_store = create_cold_store(scenario, session)
        pos_a = create_cold_store_position(scenario, session, cold_store_id=cold_store.id, code_suffix="-A")
        pos_b = create_cold_store_position(scenario, session, cold_store_id=cold_store.id, code_suffix="-B")
        session.commit()
        place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_a.id, moved_weight_kg=Decimal("2.000"), moved_package_count=2)
        with pytest.raises(InsufficientStorageLocationBalanceError):
            transfer_one(scenario, session, finished_goods_lot_id=fg_lot_id, source_location_id=pos_a.id, destination_location_id=pos_b.id, moved_weight_kg=Decimal("2.001"), moved_package_count=1)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_source_package_count_cannot_go_negative(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=5, packed_output_weight_kg=Decimal("5.000"))
        cold_store = create_cold_store(scenario, session)
        pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
        session.commit()
        place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos.id, moved_weight_kg=Decimal("2.000"), moved_package_count=2)
        with pytest.raises(InsufficientStorageLocationBalanceError):
            release_one(scenario, session, finished_goods_lot_id=fg_lot_id, source_location_id=pos.id, moved_weight_kg=Decimal("1.000"), moved_package_count=3)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_non_storage_location_rejected(test_engine) -> None:
    """A location that is not a cold_store_position (e.g. a greenhouse)
    must never become eligible for finished-goods placement."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=5, packed_output_weight_kg=Decimal("5.000"))
        greenhouse = location_service.create_location(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            location_type_code="greenhouse", code=f"GH-{scenario['suffix']}", name="Greenhouse",
            parent_location_id=None, greenhouse_classification="leafy_greens", occupiable=None,
        )
        session.commit()
        with pytest.raises(IneligibleStorageLocationError):
            place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=greenhouse.id, moved_weight_kg=Decimal("1.000"), moved_package_count=1)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_wrong_tenant_farm_location_rejected(test_engine) -> None:
    scenario_a = build_committed_scenario(test_engine, lot_a_count=None)
    scenario_b = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario_a, session, package_count=5, packed_output_weight_kg=Decimal("5.000"))
        cold_store_b = create_cold_store(scenario_b, session)
        pos_b = create_cold_store_position(scenario_b, session, cold_store_id=cold_store_b.id)
        session.commit()
        with pytest.raises(StorageLocationNotFoundError):
            place_one(scenario_a, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_b.id, moved_weight_kg=Decimal("1.000"), moved_package_count=1)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario_a["tenant_id"])
        cleanup_scenario(test_engine, scenario_b["tenant_id"])


@pytest.mark.integration
def test_transfer_shape_validation_rejects_same_source_and_destination(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=5, packed_output_weight_kg=Decimal("5.000"))
        cold_store = create_cold_store(scenario, session)
        pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
        session.commit()
        place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos.id, moved_weight_kg=Decimal("2.000"), moved_package_count=2)
        with pytest.raises(StorageMovementValidationError):
            transfer_one(scenario, session, finished_goods_lot_id=fg_lot_id, source_location_id=pos.id, destination_location_id=pos.id, moved_weight_kg=Decimal("1.000"), moved_package_count=1)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_package_count_bigint_max_accepted(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=MAX_WHOLE_UNIT_COUNT, packed_output_weight_kg=Decimal("1.000"))
        cold_store = create_cold_store(scenario, session)
        pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
        session.commit()
        movement = place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos.id, moved_weight_kg=Decimal("1.000"), moved_package_count=MAX_WHOLE_UNIT_COUNT)
        assert movement.moved_package_count == MAX_WHOLE_UNIT_COUNT
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_canonical_decimal_weight_serialization(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=5, packed_output_weight_kg=Decimal("5.000"))
        cold_store = create_cold_store(scenario, session)
        pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
        session.commit()
        movement = place_one(scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos.id, moved_weight_kg=Decimal("3.500"), moved_package_count=3)
        history = finished_goods_storage_service.get_movement_history(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        dumped = history[0].model_dump(mode="json")
        assert dumped["moved_weight_kg"] == "3.5"
        assert dumped["id"] == str(movement.id)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
