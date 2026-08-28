"""POSTHARVEST-OPS-001H: whole-event reversal of a PackingEvent -- never a
field-by-field correction. Restores every source GradedProduceLot's
ledger balance by exactly the quantity `packing_consumption` debited, and
neutralizes the FinishedGoodsLot's opening quantity.

PRE-COMMIT AUDIT: the downstream gate never infers safety from a live/net
balance. It is two independent, unconditional checks: (1) the
finished-goods ledger carries no entry beyond the lot's own
`packing_receipt` (currently the only other kind is `dispatch_issue`, but
the check is written generically against `entry_kind`, not a `DispatchLine`
existence check, so any future ledger kind is covered automatically too);
(2) `finished_goods_storage_movements` has no row at all for this lot,
regardless of net placement -- a lot placed and later fully released nets
to zero but the custody fact still happened and is never undone by any row
in that table. Neither dispatch nor storage placement/release has a
reversal mechanism in this ticket's scope."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services import finished_goods_ledger_service, graded_produce_lot_ledger_service, packing_service
from app.services.errors import (
    InvalidPackingReversalEffectiveTimeError,
    PackingEventAlreadyReversedError,
    PackingEventNotFoundError,
    PackingReversalBlockedByDownstreamActivityError,
    PackingReversalCommandReusedWithDifferentPayloadError,
    PackingReversalEventNotFoundError,
    PackingReversalValidationError,
)
from tests._dispatch_scenario import dispatch_one
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, now
from tests._storage_scenario import create_cold_store, create_cold_store_position, place_one, release_one


def _session(test_engine):
    conn = test_engine.connect()
    return Session(bind=conn), conn


def _pack_full_gpl_a(scenario, db: Session, *, package_count: int = 1):
    """Packs scenario['gpl_a_id']'s FULL weight/count into a new
    finished-goods lot. Returns (finished_goods_lot_id, packing_event_id).
    Local, count-aware variant of `tests._dispatch_scenario.pack_one`
    (which always passes `consumed_whole_unit_count=None`, incompatible
    with this scenario's default count-tracking lot_a)."""
    event = packing_service.record_packing(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), pack_specification_version_id=scenario["pack_specification_version_id"],
        effective_time=now(), finished_goods_lot_code=f"FG-{uuid.uuid4().hex[:8]}", package_count=package_count,
        packed_output_weight_kg=scenario["lot_a_weight"], process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[
            {
                "graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": scenario["lot_a_weight"],
                "consumed_whole_unit_count": scenario["lot_a_count"], "note": None,
            }
        ],
    )
    detail = packing_service.get_packing_event(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=event.id
    )
    return detail.finished_goods_lot.id, event.id


def _reverse(scenario, *, db, packing_event_id, client_command_id=None, effective_time=None,
             reason_code="OPERATOR_ERROR", note="wrong finished goods lot code"):
    return packing_service.reverse_packing_event(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=client_command_id or uuid.uuid4(), packing_event_id=packing_event_id,
        effective_time=effective_time or now(), reason_code=reason_code, note=note,
    )


@pytest.mark.integration
def test_reversal_restores_gpl_and_neutralizes_fg_balances(test_engine) -> None:
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        fg_lot_id, packing_event_id = _pack_full_gpl_a(scenario, session)

        reversal = _reverse(scenario, db=session, packing_event_id=packing_event_id)
        assert reversal.packing_event_id == packing_event_id

        gpl_balance = graded_produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            graded_produce_lot_id=scenario["gpl_a_id"],
        )
        assert gpl_balance.available_weight_kg == scenario["lot_a_weight"]

        fg_balance = finished_goods_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        assert fg_balance.available_weight_kg == Decimal("0")
        assert fg_balance.available_package_count == 0

        read = packing_service.get_packing_reversal_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=packing_event_id
        )
        assert read.inputs[0].graded_produce_lot_id == scenario["gpl_a_id"]
        assert read.neutralized_finished_goods_weight_kg == scenario["lot_a_weight"]
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_reversal_idempotent_replay(test_engine) -> None:
    """FINAL VERIFICATION section 3: an exact-fingerprint replay under the
    same client_command_id must create no duplicate reversal fact, ledger
    row, or audit event -- not merely return the same id."""
    from sqlalchemy import text

    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        _, packing_event_id = _pack_full_gpl_a(scenario, session)
        cmd_id = uuid.uuid4()
        effective_time = now()
        first = _reverse(scenario, db=session, packing_event_id=packing_event_id, client_command_id=cmd_id, effective_time=effective_time)
        second = _reverse(scenario, db=session, packing_event_id=packing_event_id, client_command_id=cmd_id, effective_time=effective_time)
        assert first.id == second.id

        reversal_count = session.execute(
            text("SELECT count(*) FROM packing_reversal_events WHERE packing_event_id = :pid"),
            {"pid": packing_event_id},
        ).scalar_one()
        assert reversal_count == 1

        fg_ledger_count = session.execute(
            text(
                "SELECT count(*) FROM finished_goods_ledger_entries "
                "WHERE packing_reversal_event_id = :rid AND entry_kind = 'packing_reversal'"
            ),
            {"rid": first.id},
        ).scalar_one()
        assert fg_ledger_count == 1

        input_ledger_count = session.execute(
            text(
                "SELECT count(*) FROM graded_produce_lot_ledger_entries gle "
                "JOIN packing_reversal_inputs pri ON pri.id = gle.id "
                "WHERE pri.packing_reversal_event_id = :rid AND gle.entry_kind = 'packing_reversal'"
            ),
            {"rid": first.id},
        ).scalar_one()
        assert input_ledger_count == 1

        audit_count = session.execute(
            text(
                "SELECT count(*) FROM audit_events "
                "WHERE entity_type = 'packing_reversal_event' AND entity_id = :rid"
            ),
            {"rid": first.id},
        ).scalar_one()
        assert audit_count == 1
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_reversal_reused_with_different_payload(test_engine) -> None:
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        _, packing_event_id = _pack_full_gpl_a(scenario, session)
        cmd_id = uuid.uuid4()
        _reverse(scenario, db=session, packing_event_id=packing_event_id, client_command_id=cmd_id, note="reason A")
        with pytest.raises(PackingReversalCommandReusedWithDifferentPayloadError):
            _reverse(scenario, db=session, packing_event_id=packing_event_id, client_command_id=cmd_id, note="reason B")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_reversal_already_reversed(test_engine) -> None:
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        _, packing_event_id = _pack_full_gpl_a(scenario, session)
        _reverse(scenario, db=session, packing_event_id=packing_event_id)
        with pytest.raises(PackingEventAlreadyReversedError):
            _reverse(scenario, db=session, packing_event_id=packing_event_id, client_command_id=uuid.uuid4())
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_reversal_blocked_by_dispatch(test_engine) -> None:
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        fg_lot_id, packing_event_id = _pack_full_gpl_a(scenario, session, package_count=10)
        dispatch_one(scenario, session, finished_goods_lot_id=fg_lot_id, dispatched_weight_kg=Decimal("1.000"), dispatched_package_count=1)

        with pytest.raises(PackingReversalBlockedByDownstreamActivityError):
            _reverse(scenario, db=session, packing_event_id=packing_event_id)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_reversal_blocked_by_storage_placement(test_engine) -> None:
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        fg_lot_id, packing_event_id = _pack_full_gpl_a(scenario, session, package_count=10)
        cold_store = create_cold_store(scenario, session)
        position = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
        place_one(
            scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=position.id,
            moved_weight_kg=Decimal("1.000"), moved_package_count=1,
        )

        with pytest.raises(PackingReversalBlockedByDownstreamActivityError):
            _reverse(scenario, db=session, packing_event_id=packing_event_id)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_reversal_blocked_by_storage_history_even_at_zero_net_balance(test_engine) -> None:
    """PRE-COMMIT AUDIT: a lot placed into cold storage and then fully
    released back to unplaced nets to zero -- but the custody fact still
    happened, is immutable history, and must still block reversal. Net/live
    balance is never a valid proxy for "this never happened"."""
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        fg_lot_id, packing_event_id = _pack_full_gpl_a(scenario, session, package_count=10)
        cold_store = create_cold_store(scenario, session)
        position = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
        place_one(
            scenario, session, finished_goods_lot_id=fg_lot_id, destination_location_id=position.id,
            moved_weight_kg=Decimal("1.000"), moved_package_count=1,
        )
        release_one(
            scenario, session, finished_goods_lot_id=fg_lot_id, source_location_id=position.id,
            moved_weight_kg=Decimal("1.000"), moved_package_count=1,
        )

        # Net placed quantity is now back to zero -- reversal must still be blocked.
        with pytest.raises(PackingReversalBlockedByDownstreamActivityError):
            _reverse(scenario, db=session, packing_event_id=packing_event_id)
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_reversal_reason_required_note_optional(test_engine) -> None:
    """Product requirement: reason is mandatory. PRE-COMMIT AUDIT: note is
    optional (mirrors SeedlingDispositionEvent's own REVERSAL shape) --
    unless proven otherwise, do not add unnecessary operator friction."""
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        _, packing_event_id = _pack_full_gpl_a(scenario, session)
        with pytest.raises(PackingReversalValidationError):
            _reverse(scenario, db=session, packing_event_id=packing_event_id, reason_code="   ")

        # A blank/omitted note must NOT raise -- it is optional.
        reversal = _reverse(scenario, db=session, packing_event_id=packing_event_id, note=None)
        assert reversal.note is None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_reversal_not_found(test_engine) -> None:
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(PackingEventNotFoundError):
            _reverse(scenario, db=session, packing_event_id=uuid.uuid4())
        _, packing_event_id = _pack_full_gpl_a(scenario, session)
        with pytest.raises(PackingReversalEventNotFoundError):
            packing_service.get_packing_reversal_event(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                packing_event_id=packing_event_id,
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_reversal_effective_time_before_event_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        _, packing_event_id = _pack_full_gpl_a(scenario, session)
        event = packing_service.get_packing_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], packing_event_id=packing_event_id
        )
        with pytest.raises(InvalidPackingReversalEffectiveTimeError):
            _reverse(
                scenario, db=session, packing_event_id=packing_event_id,
                effective_time=event.effective_time - timedelta(days=1),
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
