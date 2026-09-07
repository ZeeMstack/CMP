"""STORE-INV-002A.2: HTTP-level authorization behavior for the new quality
routes -- extends `test_authz_mutation_enforcement_architecture.py`'s
structural proof with end-to-end behavior: a granted role succeeds, a
zero/wrong-permission role is denied with zero side effects, and a
segregation-of-duties conflict surfaces as 409 (a domain conflict), never
a generic 403."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models.quality_disposition_event import QualityDispositionEvent
from app.services import (
    farm_service,
    goods_receipt_service,
    inventory_item_seed_profile_service,
    membership_service,
    tenant_service,
    user_service,
)
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_item, uom_id

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _enable_dev_auth(monkeypatch):
    """This local `.env` runs with `ENABLE_DEV_AUTH=false` (every existing
    `client`-fixture HTTP test in this suite currently fails identically,
    confirmed pre-existing and unrelated to this ticket) -- mirrors
    `test_dev_auth.py`'s own sanctioned monkeypatch pattern to exercise the
    dev header auth path for this module's tests without touching `.env`."""
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)


def _membership_headers(db_session, *, tenant_id, role_code: str) -> dict[str, str]:
    user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"q-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com", display_name="Quality HTTP Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    return user, {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}


@pytest.mark.integration
def test_qc_officer_can_record_disposition_storekeeper_cannot(client, db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code=f"t-qc-{uuid.uuid4().hex[:8]}", name="QC HTTP Tenant")
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="qc-farm", name="QC Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    receiver, _receiver_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="storekeeper")
    qc_user, qc_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="qc_officer")
    _storekeeper_user, storekeeper_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="storekeeper")

    category = build_category(db_session, tenant, actor_user_id=receiver.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=receiver.id,
        lot_tracking_required=True, qc_release_required=True,
    )
    receipt = goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=receiver.id, client_command_id=uuid.uuid4(),
        received_at=NOW, supplier_name=None, external_system=None, external_document_id=None, notes=None,
        lines=[
            GoodsReceiptLineInput(
                inventory_item_id=item.id, entered_quantity=Decimal("100"), entered_uom_id=uom_id(db_session, "kg"),
                manufacturer_name="Acme", manufacturer_lot_reference=f"LOT-{uuid.uuid4().hex[:8]}",
            )
        ],
    )
    from app.models.goods_receipt_line import GoodsReceiptLine
    from app.models.inventory_quantity_cohort import InventoryQuantityCohort

    line = db_session.execute(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
    ).scalar_one()
    cohort = db_session.execute(
        select(InventoryQuantityCohort).where(InventoryQuantityCohort.source_goods_receipt_line_id == line.id)
    ).scalar_one()
    db_session.commit()

    # storekeeper: 403, zero side effects
    before_count = db_session.execute(
        select(func.count()).select_from(QualityDispositionEvent).where(
            QualityDispositionEvent.inventory_quantity_cohort_id == cohort.id
        )
    ).scalar_one()
    denied = client.post(
        "/quality-dispositions",
        json={
            "client_command_id": str(uuid.uuid4()), "inventory_quantity_cohort_id": str(cohort.id),
            "disposition": "RELEASED", "effective_time": NOW.isoformat(),
        },
        headers=storekeeper_headers,
    )
    assert denied.status_code == 403
    after_count = db_session.execute(
        select(func.count()).select_from(QualityDispositionEvent).where(
            QualityDispositionEvent.inventory_quantity_cohort_id == cohort.id
        )
    ).scalar_one()
    assert after_count == before_count

    # qc_officer (not the receiver): 201
    allowed = client.post(
        "/quality-dispositions",
        json={
            "client_command_id": str(uuid.uuid4()), "inventory_quantity_cohort_id": str(cohort.id),
            "disposition": "RELEASED", "effective_time": NOW.isoformat(),
        },
        headers=qc_headers,
    )
    assert allowed.status_code == 201
    assert allowed.json()["event_kind"] == "RELEASED"


@pytest.mark.integration
def test_segregation_conflict_returns_409_not_403(client, db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code=f"t-seg-{uuid.uuid4().hex[:8]}", name="Segregation HTTP Tenant")
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="seg-farm", name="Segregation Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    # A single user who is BOTH the receiver AND holds qc_officer -- proves
    # the 409 is a domain segregation conflict, never a permission denial.
    receiver_qc, receiver_qc_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="qc_officer")

    category = build_category(db_session, tenant, actor_user_id=receiver_qc.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=receiver_qc.id,
        lot_tracking_required=True, qc_release_required=True,
    )
    receipt = goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=receiver_qc.id, client_command_id=uuid.uuid4(),
        received_at=NOW, supplier_name=None, external_system=None, external_document_id=None, notes=None,
        lines=[
            GoodsReceiptLineInput(
                inventory_item_id=item.id, entered_quantity=Decimal("50"), entered_uom_id=uom_id(db_session, "kg"),
                manufacturer_name="Acme", manufacturer_lot_reference=f"LOT-{uuid.uuid4().hex[:8]}",
            )
        ],
    )
    from app.models.goods_receipt_line import GoodsReceiptLine
    from app.models.inventory_quantity_cohort import InventoryQuantityCohort

    line = db_session.execute(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
    ).scalar_one()
    cohort = db_session.execute(
        select(InventoryQuantityCohort).where(InventoryQuantityCohort.source_goods_receipt_line_id == line.id)
    ).scalar_one()
    db_session.commit()

    response = client.post(
        "/quality-dispositions",
        json={
            "client_command_id": str(uuid.uuid4()), "inventory_quantity_cohort_id": str(cohort.id),
            "disposition": "RELEASED", "effective_time": NOW.isoformat(),
        },
        headers=receiver_qc_headers,
    )
    assert response.status_code == 409
    assert "another authorized user" in response.json()["detail"]


@pytest.mark.integration
def test_correction_stale_target_returns_409_via_http(client, db_session) -> None:
    """CTO closure pass §2: a correction naming an event that is no longer
    the cohort's current decision is rejected as a 409 conflict, end to
    end through the real HTTP route -- never silently reinterpreted onto
    the newer decision."""
    tenant = tenant_service.create_tenant(db_session, code=f"t-stale-{uuid.uuid4().hex[:8]}", name="Stale Target HTTP Tenant")
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="stale-farm", name="Stale Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    receiver, _receiver_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="storekeeper")
    qc_user, qc_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="qc_officer")

    category = build_category(db_session, tenant, actor_user_id=receiver.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=receiver.id,
        lot_tracking_required=False, qc_release_required=False,
    )
    receipt = goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=receiver.id, client_command_id=uuid.uuid4(),
        received_at=NOW, supplier_name=None, external_system=None, external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("30"), entered_uom_id=uom_id(db_session, "kg"))],
    )
    from app.models.goods_receipt_line import GoodsReceiptLine
    from app.models.inventory_quantity_cohort import InventoryQuantityCohort
    from app.services import inventory_quality_service

    line = db_session.execute(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
    ).scalar_one()
    cohort = db_session.execute(
        select(InventoryQuantityCohort).where(InventoryQuantityCohort.source_goods_receipt_line_id == line.id)
    ).scalar_one()
    db_session.commit()

    # implicit RELEASED -> HELD (the event we'll (stale-)target)
    held = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=qc_user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort.id, disposition="HELD", effective_time=NOW,
    )
    stale_target_id = held.id
    # A newer decision supersedes it before the HTTP correction request arrives.
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=qc_user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort.id, disposition="REJECTED", effective_time=NOW + timedelta(minutes=1),
    )
    db_session.commit()

    response = client.post(
        "/quality-disposition-corrections",
        json={
            "client_command_id": str(uuid.uuid4()), "inventory_quantity_cohort_id": str(cohort.id),
            "target_event_id": str(stale_target_id), "reason": "attempting a stale correction",
            "effective_time": NOW.isoformat(),
        },
        headers=qc_headers,
    )
    assert response.status_code == 409
    assert "changed since you opened this action" in response.json()["detail"]
