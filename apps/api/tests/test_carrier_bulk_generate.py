import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.carrier import Carrier
from app.schemas.carrier import MAX_BULK_CARRIERS, CarrierBulkCreate
from app.services import carrier_service
from app.services.errors import DuplicateCarrierCodeError
from tests.conftest import ensure_seed_tray_specification

# --- Application-level (Pydantic) validation — no DB required ---


def test_bulk_generation_above_max_rejected_before_database_writes() -> None:
    with pytest.raises(ValueError):
        CarrierBulkCreate(carrier_type_code="seed_tray", code_prefix="ST-", start=1, end=MAX_BULK_CARRIERS + 1, pad_width=5)


def test_bulk_generation_invalid_range_rejected() -> None:
    with pytest.raises(ValueError):
        CarrierBulkCreate(carrier_type_code="seed_tray", code_prefix="ST-", start=5, end=1, pad_width=5)


# --- Integration (DB) ---


@pytest.mark.integration
def test_bulk_register_20_seed_trays(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    created = carrier_service.bulk_register_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code_prefix="ST-", start=1, end=20, pad_width=5,
    )
    assert len(created) == 20
    assert {c.code for c in created} == {f"ST-{n:05d}" for n in range(1, 21)}

    audit_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "carrier.bulk_registered")
    ).scalar_one()
    assert audit_count == 1


@pytest.mark.integration
def test_bulk_carrier_collision_leaves_no_records_or_audit_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=seed_tray_spec.id, code="ST-00005", issued_date=None,
    )

    with pytest.raises(DuplicateCarrierCodeError):
        carrier_service.bulk_register_carriers(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id, code_prefix="ST-", start=1, end=10, pad_width=5,
        )

    remaining = db_session.execute(
        select(func.count()).select_from(Carrier).where(Carrier.tenant_id == tenant.id)
    ).scalar_one()
    assert remaining == 1  # only the pre-existing ST-00005

    bulk_audit_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "carrier.bulk_registered")
    ).scalar_one()
    assert bulk_audit_count == 0
