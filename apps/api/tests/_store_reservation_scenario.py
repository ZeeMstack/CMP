"""Shared, non-collected scenario helpers for STORE-INV-003 tests. Not a
test file itself (pytest's default `test_*.py` glob does not match this
name)."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.services import inventory_storage_service
from tests._store_custody_scenario import build_scenario, build_store_bin, receive_cohort


def _now():
    return datetime.now(timezone.utc)


def receive_and_putaway(
    db: Session, *, tenant_id, farm_id, actor_user_id, item_id, quantity: Decimal, bin_id=None
) -> tuple[uuid.UUID, uuid.UUID]:
    """One committed cohort of `quantity`, fully put away into a (given or
    freshly built) Bin. Returns (cohort_id, bin_id)."""
    cohort_id = receive_cohort(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, item_id=item_id, quantity=quantity
    )
    if bin_id is None:
        bin_id = build_store_bin(db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id).id
    inventory_storage_service.record_putaway(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, destination_location_id=bin_id, quantity=quantity, effective_time=_now(),
    )
    db.commit()
    return cohort_id, bin_id


__all__ = ["build_scenario", "build_store_bin", "receive_cohort", "receive_and_putaway"]
