"""POSTHARVEST-OPS-001A: direct-SQL proofs that grade-definition integrity
is enforced at the database layer, not merely by the service — mirrors
test_workflow_publish.py's own direct-SQL negative-test conventions
(`db_session.begin_nested()` + `pytest.raises(DBAPIError)`)."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services import crop_service, grade_definition_service, tenant_service


def _now():
    return datetime.now(timezone.utc)


def _setup_crop(db_session, tenant, *, code="LET"):
    return crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code=code, common_name="Lettuce",
        scientific_name=None, crop_category="leafy_green",
    )


def _setup_variety(db_session, tenant, crop, *, code="MAM"):
    return crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=None, crop_id=crop.id, code=code, name="Mamutik RZ",
        supplier_reference=None,
    )


@pytest.mark.integration
def test_direct_sql_wrong_crop_variety_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant, code="LET")
    crop_b = _setup_crop(db_session, tenant, code="TOM")
    variety_of_b = _setup_variety(db_session, tenant, crop_b)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO grade_definitions "
                    "(id, tenant_id, crop_id, variety_id, code, name, client_command_id, request_fingerprint) "
                    "VALUES (:id, :tenant_id, :crop_id, :variety_id, 'BAD', 'Bad', :cmd, 'fp')"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "crop_id": crop_a.id,
                    "variety_id": variety_of_b.id, "cmd": uuid.uuid4(),
                },
            )


@pytest.mark.integration
def test_direct_sql_cross_tenant_crop_rejected(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant_a)
    tenant_b = tenant_service.create_tenant(db_session, code="grade-db-tenant-b", name="Tenant B")

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO grade_definitions "
                    "(id, tenant_id, crop_id, variety_id, code, name, client_command_id, request_fingerprint) "
                    "VALUES (:id, :tenant_id, :crop_id, NULL, 'BAD', 'Bad', :cmd, 'fp')"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant_b.id, "crop_id": crop_a.id, "cmd": uuid.uuid4()},
            )


@pytest.mark.integration
def test_direct_sql_second_active_version_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = grade_definition_service.register_grade_definition(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="PREMIUM",
        name="Premium", crop_id=crop.id, variety_id=None, description=None,
    )
    version_1 = grade_definition_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, spec_notes=None,
    )
    grade_definition_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, version_id=version_1.id, effective_time=_now(),
    )

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO grade_definition_versions "
                    "(id, tenant_id, grade_definition_id, version_number, status, effective_from, "
                    " effective_until, client_command_id, request_fingerprint, "
                    " activation_client_command_id, activation_request_fingerprint) "
                    "VALUES (:id, :tenant_id, :gd_id, 99, 'active', :eff, NULL, :cmd, 'fp', :acmd, 'afp')"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "gd_id": definition.id, "eff": _now(),
                    "cmd": uuid.uuid4(), "acmd": uuid.uuid4(),
                },
            )


@pytest.mark.integration
def test_direct_sql_version_identity_mutation_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = grade_definition_service.register_grade_definition(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="PREMIUM",
        name="Premium", crop_id=crop.id, variety_id=None, description=None,
    )
    version = grade_definition_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, spec_notes=None,
    )

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE grade_definition_versions SET version_number = 99 WHERE id = :id"),
                {"id": version.id},
            )


@pytest.mark.integration
def test_direct_sql_grade_definition_version_hard_delete_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = grade_definition_service.register_grade_definition(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="PREMIUM",
        name="Premium", crop_id=crop.id, variety_id=None, description=None,
    )
    version = grade_definition_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, spec_notes=None,
    )

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM grade_definition_versions WHERE id = :id"), {"id": version.id})


@pytest.mark.integration
def test_direct_sql_grade_definition_hard_delete_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = grade_definition_service.register_grade_definition(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="PREMIUM",
        name="Premium", crop_id=crop.id, variety_id=None, description=None,
    )

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM grade_definitions WHERE id = :id"), {"id": definition.id})


@pytest.mark.integration
def test_direct_sql_grade_definition_update_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = grade_definition_service.register_grade_definition(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="PREMIUM",
        name="Premium", crop_id=crop.id, variety_id=None, description=None,
    )

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE grade_definitions SET name = 'Changed' WHERE id = :id"), {"id": definition.id}
            )
