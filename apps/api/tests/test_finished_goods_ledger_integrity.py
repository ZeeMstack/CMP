"""CMP-016 database-level integrity verification: proves the finished-
goods ledger's insert-integrity and deferred-reconciliation rules are
independently enforced by the database against direct SQL, not only by
the Python service layer. A module-scoped fixture builds one committed
scenario with a real packed lot (receipt already exists, used for
UPDATE/DELETE/wrong-lot tests) plus a second, receipt-less finished-goods
lot created via raw SQL — simulating pre-existing data with no receipt
yet — used to test every malformed-INSERT rejection in isolation. Every
test rolls its own connection back afterward so the shared baseline is
never mutated between tests."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import packing_service
from tests._packing_scenario import build_committed_scenario, cleanup_scenario


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def scenario(test_engine):
    from tests._packing_scenario import require_cmp_test

    s = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None, lot_b_weight="10.000", lot_b_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)

    event = packing_service.record_packing(
        session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], actor_user_id=s["user_id"],
        client_command_id=uuid.uuid4(), effective_time=_now(), finished_goods_lot_code=f"FG-{s['suffix']}",
        package_count=6, packed_output_weight_kg=Decimal("3.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"harvested_produce_lot_id": s["lot_a_id"], "consumed_weight_kg": Decimal("3.000"), "consumed_whole_unit_count": None, "note": None}],
    )
    detail = packing_service.get_packing_event(session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], packing_event_id=event.id)
    s["packing_event_id"] = event.id
    s["packing_event_effective_time"] = event.effective_time
    s["fg_lot_id"] = detail.finished_goods_lot.id
    s["fg_lot_recorded_time"] = session.execute(
        text("SELECT recorded_time FROM finished_goods_lots WHERE id = :lid"), {"lid": detail.finished_goods_lot.id}
    ).scalar_one()

    # A second, fully CMP-015-valid packing of lot B (its own event, input
    # line, produce-lot debit, finished-goods lot, and receipt all created
    # normally, so CMP-015's own deferred reconciliation is satisfied) —
    # then its CMP-016 receipt alone is removed via a privileged bypass,
    # simulating "pre-existing lot without a receipt yet" without having
    # to hand-construct an entire CMP-015-valid event from raw SQL.
    bare_event = packing_service.record_packing(
        session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], actor_user_id=s["user_id"],
        client_command_id=uuid.uuid4(), effective_time=_now(), finished_goods_lot_code=f"BARE-{s['suffix']}",
        package_count=9, packed_output_weight_kg=Decimal("1.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"harvested_produce_lot_id": s["lot_b_id"], "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": None, "note": None}],
    )
    bare_detail = packing_service.get_packing_event(session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], packing_event_id=bare_event.id)
    bare_lot_id = bare_detail.finished_goods_lot.id
    session.commit()

    require_cmp_test(test_engine)
    bypass_conn = test_engine.connect()
    trans = bypass_conn.begin()
    bypass_conn.execute(text("SET session_replication_role = replica"))
    bypass_conn.execute(text("DELETE FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = :lid"), {"lid": bare_lot_id})
    bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    bypass_conn.close()

    s["bare_event_id"] = bare_event.id
    s["bare_lot_id"] = bare_lot_id
    s["bare_lot_recorded_time"] = session.execute(
        text("SELECT recorded_time FROM finished_goods_lots WHERE id = :lid"), {"lid": bare_lot_id}
    ).scalar_one()
    s["bare_event_effective_time"] = session.execute(
        text("SELECT effective_time FROM packing_events WHERE id = :eid"), {"eid": bare_event.id}
    ).scalar_one()

    session.close()
    conn.close()
    yield s
    cleanup_scenario(test_engine, s["tenant_id"])


def _valid_params(scenario):
    return {
        "id": scenario["bare_lot_id"], "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
        "lid": scenario["bare_lot_id"], "eid": scenario["bare_event_id"], "weight": Decimal("1.000"), "count": 9,
        "eff": scenario["bare_event_effective_time"], "rec": scenario["bare_lot_recorded_time"],
        "uid": scenario["user_id"], "note": None,
    }


def _try_insert(test_engine, params, *, match):
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match=match):
            conn.execute(
                text(
                    "INSERT INTO finished_goods_ledger_entries "
                    "(id, tenant_id, farm_id, finished_goods_lot_id, packing_event_id, entry_kind, "
                    "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "VALUES (:id, :tid, :fid, :lid, :eid, 'packing_receipt', :weight, :count, :eff, :rec, :uid, :note)"
                ),
                params,
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_wrong_weight_rejected(scenario, test_engine) -> None:
    params = _valid_params(scenario)
    params["weight"] = Decimal("999.000")
    _try_insert(test_engine, params, match="net packed weight")


@pytest.mark.integration
def test_direct_sql_wrong_package_count_rejected(scenario, test_engine) -> None:
    params = _valid_params(scenario)
    params["count"] = 12345
    _try_insert(test_engine, params, match="package count")


@pytest.mark.integration
def test_direct_sql_wrong_event_rejected(scenario, test_engine) -> None:
    params = _valid_params(scenario)
    params["eid"] = scenario["packing_event_id"]
    _try_insert(test_engine, params, match="packing event does not match")


@pytest.mark.integration
def test_direct_sql_wrong_actor_rejected(scenario, test_engine) -> None:
    # The packing event's own actor is scenario["user_id"]; substitute a
    # fresh, unrelated (non-existent) user id.
    params = _valid_params(scenario)
    params["uid"] = uuid.uuid4()
    _try_insert(test_engine, params, match="actor does not match|violates foreign key")


@pytest.mark.integration
def test_direct_sql_wrong_effective_time_rejected(scenario, test_engine) -> None:
    from datetime import timedelta

    params = _valid_params(scenario)
    params["eff"] = scenario["bare_event_effective_time"] - timedelta(days=1)
    _try_insert(test_engine, params, match="effective time does not match")


@pytest.mark.integration
def test_direct_sql_wrong_recorded_time_rejected(scenario, test_engine) -> None:
    from datetime import timedelta

    params = _valid_params(scenario)
    params["rec"] = scenario["bare_lot_recorded_time"] - timedelta(days=1)
    _try_insert(test_engine, params, match="recorded time does not match")


@pytest.mark.integration
def test_direct_sql_non_null_note_rejected(scenario, test_engine) -> None:
    params = _valid_params(scenario)
    params["note"] = "not allowed"
    _try_insert(test_engine, params, match="ck_finished_goods_ledger_entries_note_null")


@pytest.mark.integration
def test_direct_sql_wrong_deterministic_id_rejected(scenario, test_engine) -> None:
    params = _valid_params(scenario)
    params["id"] = uuid.uuid4()
    _try_insert(test_engine, params, match="ck_finished_goods_ledger_entries_deterministic_id")


@pytest.mark.integration
def test_direct_sql_wrong_tenant_rejected(scenario, test_engine) -> None:
    params = _valid_params(scenario)
    params["tid"] = uuid.uuid4()
    _try_insert(test_engine, params, match="tenant/farm does not match|violates foreign key")


@pytest.mark.integration
def test_direct_sql_output_lot_without_receipt_fails_at_commit(test_engine) -> None:
    """A finished-goods lot inserted directly (bypassing packing_service,
    which always creates its receipt) must fail deferred reconciliation at
    commit, not merely at some later read. Built by packing normally (a
    fully CMP-015-valid event/input-line/debit/lot/receipt chain), then
    privilege-deleting just the output lot and its receipt (so the event
    still has its required input line and debit, satisfying CMP-015's own
    reconciliation), then re-inserting only the lot, deliberately without
    its receipt."""
    from tests._packing_scenario import require_cmp_test

    s = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        event = packing_service.record_packing(
            session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], actor_user_id=s["user_id"],
            client_command_id=uuid.uuid4(), effective_time=_now(), finished_goods_lot_code=f"FG-{s['suffix']}",
            package_count=1, packed_output_weight_kg=Decimal("1.000"), process_loss_weight_kg=Decimal("0"),
            rejected_weight_kg=Decimal("0"), note=None,
            input_lines=[{"harvested_produce_lot_id": s["lot_a_id"], "consumed_weight_kg": Decimal("1.000"), "consumed_whole_unit_count": None, "note": None}],
        )
        event_id = event.id
        session.commit()
        session.close()
        conn.close()

        require_cmp_test(test_engine)
        bypass_conn = test_engine.connect()
        trans = bypass_conn.begin()
        bypass_conn.execute(text("SET session_replication_role = replica"))
        bypass_conn.execute(
            text("DELETE FROM finished_goods_ledger_entries WHERE packing_event_id = :eid"), {"eid": event_id}
        )
        bypass_conn.execute(text("DELETE FROM finished_goods_lots WHERE packing_event_id = :eid"), {"eid": event_id})
        bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
        bypass_conn.close()

        conn2 = test_engine.connect()
        trans2 = conn2.begin()
        try:
            with pytest.raises(Exception, match="must have exactly one packing receipt"):
                conn2.execute(
                    text(
                        "INSERT INTO finished_goods_lots "
                        "(id, tenant_id, farm_id, code, packing_event_id, crop_id, variety_id, "
                        "net_packed_weight_kg, package_count, effective_time, recorded_time) "
                        "SELECT gen_random_uuid(), tenant_id, farm_id, 'ORPHAN-LOT', id, crop_id, variety_id, "
                        "packed_output_weight_kg, 1, effective_time, effective_time "
                        "FROM packing_events WHERE id = :eid"
                    ),
                    {"eid": event_id},
                )
                trans2.commit()
        finally:
            trans2.rollback()
            conn2.close()
    finally:
        cleanup_scenario(test_engine, s["tenant_id"])


@pytest.mark.integration
def test_receipt_update_rejected(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="append-only"):
            conn.execute(
                text("UPDATE finished_goods_ledger_entries SET weight_delta_kg = 1.000 WHERE id = :lid"),
                {"lid": scenario["fg_lot_id"]},
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_receipt_delete_rejected(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="hard-deleted|not permitted"):
            conn.execute(
                text("DELETE FROM finished_goods_ledger_entries WHERE id = :lid"), {"lid": scenario["fg_lot_id"]}
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_duplicate_receipt_rejected(scenario, test_engine) -> None:
    """A second packing_receipt row for the same already-receipted lot
    must be rejected. Under the deterministic-identity convention this is
    unreachable via a *different* id (the deterministic-id CHECK requires
    `id = finished_goods_lot_id`, so any duplicate attempt necessarily
    reuses the same id and collides on the primary key first) — the
    partial unique index on `finished_goods_lot_id` is a forward-
    compatibility tripwire for that same reason, exactly like CMP-014's
    own precedent. This test proves the row is rejected either way."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="duplicate key value violates"):
            conn.execute(
                text(
                    "INSERT INTO finished_goods_ledger_entries "
                    "(id, tenant_id, farm_id, finished_goods_lot_id, packing_event_id, entry_kind, "
                    "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "SELECT id, tenant_id, farm_id, finished_goods_lot_id, packing_event_id, "
                    "entry_kind, weight_delta_kg, package_count_delta, effective_time, recorded_time, "
                    "actor_user_id, note FROM finished_goods_ledger_entries WHERE finished_goods_lot_id = :lid"
                ),
                {"lid": scenario["fg_lot_id"]},
            )
    finally:
        trans.rollback()
        conn.close()
