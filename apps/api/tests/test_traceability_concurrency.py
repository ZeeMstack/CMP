"""CMP-019 read-consistency concurrency test: proves a trace's dedicated
REPEATABLE READ snapshot connection is internally coherent across multiple
SELECTs even while a concurrent dispatch commits in between them -- the
two reads inside one trace snapshot must be identical (both pre-commit),
and only a brand-new snapshot opened afterward may see the post-commit
state. Uses a real second thread and `threading.Event`s with bounded
waits -- no sleeps, no test-only hooks added to production code (the
trace's own internal, already-private helper functions and
`_snapshot_connection` context manager are exercised directly, exactly as
the service itself uses them)."""
import threading
import uuid
from decimal import Decimal

import pytest

from app.services import dispatch_service, traceability_service
from tests._traceability_scenario import (
    build_committed_tenant_farm,
    build_batch_with_assignments,
    cleanup_traceability_scenario,
    committed_connection,
    harvest_all,
    now,
    pack_lot,
)


@pytest.mark.integration
def test_trace_snapshot_is_never_mixed_across_a_concurrent_dispatch_commit(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"], weight_per_line=Decimal("8.000"))
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("8.000"), package_count=8)
            session.commit()
            farm_id, user_id = farm.id, user.id

        snapshot_ready = threading.Event()
        mutation_committed = threading.Event()
        results: dict[str, object] = {}

        def trace_thread() -> None:
            with traceability_service._snapshot_connection(test_engine) as conn:
                before = traceability_service._bulk_available(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=[fg_lot_id])
                results["before"] = before.get(fg_lot_id, (Decimal("0"), 0))
                snapshot_ready.set()
                assert mutation_committed.wait(timeout=10), "the concurrent dispatch must commit within the timeout"
                after = traceability_service._bulk_available(conn, tenant_id=tenant_id, farm_id=farm_id, fg_lot_ids=[fg_lot_id])
                results["after_same_snapshot"] = after.get(fg_lot_id, (Decimal("0"), 0))

        t = threading.Thread(target=trace_thread)
        t.start()
        assert snapshot_ready.wait(timeout=10), "the trace thread must establish its snapshot before this test proceeds"

        with committed_connection(test_engine) as mutate_session:
            dispatch_service.record_dispatch(
                mutate_session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id,
                client_command_id=uuid.uuid4(), effective_time=now(), code=f"DISP-{uuid.uuid4().hex[:8]}",
                external_reference=None, note=None, dispatch_temperature_c=Decimal("4.0"),
                lines=[{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": Decimal("3.000"), "dispatched_package_count": 3}],
            )
            mutate_session.commit()
        mutation_committed.set()

        t.join(timeout=15)
        assert not t.is_alive(), "the trace thread must finish within the bounded join timeout"

        assert results["before"] == (Decimal("8.000"), 8)
        assert results["after_same_snapshot"] == results["before"], (
            "a REPEATABLE READ snapshot must not observe a commit that happened after it was established"
        )

        # A brand-new trace, opened after the dispatch committed, must see
        # the updated state -- the isolation guarantee is per-snapshot, not
        # a permanent staleness.
        fresh_trace = traceability_service.get_finished_goods_lot_trace(
            tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
        )
        assert fresh_trace["subject"]["available_weight_kg"] == Decimal("5.000")
        assert fresh_trace["subject"]["available_package_count"] == 5
        assert len(fresh_trace["dispatches"]) == 1
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
