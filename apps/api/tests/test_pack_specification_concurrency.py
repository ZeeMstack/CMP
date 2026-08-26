"""POSTHARVEST-OPS-001B: real two-connection concurrency tests. Same
committed-connection racing pattern as test_grade_definition_concurrency.py
-- each worker opens its own connection/Session against `test_engine` and
the race is synchronized with a `threading.Barrier`."""
import threading
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pack_specification_version import PackSpecificationVersion
from app.models.packaging_unit import PackagingUnit
from app.services import pack_specification_service, packaging_unit_service
from app.services.errors import PackagingUnitNotActiveError, PackSpecificationVersionNotActiveError
from tests._pack_specification_scenario import build_committed_scenario, cleanup_scenario, now


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
            version = pack_specification_service.create_draft_version(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), pack_specification_id=scenario["pack_specification_id"],
                grade_definition_version_id=None, packaging_unit_id=scenario["packaging_unit_id"],
                nominal_net_weight_kg=Decimal("1.000"), whole_units_per_pack=None, spec_notes=None,
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
            version = pack_specification_service.activate_version(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), pack_specification_id=scenario["pack_specification_id"],
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
                    select(PackSpecificationVersion).where(
                        PackSpecificationVersion.pack_specification_id == scenario["pack_specification_id"],
                        PackSpecificationVersion.status == "active",
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

    setup_conn = test_engine.connect()
    setup_session = Session(bind=setup_conn)
    pack_specification_service.activate_version(
        setup_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), pack_specification_id=scenario["pack_specification_id"],
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
            pack_specification_service.retire_version(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), pack_specification_id=scenario["pack_specification_id"],
                version_id=version_1_id, effective_time=race_time,
            )
            results["retire"] = ("ok", None)
        except PackSpecificationVersionNotActiveError:
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
            pack_specification_service.activate_version(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), pack_specification_id=scenario["pack_specification_id"],
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
        assert results["activate"][0] == "ok", results
        assert results["retire"][0] in ("ok", "not_active"), results

        with test_engine.connect() as verify_conn:
            verify_session = Session(bind=verify_conn)
            version_1 = verify_session.get(PackSpecificationVersion, version_1_id)
            version_2 = verify_session.get(PackSpecificationVersion, version_2_id)
            active_rows = verify_session.execute(
                select(PackSpecificationVersion).where(
                    PackSpecificationVersion.pack_specification_id == scenario["pack_specification_id"],
                    PackSpecificationVersion.status == "active",
                )
            ).scalars().all()

        assert version_1.status == "retired"
        assert version_1.effective_until == race_time
        assert version_2.status == "active"
        assert version_2.effective_from == race_time
        assert len(active_rows) == 1, "no invalid window: exactly one active version must remain"
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_version_creation_vs_packaging_unit_retirement_race_is_serialized(test_engine) -> None:
    """POSTHARVEST-OPS-001B concurrency requirement D: a new
    PackSpecificationVersion creation and a PackagingUnit retirement,
    racing against the same unit, must serialize around the unit's row
    lock -- the new version either validly captures the unit while still
    ACTIVE, or the create fails cleanly with PackagingUnitNotActiveError.
    It must never create a version that bypassed the active-unit rule."""
    scenario = build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def create_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            version = pack_specification_service.create_draft_version(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), pack_specification_id=scenario["pack_specification_id"],
                grade_definition_version_id=None, packaging_unit_id=scenario["packaging_unit_id"],
                nominal_net_weight_kg=Decimal("1.000"), whole_units_per_pack=None, spec_notes=None,
            )
            results["create"] = ("ok", version.id)
        except PackagingUnitNotActiveError:
            results["create"] = ("not_active", None)
        except Exception as exc:  # pragma: no cover
            results["create"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def retire_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            packaging_unit_service.retire_packaging_unit(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), packaging_unit_id=scenario["packaging_unit_id"],
            )
            results["retire"] = ("ok", None)
        except Exception as exc:  # pragma: no cover
            results["retire"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=create_worker)
    t_b = threading.Thread(target=retire_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive(), "a deadlock would leave a thread hung past the join timeout"
        # Retirement is never blocked by a concurrent version-creation
        # attempt (only serialized behind it) -- it always succeeds.
        assert results["retire"][0] == "ok", results
        assert results["create"][0] in ("ok", "not_active"), results

        with test_engine.connect() as verify_conn:
            verify_session = Session(bind=verify_conn)
            unit = verify_session.get(PackagingUnit, scenario["packaging_unit_id"])
            assert unit.status == "retired"

            if results["create"][0] == "ok":
                version = verify_session.get(PackSpecificationVersion, results["create"][1])
                assert version is not None
                assert version.packaging_unit_id == scenario["packaging_unit_id"]
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])
