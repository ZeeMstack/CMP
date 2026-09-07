"""Shared, non-collected scenario helpers for STORE-INV-002A.1 tests. Not a
test file itself (pytest's default `test_*.py` glob does not match this
name)."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.inventory_quantity_cohort import InventoryQuantityCohort
from app.models.unit_of_measure import UnitOfMeasure
from app.services import crop_service, inventory_category_service, inventory_item_service
from app.services.inventory_existence_ledger_service import _split_cohort_core


def uom_id(db: Session, code: str) -> uuid.UUID:
    return db.execute(select(UnitOfMeasure.id).where(UnitOfMeasure.code == code)).scalar_one()


def build_category(db: Session, tenant, *, actor_user_id=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
        code=f"CAT-{uuid.uuid4().hex[:8]}", name="Test Category",
    )
    defaults.update(overrides)
    return inventory_category_service.register_inventory_category(db, **defaults)


def build_item(db: Session, tenant, category_id, base_uom_id, *, actor_user_id=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
        code=f"ITEM-{uuid.uuid4().hex[:8]}", name="Test Item", category_id=category_id,
        base_uom_id=base_uom_id, lot_tracking_required=False, expiry_tracking_required=False,
        qc_release_required=False,
    )
    defaults.update(overrides)
    return inventory_item_service.register_inventory_item(db, **defaults)


def build_crop_and_variety(db: Session, tenant, *, actor_user_id=None, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db, tenant_id=tenant.id, actor_user_id=actor_user_id, code=f"CROP-{suffix}", common_name="Test Crop",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db, tenant_id=tenant.id, actor_user_id=actor_user_id, crop_id=crop.id, code=f"VAR-{suffix}",
        name="Test Variety", supplier_reference=None,
    )
    return crop, variety


def split_cohort_for_test(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    source_cohort_id: uuid.UUID,
    allocations: list[Decimal],
    reason: str,
    effective_time: datetime,
) -> list[InventoryQuantityCohort]:
    """Test-only committing entry point for the internal `_split_cohort_core`
    primitive (CTO integrity review, pre-commit cleanup pass). Production
    code deliberately has NO committing sibling of `_split_cohort_core`
    anywhere -- `.1` has no route, no `Permission`, no operator-facing
    "Split Cohort" concept, and `STORE-INV-002A.2`'s real quality command is
    what must call `_split_cohort_core` directly, composing it with its own
    child `QualityDispositionEvent` and audit event before its own single
    commit. This helper exists only so today's tests -- which have no
    surrounding command to compose into -- can exercise the core and commit
    the result themselves."""
    children = _split_cohort_core(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, source_cohort_id=source_cohort_id,
        allocations=allocations, reason=reason, effective_time=effective_time,
    )
    db.commit()
    for child in children:
        db.refresh(child)
    return children
