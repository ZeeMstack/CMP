"""Shared, non-collected helper for PILOT-SETUP-001B2 platform Tenant
onboarding tests (pytest's default `test_*.py` discovery glob does not
match this name). `platform_tenant_service.onboard_tenant` genuinely
commits, on its own dedicated connection, independent of the
rollback-on-teardown `db_session` fixture -- any test that exercises it
(directly, or indirectly via `POST /platform/tenants` through the `client`
fixture, which overrides `get_engine` to point at `test_engine`) must clean
up the rows it commits itself.

Mirrors `tests/_traceability_scenario.py::cleanup_traceability_scenario`'s
own established technique for this exact problem: `audit_events` is
database-level append-only (`reject_audit_event_mutation`, a BEFORE
UPDATE/DELETE trigger -- see CLAUDE.md rule 7, "Immutable history"), so a
plain `DELETE` against it always fails, and a plain `DELETE FROM tenants`
would then fail too on the `audit_events.tenant_id` foreign key. Only a
privileged test-cleanup connection may use
`SET session_replication_role = replica` (disables triggers AND FK
enforcement for that session) to unwind a scenario's rows regardless of
insertion order -- gated by `require_cmp_test` so this is never attempted
against anything but the dedicated test database."""

import uuid

from sqlalchemy import Engine, text

from tests._packing_scenario import require_cmp_test


def cleanup_onboarded_tenant(
    engine: Engine, tenant_id: uuid.UUID | None, user_id: uuid.UUID | None
) -> None:
    """Deletes the rows a real `onboard_tenant` call may have committed.
    Tolerant of either id being None (e.g. after a deliberately-failed
    onboarding that rolled back, or when the User was resolved/pre-existing
    rather than created by this test). `audit_events` rows are left in
    place -- append-only, by design, never deleted even for test cleanup."""
    require_cmp_test(engine)
    conn = engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        if tenant_id is not None:
            conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": str(tenant_id)})
            conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": str(tenant_id)})
        if user_id is not None:
            conn.execute(text("DELETE FROM tenant_memberships WHERE user_id = :uid"), {"uid": str(user_id)})
            conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": str(user_id)})
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
