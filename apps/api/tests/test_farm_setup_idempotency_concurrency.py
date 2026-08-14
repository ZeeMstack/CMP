"""FARM-SETUP-001.1 section 8/9: deterministic concurrency proofs for Farm
Setup idempotency.

Sequential replay tests (`test_idempotent_replay_returns_same_greenhouse` in
`test_farm_setup.py`) only prove that a SECOND call made after the first has
already committed sees the prior `audit_events` row. They cannot prove
anything about two callers racing to submit the SAME `client_command_id` at
the same time -- both could observe "no prior event" before either commits.

Like `test_occupancy_capacity_concurrency.py`, this uses two independent DB
connections/sessions (never a shared, rollback-only `db_session`) and
`threading.Barrier` for start synchronization -- no sleeps. Correctness is
decided by `create_greenhouse_setup`'s own `pg_advisory_xact_lock(tenant_id
+ client_command_id)` (FARM-SETUP-001.1), which serializes the two
transactions so the second can never proceed past the idempotency check
until the first has fully committed (or rolled back)."""
import threading
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.farm_setup import GreenhouseSetupCreate, NurserySetupConfig, TableGeneratorConfig
from app.services import farm_setup_service
from app.services.errors import FarmSetupCommandReusedWithDifferentPayloadError
from tests._traceability_scenario import build_committed_tenant_farm, cleanup_traceability_scenario


def _nursery_payload(*, code: str, ccid: uuid.UUID) -> GreenhouseSetupCreate:
    return GreenhouseSetupCreate(
        code=code, name="Concurrent Nursery", classification="nursery", client_command_id=ccid,
        nursery=NurserySetupConfig(
            seedling_tables=TableGeneratorConfig(code_prefix="ST", start=1, end=2, pad_width=2, capacity=30),
        ),
    )


def _setup_worker(test_engine, results, name, *, tenant_id, farm_id, user_id, payload, barrier) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        result = farm_setup_service.create_greenhouse_setup(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, payload=payload,
        )
        results[name] = ("ok", result.greenhouse_id)
    except FarmSetupCommandReusedWithDifferentPayloadError as exc:
        session.rollback()
        results[name] = ("reused_conflict", str(exc))
    except Exception as exc:  # pragma: no cover - surfaced via assertion below
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


def _run_pair(test_engine, *, tenant_id, farm_id, user_id, payload_a, payload_b):
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    t_a = threading.Thread(
        target=_setup_worker, args=(test_engine, results, "a"),
        kwargs=dict(tenant_id=tenant_id, farm_id=farm_id, user_id=user_id, payload=payload_a, barrier=barrier),
    )
    t_b = threading.Thread(
        target=_setup_worker, args=(test_engine, results, "b"),
        kwargs=dict(tenant_id=tenant_id, farm_id=farm_id, user_id=user_id, payload=payload_b, barrier=barrier),
    )
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)
    assert not t_a.is_alive() and not t_b.is_alive()
    return results


@pytest.mark.integration
def test_concurrent_identical_payload_same_command_id_resolves_to_single_setup(test_engine) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant, user, farm = build_committed_tenant_farm(session, suffix=f"fs-conc-{uuid.uuid4().hex[:8]}")
    tenant_id, user_id, farm_id = tenant.id, user.id, farm.id
    session.commit()
    session.close()
    conn.close()

    try:
        ccid = uuid.uuid4()
        payload = _nursery_payload(code="NUR-CONC-SAME", ccid=ccid)
        results = _run_pair(
            test_engine, tenant_id=tenant_id, farm_id=farm_id, user_id=user_id, payload_a=payload, payload_b=payload,
        )

        # The advisory lock serializes the two attempts -- neither may
        # observe an unresolved race. Both must succeed: the first as the
        # real create, the second as an idempotent replay of the same
        # Greenhouse (never a second physical setup, never an error).
        assert results["a"][0] == "ok", results
        assert results["b"][0] == "ok", results
        assert results["a"][1] == results["b"][1], "both calls must resolve to the SAME greenhouse_id"

        check_conn = test_engine.connect()
        try:
            location_count = check_conn.execute(
                text("SELECT COUNT(*) FROM locations WHERE tenant_id = :tid AND code = 'NUR-CONC-SAME'"),
                {"tid": tenant_id},
            ).scalar_one()
            event_count = check_conn.execute(
                text(
                    "SELECT COUNT(*) FROM audit_events WHERE tenant_id = :tid "
                    "AND action = 'farm_setup.greenhouse_created' AND event_data->>'client_command_id' = :ccid"
                ),
                {"tid": tenant_id, "ccid": str(ccid)},
            ).scalar_one()
        finally:
            check_conn.close()
        assert location_count == 1, "no duplicate physical Greenhouse may be created"
        assert event_count == 1, "exactly one logical setup command may exist for this client_command_id"
    finally:
        cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_concurrent_different_payload_same_command_id_never_produces_two_setups(test_engine) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant, user, farm = build_committed_tenant_farm(session, suffix=f"fs-conc-{uuid.uuid4().hex[:8]}")
    tenant_id, user_id, farm_id = tenant.id, user.id, farm.id
    session.commit()
    session.close()
    conn.close()

    try:
        ccid = uuid.uuid4()
        payload_a = _nursery_payload(code="NUR-CONC-A", ccid=ccid)
        payload_b = _nursery_payload(code="NUR-CONC-B", ccid=ccid)
        results = _run_pair(
            test_engine, tenant_id=tenant_id, farm_id=farm_id, user_id=user_id, payload_a=payload_a, payload_b=payload_b,
        )

        outcomes = [results["a"][0], results["b"][0]]
        # Exactly one of the two genuinely different payloads may create a
        # setup; the other must be rejected as a command-id reuse with
        # different content -- never both "ok" (that would mean two
        # Greenhouses exist under one client_command_id).
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("reused_conflict") == 1, results

        check_conn = test_engine.connect()
        try:
            greenhouse_count = check_conn.execute(
                text(
                    "SELECT COUNT(*) FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
                    "WHERE l.tenant_id = :tid AND lt.code = 'greenhouse' AND l.code IN ('NUR-CONC-A', 'NUR-CONC-B')"
                ),
                {"tid": tenant_id},
            ).scalar_one()
            event_count = check_conn.execute(
                text(
                    "SELECT COUNT(*) FROM audit_events WHERE tenant_id = :tid "
                    "AND action = 'farm_setup.greenhouse_created' AND event_data->>'client_command_id' = :ccid"
                ),
                {"tid": tenant_id, "ccid": str(ccid)},
            ).scalar_one()
        finally:
            check_conn.close()
        assert greenhouse_count == 1, "only the winning payload's Greenhouse may exist"
        assert event_count == 1, "exactly one logical setup command may exist for this client_command_id"
    finally:
        cleanup_traceability_scenario(test_engine, tenant_id)
