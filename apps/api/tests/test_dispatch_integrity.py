"""CMP-017 database-level integrity verification: proves the dispatch
insert-integrity (v2) trigger and deferred dispatch reconciliation are
independently enforced by the database against direct SQL, not only by
the Python service layer. A module-scoped fixture packs one finished-
goods lot and dispatches a small amount from it twice: one genuinely
valid dispatch (kept intact, used for the duplicate-issue test) and one
whose ledger issue is privilege-deleted afterward, leaving a "bare"
dispatch line with no issue yet — used for every malformed-INSERT
rejection test in isolation. Every test rolls its own connection back
afterward so the shared baseline is never mutated between tests."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import dispatch_service, packing_service
from app.services.errors import DispatchFinishedGoodsLotNotFoundError
from tests._dispatch_scenario import dispatch_one, pack_one
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, require_cmp_test


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def scenario(test_engine):
    s = build_committed_scenario(test_engine, lot_a_weight="20.000", lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)

    fg_lot_id, packing_event_id = pack_one(
        s, session, package_count=10, packed_output_weight_kg=Decimal("8.000")
    )

    # A genuinely valid, kept-intact dispatch (used for the duplicate-issue test).
    issued_event = dispatch_one(
        s, session, finished_goods_lot_id=fg_lot_id, dispatched_weight_kg=Decimal("1.000"),
        dispatched_package_count=1, code_suffix="-ISSUED",
    )
    issued_line_id = session.execute(
        text("SELECT id FROM dispatch_lines WHERE dispatch_event_id = :eid"), {"eid": issued_event.id}
    ).scalar_one()

    # A second, fully valid dispatch (its own event/line/issue all created
    # normally, so deferred reconciliation is satisfied) -- then its
    # ledger issue alone is removed via a privileged bypass, simulating a
    # "line without its issue yet" without hand-constructing one from raw
    # SQL against a foreign key it cannot otherwise satisfy.
    bare_event = dispatch_one(
        s, session, finished_goods_lot_id=fg_lot_id, dispatched_weight_kg=Decimal("1.000"),
        dispatched_package_count=1, code_suffix="-BARE",
    )
    bare_line_id = session.execute(
        text("SELECT id FROM dispatch_lines WHERE dispatch_event_id = :eid"), {"eid": bare_event.id}
    ).scalar_one()
    session.commit()

    require_cmp_test(test_engine)
    bypass_conn = test_engine.connect()
    trans = bypass_conn.begin()
    bypass_conn.execute(text("SET session_replication_role = replica"))
    bypass_conn.execute(text("DELETE FROM finished_goods_ledger_entries WHERE dispatch_line_id = :lid"), {"lid": bare_line_id})
    bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    bypass_conn.close()

    s["fg_lot_id"] = fg_lot_id
    s["packing_event_id"] = packing_event_id
    s["issued_event_id"] = issued_event.id
    s["issued_line_id"] = issued_line_id
    s["bare_event_id"] = bare_event.id
    s["bare_line_id"] = bare_line_id
    s["bare_event_actor_id"] = s["user_id"]
    s["bare_event_effective_time"] = session.execute(
        text("SELECT effective_time FROM dispatch_events WHERE id = :eid"), {"eid": bare_event.id}
    ).scalar_one()
    s["bare_event_recorded_time"] = session.execute(
        text("SELECT recorded_time FROM dispatch_events WHERE id = :eid"), {"eid": bare_event.id}
    ).scalar_one()

    session.close()
    conn.close()
    yield s
    cleanup_scenario(test_engine, s["tenant_id"])


def _valid_params(scenario):
    return {
        "id": scenario["bare_line_id"], "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
        "lid": scenario["fg_lot_id"], "line_id": scenario["bare_line_id"], "weight": Decimal("-1.000"), "count": -1,
        "eff": scenario["bare_event_effective_time"], "rec": scenario["bare_event_recorded_time"],
        "uid": scenario["bare_event_actor_id"], "note": None,
    }


def _try_insert(test_engine, params, *, match):
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match=match):
            conn.execute(
                text(
                    "INSERT INTO finished_goods_ledger_entries "
                    "(id, tenant_id, farm_id, finished_goods_lot_id, dispatch_line_id, entry_kind, "
                    "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "VALUES (:id, :tid, :fid, :lid, :line_id, 'dispatch_issue', :weight, :count, :eff, :rec, :uid, :note)"
                ),
                params,
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_wrong_weight_rejected(scenario, test_engine) -> None:
    params = _valid_params(scenario)
    params["weight"] = Decimal("-999.000")
    _try_insert(test_engine, params, match="negative dispatch line weight")


@pytest.mark.integration
def test_direct_sql_wrong_package_count_rejected(scenario, test_engine) -> None:
    params = _valid_params(scenario)
    params["count"] = -12345
    _try_insert(test_engine, params, match="negative dispatch line package count")


@pytest.mark.integration
def test_direct_sql_wrong_actor_rejected(scenario, test_engine) -> None:
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
    params["rec"] = scenario["bare_event_recorded_time"] - timedelta(days=1)
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
def test_direct_sql_wrong_source_pattern_rejected(scenario, test_engine) -> None:
    """A dispatch_issue row must have packing_event_id NULL -- attempting
    to also populate it (in addition to the required dispatch_line_id)
    violates the typed-source XOR CHECK."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="ck_finished_goods_ledger_entries_typed_source_shape"):
            conn.execute(
                text(
                    "INSERT INTO finished_goods_ledger_entries "
                    "(id, tenant_id, farm_id, finished_goods_lot_id, packing_event_id, dispatch_line_id, "
                    "entry_kind, weight_delta_kg, package_count_delta, effective_time, recorded_time, "
                    "actor_user_id, note) "
                    "VALUES (:id, :tid, :fid, :lid, :peid, :line_id, 'dispatch_issue', :weight, :count, "
                    ":eff, :rec, :uid, NULL)"
                ),
                {
                    "id": scenario["bare_line_id"], "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                    "lid": scenario["fg_lot_id"], "peid": scenario["packing_event_id"],
                    "line_id": scenario["bare_line_id"], "weight": Decimal("-1.000"), "count": -1,
                    "eff": scenario["bare_event_effective_time"], "rec": scenario["bare_event_recorded_time"],
                    "uid": scenario["bare_event_actor_id"],
                },
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_weight_overdraw_rejected(scenario, test_engine) -> None:
    """A dispatch line whose own weight exceeds the lot's remaining
    balance must be rejected by the trigger's balance check even though
    every other field matches exactly."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        event_id = uuid.uuid4()
        line_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO dispatch_events "
                "(id, tenant_id, farm_id, code, effective_time, actor_user_id, client_command_id, "
                "request_fingerprint, external_reference, note) "
                "VALUES (:id, :tid, :fid, :code, :eff, :uid, :ccid, 'fp', NULL, NULL)"
            ),
            {
                "id": event_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                "code": f"OVERDRAW-W-{uuid.uuid4().hex[:8]}", "eff": _now(), "uid": scenario["user_id"],
                "ccid": uuid.uuid4(),
            },
        )
        conn.execute(
            text(
                "INSERT INTO dispatch_lines "
                "(id, tenant_id, farm_id, dispatch_event_id, finished_goods_lot_id, dispatched_weight_kg, "
                "dispatched_package_count) VALUES (:id, :tid, :fid, :eid, :lid, 999.000, 1)"
            ),
            {
                "id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "eid": event_id,
                "lid": scenario["fg_lot_id"],
            },
        )
        event_row = conn.execute(
            text("SELECT effective_time, recorded_time FROM dispatch_events WHERE id = :eid"), {"eid": event_id}
        ).one()
        with pytest.raises(Exception, match="negative available weight"):
            conn.execute(
                text(
                    "INSERT INTO finished_goods_ledger_entries "
                    "(id, tenant_id, farm_id, finished_goods_lot_id, dispatch_line_id, entry_kind, "
                    "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "VALUES (:id, :tid, :fid, :lid, :line_id, 'dispatch_issue', -999.000, -1, :eff, :rec, :uid, NULL)"
                ),
                {
                    "id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                    "lid": scenario["fg_lot_id"], "line_id": line_id, "eff": event_row.effective_time,
                    "rec": event_row.recorded_time, "uid": scenario["user_id"],
                },
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_count_overdraw_rejected(scenario, test_engine) -> None:
    """Same as the weight-overdraw proof above, but for package count
    independently -- a huge count with a modest, in-range weight."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        event_id = uuid.uuid4()
        line_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO dispatch_events "
                "(id, tenant_id, farm_id, code, effective_time, actor_user_id, client_command_id, "
                "request_fingerprint, external_reference, note) "
                "VALUES (:id, :tid, :fid, :code, :eff, :uid, :ccid, 'fp', NULL, NULL)"
            ),
            {
                "id": event_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                "code": f"OVERDRAW-C-{uuid.uuid4().hex[:8]}", "eff": _now(), "uid": scenario["user_id"],
                "ccid": uuid.uuid4(),
            },
        )
        conn.execute(
            text(
                "INSERT INTO dispatch_lines "
                "(id, tenant_id, farm_id, dispatch_event_id, finished_goods_lot_id, dispatched_weight_kg, "
                "dispatched_package_count) VALUES (:id, :tid, :fid, :eid, :lid, 0.500, 999999)"
            ),
            {
                "id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "eid": event_id,
                "lid": scenario["fg_lot_id"],
            },
        )
        event_row = conn.execute(
            text("SELECT effective_time, recorded_time FROM dispatch_events WHERE id = :eid"), {"eid": event_id}
        ).one()
        with pytest.raises(Exception, match="negative available package count"):
            conn.execute(
                text(
                    "INSERT INTO finished_goods_ledger_entries "
                    "(id, tenant_id, farm_id, finished_goods_lot_id, dispatch_line_id, entry_kind, "
                    "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "VALUES (:id, :tid, :fid, :lid, :line_id, 'dispatch_issue', -0.500, -999999, :eff, :rec, :uid, NULL)"
                ),
                {
                    "id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                    "lid": scenario["fg_lot_id"], "line_id": line_id, "eff": event_row.effective_time,
                    "rec": event_row.recorded_time, "uid": scenario["user_id"],
                },
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_dispatch_event_without_lines_fails_at_commit(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="must have at least one line"):
            conn.execute(
                text(
                    "INSERT INTO dispatch_events "
                    "(id, tenant_id, farm_id, code, effective_time, actor_user_id, client_command_id, "
                    "request_fingerprint, external_reference, note) "
                    "VALUES (:id, :tid, :fid, :code, :eff, :uid, :ccid, 'fp', NULL, NULL)"
                ),
                {
                    "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                    "code": f"EMPTY-{uuid.uuid4().hex[:8]}", "eff": _now(), "uid": scenario["user_id"],
                    "ccid": uuid.uuid4(),
                },
            )
            trans.commit()
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_dispatch_line_without_issue_fails_at_commit(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        event_id = uuid.uuid4()
        line_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO dispatch_events "
                "(id, tenant_id, farm_id, code, effective_time, actor_user_id, client_command_id, "
                "request_fingerprint, external_reference, note) "
                "VALUES (:id, :tid, :fid, :code, :eff, :uid, :ccid, 'fp', NULL, NULL)"
            ),
            {
                "id": event_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                "code": f"NOISSUE-{uuid.uuid4().hex[:8]}", "eff": _now(), "uid": scenario["user_id"],
                "ccid": uuid.uuid4(),
            },
        )
        with pytest.raises(Exception, match="missing or mismatched its dispatch_issue"):
            conn.execute(
                text(
                    "INSERT INTO dispatch_lines "
                    "(id, tenant_id, farm_id, dispatch_event_id, finished_goods_lot_id, dispatched_weight_kg, "
                    "dispatched_package_count) VALUES (:id, :tid, :fid, :eid, :lid, 1.000, 1)"
                ),
                {
                    "id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "eid": event_id,
                    "lid": scenario["fg_lot_id"],
                },
            )
            trans.commit()
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_duplicate_issue_for_already_issued_line_rejected(scenario, test_engine) -> None:
    """A second dispatch_issue row for an already-issued line must be
    rejected. Under the deterministic-identity convention this is
    unreachable via a different id (the CHECK requires
    `id = dispatch_line_id`, so any duplicate attempt necessarily reuses
    the same id and collides on the primary key first) -- the partial
    unique index on `dispatch_line_id` is a forward-compatibility
    tripwire for that same reason, exactly like CMP-016's own precedent."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="duplicate key value violates"):
            conn.execute(
                text(
                    "INSERT INTO finished_goods_ledger_entries "
                    "(id, tenant_id, farm_id, finished_goods_lot_id, dispatch_line_id, entry_kind, "
                    "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "SELECT id, tenant_id, farm_id, finished_goods_lot_id, dispatch_line_id, "
                    "entry_kind, weight_delta_kg, package_count_delta, effective_time, recorded_time, "
                    "actor_user_id, note FROM finished_goods_ledger_entries WHERE dispatch_line_id = :lid"
                ),
                {"lid": scenario["issued_line_id"]},
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_dispatch_event_update_rejected(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="append-only"):
            conn.execute(
                text("UPDATE dispatch_events SET code = 'RENAMED' WHERE id = :eid"),
                {"eid": scenario["issued_event_id"]},
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_dispatch_event_delete_rejected(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="hard-deleted|not permitted"):
            conn.execute(text("DELETE FROM dispatch_events WHERE id = :eid"), {"eid": scenario["issued_event_id"]})
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_dispatch_line_update_rejected(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="append-only"):
            conn.execute(
                text("UPDATE dispatch_lines SET dispatched_weight_kg = 5.000 WHERE id = :lid"),
                {"lid": scenario["issued_line_id"]},
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_dispatch_line_delete_rejected(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="hard-deleted|not permitted"):
            conn.execute(text("DELETE FROM dispatch_lines WHERE id = :lid"), {"lid": scenario["issued_line_id"]})
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_issue_update_rejected(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="append-only"):
            conn.execute(
                text("UPDATE finished_goods_ledger_entries SET weight_delta_kg = -1.000 WHERE id = :lid"),
                {"lid": scenario["issued_line_id"]},
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_issue_delete_rejected(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="hard-deleted|not permitted"):
            conn.execute(
                text("DELETE FROM finished_goods_ledger_entries WHERE id = :lid"), {"lid": scenario["issued_line_id"]}
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_incomplete_lineage_rejects_dispatch(test_engine) -> None:
    """A finished-goods lot whose packing event has since lost its own
    input lines (breaking traceability back to a harvest/crop batch) must
    be rejected outright by the dispatch command, not silently dispatched
    against an unresolvable lineage. Built by packing normally (a fully
    CMP-015/016-valid event/input-line/debit/lot/receipt chain), then
    privilege-deleting just the packing input line (leaving the receipt
    and lot otherwise intact)."""
    s = build_committed_scenario(test_engine, lot_a_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        fg_lot_id, packing_event_id = pack_one(s, session, package_count=1, packed_output_weight_kg=Decimal("1.000"))
        session.commit()
        session.close()
        conn.close()

        require_cmp_test(test_engine)
        bypass_conn = test_engine.connect()
        trans = bypass_conn.begin()
        bypass_conn.execute(text("SET session_replication_role = replica"))
        bypass_conn.execute(
            text("DELETE FROM packing_input_lines WHERE packing_event_id = :eid"), {"eid": packing_event_id}
        )
        bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
        bypass_conn.close()

        conn2 = test_engine.connect()
        session2 = Session(bind=conn2)
        try:
            with pytest.raises(DispatchFinishedGoodsLotNotFoundError):
                dispatch_service.record_dispatch(
                    session2, tenant_id=s["tenant_id"], farm_id=s["farm_id"], actor_user_id=s["user_id"],
                    client_command_id=uuid.uuid4(), effective_time=_now(), code=f"DISP-{s['suffix']}",
                    external_reference=None, note=None,
                    lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1}],
                )
        finally:
            session2.close()
            conn2.close()
    finally:
        cleanup_scenario(test_engine, s["tenant_id"])
