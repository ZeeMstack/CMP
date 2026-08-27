"""CMP-015 database-level integrity verification: proves the packing
tables' insert-integrity and deferred-reconciliation rules are
independently enforced by the database against direct SQL, not only by
the Python service layer. One committed scenario (two harvested lots, one
already-successful packing event consuming part of lot A) is built once
via a module-scoped fixture; every test attempts a direct-SQL statement
that must be rejected (or, for the deferred-reconciliation test, commits
and is caught by the deferred trigger) and rolls its own connection back
afterward so the shared baseline is never mutated between tests."""
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
    s = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None, lot_b_weight="10.000", lot_b_count=None)
    conn = test_engine.connect()
    session = Session(bind=conn)
    event = packing_service.record_packing(
        session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], actor_user_id=s["user_id"],
        client_command_id=uuid.uuid4(), pack_specification_version_id=s["pack_specification_version_id"],
        effective_time=_now(), finished_goods_lot_code=f"FG-{s['suffix']}",
        package_count=1, packed_output_weight_kg=Decimal("3.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"graded_produce_lot_id": s["gpl_a_id"], "consumed_weight_kg": Decimal("3.000"), "consumed_whole_unit_count": None, "note": None}],
    )
    detail = packing_service.get_packing_event(session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], packing_event_id=event.id)
    s["packing_event_id"] = event.id
    s["packing_event_effective_time"] = event.effective_time
    s["existing_input_line_id"] = detail.input_lines[0].id
    session.close()
    conn.close()
    yield s
    cleanup_scenario(test_engine, s["tenant_id"])


def _rollback_only(test_engine, sql: str, params: dict):
    """Runs one direct-SQL statement in its own transaction and always
    rolls it back, so a passing (row inserted) or failing (exception)
    attempt never mutates the shared module-scoped baseline."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text(sql), params)
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_overdraw_rejected(scenario, test_engine) -> None:
    """GPL B has 10kg available (untouched by the fixture's own packing,
    which only consumed from GPL A). A direct-SQL packing_input_lines
    insert for 11kg must be rejected by the v3 trigger's own balance check
    (POSTHARVEST-OPS-001E moved balance sufficiency to the input-line
    insert itself, ahead of the ledger insert), independent of the Python
    service layer. Uses GPL B (not GPL A, which already has an input line
    under this packing event) to avoid the one-lot-per-event unique
    constraint firing first."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        line_id = uuid.uuid4()
        with pytest.raises(Exception, match="exceeds source graded produce lot"):
            conn.execute(
                text(
                    "INSERT INTO packing_input_lines "
                    "(id, tenant_id, farm_id, packing_event_id, graded_produce_lot_id, consumed_weight_kg, "
                    "consumed_whole_unit_count, note) "
                    "VALUES (:id, :tid, :fid, :eid, :lid, 11.000, NULL, NULL)"
                ),
                {"id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                 "eid": scenario["packing_event_id"], "lid": scenario["gpl_b_id"]},
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_malformed_ledger_projection_rejected(scenario, test_engine) -> None:
    """A packing_consumption row whose weight does not match the negative
    of its own input line's consumed weight must be rejected."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        line_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO packing_input_lines "
                "(id, tenant_id, farm_id, packing_event_id, graded_produce_lot_id, consumed_weight_kg, "
                "consumed_whole_unit_count, note) "
                "VALUES (:id, :tid, :fid, :eid, :lid, 1.000, NULL, NULL)"
            ),
            {"id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
             "eid": scenario["packing_event_id"], "lid": scenario["gpl_b_id"]},
        )
        with pytest.raises(Exception, match="does not match the negative"):
            conn.execute(
                text(
                    "INSERT INTO graded_produce_lot_ledger_entries "
                    "(id, tenant_id, farm_id, graded_produce_lot_id, grading_event_id, packing_event_id, entry_kind, "
                    "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "VALUES (:id, :tid, :fid, :lid, NULL, :eid, 'packing_consumption', -999.000, NULL, :eff, now(), :uid, NULL)"
                ),
                {"id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "lid": scenario["gpl_b_id"],
                 "eid": scenario["packing_event_id"], "eff": scenario["packing_event_effective_time"],
                 "uid": scenario["user_id"]},
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_unknown_entry_kind_rejected(scenario, test_engine) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="unknown ledger entry kind"):
            conn.execute(
                text(
                    "INSERT INTO graded_produce_lot_ledger_entries "
                    "(id, tenant_id, farm_id, graded_produce_lot_id, grading_event_id, packing_event_id, entry_kind, "
                    "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "VALUES (:id, :tid, :fid, :lid, NULL, :eid, 'future_kind', -1.000, NULL, :eff, now(), :uid, NULL)"
                ),
                {"id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                 "lid": scenario["gpl_b_id"], "eid": scenario["packing_event_id"],
                 "eff": scenario["packing_event_effective_time"], "uid": scenario["user_id"]},
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_typed_source_xor_rejected(scenario, test_engine) -> None:
    """A packing_consumption row with NULL packing_event_id/harvest_event_id
    is unrepresentable: the v2 trigger's own input-line lookup (keyed on
    NEW.id, deterministic-identity convention) fails first, before the row
    could ever reach the typed-source-shape CHECK — a second, independent
    line of defense for any row shape that ever slipped past the trigger."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="packing input line not found for ledger debit"):
            conn.execute(
                text(
                    "INSERT INTO graded_produce_lot_ledger_entries "
                    "(id, tenant_id, farm_id, graded_produce_lot_id, grading_event_id, packing_event_id, entry_kind, "
                    "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "VALUES (:id, :tid, :fid, :lid, NULL, NULL, 'packing_consumption', -1.000, NULL, :eff, now(), :uid, NULL)"
                ),
                {"id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                 "lid": scenario["gpl_b_id"], "eff": scenario["packing_event_effective_time"],
                 "uid": scenario["user_id"]},
            )
    finally:
        trans.rollback()
        conn.close()




@pytest.mark.integration
def test_direct_sql_positive_weight_rejected_for_packing_consumption(scenario, test_engine) -> None:
    """The kind-signed weight envelope CHECK, reached directly by bypassing
    the v2 trigger (session_replication_role = replica, which the earlier
    lesson from CMP-014 established bypasses triggers but never CHECK
    constraints) — a packing_consumption row can never carry a positive
    delta, independent of whatever the trigger itself would have caught."""
    from tests._packing_scenario import require_cmp_test

    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        with pytest.raises(Exception, match="ck_graded_produce_lot_ledger_entries_weight_envelope"):
            conn.execute(
                text(
                    "INSERT INTO graded_produce_lot_ledger_entries "
                    "(id, tenant_id, farm_id, graded_produce_lot_id, grading_event_id, packing_event_id, entry_kind, "
                    "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "VALUES (:id, :tid, :fid, :lid, NULL, :eid, 'packing_consumption', 1.000, NULL, :eff, now(), :uid, NULL)"
                ),
                {"id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                 "lid": scenario["gpl_b_id"], "eid": scenario["packing_event_id"],
                 "eff": scenario["packing_event_effective_time"], "uid": scenario["user_id"]},
            )
    finally:
        trans.rollback()
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        conn.close()


@pytest.mark.integration
def test_cmp014_harvest_receipt_insert_still_works_via_v2_trigger(scenario, test_engine) -> None:
    """Regression: the v2 trigger's harvest_receipt branch must still
    accept a well-formed, deterministic receipt exactly like CMP-014's
    original function did — proven here by re-deriving lot B's own
    already-existing receipt fields and re-affirming they satisfy the v2
    function (indirectly, by confirming the original insert succeeded and
    is still queryable with entry_kind = 'harvest_receipt'). Unaffected by
    POSTHARVEST-OPS-001E -- produce_lot_ledger_entries no longer has a
    packing_event_id column at all (Packing debits GradedProduceLot
    balance exclusively now), so that column is dropped from this read."""
    conn = test_engine.connect()
    row = conn.execute(
        text(
            "SELECT entry_kind, harvest_event_id FROM produce_lot_ledger_entries "
            "WHERE produce_lot_id = :lid AND entry_kind = 'harvest_receipt'"
        ),
        {"lid": scenario["lot_b_id"]},
    ).one()
    conn.close()
    assert row.entry_kind == "harvest_receipt"
    assert row.harvest_event_id is not None


@pytest.mark.integration
def test_late_input_line_without_matching_debit_fails_deferred_reconciliation(scenario, test_engine) -> None:
    """A direct-SQL input line inserted against an existing, already-
    reconciled packing event without its matching ledger debit must fail
    the deferred packing-reconciliation trigger at commit."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(
            text(
                "INSERT INTO packing_input_lines "
                "(id, tenant_id, farm_id, packing_event_id, graded_produce_lot_id, consumed_weight_kg, "
                "consumed_whole_unit_count, note) "
                "VALUES (:id, :tid, :fid, :eid, :lid, 1.000, NULL, NULL)"
            ),
            {"id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
             "eid": scenario["packing_event_id"], "lid": scenario["gpl_b_id"]},
        )
        with pytest.raises(Exception, match="input-line count does not match graded ledger-debit count"):
            trans.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_direct_sql_debit_referencing_wrong_lot_rejected(scenario, test_engine) -> None:
    """A packing_consumption row sharing its id with a real (but not yet
    debited) input line — the deterministic identity convention — but
    naming a *different* produce lot than that line's own must be
    rejected. Uses a fresh input line under a second packing_event (not
    the fixture's own, already-complete one) so the ledger id doesn't
    collide with an existing PK."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        event_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO packing_events "
                "(id, tenant_id, farm_id, crop_id, variety_id, pack_specification_version_id, "
                "total_input_weight_kg, packed_output_weight_kg, "
                "process_loss_weight_kg, rejected_weight_kg, effective_time, actor_user_id, client_command_id, "
                "request_fingerprint, note) "
                "SELECT :id, tenant_id, farm_id, crop_id, variety_id, :specid, 1.000, 1.000, 0, 0, :eff, :uid, "
                "gen_random_uuid(), 'x', NULL FROM harvested_produce_lots WHERE id = :lid"
            ),
            {"id": event_id, "eff": scenario["packing_event_effective_time"], "uid": scenario["user_id"],
             "lid": scenario["lot_b_id"], "specid": scenario["pack_specification_version_id"]},
        )
        line_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO packing_input_lines "
                "(id, tenant_id, farm_id, packing_event_id, graded_produce_lot_id, consumed_weight_kg, "
                "consumed_whole_unit_count, note) "
                "VALUES (:id, :tid, :fid, :eid, :lid, 1.000, NULL, NULL)"
            ),
            {"id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "eid": event_id,
             "lid": scenario["gpl_b_id"]},
        )
        with pytest.raises(Exception, match="does not match its input line"):
            conn.execute(
                text(
                    "INSERT INTO graded_produce_lot_ledger_entries "
                    "(id, tenant_id, farm_id, graded_produce_lot_id, grading_event_id, packing_event_id, entry_kind, "
                    "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
                    "VALUES (:id, :tid, :fid, :wrong_lid, NULL, :eid, 'packing_consumption', -1.000, NULL, :eff, now(), :uid, NULL)"
                ),
                {"id": line_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                 "wrong_lid": scenario["gpl_a_id"], "eid": event_id,
                 "eff": scenario["packing_event_effective_time"], "uid": scenario["user_id"]},
            )
    finally:
        trans.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_count_overdraw_rejected(test_engine) -> None:
    """A count-tracked lot's own dedicated scenario (module fixture above
    uses count=None lots) — a direct-SQL debit whose count exceeds the
    lot's available count must be rejected by the v2 trigger."""
    from sqlalchemy.orm import Session

    from tests._packing_scenario import build_committed_scenario, cleanup_scenario

    s = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=40)
    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    event = packing_service.record_packing(
        setup_session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], actor_user_id=s["user_id"],
        client_command_id=uuid.uuid4(), pack_specification_version_id=s["pack_specification_version_id"],
        effective_time=_now(), finished_goods_lot_code=f"FG-{s['suffix']}",
        package_count=1, packed_output_weight_kg=Decimal("3.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"graded_produce_lot_id": s["gpl_a_id"], "consumed_weight_kg": Decimal("3.000"), "consumed_whole_unit_count": 12, "note": None}],
    )
    setup_session.close()
    setup_conn.close()

    # GPL A has 7kg / 28 units remaining. A direct-SQL debit for 1kg but
    # 999 units must be rejected on the count check, not the weight check.
    # Uses a second, fresh packing_event (not the setup event above, which
    # already has an input line for GPL A — the one-lot-per-event unique
    # constraint would otherwise fire first).
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        event_id = uuid.uuid4()
        event_effective_time = _now()
        conn.execute(
            text(
                "INSERT INTO packing_events "
                "(id, tenant_id, farm_id, crop_id, variety_id, pack_specification_version_id, "
                "total_input_weight_kg, packed_output_weight_kg, "
                "process_loss_weight_kg, rejected_weight_kg, effective_time, actor_user_id, client_command_id, "
                "request_fingerprint, note) "
                "SELECT :id, tenant_id, farm_id, crop_id, variety_id, :specid, 1.000, 1.000, 0, 0, :eff, :uid, "
                "gen_random_uuid(), 'x', NULL FROM harvested_produce_lots WHERE id = :lid"
            ),
            {"id": event_id, "eff": event_effective_time, "uid": s["user_id"], "lid": s["lot_a_id"],
             "specid": s["pack_specification_version_id"]},
        )
        line_id = uuid.uuid4()
        with pytest.raises(Exception, match="exceeds source graded produce lot"):
            conn.execute(
                text(
                    "INSERT INTO packing_input_lines "
                    "(id, tenant_id, farm_id, packing_event_id, graded_produce_lot_id, consumed_weight_kg, "
                    "consumed_whole_unit_count, note) "
                    "VALUES (:id, :tid, :fid, :eid, :lid, 1.000, 999, NULL)"
                ),
                {"id": line_id, "tid": s["tenant_id"], "fid": s["farm_id"], "eid": event_id, "lid": s["gpl_a_id"]},
            )
    finally:
        trans.rollback()
        conn.close()
        cleanup_scenario(test_engine, s["tenant_id"])


@pytest.mark.integration
def test_direct_sql_residual_weight_count_mismatch_rejected(test_engine) -> None:
    """Direct-SQL proof (bypassing the service's own Python-level residual
    check) that the v2 trigger independently rejects a debit that would
    leave the lot with weight at zero but count still positive."""
    from sqlalchemy.orm import Session

    from tests._packing_scenario import build_committed_scenario, cleanup_scenario

    s = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=40)
    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    event = packing_service.record_packing(
        setup_session, tenant_id=s["tenant_id"], farm_id=s["farm_id"], actor_user_id=s["user_id"],
        client_command_id=uuid.uuid4(), pack_specification_version_id=s["pack_specification_version_id"],
        effective_time=_now(), finished_goods_lot_code=f"FG-{s['suffix']}",
        package_count=1, packed_output_weight_kg=Decimal("3.000"), process_loss_weight_kg=Decimal("0"),
        rejected_weight_kg=Decimal("0"), note=None,
        input_lines=[{"graded_produce_lot_id": s["gpl_a_id"], "consumed_weight_kg": Decimal("3.000"), "consumed_whole_unit_count": 12, "note": None}],
    )
    setup_session.close()
    setup_conn.close()

    # GPL A has 7kg / 28 units remaining. Consuming all 7kg but only 20 of
    # the 28 units would leave (weight=0, count=8) — a mismatched residual.
    # Uses a second, fresh packing_event (see comment in the count-overdraw
    # test above for why the setup event can't be reused).
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        event_id = uuid.uuid4()
        event_effective_time = _now()
        conn.execute(
            text(
                "INSERT INTO packing_events "
                "(id, tenant_id, farm_id, crop_id, variety_id, pack_specification_version_id, "
                "total_input_weight_kg, packed_output_weight_kg, "
                "process_loss_weight_kg, rejected_weight_kg, effective_time, actor_user_id, client_command_id, "
                "request_fingerprint, note) "
                "SELECT :id, tenant_id, farm_id, crop_id, variety_id, :specid, 7.000, 7.000, 0, 0, :eff, :uid, "
                "gen_random_uuid(), 'x', NULL FROM harvested_produce_lots WHERE id = :lid"
            ),
            {"id": event_id, "eff": event_effective_time, "uid": s["user_id"], "lid": s["lot_a_id"],
             "specid": s["pack_specification_version_id"]},
        )
        line_id = uuid.uuid4()
        with pytest.raises(Exception, match="mismatched residual weight/count"):
            conn.execute(
                text(
                    "INSERT INTO packing_input_lines "
                    "(id, tenant_id, farm_id, packing_event_id, graded_produce_lot_id, consumed_weight_kg, "
                    "consumed_whole_unit_count, note) "
                    "VALUES (:id, :tid, :fid, :eid, :lid, 7.000, 20, NULL)"
                ),
                {"id": line_id, "tid": s["tenant_id"], "fid": s["farm_id"], "eid": event_id, "lid": s["gpl_a_id"]},
            )
    finally:
        trans.rollback()
        conn.close()
        cleanup_scenario(test_engine, s["tenant_id"])
