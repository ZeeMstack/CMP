"""CMP-015 verification pass, section 4: BIGINT-compatible storage and
bounds enforcement for packing_input_lines.consumed_whole_unit_count,
produce_lot_ledger_entries.whole_unit_count_delta, and
finished_goods_lots.package_count. Confirms Pydantic-level rejection
(zero, negative, above BIGINT max) and independent PostgreSQL-level
rejection of a literal BIGINT overflow, plus that a value exceeding
32-bit INT range round-trips correctly (proving the columns are
genuinely BIGINT, not INT4)."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services import packing_service
from tests._packing_scenario import build_committed_scenario, cleanup_scenario

MAX_WHOLE_UNIT_COUNT = 9223372036854775807  # 2^63 - 1, BIGINT max
BIGINT_OVERFLOW = 9223372036854775808  # 2^63, one past BIGINT max
INT32_OVERFLOW = 3_000_000_000  # exceeds signed INT4's 2147483647 max


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Pydantic-level rejection (API) -----------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("bad_count", [0, -5, BIGINT_OVERFLOW])
def test_packing_input_consumed_count_out_of_range_rejected(client, active_context, bad_count) -> None:
    _tenant, _user, headers = active_context
    resp = client.post(
        "/farms/00000000-0000-0000-0000-000000000000/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "pack_specification_version_id": str(uuid.uuid4()),
            "finished_goods_lot_code": "FG-X", "package_count": 1, "packed_output_weight_kg": "1.000",
            "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [{"graded_produce_lot_id": str(uuid.uuid4()), "consumed_weight_kg": "1.000", "consumed_whole_unit_count": bad_count}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.integration
@pytest.mark.parametrize("bad_count", [0, -1, BIGINT_OVERFLOW])
def test_package_count_out_of_range_rejected(client, active_context, bad_count) -> None:
    _tenant, _user, headers = active_context
    resp = client.post(
        "/farms/00000000-0000-0000-0000-000000000000/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "pack_specification_version_id": str(uuid.uuid4()),
            "finished_goods_lot_code": "FG-X", "package_count": bad_count, "packed_output_weight_kg": "1.000",
            "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [{"graded_produce_lot_id": str(uuid.uuid4()), "consumed_weight_kg": "1.000", "consumed_whole_unit_count": None}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.integration
def test_max_valid_counts_accepted_by_pydantic(client, active_context) -> None:
    """The exact BIGINT max itself must be accepted, not rejected — proving
    the bound is inclusive (le=MAX_WHOLE_UNIT_COUNT), not exclusive."""
    _tenant, _user, headers = active_context
    resp = client.post(
        "/farms/00000000-0000-0000-0000-000000000000/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "pack_specification_version_id": str(uuid.uuid4()),
            "finished_goods_lot_code": "FG-X", "package_count": MAX_WHOLE_UNIT_COUNT,
            "packed_output_weight_kg": "1.000", "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [{"graded_produce_lot_id": str(uuid.uuid4()), "consumed_weight_kg": "1.000", "consumed_whole_unit_count": MAX_WHOLE_UNIT_COUNT}],
        },
    )
    # Payload validates cleanly; farm doesn't exist, so 404 — never 422.
    assert resp.status_code == 404


# --- PostgreSQL-level BIGINT overflow (direct SQL) --------------------------------


@pytest.mark.integration
def test_direct_sql_consumed_count_bigint_overflow_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=40)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="out of range|numeric field overflow"):
            conn.execute(
                text(
                    "INSERT INTO packing_input_lines "
                    "(id, tenant_id, farm_id, packing_event_id, graded_produce_lot_id, consumed_weight_kg, "
                    "consumed_whole_unit_count, note) "
                    "VALUES (:id, :tid, :fid, gen_random_uuid(), :lid, 1.000, :count, NULL)"
                ),
                {"id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                 "lid": scenario["gpl_a_id"], "count": BIGINT_OVERFLOW},
            )
    finally:
        trans.rollback()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_direct_sql_package_count_bigint_overflow_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="out of range|numeric field overflow"):
            conn.execute(
                text(
                    "INSERT INTO finished_goods_lots "
                    "(id, tenant_id, farm_id, code, packing_event_id, crop_id, variety_id, net_packed_weight_kg, "
                    "package_count, effective_time) "
                    "SELECT gen_random_uuid(), tenant_id, farm_id, 'OVERFLOW-TEST', gen_random_uuid(), crop_id, "
                    "variety_id, 1.000, :count, effective_time "
                    "FROM harvested_produce_lots WHERE id = :lid"
                ),
                {"count": BIGINT_OVERFLOW, "lid": scenario["lot_a_id"]},
            )
    finally:
        trans.rollback()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_ledger_debit_count_beyond_int32_round_trips_exactly(test_engine) -> None:
    """A count comfortably beyond signed INT4 range (2,147,483,647) must
    round-trip exactly through a real packing consumption — proving
    whole_unit_count_delta is genuinely BIGINT, not silently INT4."""
    scenario = build_committed_scenario(test_engine, lot_a_weight="1.000", lot_a_count=INT32_OVERFLOW)
    from sqlalchemy.orm import Session

    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        event = packing_service.record_packing(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
            pack_specification_version_id=scenario["pack_specification_version_id"],
            effective_time=datetime.now(timezone.utc), finished_goods_lot_code=f"FG-{scenario['suffix']}",
            package_count=1, packed_output_weight_kg=Decimal("1.000"), process_loss_weight_kg=Decimal("0"),
            rejected_weight_kg=Decimal("0"), note=None,
            input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": INT32_OVERFLOW, "note": None}],
        )
        delta = session.execute(
            text(
                "SELECT whole_unit_count_delta FROM graded_produce_lot_ledger_entries "
                "WHERE packing_event_id = :eid AND entry_kind = 'packing_consumption'"
            ),
            {"eid": event.id},
        ).scalar_one()
        assert delta == -INT32_OVERFLOW
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
