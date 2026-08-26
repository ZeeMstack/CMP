"""POSTHARVEST-OPS-001A: real two-connection concurrency tests. Same
committed-connection racing pattern as test_packing_concurrency.py —
each worker opens its own connection/Session against `test_engine` and
the race is synchronized with a `threading.Barrier`."""
import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.grade_definition_version import GradeDefinitionVersion
from app.services import grade_definition_service
from app.services.errors import GradeDefinitionVersionNotActiveError
from tests._grade_definition_scenario import build_committed_scenario, cleanup_scenario, now


@pytest.mark.integration
def test_concurrent_version_creation_never_duplicates_version_number(test_engine) -> None:
    scenario = build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            version = grade_definition_service.create_draft_version(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), grade_definition_id=scenario["grade_definition_id"],
                spec_notes=None,
            )
            results[name] = ("ok", version.version_number)
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a",))
    t_b = threading.Thread(target=worker, args=("b",))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        assert results["a"][0] == "ok" and results["b"][0] == "ok", results
        numbers = sorted([results["a"][1], results["b"][1]])
        assert numbers == [1, 2], "concurrent creation must produce distinct sequential version numbers"
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_activation_of_two_drafts_leaves_one_deterministic_active_version(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, draft_version_count=2)
    version_1_id, version_2_id = scenario["draft_version_ids"]
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = now()

    def worker(name: str, version_id) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            version = grade_definition_service.activate_version(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), grade_definition_id=scenario["grade_definition_id"],
                version_id=version_id, effective_time=effective_time,
            )
            results[name] = ("ok", version.id)
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", version_1_id))
    t_b = threading.Thread(target=worker, args=("b", version_2_id))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        assert results["a"][0] == "ok" and results["b"][0] == "ok", results

        with test_engine.connect() as verify_conn:
            verify_session = Session(bind=verify_conn)
            active_rows = list(
                verify_session.execute(
                    select(GradeDefinitionVersion).where(
                        GradeDefinitionVersion.grade_definition_id == scenario["grade_definition_id"],
                        GradeDefinitionVersion.status == "active",
                    )
                ).scalars()
            )
        assert len(active_rows) == 1, "exactly one version must end up active, never two"
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_activate_vs_retire_race_leaves_valid_lifecycle_result(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, draft_version_count=2)
    version_1_id, version_2_id = scenario["draft_version_ids"]

    # Pre-activate version_1 outside the race, in the past, so the race
    # itself is exactly "retire the currently active version" vs
    # "activate the other draft as its replacement" at the same instant.
    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    grade_definition_service.activate_version(
        setup_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), grade_definition_id=scenario["grade_definition_id"],
        version_id=version_1_id, effective_time=now() - timedelta(hours=1),
    )
    setup_session.close()
    setup_conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    race_time = now()

    def retire_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            grade_definition_service.retire_version(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), grade_definition_id=scenario["grade_definition_id"],
                version_id=version_1_id, effective_time=race_time,
            )
            results["retire"] = ("ok", None)
        except GradeDefinitionVersionNotActiveError:
            results["retire"] = ("not_active", None)
        except Exception as exc:  # pragma: no cover
            results["retire"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def activate_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            grade_definition_service.activate_version(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), grade_definition_id=scenario["grade_definition_id"],
                version_id=version_2_id, effective_time=race_time,
            )
            results["activate"] = ("ok", None)
        except Exception as exc:  # pragma: no cover
            results["activate"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=retire_worker)
    t_b = threading.Thread(target=activate_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        # activation must always succeed regardless of ordering; retirement
        # either wins (version_1 was still active) or observes version_1
        # already retired-by-replacement -- never a raw crash/error.
        assert results["activate"][0] == "ok", results
        assert results["retire"][0] in ("ok", "not_active"), results

        with test_engine.connect() as verify_conn:
            verify_session = Session(bind=verify_conn)
            version_1 = verify_session.get(GradeDefinitionVersion, version_1_id)
            version_2 = verify_session.get(GradeDefinitionVersion, version_2_id)
            active_count = verify_session.execute(
                select(GradeDefinitionVersion).where(
                    GradeDefinitionVersion.grade_definition_id == scenario["grade_definition_id"],
                    GradeDefinitionVersion.status == "active",
                )
            ).scalars().all()

        assert version_1.status == "retired"
        assert version_1.effective_until == race_time
        assert version_2.status == "active"
        assert version_2.effective_from == race_time
        assert len(active_count) == 1, "no invalid window: exactly one active version must remain"
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])
