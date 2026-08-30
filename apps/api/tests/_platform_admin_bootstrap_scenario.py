"""Shared, non-collected helper for DEPLOY-001A `bootstrap_first_platform_
admin` tests (pytest's default `test_*.py` discovery glob does not match
this name). That function genuinely commits, on its own dedicated
connection, independent of the rollback-on-teardown `db_session` fixture --
any test that exercises it directly (with `test_engine`) must clean up the
rows it commits itself.

Mirrors `tests/_platform_tenant_scenario.py::cleanup_onboarded_tenant`'s
own established technique for the identical problem."""

import uuid

from sqlalchemy import Engine, text

from tests._packing_scenario import require_cmp_test


def cleanup_bootstrapped_admin(engine: Engine, user_id: uuid.UUID | None) -> None:
    """Deletes the rows a real `bootstrap_first_platform_admin` call may
    have committed. Tolerant of `user_id` being `None` (e.g. after a
    deliberately-failed bootstrap that rolled back)."""
    if user_id is None:
        return
    require_cmp_test(engine)
    conn = engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM platform_admins WHERE user_id = :uid"), {"uid": str(user_id)})
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
