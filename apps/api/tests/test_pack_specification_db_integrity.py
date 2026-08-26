"""POSTHARVEST-OPS-001B: direct-SQL proofs that packaging-unit/pack-
specification integrity is enforced at the database layer, not merely by
the service -- mirrors test_grade_definition_db_integrity.py's own
conventions (`db_session.begin_nested()` + `pytest.raises(DBAPIError)`)."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services import (
    crop_service,
    grade_definition_service,
    pack_specification_service,
    packaging_unit_service,
    tenant_service,
)


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


def _register_unit(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="CARTON", name="Carton",
    )
    defaults.update(overrides)
    return packaging_unit_service.register_packaging_unit(db_session, **defaults)


def _register_spec(db_session, tenant, crop, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="SPEC-1", name="Spec 1",
        crop_id=crop.id, variety_id=None, customer_reference=None,
    )
    defaults.update(overrides)
    return pack_specification_service.register_pack_specification(db_session, **defaults)


def _active_grade_version(db_session, tenant, crop, *, variety_id=None):
    definition = grade_definition_service.register_grade_definition(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="GRADE-A",
        name="Grade A", crop_id=crop.id, variety_id=variety_id, description=None,
    )
    version = grade_definition_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, spec_notes=None,
    )
    grade_definition_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, version_id=version.id, effective_time=_now() - timedelta(days=1),
    )
    return definition, version


def _draft_grade_version(db_session, tenant, crop):
    definition = grade_definition_service.register_grade_definition(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="GRADE-B",
        name="Grade B", crop_id=crop.id, variety_id=None, description=None,
    )
    version = grade_definition_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, spec_notes=None,
    )
    return definition, version


@pytest.mark.integration
def test_direct_sql_cross_tenant_packaging_unit_rejected(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant_a)
    spec_a = _register_spec(db_session, tenant_a, crop_a)

    tenant_b = tenant_service.create_tenant(db_session, code="pspec-db-tenant-b", name="Tenant B")
    unit_b = _register_unit(db_session, tenant_b)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO pack_specification_versions "
                    "(id, tenant_id, pack_specification_id, version_number, status, packaging_unit_id, "
                    " nominal_net_weight_kg, client_command_id, request_fingerprint) "
                    "VALUES (:id, :tenant_id, :spec_id, 1, 'draft', :unit_id, 1.000, :cmd, 'fp')"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant_a.id, "spec_id": spec_a.id, "unit_id": unit_b.id,
                    "cmd": uuid.uuid4(),
                },
            )


@pytest.mark.integration
def test_direct_sql_retired_packaging_unit_relationship_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    packaging_unit_service.retire_packaging_unit(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        packaging_unit_id=unit.id,
    )

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO pack_specification_versions "
                    "(id, tenant_id, pack_specification_id, version_number, status, packaging_unit_id, "
                    " nominal_net_weight_kg, client_command_id, request_fingerprint) "
                    "VALUES (:id, :tenant_id, :spec_id, 1, 'draft', :unit_id, 1.000, :cmd, 'fp')"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "spec_id": spec.id, "unit_id": unit.id,
                    "cmd": uuid.uuid4(),
                },
            )


@pytest.mark.integration
def test_direct_sql_cross_tenant_pack_specification_crop_rejected(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = tenant_service.create_tenant(db_session, code="pspec-db-tenant-b2", name="Tenant B")
    crop_b = _setup_crop(db_session, tenant_b, code="LET-B")

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO pack_specifications "
                    "(id, tenant_id, crop_id, code, name, client_command_id, request_fingerprint) "
                    "VALUES (:id, :tenant_id, :crop_id, 'BAD', 'Bad', :cmd, 'fp')"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant_a.id, "crop_id": crop_b.id, "cmd": uuid.uuid4()},
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
                    "INSERT INTO pack_specifications "
                    "(id, tenant_id, crop_id, variety_id, code, name, client_command_id, request_fingerprint) "
                    "VALUES (:id, :tenant_id, :crop_id, :variety_id, 'BAD', 'Bad', :cmd, 'fp')"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "crop_id": crop_a.id,
                    "variety_id": variety_of_b.id, "cmd": uuid.uuid4(),
                },
            )


@pytest.mark.integration
def test_direct_sql_wrong_crop_grade_version_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant, code="LET")
    crop_b = _setup_crop(db_session, tenant, code="TOM")
    spec = _register_spec(db_session, tenant, crop_a)
    unit = _register_unit(db_session, tenant)
    _definition, grade_version = _active_grade_version(db_session, tenant, crop_b)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO pack_specification_versions "
                    "(id, tenant_id, pack_specification_id, version_number, status, packaging_unit_id, "
                    " grade_definition_version_id, nominal_net_weight_kg, client_command_id, request_fingerprint) "
                    "VALUES (:id, :tenant_id, :spec_id, 1, 'draft', :unit_id, :grade_version_id, 1.000, :cmd, 'fp')"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "spec_id": spec.id, "unit_id": unit.id,
                    "grade_version_id": grade_version.id, "cmd": uuid.uuid4(),
                },
            )


@pytest.mark.integration
def test_direct_sql_draft_grade_version_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    _definition, grade_version = _draft_grade_version(db_session, tenant, crop)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO pack_specification_versions "
                    "(id, tenant_id, pack_specification_id, version_number, status, packaging_unit_id, "
                    " grade_definition_version_id, nominal_net_weight_kg, client_command_id, request_fingerprint) "
                    "VALUES (:id, :tenant_id, :spec_id, 1, 'draft', :unit_id, :grade_version_id, 1.000, :cmd, 'fp')"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "spec_id": spec.id, "unit_id": unit.id,
                    "grade_version_id": grade_version.id, "cmd": uuid.uuid4(),
                },
            )


@pytest.mark.integration
def test_direct_sql_second_active_version_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version_1 = pack_specification_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        pack_specification_id=spec.id, grade_definition_version_id=None, packaging_unit_id=unit.id,
        nominal_net_weight_kg=Decimal("1.000"), whole_units_per_pack=None, spec_notes=None,
    )
    pack_specification_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        pack_specification_id=spec.id, version_id=version_1.id, effective_time=_now(),
    )

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO pack_specification_versions "
                    "(id, tenant_id, pack_specification_id, version_number, status, packaging_unit_id, "
                    " nominal_net_weight_kg, effective_from, effective_until, client_command_id, "
                    " request_fingerprint, activation_client_command_id, activation_request_fingerprint) "
                    "VALUES (:id, :tenant_id, :spec_id, 99, 'active', :unit_id, 1.000, :eff, NULL, :cmd, 'fp', "
                    " :acmd, 'afp')"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "spec_id": spec.id, "unit_id": unit.id,
                    "eff": _now(), "cmd": uuid.uuid4(), "acmd": uuid.uuid4(),
                },
            )


@pytest.mark.integration
def test_direct_sql_version_identity_mutation_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = pack_specification_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        pack_specification_id=spec.id, grade_definition_version_id=None, packaging_unit_id=unit.id,
        nominal_net_weight_kg=Decimal("1.000"), whole_units_per_pack=None, spec_notes=None,
    )

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE pack_specification_versions SET version_number = 99 WHERE id = :id"),
                {"id": version.id},
            )


@pytest.mark.integration
def test_direct_sql_hard_delete_rejected_all_tables(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = pack_specification_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        pack_specification_id=spec.id, grade_definition_version_id=None, packaging_unit_id=unit.id,
        nominal_net_weight_kg=Decimal("1.000"), whole_units_per_pack=None, spec_notes=None,
    )

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM pack_specification_versions WHERE id = :id"), {"id": version.id})

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM pack_specifications WHERE id = :id"), {"id": spec.id})

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM packaging_units WHERE id = :id"), {"id": unit.id})
