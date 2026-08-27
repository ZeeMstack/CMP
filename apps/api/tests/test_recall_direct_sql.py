"""CMP-020 direct-SQL containment tests: every write-path containment gate
must be enforced by the database itself, not only by the service layer --
a direct-SQL bypass of `batch_derivation_service`/`packing_service`/
`finished_goods_storage_service`/`dispatch_service` must still be rejected
by the versioned trigger at the authoritative source-row insertion point.

`place`/`transfer` of a recalled lot succeeding, and containment lifting
after case close, are already proven at the exact same trigger boundary
by `test_recall_containment.py`'s service-level calls (a service call is
just an ordinary INSERT as far as the trigger is concerned) -- this file
adds only the raw-SQL-bypass proof for the four *rejecting* gates, plus
one explicit release-after-close round trip via direct SQL."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services import recall_service
from tests._packing_scenario import build_packing_scaffold, grade_entire_lot, require_cmp_test
from tests._recall_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    build_workflow_scaffold,
    cleanup_recall_scenario,
    close_case,
    committed_connection,
    create_cold_store_position,
    harvest_all,
    now,
    open_case,
    pack_lot,
    place,
    sow_new_batch,
)


@pytest.mark.integration
def test_direct_sql_derivation_from_recalled_batch_rejected(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            session.commit()
            batch_id = scaffold["batch"].id
            farm_id, user_id = farm.id, user.id
            run_id, stage_id = session.execute(
                text("SELECT id, workflow_stage_id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"),
                {"bid": batch_id},
            ).one()
            wf_id, wfv_id = scaffold["workflow"].id, scaffold["version"].id

            open_case(session, tenant, farm, user, crop_batch_id=batch_id)
            session.commit()

        require_cmp_test(test_engine)
        bypass_conn = test_engine.connect()
        trans = bypass_conn.begin()
        try:
            event_id = uuid.uuid4()
            bypass_conn.execute(
                text(
                    "INSERT INTO batch_derivation_events "
                    "(id, tenant_id, farm_id, derivation_kind, workflow_id, workflow_version_id, "
                    "inherited_workflow_stage_id, effective_time, actor_user_id, client_command_id, "
                    "request_fingerprint, note) "
                    "VALUES (:id, :tid, :fid, 'split', :wfid, :wfvid, :stage, :eff, :uid, :ccid, 'fp', NULL)"
                ),
                {"id": event_id, "tid": tenant_id, "fid": farm_id, "wfid": wf_id, "wfvid": wfv_id,
                 "stage": stage_id, "eff": now(), "uid": user_id, "ccid": uuid.uuid4()},
            )
            with pytest.raises(Exception, match="contained by an open recall case"):
                bypass_conn.execute(
                    text(
                        "INSERT INTO batch_derivation_sources "
                        "(id, tenant_id, farm_id, derivation_event_id, source_batch_id, "
                        "source_batch_stage_run_id, recorded_plant_quantity_total, "
                        "recorded_carrier_assignment_count) "
                        "VALUES (:id, :tid, :fid, :eid, :bid, :run, 20, 1)"
                    ),
                    {"id": uuid.uuid4(), "tid": tenant_id, "fid": farm_id, "eid": event_id, "bid": batch_id, "run": run_id},
                )
        finally:
            trans.rollback()
            bypass_conn.close()
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_direct_sql_packing_consumption_from_recalled_produce_lot_rejected(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            wf_scaffold = build_workflow_scaffold(session, tenant, user, farm)
            batch1 = sow_new_batch(session, tenant, user, farm, wf_scaffold, carrier_count=1, suffix="ds-1")
            batch2 = sow_new_batch(session, tenant, user, farm, wf_scaffold, carrier_count=1, suffix="ds-2")
            _, lot1 = harvest_all(session, tenant, user, farm, batch_id=batch1["batch"].id, assignment_ids=batch1["assignment_ids"], weight_per_line=Decimal("3.000"))
            _, lot2 = harvest_all(session, tenant, user, farm, batch_id=batch2["batch"].id, assignment_ids=batch2["assignment_ids"], weight_per_line=Decimal("2.000"))
            fg_lot_id, event_id = pack_lot(session, tenant, user, farm, produce_lot_id=lot2, weight=Decimal("2.000"), package_count=2)
            # POSTHARVEST-OPS-001E: Packing consumes GradedProduceLot, not
            # HarvestedProduceLot directly -- grade lot1's full weight into
            # its own GPL BEFORE the recall case opens (Grading itself would
            # otherwise be blocked from a source lot already under an open
            # recall), so the later raw-SQL packing_input_lines insert has a
            # real GPL to reference.
            crop_id = session.execute(text("SELECT crop_id FROM harvested_produce_lots WHERE id = :lid"), {"lid": lot1}).scalar_one()
            scaffold = build_packing_scaffold(session, tenant, user, farm, crop_id=crop_id, suffix="ds-lot1")
            gpl1 = grade_entire_lot(
                session, tenant, user, farm, produce_lot_id=lot1, weight=Decimal("3.000"), count=None,
                scaffold=scaffold, suffix="ds-lot1",
            )
            session.commit()

            open_case(session, tenant, farm, user, harvested_produce_lot_id=lot1)
            session.commit()

        require_cmp_test(test_engine)
        with test_engine.connect() as conn:
            with pytest.raises(Exception, match="source graded produce lot .* upstream harvested produce lot is contained by an open recall case"):
                with conn.begin():
                    conn.execute(
                        text(
                            "INSERT INTO packing_input_lines "
                            "(id, tenant_id, farm_id, packing_event_id, graded_produce_lot_id, "
                            "consumed_weight_kg, consumed_whole_unit_count, note) "
                            "VALUES (:id, :tid, :fid, :eid, :lid, :w, NULL, NULL)"
                        ),
                        {"id": uuid.uuid4(), "tid": tenant_id, "fid": farm_id, "eid": event_id, "lid": gpl1, "w": Decimal("1.000")},
                    )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_direct_sql_packing_consumption_from_recalled_batch_rejected(test_engine) -> None:
    """The batch is recalled (batch-source case); a *second* carrier
    assignment is harvested from it only *after* the case opens -- CMP-020
    does not block harvest, so this later produce lot is never itself in
    any produce-lot scope. Packing consumption of it must still be
    rejected because its crop batch remains contained -- isolating the
    batch-level containment check from the produce-lot-level one.

    POSTHARVEST-OPS-001E: Packing consumes GradedProduceLot, not
    HarvestedProduceLot directly, and Grading's own (pre-existing, 001C)
    insert-integrity trigger independently checks the SAME live batch
    containment -- meaning a real `grading_service.record_grading` call
    against lot1b would now be rejected by Grading itself before Packing
    ever got a chance to. To keep isolating Packing's OWN batch-level
    check specifically (this file's whole point), lot1b's GradedProduceLot
    is constructed directly via `session_replication_role = replica`
    (bypassing Grading's trigger only), then the packing_input_lines
    insert below goes through PACKING's own, real, unbypassed trigger."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            user_id = user.id
            wf_scaffold = build_workflow_scaffold(session, tenant, user, farm)
            batch1 = sow_new_batch(session, tenant, user, farm, wf_scaffold, carrier_count=2, suffix="ds-batch")
            batch2 = sow_new_batch(session, tenant, user, farm, wf_scaffold, carrier_count=1, suffix="ds-other")
            _, lot1a = harvest_all(session, tenant, user, farm, batch_id=batch1["batch"].id, assignment_ids=batch1["assignment_ids"][:1], weight_per_line=Decimal("3.000"))
            _, lot2 = harvest_all(session, tenant, user, farm, batch_id=batch2["batch"].id, assignment_ids=batch2["assignment_ids"], weight_per_line=Decimal("2.000"))
            session.commit()
            batch1_id = batch1["batch"].id

            open_case(session, tenant, farm, user, crop_batch_id=batch1_id)
            session.commit()

            # Harvest is not blocked by containment -- this produce lot is
            # created strictly after the case's scope was already frozen,
            # so it was never written into recall_scope_produce_lots.
            _, lot1b = harvest_all(session, tenant, user, farm, batch_id=batch1_id, assignment_ids=batch1["assignment_ids"][1:], weight_per_line=Decimal("1.000"))
            session.commit()

            # The packing event's own effective_time must not precede
            # lot1b's -- pack lot2 only now, after lot1b's harvest.
            fg_lot_id, event_id = pack_lot(session, tenant, user, farm, produce_lot_id=lot2, weight=Decimal("2.000"), package_count=2)
            session.commit()

            crop_id = session.execute(text("SELECT crop_id FROM harvested_produce_lots WHERE id = :lid"), {"lid": lot1b}).scalar_one()
            scaffold = build_packing_scaffold(session, tenant, user, farm, crop_id=crop_id, suffix="ds-batch-recalled")
            session.commit()

        require_cmp_test(test_engine)
        grading_event_id = uuid.uuid4()
        gpl1b = uuid.uuid4()
        bypass_conn = test_engine.connect()
        bypass_trans = bypass_conn.begin()
        bypass_conn.execute(text("SET session_replication_role = replica"))
        bypass_conn.execute(
            text(
                "INSERT INTO grading_events "
                "(id, tenant_id, farm_id, source_harvested_produce_lot_id, processing_hall_location_id, "
                "effective_time, recorded_time, actor_user_id, client_command_id, request_fingerprint, note, "
                "input_presented_weight_kg, input_presented_whole_unit_count, "
                "rejected_weight_kg, rejected_whole_unit_count, loss_weight_kg, loss_whole_unit_count, "
                "sample_weight_kg, sample_whole_unit_count, remainder_weight_kg, remainder_whole_unit_count) "
                "VALUES (:id, :tid, :fid, :lid, :hall, :eff, :eff, :uid, :ccid, 'fp', NULL, "
                "1.000, NULL, 0, NULL, 0, NULL, 0, NULL, 0, NULL)"
            ),
            {
                "id": grading_event_id, "tid": tenant_id, "fid": farm_id, "lid": lot1b,
                "hall": scaffold["packing_hall_location_id"], "eff": now(), "uid": user_id, "ccid": uuid.uuid4(),
            },
        )
        bypass_conn.execute(
            text(
                "INSERT INTO graded_produce_lots "
                "(id, tenant_id, farm_id, grading_event_id, crop_id, variety_id, grade_definition_version_id, "
                "code, original_received_weight_kg, original_received_whole_unit_count, effective_time, recorded_at) "
                "SELECT :id, :tid, :fid, :geid, crop_id, variety_id, :gdvid, 'GPL-DS-BATCH', 1.000, NULL, :eff, :eff "
                "FROM harvested_produce_lots WHERE id = :lid"
            ),
            {
                "id": gpl1b, "tid": tenant_id, "fid": farm_id, "geid": grading_event_id,
                "gdvid": scaffold["grade_definition_version_id"], "eff": now(), "lid": lot1b,
            },
        )
        bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
        bypass_trans.commit()
        bypass_conn.close()

        with test_engine.connect() as conn:
            with pytest.raises(Exception, match="upstream crop batch is contained by an open recall case"):
                with conn.begin():
                    conn.execute(
                        text(
                            "INSERT INTO packing_input_lines "
                            "(id, tenant_id, farm_id, packing_event_id, graded_produce_lot_id, "
                            "consumed_weight_kg, consumed_whole_unit_count, note) "
                            "VALUES (:id, :tid, :fid, :eid, :lid, :w, NULL, NULL)"
                        ),
                        {"id": uuid.uuid4(), "tid": tenant_id, "fid": farm_id, "eid": event_id, "lid": gpl1b, "w": Decimal("1.000")},
                    )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_direct_sql_release_of_recalled_fg_lot_rejected_then_allowed_after_close(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id, user_id = farm.id, user.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            pos = create_cold_store_position(session, tenant, user, farm)
            pos_id = pos.id
            place(session, tenant, user, farm, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_id, weight=Decimal("5.000"), count=5)
            session.commit()

            case = open_case(session, tenant, farm, user, finished_goods_lot_id=fg_lot_id)
            session.commit()
            case_id = case.id

        require_cmp_test(test_engine)
        with test_engine.connect() as conn:
            with pytest.raises(Exception, match="release is blocked"):
                with conn.begin():
                    conn.execute(
                        text(
                            "INSERT INTO finished_goods_storage_movements "
                            "(id, tenant_id, farm_id, finished_goods_lot_id, movement_kind, source_location_id, "
                            "destination_location_id, moved_weight_kg, moved_package_count, effective_time, "
                            "actor_user_id, client_command_id, request_fingerprint, note) "
                            "VALUES (:id, :tid, :fid, :lid, 'release', :src, NULL, :w, :c, :eff, :uid, :ccid, 'fp', NULL)"
                        ),
                        {"id": uuid.uuid4(), "tid": tenant_id, "fid": farm_id, "lid": fg_lot_id, "src": pos_id,
                         "w": Decimal("1.000"), "c": 1, "eff": now(), "uid": user_id, "ccid": uuid.uuid4()},
                    )

        with committed_connection(test_engine) as session2:
            recall_service.close_recall_case(
                session2, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, recall_case_id=case_id,
                client_command_id=uuid.uuid4(), effective_time=now(), close_reason="segregated",
            )
            session2.commit()

        # After close, direct-SQL release succeeds -- containment no longer applies.
        with test_engine.connect() as conn2:
            with conn2.begin():
                conn2.execute(
                    text(
                        "INSERT INTO finished_goods_storage_movements "
                        "(id, tenant_id, farm_id, finished_goods_lot_id, movement_kind, source_location_id, "
                        "destination_location_id, moved_weight_kg, moved_package_count, effective_time, "
                        "actor_user_id, client_command_id, request_fingerprint, note) "
                        "VALUES (:id, :tid, :fid, :lid, 'release', :src, NULL, :w, :c, :eff, :uid, :ccid, 'fp', NULL)"
                    ),
                    {"id": uuid.uuid4(), "tid": tenant_id, "fid": farm_id, "lid": fg_lot_id, "src": pos_id,
                     "w": Decimal("1.000"), "c": 1, "eff": now(), "uid": user_id, "ccid": uuid.uuid4()},
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_direct_sql_dispatch_issue_of_recalled_fg_lot_rejected(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id, user_id = farm.id, user.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()

            case = open_case(session, tenant, farm, user, finished_goods_lot_id=fg_lot_id)
            session.commit()

        require_cmp_test(test_engine)
        bypass_conn = test_engine.connect()
        trans = bypass_conn.begin()
        dispatch_event_id = uuid.uuid4()
        dispatch_line_id = uuid.uuid4()
        eff = now()
        try:
            bypass_conn.execute(text("SET session_replication_role = replica"))
            bypass_conn.execute(
                text(
                    "INSERT INTO dispatch_events "
                    "(id, tenant_id, farm_id, code, client_command_id, request_fingerprint, effective_time, "
                    "actor_user_id, external_reference, note) "
                    "VALUES (:id, :tid, :fid, :code, :ccid, 'fp', :eff, :uid, NULL, NULL)"
                ),
                {"id": dispatch_event_id, "tid": tenant_id, "fid": farm_id, "code": f"DS-{uuid.uuid4().hex[:8]}",
                 "ccid": uuid.uuid4(), "eff": eff, "uid": user_id},
            )
            bypass_conn.execute(
                text(
                    "INSERT INTO dispatch_lines "
                    "(id, tenant_id, farm_id, dispatch_event_id, finished_goods_lot_id, dispatched_weight_kg, "
                    "dispatched_package_count) VALUES (:id, :tid, :fid, :eid, :lid, :w, :c)"
                ),
                {"id": dispatch_line_id, "tid": tenant_id, "fid": farm_id, "eid": dispatch_event_id,
                 "lid": fg_lot_id, "w": Decimal("1.000"), "c": 1},
            )
            recorded_time = bypass_conn.execute(
                text("SELECT recorded_time FROM dispatch_events WHERE id = :id"), {"id": dispatch_event_id}
            ).scalar_one()
            bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
            trans.commit()
        except Exception:
            trans.rollback()
            bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
            bypass_conn.commit()
            bypass_conn.close()
            raise
        bypass_conn.close()

        # Now attempt the ledger insert with ordinary (non-replica) session
        # so the CMP-020 containment trigger actually fires.
        with test_engine.connect() as conn:
            with pytest.raises(Exception, match="is contained by an open recall case"):
                with conn.begin():
                    conn.execute(
                        text(
                            "INSERT INTO finished_goods_ledger_entries "
                            "(id, tenant_id, farm_id, finished_goods_lot_id, packing_event_id, dispatch_line_id, "
                            "entry_kind, weight_delta_kg, package_count_delta, effective_time, recorded_time, "
                            "actor_user_id, note) "
                            "VALUES (:id, :tid, :fid, :lid, NULL, :dlid, 'dispatch_issue', :w, :c, :eff, :rec, :uid, NULL)"
                        ),
                        {"id": dispatch_line_id, "tid": tenant_id, "fid": farm_id, "lid": fg_lot_id,
                         "dlid": dispatch_line_id, "w": Decimal("-1.000"), "c": -1, "eff": eff, "rec": recorded_time,
                         "uid": user_id},
                    )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)
