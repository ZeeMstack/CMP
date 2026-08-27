"""CMP-015 verification pass, section 1: regression proof that widening
`_parse_strict_decimal` with an `allow_zero` parameter did not loosen any
pre-existing caller. Every caller except `PackingEventCreate`'s
process-loss/rejected-weight fields still calls the function with its
default (`allow_zero=False`) and must still reject zero and binary
floats identically to before CMP-015."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services import packing_service
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, now


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Pydantic-level (fast, still requires DB for the client/active_context fixtures) ---


@pytest.mark.integration
def test_harvest_source_weight_zero_rejected(client, active_context) -> None:
    _tenant, _user, headers = active_context
    resp = client.post(
        "/farms/00000000-0000-0000-0000-000000000000/crop-batches/00000000-0000-0000-0000-000000000000/harvests",
        headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "produce_lot_code": "X",
            "source_lines": [{"batch_carrier_assignment_id": str(uuid.uuid4()), "harvested_weight_kg": "0", "whole_unit_count": None}],
        },
    )
    assert resp.status_code == 422
    assert "positive" in resp.text


@pytest.mark.integration
def test_harvest_source_weight_binary_float_rejected(client, active_context) -> None:
    _tenant, _user, headers = active_context
    resp = client.post(
        "/farms/00000000-0000-0000-0000-000000000000/crop-batches/00000000-0000-0000-0000-000000000000/harvests",
        headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "produce_lot_code": "X",
            "source_lines": [{"batch_carrier_assignment_id": str(uuid.uuid4()), "harvested_weight_kg": 1.5, "whole_unit_count": None}],
        },
    )
    assert resp.status_code == 422
    assert "binary float" in resp.text


@pytest.mark.integration
def test_packing_input_consumed_weight_zero_rejected(client, active_context) -> None:
    _tenant, _user, headers = active_context
    resp = client.post(
        "/farms/00000000-0000-0000-0000-000000000000/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "pack_specification_version_id": str(uuid.uuid4()),
            "finished_goods_lot_code": "FG-X", "package_count": 1, "packed_output_weight_kg": "1.000",
            "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [{"graded_produce_lot_id": str(uuid.uuid4()), "consumed_weight_kg": "0", "consumed_whole_unit_count": None}],
        },
    )
    assert resp.status_code == 422
    assert "positive" in resp.text


@pytest.mark.integration
def test_packed_output_weight_zero_rejected(client, active_context) -> None:
    _tenant, _user, headers = active_context
    resp = client.post(
        "/farms/00000000-0000-0000-0000-000000000000/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "pack_specification_version_id": str(uuid.uuid4()),
            "finished_goods_lot_code": "FG-X", "package_count": 1, "packed_output_weight_kg": "0",
            "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [{"graded_produce_lot_id": str(uuid.uuid4()), "consumed_weight_kg": "1.000", "consumed_whole_unit_count": None}],
        },
    )
    assert resp.status_code == 422
    assert "positive" in resp.text


@pytest.mark.integration
def test_packing_weight_fields_binary_float_rejected(client, active_context) -> None:
    _tenant, _user, headers = active_context
    resp = client.post(
        "/farms/00000000-0000-0000-0000-000000000000/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "pack_specification_version_id": str(uuid.uuid4()),
            "finished_goods_lot_code": "FG-X", "package_count": 1, "packed_output_weight_kg": 1.5,
            "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [{"graded_produce_lot_id": str(uuid.uuid4()), "consumed_weight_kg": "1.000", "consumed_whole_unit_count": None}],
        },
    )
    assert resp.status_code == 422
    assert "binary float" in resp.text


@pytest.mark.integration
def test_process_loss_and_rejected_weight_zero_accepted(client, active_context) -> None:
    """Zero must be accepted for these two fields specifically — a
    Pydantic-validation-only proof (farm/lot don't need to exist, since a
    downstream 404 after 422-free validation still proves the zero value
    itself was NOT the rejection reason)."""
    _tenant, _user, headers = active_context
    resp = client.post(
        "/farms/00000000-0000-0000-0000-000000000000/packing-events", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "pack_specification_version_id": str(uuid.uuid4()),
            "finished_goods_lot_code": "FG-X", "package_count": 1, "packed_output_weight_kg": "1.000",
            "process_loss_weight_kg": "0", "rejected_weight_kg": "0",
            "input_lines": [{"graded_produce_lot_id": str(uuid.uuid4()), "consumed_weight_kg": "1.000", "consumed_whole_unit_count": None}],
        },
    )
    # Payload itself validates cleanly (zero accepted); the farm doesn't
    # exist, so the request proceeds to a 404 from the service layer —
    # never a 422 about process_loss_weight_kg/rejected_weight_kg.
    assert resp.status_code == 404


# --- Database-level CHECK constraints (direct SQL) --------------------------------


@pytest.mark.integration
def test_harvested_produce_lot_total_weight_zero_rejected_by_check(test_engine) -> None:
    """harvested_produce_lots is append-only (UPDATE always rejected by its
    own trigger), so proving the weight-envelope CHECK independently
    requires a fresh INSERT with triggers bypassed via
    session_replication_role — the same established pattern used
    throughout the CMP-013/014/015 integrity test files."""
    from tests._packing_scenario import require_cmp_test

    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        with pytest.raises(Exception, match="ck_harvested_produce_lots_weight_envelope"):
            conn.execute(
                text(
                    "INSERT INTO harvested_produce_lots "
                    "(id, tenant_id, farm_id, code, harvest_event_id, batch_id, workflow_id, workflow_version_id, "
                    "crop_id, variety_id, total_harvested_weight_kg, total_whole_unit_count, effective_time) "
                    "SELECT gen_random_uuid(), tenant_id, farm_id, 'ZERO-TEST', :heid, batch_id, workflow_id, "
                    "workflow_version_id, crop_id, variety_id, 0, NULL, effective_time "
                    "FROM harvested_produce_lots WHERE id = :lid"
                ),
                {"heid": scenario["harvest_b_id"], "lid": scenario["lot_a_id"]},
            )
    finally:
        trans.rollback()
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_harvest_receipt_ledger_weight_zero_rejected_by_check(test_engine) -> None:
    """produce_lot_ledger_entries is append-only, so the same
    trigger-bypass-then-INSERT pattern is required here too."""
    from tests._packing_scenario import require_cmp_test

    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        with pytest.raises(Exception, match="ck_produce_lot_ledger_entries_weight_envelope"):
            conn.execute(
                text(
                    "INSERT INTO produce_lot_ledger_entries "
                    "(id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, "
                    "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "VALUES (gen_random_uuid(), :tid, :fid, :lid, :heid, 'harvest_receipt', 0, NULL, "
                    "now(), now(), :uid, NULL)"
                ),
                {"tid": scenario["tenant_id"], "fid": scenario["farm_id"], "lid": scenario["lot_a_id"],
                 "heid": scenario["harvest_a_id"], "uid": scenario["user_id"]},
            )
    finally:
        trans.rollback()
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_packing_input_line_weight_zero_rejected_by_check(test_engine) -> None:
    from sqlalchemy.orm import Session

    scenario = build_committed_scenario(test_engine, lot_a_count=None, lot_b_count=None)
    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    event = packing_service.record_packing(
        setup_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
        pack_specification_version_id=scenario["pack_specification_version_id"], effective_time=now(),
        finished_goods_lot_code=f"FG-{scenario['suffix']}", package_count=1,
        packed_output_weight_kg=Decimal("1.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": None, "note": None}],
    )
    event_id = event.id
    setup_session.close()
    setup_conn.close()

    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="ck_packing_input_lines_weight_positive"):
            conn.execute(
                text(
                    "INSERT INTO packing_input_lines "
                    "(id, tenant_id, farm_id, packing_event_id, graded_produce_lot_id, consumed_weight_kg, "
                    "consumed_whole_unit_count, note) "
                    "VALUES (:id, :tid, :fid, :eid, :lid, 0, NULL, NULL)"
                ),
                {"id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                 "eid": event_id, "lid": scenario["gpl_b_id"]},
            )
    finally:
        trans.rollback()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_packing_event_packed_output_weight_zero_rejected_by_check(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="ck_packing_events_packed_output_positive"):
            conn.execute(
                text(
                    "INSERT INTO packing_events "
                    "(id, tenant_id, farm_id, crop_id, variety_id, pack_specification_version_id, "
                    "total_input_weight_kg, packed_output_weight_kg, "
                    "process_loss_weight_kg, rejected_weight_kg, effective_time, actor_user_id, client_command_id, "
                    "request_fingerprint, note) "
                    "SELECT gen_random_uuid(), tenant_id, farm_id, crop_id, variety_id, :specid, 1.000, 0, 1.000, 0, "
                    "effective_time, :uid, gen_random_uuid(), 'x', NULL "
                    "FROM harvested_produce_lots WHERE id = :lid"
                ),
                {"uid": scenario["user_id"], "lid": scenario["lot_a_id"], "specid": scenario["pack_specification_version_id"]},
            )
    finally:
        trans.rollback()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
