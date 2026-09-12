"""STORE-INV-002A.2 CTO closure pass: quality disposition state machine,
command-level idempotency, stale-target correction, segregation-of-duties
(scoped to `qc_release_required`), partial-quantity disposition, partial
CORRECTION, and the usable-existence read model."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.inventory_quality_command import InventoryQualityCommand
from app.models.inventory_quantity_cohort import InventoryQuantityCohort
from app.models.quality_disposition_event import QualityDispositionEvent
from app.services import goods_receipt_service, inventory_quality_service, user_service
from app.services.errors import (
    InvalidQualityDispositionTransitionError,
    InventoryQuantityCohortSplitAllocationExceedsBalanceError,
    QualityCorrectionCommandReusedWithDifferentPayloadError,
    QualityCorrectionTargetNotCurrentError,
    QualityDispositionCommandReusedWithDifferentPayloadError,
    QualityDispositionEventNotFoundError,
    QualityDispositionNoCurrentHumanDecisionError,
    QualityPartialCorrectionCommandReusedWithDifferentPayloadError,
    QualityPartialDispositionCommandReusedWithDifferentPayloadError,
    QualitySegregationOfDutiesError,
)
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_item, uom_id

# PILOT-BLOCKER-005 F07: anchored an hour in the past, not real wall-clock
# "now" -- ordinary Quality dispositions now reject a future effective_time
# (a tight ~30s clock-skew allowance only), so a fixed module-level "now"
# plus forward minute offsets (used throughout this file purely to establish
# a deterministic event order) must never be able to drift into the future
# relative to actual wall-clock time by the time a given test runs. Every
# `NOW + timedelta(minutes=N)` below stays comfortably in the past; only the
# relative ordering between events (what these tests actually assert on)
# matters, never the absolute anchor.
NOW = datetime.now(timezone.utc) - timedelta(hours=1)


def _receive_cohort(
    db_session, tenant, farm, *, actor_user_id, qc_release_required=True, quantity=Decimal("500")
) -> tuple[uuid.UUID, uuid.UUID]:
    """Returns (cohort_id, received_by_user_id)."""
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
                inventory_item_id=item.id, entered_quantity=quantity, entered_uom_id=uom_id(db_session, "kg"),
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
    return cohort.id, receipt.received_by_user_id


def _other_user(db_session, suffix: str):
    return user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"other-{suffix}-{uuid.uuid4().hex[:6]}",
        email=f"other-{suffix}-{uuid.uuid4().hex[:6]}@example.com", display_name="Other User",
    )


def _current_event_id(db_session, tenant, cohort_id) -> uuid.UUID:
    event = inventory_quality_service.resolve_current_event(db_session, tenant_id=tenant.id, cohort_id=cohort_id)
    assert event is not None
    return event.id


# --- State machine -----------------------------------------------------------


@pytest.mark.integration
def test_quarantine_to_released_by_other_actor(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    other = _other_user(db_session, "a")
    event = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="RELEASED", effective_time=NOW,
    )
    assert event.event_kind == "RELEASED"
    assert inventory_quality_service.resolve_current_state(db_session, tenant_id=tenant.id, cohort_id=cohort_id) == "RELEASED"


@pytest.mark.integration
@pytest.mark.parametrize(
    "path",
    [
        ["RELEASED", "HELD"],
        ["RELEASED", "REJECTED"],
        ["HELD", "HOLD_RELEASED"],
        ["HELD", "REJECTED"],
        ["HELD", "HOLD_RELEASED", "HELD"],
        ["HELD", "HOLD_RELEASED", "REJECTED"],
    ],
)
def test_legal_transition_chains(db_session, active_context_with_farm, path) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    other = _other_user(db_session, "chain")
    for i, disposition in enumerate(path):
        actor = other.id if disposition in ("RELEASED", "HOLD_RELEASED") else user.id
        inventory_quality_service.record_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=actor, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, disposition=disposition, effective_time=NOW + timedelta(minutes=i + 1),
        )
    assert inventory_quality_service.resolve_current_state(db_session, tenant_id=tenant.id, cohort_id=cohort_id) == path[-1]


@pytest.mark.integration
def test_implicit_released_reachable_hold_and_reject_directly(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False)
    assert inventory_quality_service.resolve_current_state(db_session, tenant_id=tenant.id, cohort_id=cohort_id) == "RELEASED"
    event = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW,
    )
    assert event.event_kind == "HELD"


@pytest.mark.integration
def test_rejected_is_ordinarily_terminal(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False)
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    with pytest.raises(InvalidQualityDispositionTransitionError):
        inventory_quality_service.record_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, disposition="RELEASED", effective_time=NOW + timedelta(minutes=1),
        )


@pytest.mark.integration
def test_quarantine_cannot_skip_to_hold_release(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    with pytest.raises(InvalidQualityDispositionTransitionError):
        inventory_quality_service.record_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, disposition="HOLD_RELEASED", effective_time=NOW,
        )


# --- Segregation of duties (CTO closure pass §4: scoped to qc_release_required) --


@pytest.mark.integration
def test_qc_required_receiver_cannot_release_own_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=True)
    assert receiver_id == user.id
    with pytest.raises(QualitySegregationOfDutiesError):
        inventory_quality_service.record_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, disposition="RELEASED", effective_time=NOW,
        )


@pytest.mark.integration
def test_qc_required_receiver_cannot_hold_release_own_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=True)
    other = _other_user(db_session, "hr")
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="RELEASED", effective_time=NOW,
    )
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW + timedelta(minutes=1),
    )
    with pytest.raises(QualitySegregationOfDutiesError):
        inventory_quality_service.record_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, disposition="HOLD_RELEASED", effective_time=NOW + timedelta(minutes=2),
        )


@pytest.mark.integration
def test_different_qc_actor_can_release(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=True)
    other = _other_user(db_session, "diff")
    event = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="RELEASED", effective_time=NOW,
    )
    assert event.event_kind == "RELEASED"
    assert other.id != receiver_id


@pytest.mark.integration
def test_qc_required_receiver_can_hold_and_reject_own_receipt(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=True)
    event = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW,
    )
    assert event.event_kind == "HELD"
    event2 = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW + timedelta(minutes=1),
    )
    assert event2.event_kind == "REJECTED"


@pytest.mark.integration
def test_non_qc_material_never_restricts_receivers_own_release(db_session, active_context_with_farm) -> None:
    """The frozen rule is anchored to `qc_release_required = true` only
    (docs/domain/STORE_INVENTORY_MODEL.md §11). A non-QC item's own
    receiver may freely place it on Hold and later Hold-Release/Release it
    themselves -- even though `inventory_quality.manage` is what lets them
    act at all, segregation itself never applies here."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False)
    assert receiver_id == user.id
    # Non-QC material starts implicit RELEASED -- exercise Hold then
    # Hold-Release, both by the receiver, to prove no restriction applies
    # to either the ordinary RELEASED-reachable-implicitly state or the
    # explicit HOLD_RELEASED transition.
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW,
    )
    event = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HOLD_RELEASED", effective_time=NOW + timedelta(minutes=1),
    )
    assert event.event_kind == "HOLD_RELEASED"


@pytest.mark.integration
def test_prior_qc_actor_who_is_not_receiver_may_grant_usability(db_session, active_context_with_farm) -> None:
    """The check is anchored to the ORIGINAL RECEIVER only -- an actor who
    merely placed a prior (now-corrected) disposition, but is not the
    receiver, may still grant usability."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=True)
    qc_actor_1 = _other_user(db_session, "qc1")
    qc_actor_2 = _other_user(db_session, "qc2")
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=qc_actor_1.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW,
    )
    event = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=qc_actor_2.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HOLD_RELEASED", effective_time=NOW + timedelta(minutes=1),
    )
    assert event.event_kind == "HOLD_RELEASED"


# --- Correction (target_event_id required, stale-target rejected) -----------


@pytest.mark.integration
def test_correct_current_human_event_falls_through_to_predecessor(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=True)
    other = _other_user(db_session, "corr1")
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="RELEASED", effective_time=NOW,
    )
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW + timedelta(minutes=1),
    )
    held_event_id = _current_event_id(db_session, tenant, cohort_id)
    reversal, replacement = inventory_quality_service.correct_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, target_event_id=held_event_id, reason="placed on hold by mistake",
        replacement_disposition=None, effective_time=NOW + timedelta(minutes=2),
    )
    assert reversal.event_kind == "REVERSAL"
    assert replacement is None
    assert inventory_quality_service.resolve_current_state(db_session, tenant_id=tenant.id, cohort_id=cohort_id) == "RELEASED"


@pytest.mark.integration
def test_correct_with_replacement_atomic(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False)
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    rejected_event_id = _current_event_id(db_session, tenant, cohort_id)
    other = _other_user(db_session, "corr2")
    reversal, replacement = inventory_quality_service.correct_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, target_event_id=rejected_event_id, reason="mistaken reject, should be held pending review",
        replacement_disposition="HELD", effective_time=NOW + timedelta(minutes=1),
    )
    assert reversal.event_kind == "REVERSAL"
    assert replacement is not None and replacement.event_kind == "HELD"
    assert inventory_quality_service.resolve_current_state(db_session, tenant_id=tenant.id, cohort_id=cohort_id) == "HELD"


@pytest.mark.integration
def test_correction_usable_result_enforces_segregation_when_qc_required(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=True)
    other = _other_user(db_session, "seg-corr")
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="RELEASED", effective_time=NOW,
    )
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW + timedelta(minutes=1),
    )
    rejected_event_id = _current_event_id(db_session, tenant, cohort_id)
    with pytest.raises(QualitySegregationOfDutiesError):
        inventory_quality_service.correct_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=receiver_id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, target_event_id=rejected_event_id, reason="reject was a mistake",
            replacement_disposition=None, effective_time=NOW + timedelta(minutes=2),
        )


@pytest.mark.integration
def test_correction_usable_result_unrestricted_when_not_qc_required(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False)
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    rejected_event_id = _current_event_id(db_session, tenant, cohort_id)
    reversal, _replacement = inventory_quality_service.correct_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=receiver_id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, target_event_id=rejected_event_id, reason="reject was a mistake",
        replacement_disposition=None, effective_time=NOW + timedelta(minutes=1),
    )
    assert reversal.event_kind == "REVERSAL"


@pytest.mark.integration
def test_correction_cannot_target_opening_quarantine(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id)
    quarantine_event_id = _current_event_id(db_session, tenant, cohort_id)
    with pytest.raises(QualityDispositionNoCurrentHumanDecisionError):
        inventory_quality_service.correct_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, target_event_id=quarantine_event_id, reason="should not be quarantined",
            replacement_disposition=None, effective_time=NOW,
        )


@pytest.mark.integration
def test_correction_targeting_superseded_event_is_stale(db_session, active_context_with_farm) -> None:
    """A caller who observed an OLDER event (e.g. via a stale cached
    work-queue row) and attempts to correct it after a newer decision has
    since been recorded is rejected as stale -- never silently
    reinterpreted onto the newer decision."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=True)
    other = _other_user(db_session, "stale")
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="RELEASED", effective_time=NOW,
    )
    released_event_id = _current_event_id(db_session, tenant, cohort_id)
    # A newer decision supersedes it before the correction is attempted.
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW + timedelta(minutes=1),
    )
    with pytest.raises(QualityCorrectionTargetNotCurrentError):
        inventory_quality_service.correct_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, target_event_id=released_event_id, reason="stale attempt",
            replacement_disposition=None, effective_time=NOW + timedelta(minutes=2),
        )


@pytest.mark.integration
def test_correction_unknown_target_event_not_found(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=True)
    other = _other_user(db_session, "notfound")
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="RELEASED", effective_time=NOW,
    )
    with pytest.raises(QualityDispositionEventNotFoundError):
        inventory_quality_service.correct_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, target_event_id=uuid.uuid4(), reason="bogus target",
            replacement_disposition=None, effective_time=NOW + timedelta(minutes=1),
        )


@pytest.mark.integration
def test_correction_target_from_different_cohort_not_found(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_a, _r1 = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=True)
    cohort_b, _r2 = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=True)
    other = _other_user(db_session, "crosscohort")
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_a, disposition="RELEASED", effective_time=NOW,
    )
    event_from_a = _current_event_id(db_session, tenant, cohort_a)
    with pytest.raises(QualityDispositionEventNotFoundError):
        inventory_quality_service.correct_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_b, target_event_id=event_from_a, reason="wrong cohort",
            replacement_disposition=None, effective_time=NOW + timedelta(minutes=1),
        )


# --- Partial-quantity disposition ----------------------------------------------


@pytest.mark.integration
def test_partial_disposition_worked_example_a(db_session, active_context_with_farm) -> None:
    """500 kg RECEIVED_QUARANTINED -> 450 Released / 50 Rejected. Exists=500, Usable=450."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, quantity=Decimal("500"))
    other = _other_user(db_session, "partial-a")

    item_id = db_session.execute(
        select(InventoryQuantityCohort.inventory_item_id).where(InventoryQuantityCohort.id == cohort_id)
    ).scalar_one()

    inventory_quality_service.apply_quality_disposition_to_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        source_cohort_id=cohort_id, quantity=Decimal("450"), disposition="RELEASED", effective_time=NOW,
        reason="450kg inspected and released",
    )
    inventory_quality_service.apply_quality_disposition_to_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_cohort_id=cohort_id, quantity=Decimal("50"), disposition="REJECTED",
        effective_time=NOW + timedelta(minutes=1), reason="50kg damaged",
    )

    from app.services.inventory_existence_read_service import get_item_existence

    exists = get_item_existence(db_session, tenant_id=tenant.id, inventory_item_id=item_id)
    usable = inventory_quality_service.get_item_usable_existence(db_session, tenant_id=tenant.id, inventory_item_id=item_id)
    assert exists == Decimal("500.000")
    assert usable == Decimal("450.000")


@pytest.mark.integration
def test_partial_disposition_worked_example_b(db_session, active_context_with_farm) -> None:
    """500 kg already RELEASED -> partial 100kg Hold. Remainder 400 Released, 100 Held. Usable=400."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(
        db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False, quantity=Decimal("500")
    )
    item_id = db_session.execute(
        select(InventoryQuantityCohort.inventory_item_id).where(InventoryQuantityCohort.id == cohort_id)
    ).scalar_one()

    inventory_quality_service.apply_quality_disposition_to_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_cohort_id=cohort_id, quantity=Decimal("100"), disposition="HELD", effective_time=NOW,
        reason="suspect quantity",
    )
    assert inventory_quality_service.resolve_current_state(db_session, tenant_id=tenant.id, cohort_id=cohort_id) == "RELEASED"
    usable = inventory_quality_service.get_item_usable_existence(db_session, tenant_id=tenant.id, inventory_item_id=item_id)
    assert usable == Decimal("400.000")


@pytest.mark.integration
def test_partial_disposition_over_allocation_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(
        db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False, quantity=Decimal("100")
    )
    with pytest.raises(InventoryQuantityCohortSplitAllocationExceedsBalanceError):
        inventory_quality_service.apply_quality_disposition_to_partial_quantity(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            source_cohort_id=cohort_id, quantity=Decimal("150"), disposition="HELD", effective_time=NOW,
        )


@pytest.mark.integration
def test_partial_disposition_idempotent_replay_no_duplicate_children(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(
        db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False, quantity=Decimal("100")
    )
    command_id = uuid.uuid4()
    child1 = inventory_quality_service.apply_quality_disposition_to_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        source_cohort_id=cohort_id, quantity=Decimal("30"), disposition="HELD", effective_time=NOW,
        reason="replay-test",
    )
    child2 = inventory_quality_service.apply_quality_disposition_to_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        source_cohort_id=cohort_id, quantity=Decimal("30"), disposition="HELD", effective_time=NOW,
        reason="replay-test",
    )
    assert child1.id == child2.id
    children = db_session.execute(
        select(InventoryQuantityCohort).where(InventoryQuantityCohort.parent_cohort_id == cohort_id)
    ).scalars().all()
    assert len(children) == 1


@pytest.mark.integration
def test_partial_disposition_rejected_source_has_no_forward_transition(db_session, active_context_with_farm) -> None:
    """Phase 9's frozen terminal-state rule holds for ordinary partial
    actions too -- REJECTED -> RELEASED is only ever reachable via the
    dedicated `PARTIAL_CORRECT` command, never the ordinary partial
    disposition path."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(
        db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False, quantity=Decimal("100")
    )
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    with pytest.raises(InvalidQualityDispositionTransitionError):
        inventory_quality_service.apply_quality_disposition_to_partial_quantity(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            source_cohort_id=cohort_id, quantity=Decimal("10"), disposition="RELEASED",
            effective_time=NOW + timedelta(minutes=1),
        )


# --- Partial CORRECTION ("Correct decision for part of quantity") -----------


@pytest.mark.integration
def test_partial_correction_worked_example(db_session, active_context_with_farm) -> None:
    """100 kg currently REJECTED; 20 kg was wrongly rejected. Correct
    decision for part: quantity=20, corrected=RELEASED. Result: 80 kg
    source remains REJECTED, 20 kg child carries corrected RELEASED truth,
    existence stays 100, usable becomes 20."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(
        db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False, quantity=Decimal("100")
    )
    item_id = db_session.execute(
        select(InventoryQuantityCohort.inventory_item_id).where(InventoryQuantityCohort.id == cohort_id)
    ).scalar_one()
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    rejected_event_id = _current_event_id(db_session, tenant, cohort_id)

    child = inventory_quality_service.correct_quality_disposition_for_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_cohort_id=cohort_id, target_event_id=rejected_event_id, quantity=Decimal("20"),
        corrected_disposition="RELEASED", reason="20kg wrongly rejected", effective_time=NOW + timedelta(minutes=1),
    )

    assert inventory_quality_service.resolve_current_state(db_session, tenant_id=tenant.id, cohort_id=cohort_id) == "REJECTED"
    assert inventory_quality_service.resolve_current_state(db_session, tenant_id=tenant.id, cohort_id=child.id) == "RELEASED"

    from app.services.inventory_existence_ledger_service import get_cohort_balance
    from app.services.inventory_existence_read_service import get_item_existence

    assert get_cohort_balance(db_session, cohort_id=cohort_id) == Decimal("80.000")
    assert get_cohort_balance(db_session, cohort_id=child.id) == Decimal("20.000")
    assert get_item_existence(db_session, tenant_id=tenant.id, inventory_item_id=item_id) == Decimal("100.000")
    usable = inventory_quality_service.get_item_usable_existence(db_session, tenant_id=tenant.id, inventory_item_id=item_id)
    assert usable == Decimal("20.000")


@pytest.mark.integration
def test_partial_correction_idempotent_replay_no_duplicate_child(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(
        db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False, quantity=Decimal("100")
    )
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    rejected_event_id = _current_event_id(db_session, tenant, cohort_id)
    command_id = uuid.uuid4()

    child1 = inventory_quality_service.correct_quality_disposition_for_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        source_cohort_id=cohort_id, target_event_id=rejected_event_id, quantity=Decimal("20"),
        corrected_disposition="RELEASED", reason="replay test", effective_time=NOW + timedelta(minutes=1),
    )
    child2 = inventory_quality_service.correct_quality_disposition_for_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        source_cohort_id=cohort_id, target_event_id=rejected_event_id, quantity=Decimal("20"),
        corrected_disposition="RELEASED", reason="replay test", effective_time=NOW + timedelta(minutes=1),
    )
    assert child1.id == child2.id
    children = db_session.execute(
        select(InventoryQuantityCohort).where(InventoryQuantityCohort.parent_cohort_id == cohort_id)
    ).scalars().all()
    assert len(children) == 1


@pytest.mark.integration
def test_partial_correction_repeatable_against_same_stable_target(db_session, active_context_with_farm) -> None:
    """Unlike whole-cohort CORRECT, the SAME target_event_id may
    legitimately be the target of more than one PARTIAL_CORRECT command
    over time -- the source's own current event never changes as a result
    of this command (Phase 8 Example C precedent: discovering more
    quantity needs correcting later, against the same stable source
    classification)."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(
        db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False, quantity=Decimal("100")
    )
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    rejected_event_id = _current_event_id(db_session, tenant, cohort_id)

    inventory_quality_service.correct_quality_disposition_for_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_cohort_id=cohort_id, target_event_id=rejected_event_id, quantity=Decimal("20"),
        corrected_disposition="RELEASED", reason="first correction", effective_time=NOW + timedelta(minutes=1),
    )
    # source's own current event is still the same REJECTED event
    assert _current_event_id(db_session, tenant, cohort_id) == rejected_event_id

    second_child = inventory_quality_service.correct_quality_disposition_for_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_cohort_id=cohort_id, target_event_id=rejected_event_id, quantity=Decimal("15"),
        corrected_disposition="RELEASED", reason="second correction", effective_time=NOW + timedelta(minutes=2),
    )
    assert second_child.id is not None

    from app.services.inventory_existence_ledger_service import get_cohort_balance

    assert get_cohort_balance(db_session, cohort_id=cohort_id) == Decimal("65.000")


@pytest.mark.integration
def test_partial_correction_cannot_target_opening_quarantine(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, quantity=Decimal("100"))
    quarantine_event_id = _current_event_id(db_session, tenant, cohort_id)
    with pytest.raises(QualityDispositionNoCurrentHumanDecisionError):
        inventory_quality_service.correct_quality_disposition_for_partial_quantity(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            source_cohort_id=cohort_id, target_event_id=quarantine_event_id, quantity=Decimal("10"),
            corrected_disposition="RELEASED", reason="cannot correct opening quarantine", effective_time=NOW,
        )


@pytest.mark.integration
def test_partial_correction_stale_target_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(
        db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False, quantity=Decimal("100")
    )
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    rejected_event_id = _current_event_id(db_session, tenant, cohort_id)
    other = _other_user(db_session, "partial-stale")
    inventory_quality_service.correct_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, target_event_id=rejected_event_id, reason="whole-cohort correction supersedes",
        replacement_disposition="HELD", effective_time=NOW + timedelta(minutes=1),
    )
    with pytest.raises(QualityCorrectionTargetNotCurrentError):
        inventory_quality_service.correct_quality_disposition_for_partial_quantity(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            source_cohort_id=cohort_id, target_event_id=rejected_event_id, quantity=Decimal("10"),
            corrected_disposition="RELEASED", reason="now stale", effective_time=NOW + timedelta(minutes=2),
        )


@pytest.mark.integration
def test_partial_correction_segregation_enforced_when_qc_required(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=True)
    other = _other_user(db_session, "partial-seg")
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    rejected_event_id = _current_event_id(db_session, tenant, cohort_id)
    with pytest.raises(QualitySegregationOfDutiesError):
        inventory_quality_service.correct_quality_disposition_for_partial_quantity(
            db_session, tenant_id=tenant.id, actor_user_id=receiver_id, client_command_id=uuid.uuid4(),
            source_cohort_id=cohort_id, target_event_id=rejected_event_id, quantity=Decimal("10"),
            corrected_disposition="RELEASED", reason="receiver cannot self-release", effective_time=NOW + timedelta(minutes=1),
        )


# --- Idempotency (command-level) ------------------------------------------------


@pytest.mark.integration
def test_a_same_command_same_payload_same_cohort_is_one_logical_command(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False)
    command_id = uuid.uuid4()
    e1 = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW, reason="r",
    )
    e2 = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW, reason="r",
    )
    assert e1.id == e2.id
    command_count = db_session.execute(
        select(InventoryQualityCommand).where(InventoryQualityCommand.client_command_id == command_id)
    ).scalars().all()
    assert len(command_count) == 1


@pytest.mark.integration
def test_c_same_command_different_payload_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False)
    command_id = uuid.uuid4()
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW, reason="r",
    )
    with pytest.raises(QualityDispositionCommandReusedWithDifferentPayloadError):
        inventory_quality_service.record_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
            cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW, reason="r",
        )


@pytest.mark.integration
def test_d_correction_with_reversal_and_replacement_is_one_logical_command(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False)
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    rejected_event_id = _current_event_id(db_session, tenant, cohort_id)
    command_id = uuid.uuid4()

    reversal, replacement = inventory_quality_service.correct_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        cohort_id=cohort_id, target_event_id=rejected_event_id, reason="mistake",
        replacement_disposition="HELD", effective_time=NOW + timedelta(minutes=1),
    )
    assert replacement is not None

    commands = db_session.execute(
        select(InventoryQualityCommand).where(InventoryQualityCommand.client_command_id == command_id)
    ).scalars().all()
    assert len(commands) == 1
    events = db_session.execute(
        select(QualityDispositionEvent).where(QualityDispositionEvent.command_id == commands[0].id)
    ).scalars().all()
    assert {e.id for e in events} == {reversal.id, replacement.id}


@pytest.mark.integration
def test_e_replay_of_correction_creates_no_second_reversal_or_replacement(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False)
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    rejected_event_id = _current_event_id(db_session, tenant, cohort_id)
    command_id = uuid.uuid4()

    first_reversal, first_replacement = inventory_quality_service.correct_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        cohort_id=cohort_id, target_event_id=rejected_event_id, reason="mistake",
        replacement_disposition="HELD", effective_time=NOW + timedelta(minutes=1),
    )
    second_reversal, second_replacement = inventory_quality_service.correct_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        cohort_id=cohort_id, target_event_id=rejected_event_id, reason="mistake",
        replacement_disposition="HELD", effective_time=NOW + timedelta(minutes=1),
    )
    assert first_reversal.id == second_reversal.id
    assert first_replacement is not None and second_replacement is not None
    assert first_replacement.id == second_replacement.id

    reversal_count = db_session.execute(
        select(QualityDispositionEvent).where(
            QualityDispositionEvent.reverses_event_id == rejected_event_id,
        )
    ).scalars().all()
    assert len(reversal_count) == 1


@pytest.mark.integration
def test_correction_command_reused_with_different_payload_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False)
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=NOW,
    )
    held_event_id = _current_event_id(db_session, tenant, cohort_id)
    command_id = uuid.uuid4()
    inventory_quality_service.correct_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        cohort_id=cohort_id, target_event_id=held_event_id, reason="mistake", replacement_disposition=None,
        effective_time=NOW + timedelta(minutes=1),
    )
    with pytest.raises(QualityCorrectionCommandReusedWithDifferentPayloadError):
        inventory_quality_service.correct_quality_disposition(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
            cohort_id=cohort_id, target_event_id=held_event_id, reason="different reason",
            replacement_disposition=None, effective_time=NOW + timedelta(minutes=1),
        )


@pytest.mark.integration
def test_partial_disposition_command_reused_with_different_payload_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(
        db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False, quantity=Decimal("100")
    )
    command_id = uuid.uuid4()
    inventory_quality_service.apply_quality_disposition_to_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        source_cohort_id=cohort_id, quantity=Decimal("10"), disposition="HELD", effective_time=NOW,
    )
    with pytest.raises(QualityPartialDispositionCommandReusedWithDifferentPayloadError):
        inventory_quality_service.apply_quality_disposition_to_partial_quantity(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
            source_cohort_id=cohort_id, quantity=Decimal("20"), disposition="HELD", effective_time=NOW,
        )


@pytest.mark.integration
def test_partial_correction_command_reused_with_different_payload_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(
        db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False, quantity=Decimal("100")
    )
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=NOW,
    )
    rejected_event_id = _current_event_id(db_session, tenant, cohort_id)
    command_id = uuid.uuid4()
    inventory_quality_service.correct_quality_disposition_for_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
        source_cohort_id=cohort_id, target_event_id=rejected_event_id, quantity=Decimal("10"),
        corrected_disposition="RELEASED", reason="r", effective_time=NOW + timedelta(minutes=1),
    )
    with pytest.raises(QualityPartialCorrectionCommandReusedWithDifferentPayloadError):
        inventory_quality_service.correct_quality_disposition_for_partial_quantity(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=command_id,
            source_cohort_id=cohort_id, target_event_id=rejected_event_id, quantity=Decimal("20"),
            corrected_disposition="RELEASED", reason="r", effective_time=NOW + timedelta(minutes=1),
        )


# --- Usable existence ----------------------------------------------------------


@pytest.mark.integration
def test_usable_existence_excludes_quarantined_held_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, quantity=Decimal("200"))
    item_id = db_session.execute(
        select(InventoryQuantityCohort.inventory_item_id).where(InventoryQuantityCohort.id == cohort_id)
    ).scalar_one()
    assert inventory_quality_service.get_item_usable_existence(db_session, tenant_id=tenant.id, inventory_item_id=item_id) == Decimal("0")

    other = _other_user(db_session, "usable")
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="RELEASED", effective_time=NOW,
    )
    assert inventory_quality_service.get_item_usable_existence(db_session, tenant_id=tenant.id, inventory_item_id=item_id) == Decimal("200.000")


@pytest.mark.integration
def test_usable_existence_company_wide_across_farms(db_session, active_context) -> None:
    from app.services import farm_service

    tenant, user, _headers = active_context
    farm_a = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="farm-a", name="Farm A",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    farm_b = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code="farm-b", name="Farm B",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id,
        lot_tracking_required=False, qc_release_required=False,
    )
    for farm in (farm_a, farm_b):
        goods_receipt_service.record_goods_receipt(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            received_at=NOW, supplier_name=None, external_system=None, external_document_id=None, notes=None,
            lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("50"), entered_uom_id=uom_id(db_session, "kg"))],
        )
    usable = inventory_quality_service.get_item_usable_existence(db_session, tenant_id=tenant.id, inventory_item_id=item.id)
    assert usable == Decimal("100.000")


# --- Quality work queue ---------------------------------------------------------


@pytest.mark.integration
def test_quality_work_queue_lists_positive_balance_cohorts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(db_session, tenant, farm, actor_user_id=user.id, quantity=Decimal("77"))
    rows = inventory_quality_service.list_quality_work_queue(db_session, tenant_id=tenant.id)
    matching = [r for r in rows if r["inventory_quantity_cohort_id"] == cohort_id]
    assert len(matching) == 1
    assert matching[0]["current_state"] == "RECEIVED_QUARANTINED"
    assert matching[0]["balance"] == Decimal("77.000")
    assert matching[0]["current_event_id"] is not None


@pytest.mark.integration
def test_quality_work_queue_excludes_zero_balance_source_after_full_split(db_session, active_context_with_farm) -> None:
    """A source cohort left at exactly zero balance after a full split
    must not remain as operator QC work -- only the child (which holds the
    actual positive balance) does."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id, _receiver_id = _receive_cohort(
        db_session, tenant, farm, actor_user_id=user.id, qc_release_required=False, quantity=Decimal("40")
    )
    child = inventory_quality_service.apply_quality_disposition_to_partial_quantity(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_cohort_id=cohort_id, quantity=Decimal("40"), disposition="HELD", effective_time=NOW,
        reason="full split to held",
    )
    rows = inventory_quality_service.list_quality_work_queue(db_session, tenant_id=tenant.id)
    ids = {r["inventory_quantity_cohort_id"] for r in rows}
    assert cohort_id not in ids
    assert child.id in ids
