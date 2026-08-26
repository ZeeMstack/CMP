"""Shared, non-collected scenario builder for POSTHARVEST-OPS-001B
concurrency/migration tests. Builds a committed tenant/crop/PackagingUnit/
PackSpecification (optionally with N draft versions already created), and
a matching `session_replication_role`-guarded cleanup -- same pattern
`tests/_grade_definition_scenario.py` already established. Not a test
file itself (pytest's default `test_*.py` discovery glob does not match
this name)."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    crop_service,
    membership_service,
    pack_specification_service,
    packaging_unit_service,
    tenant_service,
    user_service,
)


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
    """Returns a dict with tenant_id/user_id/crop_id/packaging_unit_id/
    pack_specification_id and, if draft_version_count > 0,
    draft_version_ids (a list, in creation order — each already
    committed, still in 'draft' status, referencing the committed
    packaging unit)."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"pspec-{suffix}", name="Pack Spec Tenant")
    user = user_service.create_user(
        session, oidc_issuer="pspec", oidc_subject=suffix, email=f"pspec-{suffix}@example.com",
        display_name="Pack Spec User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    unit = packaging_unit_service.register_packaging_unit(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"unit-{suffix}", name="Test Unit",
    )
    spec = pack_specification_service.register_pack_specification(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"spec-{suffix}", name="Test Spec", crop_id=crop.id, variety_id=None, customer_reference=None,
    )

    draft_version_ids = []
    for _ in range(draft_version_count):
        version = pack_specification_service.create_draft_version(
            session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            pack_specification_id=spec.id, grade_definition_version_id=None, packaging_unit_id=unit.id,
            nominal_net_weight_kg=Decimal("5.000"), whole_units_per_pack=None, spec_notes=None,
        )
        draft_version_ids.append(version.id)

    session.commit()
    result = {
        "tenant_id": tenant.id, "user_id": user.id, "crop_id": crop.id, "packaging_unit_id": unit.id,
        "pack_specification_id": spec.id, "draft_version_ids": draft_version_ids, "suffix": suffix,
    }
    session.close()
    conn.close()
    return result


def build_packaging_unit_only_scenario(test_engine):
    """Isolated scenario: one committed PackagingUnit, and nothing else --
    no crop, no PackSpecification, no version. Used to prove the downgrade
    guard fires on PackagingUnit existence alone, independent of the other
    two tables."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"pu-only-{suffix}", name="Packaging Unit Only Tenant")
    user = user_service.create_user(
        session, oidc_issuer="pu-only", oidc_subject=suffix, email=f"pu-only-{suffix}@example.com",
        display_name="Packaging Unit Only User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    unit = packaging_unit_service.register_packaging_unit(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"unit-{suffix}", name="Test Unit",
    )
    session.commit()
    result = {"tenant_id": tenant.id, "user_id": user.id, "packaging_unit_id": unit.id, "suffix": suffix}
    session.close()
    conn.close()
    return result


def build_pack_specification_only_scenario(test_engine):
    """Isolated scenario: one committed PackSpecification (and its
    required crop), with the packaging_units table left completely EMPTY
    for this tenant -- no PackagingUnit row is ever created. Used to
    prove the downgrade guard fires on PackSpecification existence alone,
    independent of the other two tables (a PackSpecification never
    requires a PackagingUnit -- only its VERSION does)."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"ps-only-{suffix}", name="Pack Spec Only Tenant")
    user = user_service.create_user(
        session, oidc_issuer="ps-only", oidc_subject=suffix, email=f"ps-only-{suffix}@example.com",
        display_name="Pack Spec Only User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    spec = pack_specification_service.register_pack_specification(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"spec-{suffix}", name="Test Spec", crop_id=crop.id, variety_id=None, customer_reference=None,
    )
    session.commit()
    result = {
        "tenant_id": tenant.id, "user_id": user.id, "crop_id": crop.id, "pack_specification_id": spec.id,
        "suffix": suffix,
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
        conn.execute(text("DELETE FROM pack_specification_versions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM pack_specifications WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM packaging_units WHERE tenant_id = :tid"), {"tid": tenant_id})
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
