"""Shared, non-collected scenario helpers for STORE-INV-002B tests. Not a
test file itself (pytest's default `test_*.py` glob does not match this
name)."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.location import Location
from app.services import goods_receipt_service, location_service
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_item, uom_id
from tests._traceability_scenario import build_committed_tenant_farm


def build_store_bin(db: Session, *, tenant_id, farm_id, actor_user_id, store_id=None, code=None) -> Location:
    if store_id is None:
        store_id = location_service.create_location(
            db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, location_type_code="store",
            code=f"STORE-{uuid.uuid4().hex[:8]}", name="Test Store", parent_location_id=None,
            greenhouse_classification=None, occupiable=None,
        ).id
    return location_service.create_location(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, location_type_code="store_bin",
        code=code or f"BIN-{uuid.uuid4().hex[:8]}", name="Test Bin", parent_location_id=store_id,
        greenhouse_classification=None, occupiable=None,
    )


def receive_cohort(db: Session, *, tenant_id, farm_id, actor_user_id, item_id, quantity: Decimal) -> uuid.UUID:
    receipt = goods_receipt_service.record_goods_receipt(
        db, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item_id, entered_quantity=quantity, entered_uom_id=uom_id(db, "kg"))],
    )
    line = db.execute(select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)).scalar_one()
    return line.id


def build_scenario(test_engine, *, qc_release_required: bool = False):
    """One committed tenant/farm/item, ready for `receive_cohort`."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        tenant, user, farm = build_committed_tenant_farm(session)
        category = build_category(session, tenant, actor_user_id=user.id)
        item = build_item(
            session, tenant, category.id, uom_id(session, "kg"), actor_user_id=user.id,
            qc_release_required=qc_release_required,
        )
        session.commit()
        return {"tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "item_id": item.id}
    finally:
        session.close()
        conn.close()
