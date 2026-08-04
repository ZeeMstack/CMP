"""Failure-path proof for the CMP-011 committed-connection cleanup helpers'
`session_replication_role` hardening (see the `_cleanup_scenario` functions
in test_transplant_concurrency.py, test_transplant_rollback.py, and
test_transplant_downgrade_guard.py).

Confirms that when a cleanup DELETE fails mid-transaction, strictly after
replica mode has already been enabled, the recovery path — roll back the
aborted transaction first, then issue `SET session_replication_role =
DEFAULT` as its own statement and commit that restoration on its own —
actually restores the setting, leaves the database usable for further real
work, and never touches any tenant other than the one this test owns. This
never relies on connection-close, plain rollback, or Postgres's
transactional GUC-reset behavior alone."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import farm_service, membership_service, tenant_service, user_service


def _create_committed_tenant(test_engine, *, suffix: str) -> uuid.UUID:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        tenant = tenant_service.create_tenant(session, code=f"cleanup-safety-{suffix}", name="Cleanup Safety")
        tenant_id = tenant.id
        user = user_service.create_user(
            session, oidc_issuer="cleanup-safety", oidc_subject=suffix,
            email=f"cleanup-safety-{suffix}@example.com", display_name="Cleanup Safety User",
        )
        membership_service.add_membership(
            session, tenant_id=tenant_id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
        )
        farm_service.create_farm(
            session, tenant_id=tenant_id, actor_user_id=user.id, code=f"farm-{suffix}", name="Cleanup Safety Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        session.commit()
        return tenant_id
    finally:
        session.close()
        conn.close()


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    """The same hardened shape as the three CMP-011 committed-connection
    test files' own `_cleanup_scenario` (trimmed to the tables this test
    actually creates: tenants, tenant_memberships, farms)."""
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup (session_replication_role) against "
            f"database {current_db!r}; this cleanup is only permitted against 'cmp_test'"
        )

    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    except Exception:
        trans.rollback()
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        raise
    else:
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


def _failing_cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    """Identical to `_cleanup_scenario` above, except the second statement
    deliberately references a column that does not exist on `farms`. Replica
    mode is already active by the time this fails, so it exercises exactly
    the failure path the three real cleanup helpers must survive: a real
    Postgres error mid-transaction, after `SET session_replication_role =
    replica` has already run and before the transaction's own commit."""
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup (session_replication_role) against "
            f"database {current_db!r}; this cleanup is only permitted against 'cmp_test'"
        )

    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(
            text("DELETE FROM farms WHERE tenant_id = :tid AND no_such_column_xyz = 1"), {"tid": tenant_id}
        )
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    except Exception:
        trans.rollback()
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        raise
    else:
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()


@pytest.mark.integration
def test_cleanup_failure_path_restores_default_and_preserves_unrelated_tenant(test_engine) -> None:
    with test_engine.connect() as baseline_conn:
        default_role = baseline_conn.execute(text("SHOW session_replication_role")).scalar_one()

    suffix = uuid.uuid4().hex[:8]
    other_suffix = uuid.uuid4().hex[:8]
    tenant_id = _create_committed_tenant(test_engine, suffix=suffix)
    other_tenant_id = _create_committed_tenant(test_engine, suffix=other_suffix)

    try:
        with pytest.raises(Exception, match="no_such_column_xyz"):
            _failing_cleanup_scenario(test_engine, tenant_id)

        # session_replication_role must be restored to origin/default — not
        # left in replica mode — immediately after the failure, on a freshly
        # checked-out connection from the same pool the failing cleanup used.
        with test_engine.connect() as verify_conn:
            role = verify_conn.execute(text("SHOW session_replication_role")).scalar_one()
            assert role == default_role

            # The database must still be cmp_test.
            current_db = verify_conn.execute(text("SELECT current_database()")).scalar_one()
            assert current_db == "cmp_test"

            # The failed cleanup transaction must have rolled back in full:
            # this test's own farm/tenant rows (targeted by the first,
            # otherwise-successful DELETE) must still exist, not be
            # half-deleted.
            own_tenant_still_present = verify_conn.execute(
                text("SELECT count(*) FROM tenants WHERE id = :tid"), {"tid": tenant_id}
            ).scalar_one()
            assert own_tenant_still_present == 1, "a failed cleanup transaction must roll back in full"

            # No unrelated tenant's data was touched by this tenant's failed
            # cleanup attempt.
            other_tenant_still_present = verify_conn.execute(
                text("SELECT count(*) FROM tenants WHERE id = :tid"), {"tid": other_tenant_id}
            ).scalar_one()
            assert other_tenant_still_present == 1, "an unrelated tenant must never be touched by another cleanup"

        # The connection/database must remain fully usable for further real
        # privileged work after the failure — proven by actually running the
        # real, hardened cleanup successfully for both test-owned tenants.
        _cleanup_scenario(test_engine, tenant_id)
        _cleanup_scenario(test_engine, other_tenant_id)

        with test_engine.connect() as final_conn:
            remaining = final_conn.execute(
                text("SELECT count(*) FROM tenants WHERE id IN (:a, :b)"), {"a": tenant_id, "b": other_tenant_id}
            ).scalar_one()
            assert remaining == 0
            role_after_real_cleanup = final_conn.execute(text("SHOW session_replication_role")).scalar_one()
            assert role_after_real_cleanup == default_role
    except Exception:
        # Best-effort teardown if an assertion above failed before the real
        # cleanup ran, so this test never leaks rows into the shared database.
        _cleanup_scenario(test_engine, tenant_id)
        _cleanup_scenario(test_engine, other_tenant_id)
        raise
