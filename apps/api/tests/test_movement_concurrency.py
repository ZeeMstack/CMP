"""Real two-connection concurrency tests. These commit their own setup data
(via dedicated connections, not the rollback-only `db_session` fixture) so
that two independent database sessions can genuinely race against each
other — a shared, uncommitted savepoint-scoped session cannot demonstrate a
real Postgres-level conflict. Cleanup bypasses the append-only/no-delete
triggers via `session_replication_role = replica`, scoped to this test only,
purely to keep `cmp_test` tidy between runs.
"""
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import asset_service, farm_service, location_service, membership_service, tenant_service, user_service
from app.services.errors import MovementCommandReusedWithDifferentPayloadError, TargetOccupiedError


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"race-{suffix}", name="Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="race", oidc_subject=suffix, email=f"race-{suffix}@example.com", display_name="Race User"
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    greenhouse = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code="gh-1", name="GH",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    chamber = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code="GC-1", name="Chamber",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=None,
    )
    position = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="chamber_position", code="P01", name="Position 1",
        parent_location_id=chamber.id, greenhouse_classification=None, occupiable=None,
    )
    trolley_a = asset_service.register_asset(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code="GT-A", name="Trolley A", commissioned_date=None,
    )
    trolley_b = asset_service.register_asset(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code="GT-B", name="Trolley B", commissioned_date=None,
    )
    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id,
        "position_id": position.id, "trolley_a_id": trolley_a.id, "trolley_b_id": trolley_b.id,
    }
    session.close()
    conn.close()
    return result


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM occupancies WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM movements WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM asset_positions WHERE asset_id IN (SELECT id FROM assets WHERE tenant_id = :tid)"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM assets WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM locations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_concurrent_target_occupation_leaves_one_winner(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def worker(name: str, trolley_id: uuid.UUID) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            from app.services import movement_service

            movement = movement_service.execute_movement(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), effective_time=_now(),
                occupant_kind="asset", occupant_id=trolley_id,
                destination_kind="location", destination_id=scenario["position_id"], reason=None,
            )
            results[name] = ("ok", movement.id)
        except TargetOccupiedError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover - surfaced via assertion below
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", scenario["trolley_a_id"]))
    t_b = threading.Thread(target=worker, args=("b", scenario["trolley_b_id"]))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_duplicate_command_id_is_safe(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    shared_command_id = uuid.uuid4()
    effective_time = _now()

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            from app.services import movement_service

            movement = movement_service.execute_movement(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=shared_command_id, effective_time=effective_time,
                occupant_kind="asset", occupant_id=scenario["trolley_a_id"],
                destination_kind="location", destination_id=scenario["position_id"], reason=None,
            )
            results[name] = ("ok", movement.id)
        except MovementCommandReusedWithDifferentPayloadError as exc:
            results[name] = ("rejected", str(exc))
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
        assert results["a"][0] == "ok", results
        assert results["b"][0] == "ok", results
        assert results["a"][1] == results["b"][1], "both calls must resolve to the same movement"
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])
