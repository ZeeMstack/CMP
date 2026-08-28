"""POSTHARVEST-OPS-001H: whole-event reversal of a GradingEvent -- never a
field-by-field correction. Restores the source HarvestedProduceLot's
ledger balance by exactly the quantity `grading_consumption` debited, and
zeroes every output GradedProduceLot's balance. Blocked while any output
is still consumed by an ACTIVE (non-reversed) PackingEvent.

PRE-COMMIT AUDIT: reason_code is mandatory; note is optional (mirrors
SeedlingDispositionEvent's own REVERSAL shape)."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services import graded_produce_lot_ledger_service, grading_service, packing_service, produce_lot_ledger_service
from app.services.errors import (
    GradingEventAlreadyReversedError,
    GradingEventNotFoundError,
    GradingReversalBlockedByActivePackingError,
    GradingReversalCommandReusedWithDifferentPayloadError,
    GradingReversalEventNotFoundError,
    GradingReversalValidationError,
    InvalidGradingReversalEffectiveTimeError,
)
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, now


def _session(test_engine):
    conn = test_engine.connect()
    return Session(bind=conn), conn


def _pack_full_gpl_a(scenario, db: Session):
    """Packs scenario['gpl_a_id']'s FULL weight/count into a new
    finished-goods lot. Returns (finished_goods_lot_id, packing_event_id).
    Local, count-aware variant of `tests._dispatch_scenario.pack_one`
    (which always passes `consumed_whole_unit_count=None`, incompatible
    with this scenario's default count-tracking lot_a)."""
    event = packing_service.record_packing(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), pack_specification_version_id=scenario["pack_specification_version_id"],
        effective_time=now(), finished_goods_lot_code=f"FG-{uuid.uuid4().hex[:8]}", package_count=1,
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


def _reverse(scenario, *, db, grading_event_id, client_command_id=None, effective_time=None,
             reason_code="OPERATOR_ERROR", note="wrong source lot selected"):
    return grading_service.reverse_grading_event(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=client_command_id or uuid.uuid4(), grading_event_id=grading_event_id,
        effective_time=effective_time or now(), reason_code=reason_code, note=note,
    )


def _grading_event_id_for_gpl(session: Session, gpl_id) -> uuid.UUID:
    from sqlalchemy import text
    return session.execute(
        text("SELECT grading_event_id FROM graded_produce_lots WHERE id = :id"), {"id": gpl_id}
    ).scalar_one()


@pytest.mark.integration
def test_reversal_restores_hpl_balance_and_zeroes_gpl(test_engine) -> None:
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        grading_event_id = _grading_event_id_for_gpl(session, scenario["gpl_a_id"])

        reversal = _reverse(scenario, db=session, grading_event_id=grading_event_id)
        assert reversal.grading_event_id == grading_event_id

        hpl_balance = produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], produce_lot_id=scenario["lot_a_id"]
        )
        assert hpl_balance.available_weight_kg == scenario["lot_a_weight"]

        gpl_balance = graded_produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            graded_produce_lot_id=scenario["gpl_a_id"],
        )
        assert gpl_balance.available_weight_kg == Decimal("0")

        read = grading_service.get_grading_reversal_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=grading_event_id
        )
        assert read.outputs[0].graded_produce_lot_id == scenario["gpl_a_id"]
        assert read.restored_produce_lot_weight_kg == scenario["lot_a_weight"]
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
        grading_event_id = _grading_event_id_for_gpl(session, scenario["gpl_a_id"])
        cmd_id = uuid.uuid4()
        effective_time = now()
        first = _reverse(scenario, db=session, grading_event_id=grading_event_id, client_command_id=cmd_id, effective_time=effective_time)
        second = _reverse(scenario, db=session, grading_event_id=grading_event_id, client_command_id=cmd_id, effective_time=effective_time)
        assert first.id == second.id

        reversal_count = session.execute(
            text("SELECT count(*) FROM grading_reversal_events WHERE grading_event_id = :gid"),
            {"gid": grading_event_id},
        ).scalar_one()
        assert reversal_count == 1

        ledger_count = session.execute(
            text(
                "SELECT count(*) FROM produce_lot_ledger_entries "
                "WHERE grading_reversal_event_id = :rid AND entry_kind = 'grading_reversal'"
            ),
            {"rid": first.id},
        ).scalar_one()
        assert ledger_count == 1

        output_ledger_count = session.execute(
            text(
                "SELECT count(*) FROM graded_produce_lot_ledger_entries gle "
                "JOIN grading_reversal_outputs gro ON gro.id = gle.id "
                "WHERE gro.grading_reversal_event_id = :rid AND gle.entry_kind = 'grading_reversal'"
            ),
            {"rid": first.id},
        ).scalar_one()
        assert output_ledger_count == 1

        audit_count = session.execute(
            text(
                "SELECT count(*) FROM audit_events "
                "WHERE entity_type = 'grading_reversal_event' AND entity_id = :rid"
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
        grading_event_id = _grading_event_id_for_gpl(session, scenario["gpl_a_id"])
        cmd_id = uuid.uuid4()
        _reverse(scenario, db=session, grading_event_id=grading_event_id, client_command_id=cmd_id, note="reason A")
        with pytest.raises(GradingReversalCommandReusedWithDifferentPayloadError):
            _reverse(scenario, db=session, grading_event_id=grading_event_id, client_command_id=cmd_id, note="reason B")
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_reversal_already_reversed(test_engine) -> None:
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        grading_event_id = _grading_event_id_for_gpl(session, scenario["gpl_a_id"])
        _reverse(scenario, db=session, grading_event_id=grading_event_id)
        with pytest.raises(GradingEventAlreadyReversedError):
            _reverse(scenario, db=session, grading_event_id=grading_event_id, client_command_id=uuid.uuid4())
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_full_chain_grading_packing_packing_reversal_grading_reversal_reconciles(test_engine) -> None:
    """FINAL VERIFICATION section 3: Grading -> Packing -> Grading reversal
    BLOCKED -> Packing reversal -> Grading reversal -> every HPL/GPL/FG
    balance reconciles back to its pre-chain state."""
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        grading_event_id = _grading_event_id_for_gpl(session, scenario["gpl_a_id"])
        fg_lot_id, packing_event_id = _pack_full_gpl_a(scenario, session)

        with pytest.raises(GradingReversalBlockedByActivePackingError):
            _reverse(scenario, db=session, grading_event_id=grading_event_id)

        packing_service.reverse_packing_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), packing_event_id=packing_event_id, effective_time=now(),
            reason_code="OPERATOR_ERROR", note="wrong pack spec",
        )

        # Now allowed -- the only downstream PackingEvent has itself been reversed.
        reversal = _reverse(scenario, db=session, grading_event_id=grading_event_id)
        assert reversal.grading_event_id == grading_event_id

        # Final reconciliation across the whole chain: HPL balance is back to
        # its original harvested weight, the GPL that was graded/packed/
        # unpacked/ungraded is back to exactly zero, and the FG lot the
        # packing reversal neutralized is also zero.
        hpl_balance = produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], produce_lot_id=scenario["lot_a_id"]
        )
        assert hpl_balance.available_weight_kg == scenario["lot_a_weight"]

        gpl_balance = graded_produce_lot_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            graded_produce_lot_id=scenario["gpl_a_id"],
        )
        assert gpl_balance.available_weight_kg == Decimal("0")

        from app.services import finished_goods_ledger_service
        fg_balance = finished_goods_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        assert fg_balance.available_weight_kg == Decimal("0")
        assert fg_balance.available_package_count == 0
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
        grading_event_id = _grading_event_id_for_gpl(session, scenario["gpl_a_id"])
        with pytest.raises(GradingReversalValidationError):
            _reverse(scenario, db=session, grading_event_id=grading_event_id, reason_code="   ")

        # A blank/omitted note must NOT raise -- it is optional.
        reversal = _reverse(scenario, db=session, grading_event_id=grading_event_id, note=None)
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
        with pytest.raises(GradingEventNotFoundError):
            _reverse(scenario, db=session, grading_event_id=uuid.uuid4())
        with pytest.raises(GradingReversalEventNotFoundError):
            grading_event_id = _grading_event_id_for_gpl(session, scenario["gpl_a_id"])
            grading_service.get_grading_reversal_event(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                grading_event_id=grading_event_id,
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
        grading_event_id = _grading_event_id_for_gpl(session, scenario["gpl_a_id"])
        event = grading_service.get_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], grading_event_id=grading_event_id
        )
        with pytest.raises(InvalidGradingReversalEffectiveTimeError):
            _reverse(
                scenario, db=session, grading_event_id=grading_event_id,
                effective_time=event.effective_time - timedelta(days=1),
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
