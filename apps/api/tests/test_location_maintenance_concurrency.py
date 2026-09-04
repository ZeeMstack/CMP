"""UX-IA-001: real two-connection concurrency proof that
`deactivate_location` correctly serializes against a concurrent
`execute_movement` into the same Location, rather than racing a stale
pre-lock occupancy read -- both lock the same Location row
(`_lock_location` here, `_resolve_target(..., lock=True)` in
`movement_service`), so exactly one of the two commands must win and the
other must observe post-lock state and fail cleanly. Mirrors
`test_movement_concurrency.py`'s own two-connection/`threading.Barrier`
style exactly."""
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.location import Location
from app.services import asset_service, farm_service, location_service, membership_service, tenant_service, user_service
from app.services.errors import (
    InactiveParentLocationError,
    InactiveTargetError,
    LocationHasActiveChildrenError,
    LocationHasActiveOccupancyError,
    LocationNotActiveError,
    LocationParentNotActiveError,
)


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"loc-race-{suffix}", name="Loc Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="loc-race", oidc_subject=suffix, email=f"loc-race-{suffix}@example.com",
        display_name="Loc Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Loc Race Farm",
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
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=True,
    )
    trolley = asset_service.register_asset(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code="GT-1", name="Trolley", commissioned_date=None,
    )
    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id,
        "chamber_id": chamber.id, "trolley_id": trolley.id,
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
        conn.execute(text("DELETE FROM assets WHERE tenant_id = :tid"), {"tid": tenant_id})
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
def test_concurrent_deactivate_vs_movement_leaves_one_winner(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def deactivate_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            location_service.deactivate_location(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                location_id=scenario["chamber_id"],
            )
            results["deactivate"] = ("ok", None)
        except LocationHasActiveOccupancyError:
            results["deactivate"] = ("blocked_by_occupancy", None)
        except Exception as exc:  # pragma: no cover - surfaced via assertion below
            results["deactivate"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def movement_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            from app.services import movement_service

            movement_service.execute_movement(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=_now(),
                occupant_kind="asset", occupant_id=scenario["trolley_id"],
                destination_kind="location", destination_id=scenario["chamber_id"], reason=None,
            )
            results["movement"] = ("ok", None)
        except InactiveTargetError:
            results["movement"] = ("blocked_by_inactive_target", None)
        except Exception as exc:  # pragma: no cover
            results["movement"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=deactivate_worker)
    t_b = threading.Thread(target=movement_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        # Exactly one legal outcome pair: either the movement wins (occupies
        # the chamber first, so deactivate correctly observes active
        # occupancy after acquiring its lock and refuses) or the
        # deactivate wins (the chamber goes inactive first, so the
        # movement correctly observes an inactive target and refuses) --
        # never both succeeding, and never a silent inconsistent state.
        outcome = (results.get("deactivate"), results.get("movement"))
        movement_won = outcome == (("blocked_by_occupancy", None), ("ok", None))
        deactivate_won = outcome == (("ok", None), ("blocked_by_inactive_target", None))
        assert movement_won or deactivate_won, results
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_duplicate_deactivate_command_id_is_safe(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    shared_command_id = uuid.uuid4()

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            location = location_service.deactivate_location(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=shared_command_id,
                location_id=scenario["chamber_id"],
            )
            results[name] = ("ok", location.id)
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
        assert results["a"][1] == results["b"][1], "both calls must resolve to the same location"
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


def _build_store_scenario(test_engine, *, with_inactive_bin: bool):
    """A Store (parent) plus, when requested, one pre-existing, already-
    inactive Bin child -- committed via dedicated connections so two later
    threads can genuinely race against this fixed starting state."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"loc-hier-{suffix}", name="Loc Hierarchy Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="loc-hier", oidc_subject=suffix, email=f"loc-hier-{suffix}@example.com",
        display_name="Loc Hierarchy Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Loc Hierarchy Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    store = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="store", code="STORE-1", name="Store",
        parent_location_id=None, greenhouse_classification=None, occupiable=None,
    )
    bin_id = None
    if with_inactive_bin:
        bin_ = location_service.create_location(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            location_type_code="store_bin", code="BIN-1", name="Bin",
            parent_location_id=store.id, greenhouse_classification=None, occupiable=None,
        )
        location_service.deactivate_location(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            client_command_id=uuid.uuid4(), location_id=bin_.id,
        )
        bin_id = bin_.id
    result = {"tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "store_id": store.id, "bin_id": bin_id}
    session.close()
    conn.close()
    return result


def _final_hierarchy_state(test_engine, *, store_id: uuid.UUID):
    """Direct, unlocked read of committed end-state for the invariant
    assertion -- deliberately bypasses both services, mirroring how
    `test_occupancy_capacity.py`'s own DB-layer proofs read back committed
    facts rather than trusting either command's return value alone."""
    conn = test_engine.connect()
    try:
        store_status = conn.execute(select(Location.status).where(Location.id == store_id)).scalar_one()
        active_children = conn.execute(
            select(func.count()).select_from(Location).where(
                Location.parent_location_id == store_id, Location.status == "active"
            )
        ).scalar_one()
        return store_status, active_children
    finally:
        conn.close()


@pytest.mark.integration
def test_concurrent_child_create_vs_parent_deactivate_never_leaves_inactive_parent_with_active_child(
    test_engine,
) -> None:
    """Frozen invariant (docs/domain/LOCATION_MODEL.md, "Location
    maintenance lifecycle"): an inactive parent must never have an active
    child. `create_location`'s parent lookup
    (`_get_active_location_in_scope`) and `deactivate_location`'s own lock
    (`_lock_location`) now contend on the same Store row, so exactly one of
    the two orderings below must be the observed outcome -- never both
    succeeding."""
    scenario = _build_store_scenario(test_engine, with_inactive_bin=False)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def create_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            location_service.create_location(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], location_type_code="store_bin", code="BIN-RACE",
                name="Bin Race", parent_location_id=scenario["store_id"], greenhouse_classification=None,
                occupiable=None,
            )
            results["create"] = "ok"
        except InactiveParentLocationError:
            results["create"] = "blocked_by_inactive_parent"
        except Exception as exc:  # pragma: no cover - surfaced via assertion below
            results["create"] = f"error:{exc!r}"
        finally:
            session.close()
            conn.close()

    def deactivate_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            location_service.deactivate_location(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                location_id=scenario["store_id"],
            )
            results["deactivate"] = "ok"
        except LocationHasActiveChildrenError:
            results["deactivate"] = "blocked_by_active_children"
        except Exception as exc:  # pragma: no cover
            results["deactivate"] = f"error:{exc!r}"
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=create_worker)
    t_b = threading.Thread(target=deactivate_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        outcome = (results.get("create"), results.get("deactivate"))
        create_won = outcome == ("ok", "blocked_by_active_children")
        deactivate_won = outcome == ("blocked_by_inactive_parent", "ok")
        assert create_won or deactivate_won, results

        store_status, active_child_count = _final_hierarchy_state(test_engine, store_id=scenario["store_id"])
        # The one invariant this test exists to prove: never an inactive
        # parent with an active child, regardless of which side won.
        assert not (store_status == "inactive" and active_child_count > 0), (
            store_status, active_child_count, results,
        )
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_child_reactivate_vs_parent_deactivate_never_leaves_inactive_parent_with_active_child(
    test_engine,
) -> None:
    """Same invariant as above, for the other hierarchy-mutating path:
    `reactivate_location`'s parent lookup now also locks the parent row
    FOR UPDATE, so it correctly serializes against a concurrent
    `deactivate_location(parent)` rather than racing a stale pre-lock
    read."""
    scenario = _build_store_scenario(test_engine, with_inactive_bin=True)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def reactivate_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            location_service.reactivate_location(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                location_id=scenario["bin_id"],
            )
            results["reactivate"] = "ok"
        except LocationParentNotActiveError:
            results["reactivate"] = "blocked_by_inactive_parent"
        except Exception as exc:  # pragma: no cover
            results["reactivate"] = f"error:{exc!r}"
        finally:
            session.close()
            conn.close()

    def deactivate_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            location_service.deactivate_location(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                location_id=scenario["store_id"],
            )
            results["deactivate"] = "ok"
        except LocationHasActiveChildrenError:
            results["deactivate"] = "blocked_by_active_children"
        except Exception as exc:  # pragma: no cover
            results["deactivate"] = f"error:{exc!r}"
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=reactivate_worker)
    t_b = threading.Thread(target=deactivate_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        outcome = (results.get("reactivate"), results.get("deactivate"))
        reactivate_won = outcome == ("ok", "blocked_by_active_children")
        deactivate_won = outcome == ("blocked_by_inactive_parent", "ok")
        assert reactivate_won or deactivate_won, results

        store_status, active_child_count = _final_hierarchy_state(test_engine, store_id=scenario["store_id"])
        assert not (store_status == "inactive" and active_child_count > 0), (
            store_status, active_child_count, results,
        )
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])
