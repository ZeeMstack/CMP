"""Unit/integration coverage for CMP-017 dispatch beyond the acceptance
flow: event/line creation shape, deterministic issue identity, exact
negative weight/count deltas, typed-source XOR on the finished-goods
ledger, canonical Decimal serialization, BIGINT package-count bounds, and
the one-line-per-lot-per-event constraint. Model-level CHECK/append-only
enforcement against direct SQL lives in test_dispatch_integrity.py."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.dispatch_line import DispatchLine
from app.services import dispatch_service, finished_goods_ledger_service
from app.services.errors import DispatchValidationError, InsufficientFinishedGoodsBalanceError
from tests._dispatch_scenario import dispatch_one, now, pack_one
from tests._packing_scenario import build_committed_scenario, cleanup_scenario

MAX_WHOLE_UNIT_COUNT = 9223372036854775807


@pytest.mark.integration
def test_deterministic_issue_id_equals_dispatch_line_id(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session)
        event = dispatch_one(scenario, session, finished_goods_lot_id=fg_lot_id)
        line = session.execute(
            select(DispatchLine).where(DispatchLine.dispatch_event_id == event.id)
        ).scalar_one()
        ledger = finished_goods_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        issue = next(e for e in ledger if e.entry_kind == "dispatch_issue")
        assert issue.id == line.id
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_issue_weight_and_count_are_exact_negatives_of_line(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
        dispatch_one(
            scenario, session, finished_goods_lot_id=fg_lot_id, dispatched_weight_kg=Decimal("3.250"),
            dispatched_package_count=4,
        )
        ledger = finished_goods_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        issue = next(e for e in ledger if e.entry_kind == "dispatch_issue")
        assert issue.weight_delta_kg == Decimal("-3.250")
        assert issue.package_count_delta == -4
        assert issue.note is None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_ledger_typed_source_xor_dispatch_issue(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, packing_event_id = pack_one(scenario, session)
        dispatch_one(scenario, session, finished_goods_lot_id=fg_lot_id, dispatched_weight_kg=Decimal("1.000"), dispatched_package_count=1)
        ledger = finished_goods_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        receipt = next(e for e in ledger if e.entry_kind == "packing_receipt")
        issue = next(e for e in ledger if e.entry_kind == "dispatch_issue")
        assert receipt.packing_event_id == packing_event_id
        assert receipt.dispatch_line_id is None
        assert issue.packing_event_id is None
        assert issue.dispatch_line_id is not None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_balance_reflects_dispatch_issue(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
        dispatch_one(scenario, session, finished_goods_lot_id=fg_lot_id, dispatched_weight_kg=Decimal("3.000"), dispatched_package_count=4)
        balance = finished_goods_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        assert balance.available_weight_kg == Decimal("5.000")
        assert balance.available_package_count == 6
        assert balance.received_weight_kg == Decimal("8.000")
        assert balance.received_package_count == 10
        assert balance.entry_count == 2
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_repeated_partial_dispatch_until_exact_zero(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
        dispatch_one(scenario, session, finished_goods_lot_id=fg_lot_id, dispatched_weight_kg=Decimal("3.000"), dispatched_package_count=4, code_suffix="-A")
        dispatch_one(scenario, session, finished_goods_lot_id=fg_lot_id, dispatched_weight_kg=Decimal("5.000"), dispatched_package_count=6, code_suffix="-B")
        balance = finished_goods_ledger_service.get_balance(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        assert balance.available_weight_kg == Decimal("0.000")
        assert balance.available_package_count == 0
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_multiple_lines_one_event_each_own_lot(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None, lot_b_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_a, _ = pack_one(scenario, session, lot_key="lot_a_id", package_count=10, packed_output_weight_kg=Decimal("8.000"), code_suffix="-A")
        fg_lot_b, _ = pack_one(scenario, session, lot_key="lot_b_id", package_count=5, packed_output_weight_kg=Decimal("4.000"), code_suffix="-B")

        event = dispatch_service.record_dispatch(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), effective_time=now(), code=f"DISP-{scenario['suffix']}",
            external_reference=None, note=None,
            lines=[
                {"finished_goods_lot_id": fg_lot_a, "dispatched_weight_kg": Decimal("2.000"), "dispatched_package_count": 3},
                {"finished_goods_lot_id": fg_lot_b, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 2},
            ],
        )
        detail = dispatch_service.get_dispatch_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], dispatch_event_id=event.id
        )
        assert len(detail.lines) == 2
        assert detail.total_dispatched_weight_kg == Decimal("3.000")
        assert detail.total_dispatched_package_count == 5
        lot_ids = {line.finished_goods_lot_id for line in detail.lines}
        assert lot_ids == {fg_lot_a, fg_lot_b}
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_duplicate_lot_within_one_command_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
        with pytest.raises(DispatchValidationError):
            dispatch_service.record_dispatch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), effective_time=now(), code=f"DISP-{scenario['suffix']}",
                external_reference=None, note=None,
                lines=[
                    {"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1},
                    {"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1},
                ],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_weight_overdraw_rejected_independently(test_engine) -> None:
    """Requesting more weight than available must be rejected even when
    the requested count is well within balance."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
        with pytest.raises(InsufficientFinishedGoodsBalanceError):
            dispatch_service.record_dispatch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), effective_time=now(), code=f"DISP-{scenario['suffix']}",
                external_reference=None, note=None,
                lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("99.000"), "dispatched_package_count": 1}],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_count_overdraw_rejected_independently(test_engine) -> None:
    """Requesting more package count than available must be rejected even
    when the requested weight is well within balance."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
        with pytest.raises(InsufficientFinishedGoodsBalanceError):
            dispatch_service.record_dispatch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), effective_time=now(), code=f"DISP-{scenario['suffix']}",
                external_reference=None, note=None,
                lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 999}],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_one_line_per_lot_per_event_db_constraint(test_engine) -> None:
    """The service already rejects duplicate lot ids within one command
    request (see above); this proves the underlying DB constraint that
    backs it is real and independent of the service-layer check."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
        event = dispatch_one(scenario, session, finished_goods_lot_id=fg_lot_id, dispatched_weight_kg=Decimal("1.000"), dispatched_package_count=1)
        session.add(
            DispatchLine(
                id=uuid.uuid4(), tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                dispatch_event_id=event.id, finished_goods_lot_id=fg_lot_id,
                dispatched_weight_kg=Decimal("1.000"), dispatched_package_count=1,
            )
        )
        with pytest.raises(IntegrityError, match="ux_dispatch_lines_event_lot"):
            session.flush()
    finally:
        session.rollback()
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


def test_schema_accepts_more_than_fifty_lines() -> None:
    """CMP-017 has no approved maximum on lines per dispatch command -- only
    "at least one" is a real domain rule. Proves the Pydantic layer itself
    imposes no arbitrary cap, without touching the database."""
    from app.schemas.dispatch import DispatchEventCreate

    payload = DispatchEventCreate(
        client_command_id=uuid.uuid4(), effective_time=now(), code="DISP-MANYLINES",
        external_reference=None, note=None,
        lines=[
            {
                "finished_goods_lot_id": uuid.uuid4(), "dispatched_weight_kg": "1.000",
                "dispatched_package_count": 1,
            }
            for _ in range(75)
        ],
    )
    assert len(payload.lines) == 75


@pytest.mark.integration
def test_dispatch_with_more_than_fifty_lots_not_rejected_for_line_count(test_engine) -> None:
    """A dispatch naming 60 distinct finished-goods lots (each a real,
    separately packed lot) in one command must succeed -- proving line
    count alone is never grounds for rejection, matching the approved
    domain rule (at least one line, one line per lot per event) rather
    than the removed, unapproved 50-line cap."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="1000.000", lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        lot_ids = [
            pack_one(scenario, session, package_count=1, packed_output_weight_kg=Decimal("1.000"), code_suffix=f"-{i}")[0]
            for i in range(60)
        ]
        event = dispatch_service.record_dispatch(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), effective_time=now(), code=f"DISP-{scenario['suffix']}",
            external_reference=None, note=None,
            lines=[
                {"finished_goods_lot_id": lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1}
                for lot_id in lot_ids
            ],
        )
        detail = dispatch_service.get_dispatch_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], dispatch_event_id=event.id
        )
        assert len(detail.lines) == 60
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_package_count_bigint_max_accepted(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(
            scenario, session, package_count=MAX_WHOLE_UNIT_COUNT, packed_output_weight_kg=Decimal("1.000")
        )
        dispatch_one(
            scenario, session, finished_goods_lot_id=fg_lot_id, dispatched_weight_kg=Decimal("1.000"),
            dispatched_package_count=MAX_WHOLE_UNIT_COUNT,
        )
        ledger = finished_goods_ledger_service.get_ledger(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], finished_goods_lot_id=fg_lot_id
        )
        issue = next(e for e in ledger if e.entry_kind == "dispatch_issue")
        assert issue.package_count_delta == -MAX_WHOLE_UNIT_COUNT
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_canonical_decimal_weight_serialization(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, _ = pack_one(scenario, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
        event = dispatch_one(scenario, session, finished_goods_lot_id=fg_lot_id, dispatched_weight_kg=Decimal("3.500"), dispatched_package_count=4)
        detail = dispatch_service.get_dispatch_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], dispatch_event_id=event.id
        )
        dumped = detail.model_dump(mode="json")
        assert dumped["total_dispatched_weight_kg"] == "3.5"
        assert dumped["lines"][0]["dispatched_weight_kg"] == "3.5"
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
