"""STORE-INV-002A.1: direct-SQL database-integrity proofs -- append-only,
no-hard-delete, non-negative existence, the automatic opening
RECEIVED_QUARANTINED event's permanent non-reversibility, and the
current-human-event-only REVERSAL foundation, all enforced independent of
and in addition to the service layer (no such command exists yet --
STORE-INV-002A.2 scope -- so these events are inserted directly)."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.quality_disposition_event import QualityDispositionEvent
from app.services import goods_receipt_service
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_item, uom_id


def _insert_quality_event(db, *, tenant, cohort_id, actor_id, event_kind, reverses_event_id=None, reason=None):
    # Postgres `now()` is fixed for the whole transaction (== transaction
    # start), so two events inserted here would get IDENTICAL
    # effective_time/recorded_time and fall back to comparing random
    # `uuid.uuid4()` ids -- meaningless ordering. A real command computes
    # `effective_time`/`recorded_time` in Python (see `goods_receipt_
    # service`/`inventory_existence_ledger_service`), which genuinely
    # advances between statements -- `datetime.now(timezone.utc)` here
    # matches that and gives the current-event trigger real, monotonically
    # increasing timestamps to order against.
    event_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    db.execute(
        text(
            "INSERT INTO quality_disposition_events "
            "(id, tenant_id, inventory_quantity_cohort_id, event_kind, reverses_event_id, "
            " effective_time, recorded_time, actor_user_id, reason) "
            "VALUES (:id, :tenant_id, :cohort_id, :event_kind, :reverses_event_id, :effective_time, "
            " :recorded_time, :actor_id, :reason)"
        ),
        {
            "id": str(event_id), "tenant_id": str(tenant.id), "cohort_id": str(cohort_id),
            "event_kind": event_kind,
            "reverses_event_id": str(reverses_event_id) if reverses_event_id else None,
            "effective_time": now, "recorded_time": now,
            "actor_id": str(actor_id),
            "reason": reason if reason is not None else ("test" if event_kind == "REVERSAL" else None),
        },
    )
    db.flush()
    return event_id


def _receive_line(db, tenant, farm, user, item, quantity=Decimal("10")):
    receipt = goods_receipt_service.record_goods_receipt(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=quantity, entered_uom_id=uom_id(db, "kg"))],
    )
    line = db.execute(select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)).scalar_one()
    return line


@pytest.mark.integration
def test_goods_receipt_line_append_only(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    line = _receive_line(db_session, tenant, farm, user, item)

    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE goods_receipt_lines SET base_quantity = 999 WHERE id = :id"), {"id": str(line.id)}
        )
        db_session.flush()
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM goods_receipt_lines WHERE id = :id"), {"id": str(line.id)})
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_existence_ledger_entries_append_only(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    line = _receive_line(db_session, tenant, farm, user, item)

    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE inventory_existence_ledger_entries SET quantity_delta_base = 999 WHERE id = :id"),
            {"id": str(line.id)},
        )
        db_session.flush()
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM inventory_existence_ledger_entries WHERE id = :id"), {"id": str(line.id)})
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_non_negative_existence_enforced_at_db_layer(db_session, active_context_with_farm) -> None:
    """Direct-SQL bypass attempt: insert a negative adjustment entry large
    enough to drive the cohort balance below zero -- the deferred
    constraint trigger must reject it at commit, independent of the service
    layer's own pre-check."""
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    line = _receive_line(db_session, tenant, farm, user, item, quantity=Decimal("10"))

    db_session.execute(
        text(
            "INSERT INTO inventory_existence_ledger_entries "
            "(id, tenant_id, inventory_quantity_cohort_id, inventory_item_id, inventory_lot_id, "
            " receiving_farm_id, entry_kind, quantity_delta_base, effective_time, recorded_time, "
            " actor_user_id, reason) "
            "VALUES (:id, :tenant_id, :cohort_id, :item_id, NULL, :farm_id, 'adjustment', -1000, "
            " now(), now(), :actor_id, 'direct sql bypass attempt')"
        ),
        {
            "id": str(uuid.uuid4()), "tenant_id": str(tenant.id), "cohort_id": str(line.id),
            "item_id": str(item.id), "farm_id": str(farm.id), "actor_id": str(user.id),
        },
    )
    # The non-negative check is a DEFERRABLE INITIALLY DEFERRED constraint
    # trigger -- it only fires at real transaction commit. The `db_session`
    # fixture's own `commit()` merely releases a SAVEPOINT (it's bound to an
    # outer, never-really-committed transaction), so `SET CONSTRAINTS ALL
    # IMMEDIATE` is used to force the deferred check to run right here,
    # without needing a genuine top-level commit.
    with pytest.raises(DBAPIError):
        db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db_session.rollback()


@pytest.mark.integration
def test_automatic_opening_quarantine_cannot_be_reversed_at_db_layer(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id,
        lot_tracking_required=True, qc_release_required=True,
    )
    receipt = goods_receipt_service.record_goods_receipt(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
        external_document_id=None, notes=None,
        lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(db_session, "kg"))],
    )
    line = db_session.execute(select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)).scalar_one()
    opening_event = db_session.execute(
        select(QualityDispositionEvent).where(QualityDispositionEvent.inventory_quantity_cohort_id == line.id)
    ).scalar_one()
    assert opening_event.event_kind == "RECEIVED_QUARANTINED"

    with pytest.raises(DBAPIError):
        db_session.execute(
            text(
                "INSERT INTO quality_disposition_events "
                "(id, tenant_id, inventory_quantity_cohort_id, event_kind, reverses_event_id, "
                " effective_time, recorded_time, actor_user_id, reason) "
                "VALUES (:id, :tenant_id, :cohort_id, 'REVERSAL', :target_id, now(), now(), :actor_id, "
                " 'attempted bypass of the never-reversible rule')"
            ),
            {
                "id": str(uuid.uuid4()), "tenant_id": str(tenant.id), "cohort_id": str(line.id),
                "target_id": str(opening_event.id), "actor_id": str(user.id),
            },
        )
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_reversal_of_reversal_rejected_at_db_layer(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id)
    line = _receive_line(db_session, tenant, farm, user, item, quantity=Decimal("50"))

    from app.services import inventory_existence_ledger_service

    adjustment = inventory_existence_ledger_service.record_adjustment(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(), cohort_id=line.id,
        quantity_delta=Decimal("-5"), effective_time=datetime.now(timezone.utc), reason="test",
    )
    reversal = inventory_existence_ledger_service.reverse_ledger_entry(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        target_entry_id=adjustment.id, reason="undo",
    )

    with pytest.raises(DBAPIError):
        db_session.execute(
            text(
                "INSERT INTO inventory_existence_ledger_entries "
                "(id, tenant_id, inventory_quantity_cohort_id, inventory_item_id, inventory_lot_id, "
                " receiving_farm_id, entry_kind, quantity_delta_base, effective_time, recorded_time, "
                " actor_user_id, reason, reversal_of_entry_id) "
                "VALUES (:id, :tenant_id, :cohort_id, :item_id, NULL, :farm_id, 'reversal', 5, now(), now(), "
                " :actor_id, 'reversing a reversal', :target_id)"
            ),
            {
                "id": str(uuid.uuid4()), "tenant_id": str(tenant.id), "cohort_id": str(line.id),
                "item_id": str(item.id), "farm_id": str(farm.id), "actor_id": str(user.id),
                "target_id": str(reversal.id),
            },
        )
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_reversal_rejected_when_target_superseded_by_later_event_at_db_layer(
    db_session, active_context_with_farm
) -> None:
    """STORE_INVENTORY_MODEL.md §11 worked example: RECEIVED_QUARANTINED ->
    RELEASED -> HELD. A REVERSAL targeting the now-superseded RELEASED
    while HELD remains the current (latest, not-yet-reversed) disposition
    must be rejected at the DB layer -- independent of and in addition to
    the fact that `.1` exposes no route/service command that could even
    attempt it (STORE-INV-002A.2 scope)."""
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id,
        lot_tracking_required=True, qc_release_required=True,
    )
    line = _receive_line(db_session, tenant, farm, user, item)

    released_id = _insert_quality_event(
        db_session, tenant=tenant, cohort_id=line.id, actor_id=user.id, event_kind="RELEASED",
    )
    _insert_quality_event(db_session, tenant=tenant, cohort_id=line.id, actor_id=user.id, event_kind="HELD")

    with pytest.raises(DBAPIError):
        _insert_quality_event(
            db_session, tenant=tenant, cohort_id=line.id, actor_id=user.id, event_kind="REVERSAL",
            reverses_event_id=released_id, reason="attempted reversal of a superseded event",
        )
    db_session.rollback()


@pytest.mark.integration
def test_reversal_of_current_event_reexposes_prior_event_as_current_at_db_layer(
    db_session, active_context_with_farm
) -> None:
    """The mirror-image proof: reversing the actually-current HELD event
    must succeed, and doing so correctly re-exposes the earlier RELEASED
    event as current again -- a REVERSAL of RELEASED, rejected a moment ago
    while HELD stood unreversed, is now accepted."""
    tenant, user, _headers, farm = active_context_with_farm
    category = build_category(db_session, tenant, actor_user_id=user.id)
    item = build_item(
        db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=user.id,
        lot_tracking_required=True, qc_release_required=True,
    )
    line = _receive_line(db_session, tenant, farm, user, item)

    released_id = _insert_quality_event(
        db_session, tenant=tenant, cohort_id=line.id, actor_id=user.id, event_kind="RELEASED",
    )
    held_id = _insert_quality_event(db_session, tenant=tenant, cohort_id=line.id, actor_id=user.id, event_kind="HELD")

    # HELD is current (nothing later stands unreversed) -- reversing it
    # must be accepted.
    _insert_quality_event(
        db_session, tenant=tenant, cohort_id=line.id, actor_id=user.id, event_kind="REVERSAL",
        reverses_event_id=held_id, reason="mistaken hold",
    )

    # HELD is now reversed, so RELEASED is current again -- reversing it
    # must now be accepted too.
    _insert_quality_event(
        db_session, tenant=tenant, cohort_id=line.id, actor_id=user.id, event_kind="REVERSAL",
        reverses_event_id=released_id, reason="mistaken release, correcting further",
    )
