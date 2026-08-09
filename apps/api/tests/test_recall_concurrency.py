"""CMP-020 concurrency race tests: real two-connection races (same
`threading.Barrier` pattern as `test_dispatch_concurrency.py`/
`test_finished_goods_storage_concurrency.py`), proving each contested
boundary resolves to exactly one serial truth -- never a state where a
downstream operation both escaped a frozen scope AND left that scope
unaware of it."""
import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    batch_derivation_service,
    dispatch_service,
    finished_goods_storage_service,
    lineage_traversal,
    packing_service,
    recall_service,
)
from app.services.errors import RecallContainmentOpenError
from tests._packing_scenario import require_cmp_test
from tests._recall_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    cleanup_recall_scenario,
    committed_connection,
    create_cold_store_position,
    harvest_all,
    now,
    pack_lot,
    place,
)


@pytest.mark.integration
def test_recall_open_vs_batch_derivation_one_serial_truth(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2)
            session.commit()
            farm_id, user_id = farm.id, user.id
            batch_id = scaffold["batch"].id
            assignment_ids = scaffold["assignment_ids"]

        barrier = threading.Barrier(2)
        results: dict[str, tuple] = {}
        effective_time = now()

        def recall_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                case = recall_service.open_recall_case(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
                    client_command_id=uuid.uuid4(), effective_time=effective_time, code=f"RC-RACE-{uuid.uuid4().hex[:8]}",
                    crop_batch_id=batch_id, harvested_produce_lot_id=None, finished_goods_lot_id=None,
                    reason_code="contamination_suspected", reason_text="race",
                )
                session.commit()
                results["recall"] = ("ok", case.id)
            except Exception as exc:
                session.rollback()
                results["recall"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        def derivation_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                event = batch_derivation_service.split_batch(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, batch_id=batch_id,
                    client_command_id=uuid.uuid4(), effective_time=effective_time, note=None,
                    outputs=[
                        {"output_batch_code": f"OUT-A-{uuid.uuid4().hex[:6]}", "source_assignment_ids": assignment_ids[:1]},
                        {"output_batch_code": f"OUT-B-{uuid.uuid4().hex[:6]}", "source_assignment_ids": assignment_ids[1:]},
                    ],
                )
                session.commit()
                results["derivation"] = ("ok", event.id)
            except Exception as exc:
                session.rollback()
                results["derivation"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        t_recall = threading.Thread(target=recall_worker)
        t_deriv = threading.Thread(target=derivation_worker)
        t_recall.start()
        t_deriv.start()
        t_recall.join(timeout=15)
        t_deriv.join(timeout=15)

        assert not t_recall.is_alive() and not t_deriv.is_alive(), "a deadlock would leave a thread hung past the join timeout"

        recall_outcome, deriv_outcome = results["recall"][0], results["derivation"][0]
        # Never both fail, never both succeed with inconsistent state: the
        # batch lock forces exactly one strict ordering.
        assert (recall_outcome, deriv_outcome) in {("ok", "ok"), ("ok", "error"), ("error", "ok")}, results

        if deriv_outcome == "ok":
            # B. derivation committed first -> the recall (which necessarily
            # acquired the batch lock afterward) must include the new
            # descendants in its stable scope.
            assert recall_outcome == "ok"
            case_id = results["recall"][1]
            detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
            assert len(detail["frozen_scope"]["crop_batch_ids"]) == 3, "root + both split outputs must be in scope"
        else:
            # A. recall committed first -> derivation, resuming after the
            # batch lock freed, must see the now-open containment and reject.
            assert recall_outcome == "ok"
            assert isinstance(results["derivation"][1], RecallContainmentOpenError), results["derivation"]
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_open_batch_source_vs_packing_one_serial_truth(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            session.commit()
            farm_id, user_id = farm.id, user.id
            batch_id = scaffold["batch"].id

        barrier = threading.Barrier(2)
        results: dict[str, tuple] = {}
        effective_time = now()

        def recall_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                case = recall_service.open_recall_case(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
                    client_command_id=uuid.uuid4(), effective_time=effective_time, code=f"RC-RACE-{uuid.uuid4().hex[:8]}",
                    crop_batch_id=batch_id, harvested_produce_lot_id=None, finished_goods_lot_id=None,
                    reason_code="contamination_suspected", reason_text="race",
                )
                session.commit()
                results["recall"] = ("ok", case.id)
            except Exception as exc:
                session.rollback()
                results["recall"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        def packing_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                event = packing_service.record_packing(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
                    effective_time=effective_time, finished_goods_lot_code=f"FG-RACE-{uuid.uuid4().hex[:8]}", package_count=5,
                    packed_output_weight_kg=Decimal("5.000"), process_loss_weight_kg=Decimal("0"),
                    rejected_weight_kg=Decimal("0"), note=None,
                    input_lines=[{"harvested_produce_lot_id": produce_lot_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
                )
                session.commit()
                results["packing"] = ("ok", event.id)
            except Exception as exc:
                session.rollback()
                results["packing"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        t_recall = threading.Thread(target=recall_worker)
        t_pack = threading.Thread(target=packing_worker)
        t_recall.start()
        t_pack.start()
        t_recall.join(timeout=15)
        t_pack.join(timeout=15)

        assert not t_recall.is_alive() and not t_pack.is_alive()
        recall_outcome, pack_outcome = results["recall"][0], results["packing"][0]
        assert (recall_outcome, pack_outcome) in {("ok", "ok"), ("ok", "error")}, results

        if pack_outcome == "ok":
            assert recall_outcome == "ok"
            case_id = results["recall"][1]
            detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
            assert detail["frozen_scope"]["finished_goods_lot_ids"] != [], "the packing that committed first must appear in frozen scope"
        else:
            assert isinstance(results["packing"][1], RecallContainmentOpenError), results["packing"]
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_open_produce_lot_source_vs_packing_one_serial_truth(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            session.commit()
            farm_id, user_id = farm.id, user.id

        barrier = threading.Barrier(2)
        results: dict[str, tuple] = {}
        effective_time = now()

        def recall_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                case = recall_service.open_recall_case(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
                    client_command_id=uuid.uuid4(), effective_time=effective_time, code=f"RC-RACE-{uuid.uuid4().hex[:8]}",
                    crop_batch_id=None, harvested_produce_lot_id=produce_lot_id, finished_goods_lot_id=None,
                    reason_code="contamination_suspected", reason_text="race",
                )
                session.commit()
                results["recall"] = ("ok", case.id)
            except Exception as exc:
                session.rollback()
                results["recall"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        def packing_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                event = packing_service.record_packing(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
                    effective_time=effective_time, finished_goods_lot_code=f"FG-RACE-{uuid.uuid4().hex[:8]}", package_count=5,
                    packed_output_weight_kg=Decimal("5.000"), process_loss_weight_kg=Decimal("0"),
                    rejected_weight_kg=Decimal("0"), note=None,
                    input_lines=[{"harvested_produce_lot_id": produce_lot_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
                )
                session.commit()
                results["packing"] = ("ok", event.id)
            except Exception as exc:
                session.rollback()
                results["packing"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        t_recall = threading.Thread(target=recall_worker)
        t_pack = threading.Thread(target=packing_worker)
        t_recall.start()
        t_pack.start()
        t_recall.join(timeout=15)
        t_pack.join(timeout=15)

        assert not t_recall.is_alive() and not t_pack.is_alive()
        recall_outcome, pack_outcome = results["recall"][0], results["packing"][0]
        assert (recall_outcome, pack_outcome) in {("ok", "ok"), ("ok", "error")}, results

        if pack_outcome == "ok":
            assert recall_outcome == "ok"
            case_id = results["recall"][1]
            detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
            assert detail["frozen_scope"]["finished_goods_lot_ids"] != [], "the packing that committed first must appear in frozen scope"
        else:
            assert isinstance(results["packing"][1], RecallContainmentOpenError), results["packing"]
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_open_vs_storage_release_one_serial_truth(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            pos = create_cold_store_position(session, tenant, user, farm)
            pos_id = pos.id
            place(session, tenant, user, farm, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_id, weight=Decimal("5.000"), count=5)
            session.commit()
            farm_id, user_id = farm.id, user.id

        barrier = threading.Barrier(2)
        results: dict[str, tuple] = {}
        effective_time = now()

        def recall_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                case = recall_service.open_recall_case(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
                    client_command_id=uuid.uuid4(), effective_time=effective_time, code=f"RC-RACE-{uuid.uuid4().hex[:8]}",
                    crop_batch_id=None, harvested_produce_lot_id=None, finished_goods_lot_id=fg_lot_id,
                    reason_code="contamination_suspected", reason_text="race",
                )
                session.commit()
                results["recall"] = ("ok", case.id)
            except Exception as exc:
                session.rollback()
                results["recall"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        def release_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                movement = finished_goods_storage_service.record_movement(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
                    effective_time=effective_time, finished_goods_lot_id=fg_lot_id, movement_kind="release",
                    source_location_id=pos_id, destination_location_id=None, moved_weight_kg=Decimal("5.000"),
                    moved_package_count=5, note=None,
                )
                session.commit()
                results["release"] = ("ok", movement.id)
            except Exception as exc:
                session.rollback()
                results["release"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        t_recall = threading.Thread(target=recall_worker)
        t_release = threading.Thread(target=release_worker)
        t_recall.start()
        t_release.start()
        t_recall.join(timeout=15)
        t_release.join(timeout=15)

        assert not t_recall.is_alive() and not t_release.is_alive()
        recall_outcome, release_outcome = results["recall"][0], results["release"][0]
        assert recall_outcome == "ok", results
        if release_outcome == "error":
            assert isinstance(results["release"][1], RecallContainmentOpenError), results["release"]
        # If release won the race, it simply commits before the recall opens
        # against the (already unplaced) resulting state -- also valid.
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_open_vs_dispatch_one_serial_truth(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()
            farm_id, user_id = farm.id, user.id

        barrier = threading.Barrier(2)
        results: dict[str, tuple] = {}
        effective_time = now()

        def recall_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                case = recall_service.open_recall_case(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
                    client_command_id=uuid.uuid4(), effective_time=effective_time, code=f"RC-RACE-{uuid.uuid4().hex[:8]}",
                    crop_batch_id=None, harvested_produce_lot_id=None, finished_goods_lot_id=fg_lot_id,
                    reason_code="contamination_suspected", reason_text="race",
                )
                session.commit()
                results["recall"] = ("ok", case.id)
            except Exception as exc:
                session.rollback()
                results["recall"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        def dispatch_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                event = dispatch_service.record_dispatch(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
                    effective_time=effective_time, code=f"DISP-RACE-{uuid.uuid4().hex[:8]}", external_reference=None, note=None,
                    lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1}],
                )
                session.commit()
                results["dispatch"] = ("ok", event.id)
            except Exception as exc:
                session.rollback()
                results["dispatch"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        t_recall = threading.Thread(target=recall_worker)
        t_dispatch = threading.Thread(target=dispatch_worker)
        t_recall.start()
        t_dispatch.start()
        t_recall.join(timeout=15)
        t_dispatch.join(timeout=15)

        assert not t_recall.is_alive() and not t_dispatch.is_alive()
        recall_outcome, dispatch_outcome = results["recall"][0], results["dispatch"][0]
        assert recall_outcome == "ok", results
        if dispatch_outcome == "ok":
            # A. dispatch committed first -> it must appear as existing
            # dispatch exposure in the case that opened afterward.
            case_id = results["recall"][1]
            detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
            assert len(detail["live_state"]["dispatches"]) == 1
        else:
            # B. recall committed first -> dispatch, resuming after the FG
            # lot lock freed, must see the now-open containment and reject.
            assert isinstance(results["dispatch"][1], RecallContainmentOpenError), results["dispatch"]
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_close_vs_dispatch_one_serial_truth(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()
            farm_id, user_id = farm.id, user.id
            case = recall_service.open_recall_case(
                session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
                effective_time=now(), code=f"RC-{uuid.uuid4().hex[:8]}", crop_batch_id=None,
                harvested_produce_lot_id=None, finished_goods_lot_id=fg_lot_id,
                reason_code="contamination_suspected", reason_text="pre-existing",
            )
            session.commit()
            case_id = case.id

        barrier = threading.Barrier(2)
        results: dict[str, tuple] = {}
        effective_time = now()

        def close_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                closure = recall_service.close_recall_case(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, recall_case_id=case_id,
                    client_command_id=uuid.uuid4(), effective_time=effective_time, close_reason="segregated",
                )
                session.commit()
                results["close"] = ("ok", closure.id)
            except Exception as exc:
                session.rollback()
                results["close"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        def dispatch_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                event = dispatch_service.record_dispatch(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
                    effective_time=effective_time, code=f"DISP-RACE-{uuid.uuid4().hex[:8]}", external_reference=None, note=None,
                    lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1}],
                )
                session.commit()
                results["dispatch"] = ("ok", event.id)
            except Exception as exc:
                session.rollback()
                results["dispatch"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        t_close = threading.Thread(target=close_worker)
        t_dispatch = threading.Thread(target=dispatch_worker)
        t_close.start()
        t_dispatch.start()
        t_close.join(timeout=15)
        t_dispatch.join(timeout=15)

        assert not t_close.is_alive() and not t_dispatch.is_alive()
        assert results["close"][0] == "ok", results

        if results["dispatch"][0] == "error":
            assert isinstance(results["dispatch"][1], RecallContainmentOpenError), results["dispatch"]
            # After close has unconditionally committed, an ordinary retry
            # must now succeed -- containment no longer blocks it.
            with committed_connection(test_engine) as retry_session:
                event = dispatch_service.record_dispatch(
                    retry_session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
                    client_command_id=uuid.uuid4(), effective_time=now(), code=f"DISP-RETRY-{uuid.uuid4().hex[:8]}",
                    external_reference=None, note=None,
                    lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("1.000"), "dispatched_package_count": 1}],
                )
                retry_session.commit()
                assert event.id is not None
        # else: dispatch legitimately won the race and committed before
        # close -- also a valid serial ordering (close still succeeds; the
        # dispatch is simply pre-existing history from before containment
        # was active).
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_open_vs_direct_sql_dispatch_issue_one_serial_truth(test_engine) -> None:
    """The most critical escape path: a direct-SQL writer that bypasses
    `dispatch_service` entirely, racing a concurrent recall open on the
    same finished-goods lot. Both sides explicitly lock the same
    `finished_goods_lots` row first (this test's own direct-SQL side, and
    `_freeze_finished_goods_lot_source_scope` on the recall side) --
    mirroring `test_dispatch_concurrency.py`'s own direct-SQL discipline --
    so the database's row lock is the sole arbiter of a single serial
    order. Forbidden: recall commits, then a direct-SQL dispatch commits
    afterward based on a stale pre-recall containment read -- this is
    exactly the check-before-lock race CMP-020's own trigger review found
    and fixed (the v4 ledger trigger now locks the finished-goods lot
    before evaluating containment, not after)."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()
            farm_id, user_id = farm.id, user.id

        require_cmp_test(test_engine)
        barrier = threading.Barrier(2)
        results: dict[str, tuple] = {}
        effective_time = now()

        def recall_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                case = recall_service.open_recall_case(
                    session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
                    client_command_id=uuid.uuid4(), effective_time=effective_time, code=f"RC-DSQL-RACE-{uuid.uuid4().hex[:8]}",
                    crop_batch_id=None, harvested_produce_lot_id=None, finished_goods_lot_id=fg_lot_id,
                    reason_code="contamination_suspected", reason_text="direct-sql race",
                )
                session.commit()
                results["recall"] = ("ok", case.id)
            except Exception as exc:
                session.rollback()
                results["recall"] = ("error", exc)
            finally:
                session.close()
                conn.close()

        def direct_sql_dispatch_worker() -> None:
            conn = test_engine.connect()
            trans = conn.begin()
            dispatch_event_id = uuid.uuid4()
            dispatch_line_id = uuid.uuid4()
            try:
                barrier.wait(timeout=10)
                # The contested resource, locked explicitly and first --
                # the same discipline the (now-fixed) trigger and
                # dispatch_service itself both use -- so whichever
                # transaction arrives first proceeds through the whole
                # sequence uninterrupted, and the other waits here.
                conn.execute(text("SELECT 1 FROM finished_goods_lots WHERE id = :lid FOR UPDATE"), {"lid": fg_lot_id})
                conn.execute(
                    text(
                        "INSERT INTO dispatch_events "
                        "(id, tenant_id, farm_id, code, client_command_id, request_fingerprint, effective_time, "
                        "actor_user_id, external_reference, note) "
                        "VALUES (:id, :tid, :fid, :code, :ccid, 'fp', :eff, :uid, NULL, NULL)"
                    ),
                    {"id": dispatch_event_id, "tid": tenant_id, "fid": farm_id, "code": f"DSQL-RACE-{uuid.uuid4().hex[:8]}",
                     "ccid": uuid.uuid4(), "eff": effective_time, "uid": user_id},
                )
                conn.execute(
                    text(
                        "INSERT INTO dispatch_lines "
                        "(id, tenant_id, farm_id, dispatch_event_id, finished_goods_lot_id, dispatched_weight_kg, "
                        "dispatched_package_count) VALUES (:id, :tid, :fid, :eid, :lid, 1.000, 1)"
                    ),
                    {"id": dispatch_line_id, "tid": tenant_id, "fid": farm_id, "eid": dispatch_event_id, "lid": fg_lot_id},
                )
                recorded_time = conn.execute(
                    text("SELECT recorded_time FROM dispatch_events WHERE id = :eid"), {"eid": dispatch_event_id}
                ).scalar_one()
                # This INSERT's own (now-fixed) trigger re-locks the same
                # lot row FOR UPDATE first (a no-op within this same
                # transaction) and only then evaluates containment --
                # never the reverse.
                conn.execute(
                    text(
                        "INSERT INTO finished_goods_ledger_entries "
                        "(id, tenant_id, farm_id, finished_goods_lot_id, dispatch_line_id, entry_kind, "
                        "weight_delta_kg, package_count_delta, effective_time, recorded_time, actor_user_id, note) "
                        "VALUES (:id, :tid, :fid, :lid, :line_id, 'dispatch_issue', -1.000, -1, :eff, :rec, :uid, NULL)"
                    ),
                    {"id": dispatch_line_id, "tid": tenant_id, "fid": farm_id, "lid": fg_lot_id,
                     "line_id": dispatch_line_id, "eff": effective_time, "rec": recorded_time, "uid": user_id},
                )
                trans.commit()
                results["dispatch"] = ("ok", dispatch_line_id)
            except Exception as exc:
                trans.rollback()
                results["dispatch"] = ("rejected", exc)
            finally:
                conn.close()

        t_recall = threading.Thread(target=recall_worker)
        t_dispatch = threading.Thread(target=direct_sql_dispatch_worker)
        t_recall.start()
        t_dispatch.start()
        t_recall.join(timeout=15)
        t_dispatch.join(timeout=15)

        assert not t_recall.is_alive() and not t_dispatch.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        assert results["recall"][0] == "ok", results

        if results["dispatch"][0] == "ok":
            # A. direct-SQL dispatch locked/committed first -> the recall,
            # which necessarily opened afterward, must show it as existing
            # prior exposure.
            case_id = results["recall"][1]
            detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
            assert len(detail["live_state"]["dispatches"]) == 1
        else:
            # B. recall locked/committed first -> the waiting direct-SQL
            # dispatch woke to find the lot already contained and was
            # rejected by the trigger's own (now-locked-first) check --
            # never a stale pre-recall read slipping through afterward.
            assert "is contained by an open recall case" in str(results["dispatch"][1]), results["dispatch"]
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_case_detail_snapshot_is_never_mixed_across_a_concurrent_placement_commit(test_engine) -> None:
    """Mirrors `test_traceability_concurrency.py`'s own proof, applied to
    `recall_service.get_recall_case`: its dedicated REPEATABLE READ / READ
    ONLY snapshot connection must return identical live_state figures
    across two reads inside the same snapshot even while a concurrent,
    permitted `place` commits in between them -- and only a brand-new
    request opened afterward may see the updated placement."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            pos = create_cold_store_position(session, tenant, user, farm)
            pos_id = pos.id
            session.commit()
            farm_id, user_id = farm.id, user.id

            case = recall_service.open_recall_case(
                session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
                effective_time=now(), code=f"RC-SNAPSHOT-{uuid.uuid4().hex[:8]}", crop_batch_id=None,
                harvested_produce_lot_id=None, finished_goods_lot_id=fg_lot_id,
                reason_code="contamination_suspected", reason_text="snapshot isolation check",
            )
            session.commit()
            case_id = case.id

        snapshot_ready = threading.Event()
        mutation_committed = threading.Event()
        results: dict[str, object] = {}

        def detail_thread() -> None:
            with lineage_traversal._snapshot_connection(test_engine) as conn:
                before = lineage_traversal._bulk_placed(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=[fg_lot_id])
                results["before"] = before.get(fg_lot_id, (Decimal("0"), 0))[0]
                snapshot_ready.set()
                assert mutation_committed.wait(timeout=10), "the concurrent place must commit within the timeout"
                after = lineage_traversal._bulk_placed(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=[fg_lot_id])
                results["after_same_snapshot"] = after.get(fg_lot_id, (Decimal("0"), 0))[0]

        t = threading.Thread(target=detail_thread)
        t.start()
        assert snapshot_ready.wait(timeout=10), "the detail thread must establish its snapshot before this test proceeds"

        with committed_connection(test_engine) as mutate_session:
            finished_goods_storage_service.record_movement(
                mutate_session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
                effective_time=now(), finished_goods_lot_id=fg_lot_id, movement_kind="place",
                source_location_id=None, destination_location_id=pos_id, moved_weight_kg=Decimal("5.000"),
                moved_package_count=5, note=None,
            )
            mutate_session.commit()
        mutation_committed.set()

        t.join(timeout=15)
        assert not t.is_alive(), "the detail thread must finish within the bounded join timeout"

        assert results["before"] == Decimal("0.000")
        assert results["after_same_snapshot"] == results["before"], (
            "a REPEATABLE READ snapshot must not observe a commit that happened after it was established"
        )

        # A brand-new request, opened after the place committed, must see
        # the updated placement -- the isolation guarantee is per-snapshot,
        # not a permanent staleness.
        fresh_detail = recall_service.get_recall_case(
            tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine
        )
        assert fresh_detail["live_state"]["finished_goods_lots"][0]["placed_weight_kg"] == Decimal("5.000")
        assert fresh_detail["frozen_scope"]["finished_goods_lot_ids"] == [fg_lot_id]
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)
