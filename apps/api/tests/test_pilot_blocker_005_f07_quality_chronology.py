"""PILOT-BLOCKER-005 F07 (extended by PILOT-BLOCKER-008 A1): Quality
effective-time chronology integrity.

Focused coverage -- naive/future/out-of-order rejection for ORDINARY
dispositions, and confirmation that corrections (explicit target-based
operations, docs/domain/STORE_INVENTORY_MODEL.md §11) share the
timezone-aware AND 30-second future-skew rules with ordinary dispositions,
but never the nondecreasing-vs-current-event ordering rule.

The ±30s boundary cases use `inventory_quality_service._now_provider`, a
monkeypatchable seam (no freezegun/fake-clock dependency exists in this
repo) -- pinning it makes both the constructed `effective_time` and the
validator's own comparison "now" derive from the same fixed value, so the
boundary proof has zero dependency on real elapsed test-execution time."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.inventory_quantity_cohort import InventoryQuantityCohort
from app.services import goods_receipt_service, inventory_quality_service
from app.services.errors import InvalidQualityEffectiveTimeError
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_item, uom_id

# Anchored in the past, not real wall-clock "now" -- the ordinary-disposition
# future check allows only a tight ~30s clock-skew window, so a bare `NOW`
# used unmodified (test_valid_current_or_newer_ordinary_disposition_accepted)
# must stay safely non-future regardless of how long earlier tests in the
# suite took to run.
NOW = datetime.now(timezone.utc) - timedelta(minutes=10)


def _receive_cohort(db_session, tenant, farm, *, actor_user_id, qc_release_required=False) -> uuid.UUID:
    category = build_category(db_session, tenant, actor_user_id=actor_user_id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=actor_user_id,
        lot_tracking_required=True, qc_release_required=qc_release_required,
    )
    receipt = goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
        received_at=NOW, supplier_name=None, external_system=None, external_document_id=None, notes=None,
        lines=[
            GoodsReceiptLineInput(
                inventory_item_id=item.id, entered_quantity=Decimal("100"), entered_uom_id=uom_id(db_session, "kg"),
                manufacturer_name="Acme", manufacturer_lot_reference=f"LOT-{uuid.uuid4().hex[:8]}",
            )
        ],
    )
    line = db_session.execute(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
    ).scalar_one()
    cohort = db_session.execute(
        select(InventoryQuantityCohort).where(InventoryQuantityCohort.source_goods_receipt_line_id == line.id)
    ).scalar_one()
    return cohort.id


@pytest.mark.integration
def test_naive_ordinary_effective_time_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    with pytest.raises(InvalidQualityEffectiveTimeError):
        inventory_quality_service.record_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, disposition="HELD", effective_time=datetime.now(),
        )


@pytest.mark.integration
def test_future_ordinary_effective_time_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    with pytest.raises(InvalidQualityEffectiveTimeError):
        inventory_quality_service.record_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, disposition="HELD", effective_time=datetime.now(timezone.utc) + timedelta(hours=1),
        )


@pytest.mark.integration
def test_ordinary_disposition_older_than_current_decision_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW,
    )
    with pytest.raises(InvalidQualityEffectiveTimeError):
        inventory_quality_service.record_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, disposition="HOLD_RELEASED", effective_time=NOW - timedelta(minutes=1),
        )


@pytest.mark.integration
def test_valid_current_or_newer_ordinary_disposition_accepted(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW,
    )
    # Equal effective_time remains legal (rule 4) -- recorded_time/id
    # ordering resolves the later command as current.
    event = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HOLD_RELEASED", effective_time=NOW,
    )
    assert event.event_kind == "HOLD_RELEASED"
    assert inventory_quality_service.resolve_current_state(
        db_session, tenant_id=tenant.id, cohort_id=cohort_id
    ) == "HOLD_RELEASED"


@pytest.mark.integration
def test_correction_chronology_preserves_existing_target_based_semantics(db_session, active_context_with_farm) -> None:
    """Corrections stay explicit target-based operations (§11) -- a
    correction's effective_time is never compared against "current" the way
    an ordinary disposition's is; only the timezone-aware rule applies."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    held = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW,
    )
    # A naive correction effective_time is still rejected (rule 1 applies
    # everywhere)...
    with pytest.raises(InvalidQualityEffectiveTimeError):
        inventory_quality_service.correct_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, target_event_id=held.id, reason="placed on hold by mistake",
            replacement_disposition=None, effective_time=datetime.now(),
        )
    # ...but a tz-aware correction effective_time earlier than "now" (an
    # ordinary disposition would never be allowed to do this) is still
    # legal -- existing documented correction semantics are preserved
    # unchanged.
    reversal, replacement = inventory_quality_service.correct_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, target_event_id=held.id, reason="placed on hold by mistake",
        replacement_disposition=None, effective_time=NOW - timedelta(days=1),
    )
    assert reversal.event_kind == "REVERSAL"
    assert replacement is None


@pytest.mark.integration
def test_current_time_correction_accepted(db_session, active_context_with_farm) -> None:
    """PILOT-BLOCKER-008 A1: a correction at (approximately) the current
    instant is accepted -- ordinary real-clock now, comfortably inside the
    30s tolerance regardless of test execution latency."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    held = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW,
    )
    reversal, replacement = inventory_quality_service.correct_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, target_event_id=held.id, reason="current-time correction",
        replacement_disposition=None, effective_time=datetime.now(timezone.utc),
    )
    assert reversal.event_kind == "REVERSAL"
    assert replacement is None


@pytest.mark.integration
def test_correction_at_exact_30s_future_boundary_accepted(
    db_session, active_context_with_farm, monkeypatch,
) -> None:
    """PILOT-BLOCKER-008 A1: effective_time == now + 30s is accepted (rule
    is `<=`, not `<`). Pins `_now_provider` so the comparison "now" is the
    exact same fixed value the test constructs `effective_time` from --
    no real-clock race with validator execution."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    held = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW,
    )
    fixed_now = datetime.now(timezone.utc)
    monkeypatch.setattr(inventory_quality_service, "_now_provider", lambda tz: fixed_now)
    reversal, replacement = inventory_quality_service.correct_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, target_event_id=held.id, reason="exact 30s boundary",
        replacement_disposition=None, effective_time=fixed_now + timedelta(seconds=30),
    )
    assert reversal.event_kind == "REVERSAL"
    assert replacement is None


@pytest.mark.integration
def test_correction_just_beyond_30s_future_boundary_rejected(
    db_session, active_context_with_farm, monkeypatch,
) -> None:
    """PILOT-BLOCKER-008 A1: effective_time == now + 30s + 1 microsecond is
    rejected -- the smallest possible margin beyond the boundary, made safe
    by pinning `_now_provider` rather than racing real elapsed time."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    held = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW,
    )
    fixed_now = datetime.now(timezone.utc)
    monkeypatch.setattr(inventory_quality_service, "_now_provider", lambda tz: fixed_now)
    with pytest.raises(InvalidQualityEffectiveTimeError):
        inventory_quality_service.correct_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, target_event_id=held.id, reason="just beyond boundary",
            replacement_disposition=None,
            effective_time=fixed_now + timedelta(seconds=30, microseconds=1),
        )


@pytest.mark.integration
def test_grossly_future_correction_rejected(db_session, active_context_with_farm) -> None:
    """PILOT-BLOCKER-008 A1: a correction cannot be used to schedule a
    future Quality decision -- GrowCMP has no scheduled-decision model."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    held = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW,
    )
    with pytest.raises(InvalidQualityEffectiveTimeError):
        inventory_quality_service.correct_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, target_event_id=held.id, reason="grossly future",
            replacement_disposition=None,
            effective_time=datetime.now(timezone.utc) + timedelta(days=1),
        )


@pytest.mark.integration
def test_partial_correction_future_rule_matches_full_correction(
    db_session, active_context_with_farm, monkeypatch,
) -> None:
    """PILOT-BLOCKER-008 A1: `correct_quality_disposition_for_partial_
    quantity` shares the exact same future-skew rule as whole-cohort
    correction -- accepted at the 30s boundary, rejected just beyond it,
    rejected when grossly future."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    rejected_event_id = inventory_quality_service.resolve_current_event(
        db_session, tenant_id=tenant.id, cohort_id=cohort_id,
    ).id

    fixed_now = datetime.now(timezone.utc)
    monkeypatch.setattr(inventory_quality_service, "_now_provider", lambda tz: fixed_now)

    # Accepted at the exact 30s boundary.
    child = inventory_quality_service.correct_quality_disposition_for_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_cohort_id=cohort_id, target_event_id=rejected_event_id, quantity=Decimal("10"),
        corrected_disposition="RELEASED", reason="partial boundary accepted",
        effective_time=fixed_now + timedelta(seconds=30),
    )
    assert child.id is not None

    # Rejected just beyond the boundary.
    with pytest.raises(InvalidQualityEffectiveTimeError):
        inventory_quality_service.correct_quality_disposition_for_partial_quantity(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            source_cohort_id=cohort_id, target_event_id=rejected_event_id, quantity=Decimal("10"),
            corrected_disposition="RELEASED", reason="partial just beyond boundary",
            effective_time=fixed_now + timedelta(seconds=30, microseconds=1),
        )

    # Rejected when grossly future.
    with pytest.raises(InvalidQualityEffectiveTimeError):
        inventory_quality_service.correct_quality_disposition_for_partial_quantity(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            source_cohort_id=cohort_id, target_event_id=rejected_event_id, quantity=Decimal("10"),
            corrected_disposition="RELEASED", reason="partial grossly future",
            effective_time=fixed_now + timedelta(days=1),
        )
