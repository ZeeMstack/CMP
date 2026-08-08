"""Shared, non-collected scenario helpers for CMP-018 finished-goods
storage tests. Builds on `tests._dispatch_scenario`/`tests._packing_scenario`'s
own `build_committed_scenario`, adding `create_cold_store`/
`create_cold_store_position` location helpers and `place_one`/
`transfer_one`/`release_one` movement wrappers. Not a test file itself
(pytest's default `test_*.py` discovery glob does not match this name)."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.services import finished_goods_storage_service, location_service


def now():
    return datetime.now(timezone.utc)


def create_cold_store(scenario, db: Session, *, code_suffix: str = ""):
    return location_service.create_location(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        location_type_code="cold_store", code=f"CS-{scenario['suffix']}{code_suffix}", name="Cold Store",
        parent_location_id=None, greenhouse_classification=None, occupiable=None,
    )


def create_cold_store_position(scenario, db: Session, *, cold_store_id: uuid.UUID, code_suffix: str = ""):
    return location_service.create_location(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        location_type_code="cold_store_position", code=f"POS-{scenario['suffix']}{code_suffix}", name="Position",
        parent_location_id=cold_store_id, greenhouse_classification=None, occupiable=None,
    )


def place_one(
    scenario, db: Session, *, finished_goods_lot_id, destination_location_id,
    moved_weight_kg: Decimal = Decimal("3.000"), moved_package_count: int = 3, client_command_id=None,
    effective_time=None, note: str | None = None,
):
    """Records a `place` movement (unplaced -> destination). Returns the
    FinishedGoodsStorageMovement ORM object."""
    return finished_goods_storage_service.record_movement(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=client_command_id or uuid.uuid4(), effective_time=effective_time or now(),
        finished_goods_lot_id=finished_goods_lot_id, movement_kind="place", source_location_id=None,
        destination_location_id=destination_location_id, moved_weight_kg=moved_weight_kg,
        moved_package_count=moved_package_count, note=note,
    )


def transfer_one(
    scenario, db: Session, *, finished_goods_lot_id, source_location_id, destination_location_id,
    moved_weight_kg: Decimal = Decimal("1.000"), moved_package_count: int = 1, client_command_id=None,
    effective_time=None, note: str | None = None,
):
    """Records a `transfer` movement (source -> destination). Returns the
    FinishedGoodsStorageMovement ORM object."""
    return finished_goods_storage_service.record_movement(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=client_command_id or uuid.uuid4(), effective_time=effective_time or now(),
        finished_goods_lot_id=finished_goods_lot_id, movement_kind="transfer",
        source_location_id=source_location_id, destination_location_id=destination_location_id,
        moved_weight_kg=moved_weight_kg, moved_package_count=moved_package_count, note=note,
    )


def release_one(
    scenario, db: Session, *, finished_goods_lot_id, source_location_id,
    moved_weight_kg: Decimal = Decimal("1.000"), moved_package_count: int = 1, client_command_id=None,
    effective_time=None, note: str | None = None,
):
    """Records a `release` movement (source -> unplaced/staging). Returns
    the FinishedGoodsStorageMovement ORM object."""
    return finished_goods_storage_service.record_movement(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=client_command_id or uuid.uuid4(), effective_time=effective_time or now(),
        finished_goods_lot_id=finished_goods_lot_id, movement_kind="release",
        source_location_id=source_location_id, destination_location_id=None,
        moved_weight_kg=moved_weight_kg, moved_package_count=moved_package_count, note=note,
    )
