"""Shared, non-collected scenario builder for POSTHARVEST-OPS-001A grade-
definition concurrency tests. Builds a committed tenant/crop/GradeDefinition
(optionally with N draft versions already created), and a matching
`session_replication_role`-guarded cleanup — same pattern
`tests/_packing_scenario.py` already established. Not a test file itself
(pytest's default `test_*.py` discovery glob does not match this name)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import crop_service, grade_definition_service, membership_service, tenant_service, user_service


def now():
    return datetime.now(timezone.utc)


def require_cmp_test(test_engine) -> None:
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup (session_replication_role) against "
            f"database {current_db!r}; this cleanup is only permitted against 'cmp_test'"
        )


def build_committed_scenario(test_engine, *, draft_version_count: int = 0):
    """Returns a dict with tenant_id/user_id/grade_definition_id and, if
    draft_version_count > 0, draft_version_ids (a list, in creation order —
    each already committed, still in 'draft' status)."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"grade-{suffix}", name="Grade Tenant")
    user = user_service.create_user(
        session, oidc_issuer="grade", oidc_subject=suffix, email=f"grade-{suffix}@example.com",
        display_name="Grade User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    definition = grade_definition_service.register_grade_definition(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"grade-{suffix}", name="Premium", crop_id=crop.id, variety_id=None, description=None,
    )

    draft_version_ids = []
    for _ in range(draft_version_count):
        version = grade_definition_service.create_draft_version(
            session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            grade_definition_id=definition.id, spec_notes=None,
        )
        draft_version_ids.append(version.id)

    session.commit()
    result = {
        "tenant_id": tenant.id, "user_id": user.id, "crop_id": crop.id, "grade_definition_id": definition.id,
        "draft_version_ids": draft_version_ids, "suffix": suffix,
    }
    session.close()
    conn.close()
    return result


def cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM grade_definition_versions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM grade_definitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM varieties WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crops WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
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
