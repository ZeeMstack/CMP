"""UX-OPS-001D0: real two-connection races on the End Delivery command.
Mirrors test_observation_quality_concurrency.py: committed setup data, two
independent sessions released together by a barrier, cleanup bypassing the
append-only triggers (cmp_test only)."""

import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import reservoir_operations_service
from app.services.errors import WaterDeliveryEventAlreadyEndedError
from tests._water_delivery_end_scenario import build_open_delivery_scenario, cleanup_scenario


def _race(test_engine, scenario, commands: list[tuple[uuid.UUID, object]]) -> list[tuple[str, object]]:
    barrier = threading.Barrier(len(commands))
    results: list[tuple[str, object] | None] = [None] * len(commands)

    def worker(index: int, client_command_id: uuid.UUID, effective_end) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            resolved = reservoir_operations_service.end_delivery_event(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], water_delivery_event_id=scenario["delivery_id"],
                effective_end=effective_end, note=None, client_command_id=client_command_id,
            )
            results[index] = ("ok", resolved.water_delivery_end_event_id)
        except WaterDeliveryEventAlreadyEndedError as exc:
            results[index] = ("already_ended", str(exc))
        except Exception as exc:  # pragma: no cover - surfaced by the assertions below
            results[index] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    threads = [
        threading.Thread(target=worker, args=(i, command_id, end)) for i, (command_id, end) in enumerate(commands)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results  # type: ignore[return-value]


def _counts(test_engine, scenario) -> tuple[int, int]:
    with test_engine.connect() as conn:
        end_rows = conn.execute(
            text("SELECT count(*) FROM water_delivery_end_events WHERE water_delivery_event_id = :id"),
            {"id": scenario["delivery_id"]},
        ).scalar_one()
        audit_rows = conn.execute(
            text(
                "SELECT count(*) FROM audit_events WHERE tenant_id = :tid AND entity_id = :id "
                "AND action = 'water_delivery_event.ended'"
            ),
            {"tid": scenario["tenant_id"], "id": scenario["delivery_id"]},
        ).scalar_one()
    return end_rows, audit_rows


@pytest.mark.integration
def test_concurrent_close_with_different_command_ids_ends_the_delivery_exactly_once(test_engine) -> None:
    scenario = build_open_delivery_scenario(test_engine)
    try:
        end = scenario["effective_start"] + timedelta(minutes=30)
        results = _race(test_engine, scenario, [(uuid.uuid4(), end), (uuid.uuid4(), end + timedelta(minutes=1))])
        outcomes = sorted(r[0] for r in results)
        assert outcomes == ["already_ended", "ok"], results
        assert _counts(test_engine, scenario) == (1, 1)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_replay_of_the_same_command_returns_one_end_event(test_engine) -> None:
    scenario = build_open_delivery_scenario(test_engine)
    try:
        command_id = uuid.uuid4()
        end = scenario["effective_start"] + timedelta(minutes=30)
        results = _race(test_engine, scenario, [(command_id, end), (command_id, end)])
        assert [r[0] for r in results] == ["ok", "ok"], results
        assert results[0][1] == results[1][1]
        assert _counts(test_engine, scenario) == (1, 1)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])
