"""CMP-015 verification pass, section 2: database-level proof that a
packing event's effective_time is independently validated against (a) the
wall clock, (b) each source produce lot's own effective_time, and (c) the
latest pre-existing ledger entry for each source lot — not just by the
Python service layer. The "latest ledger entry" check lives in the
packing-input-line insert trigger specifically because it fires before
that same line's own ledger debit exists, so the comparison can never be
self-referential."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import packing_service
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, now


@pytest.mark.integration
def test_future_packing_event_rejected_by_clock_timestamp(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="cannot be in the future"):
            conn.execute(
                text(
                    "INSERT INTO packing_events "
                    "(id, tenant_id, farm_id, crop_id, variety_id, total_input_weight_kg, packed_output_weight_kg, "
                    "process_loss_weight_kg, rejected_weight_kg, effective_time, actor_user_id, client_command_id, "
                    "request_fingerprint, note) "
                    "SELECT gen_random_uuid(), tenant_id, farm_id, crop_id, variety_id, 1.000, 1.000, 0, 0, "
                    "clock_timestamp() + interval '1 hour', :uid, gen_random_uuid(), 'x', NULL "
                    "FROM harvested_produce_lots WHERE id = :lid"
                ),
                {"uid": scenario["user_id"], "lid": scenario["lot_a_id"]},
            )
    finally:
        trans.rollback()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


def _insert_raw_packing_event(conn, *, scenario, effective_time) -> uuid.UUID:
    event_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO packing_events "
            "(id, tenant_id, farm_id, crop_id, variety_id, total_input_weight_kg, packed_output_weight_kg, "
            "process_loss_weight_kg, rejected_weight_kg, effective_time, actor_user_id, client_command_id, "
            "request_fingerprint, note) "
            "SELECT :id, tenant_id, farm_id, crop_id, variety_id, 1.000, 1.000, 0, 0, :eff, :uid, "
            "gen_random_uuid(), 'x', NULL "
            "FROM harvested_produce_lots WHERE id = :lid"
        ),
        {"id": event_id, "eff": effective_time, "uid": scenario["user_id"], "lid": scenario["lot_a_id"]},
    )
    return event_id


@pytest.mark.integration
def test_packing_input_line_before_source_lot_effective_time_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        early_event_id = _insert_raw_packing_event(
            conn, scenario=scenario, effective_time=now() - timedelta(days=1)
        )
        with pytest.raises(Exception, match="cannot precede the source produce lot"):
            conn.execute(
                text(
                    "INSERT INTO packing_input_lines "
                    "(id, tenant_id, farm_id, packing_event_id, harvested_produce_lot_id, consumed_weight_kg, "
                    "consumed_whole_unit_count, note) "
                    "VALUES (gen_random_uuid(), :tid, :fid, :eid, :lid, 1.000, NULL, NULL)"
                ),
                {"tid": scenario["tenant_id"], "fid": scenario["farm_id"], "eid": early_event_id,
                 "lid": scenario["lot_a_id"]},
            )
    finally:
        trans.rollback()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_packing_input_line_before_latest_ledger_entry_rejected(test_engine) -> None:
    """Lot A's ledger already has a harvest_receipt at T_harvest, and (after
    a real packing consumption below) a packing_consumption at T_pack >
    T_harvest. A second, raw packing_event whose effective_time sits
    between T_harvest and T_pack must be rejected when it tries to
    reference lot A again — not because it precedes the lot's own
    creation, but because it precedes the *later* ledger entry."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    with test_engine.connect() as read_conn:
        lot_effective_time = read_conn.execute(
            text("SELECT effective_time FROM harvested_produce_lots WHERE id = :lid"), {"lid": scenario["lot_a_id"]}
        ).scalar_one()
    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    later_time = now()
    assert later_time > lot_effective_time, "the real packing debit below must postdate the lot's own effective_time"
    packing_service.record_packing(
        setup_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=later_time,
        finished_goods_lot_code=f"FG-{scenario['suffix']}", package_count=1,
        packed_output_weight_kg=Decimal("2.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"harvested_produce_lot_id": scenario["lot_a_id"], "consumed_weight_kg": Decimal("2.000"), "consumed_whole_unit_count": None, "note": None}],
    )
    setup_session.close()
    setup_conn.close()

    conn = test_engine.connect()
    trans = conn.begin()
    try:
        # Strictly after the lot's own effective_time, but strictly before
        # the packing_consumption debit just committed above.
        between_time = lot_effective_time + (later_time - lot_effective_time) / 2
        mid_event_id = _insert_raw_packing_event(conn, scenario=scenario, effective_time=between_time)
        with pytest.raises(Exception, match="cannot precede the latest existing ledger entry"):
            conn.execute(
                text(
                    "INSERT INTO packing_input_lines "
                    "(id, tenant_id, farm_id, packing_event_id, harvested_produce_lot_id, consumed_weight_kg, "
                    "consumed_whole_unit_count, note) "
                    "VALUES (gen_random_uuid(), :tid, :fid, :eid, :lid, 1.000, NULL, NULL)"
                ),
                {"tid": scenario["tenant_id"], "fid": scenario["farm_id"], "eid": mid_event_id,
                 "lid": scenario["lot_a_id"]},
            )
    finally:
        trans.rollback()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_packing_input_line_equal_to_lot_effective_time_accepted(test_engine) -> None:
    """The boundary is inclusive (>=, not >): a packing event whose
    effective_time exactly equals the source lot's own effective_time must
    be accepted, not rejected."""
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    with test_engine.connect() as read_conn:
        lot_effective_time = read_conn.execute(
            text("SELECT effective_time FROM harvested_produce_lots WHERE id = :lid"), {"lid": scenario["lot_a_id"]}
        ).scalar_one()

    conn = test_engine.connect()
    trans = conn.begin()
    try:
        event_id = _insert_raw_packing_event(conn, scenario=scenario, effective_time=lot_effective_time)
        # Must not raise.
        conn.execute(
            text(
                "INSERT INTO packing_input_lines "
                "(id, tenant_id, farm_id, packing_event_id, harvested_produce_lot_id, consumed_weight_kg, "
                "consumed_whole_unit_count, note) "
                "VALUES (gen_random_uuid(), :tid, :fid, :eid, :lid, 1.000, NULL, NULL)"
            ),
            {"tid": scenario["tenant_id"], "fid": scenario["farm_id"], "eid": event_id, "lid": scenario["lot_a_id"]},
        )
    finally:
        trans.rollback()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
