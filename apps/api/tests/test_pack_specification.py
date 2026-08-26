"""POSTHARVEST-OPS-001B: PackSpecification / PackSpecificationVersion
model, service, lifecycle, measure-rule, grade-compatibility, audit, and
idempotency tests. Mirrors test_grade_definition.py's own fixture/helper
conventions exactly."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.models.pack_specification_version import PackSpecificationVersion
from app.services import crop_service, grade_definition_service, pack_specification_service, packaging_unit_service, tenant_service
from app.services.errors import (
    CropNotFoundError,
    DuplicatePackSpecificationCodeError,
    GradeDefinitionVersionNotFoundError,
    InvalidPackSpecificationVersionEffectiveTimeError,
    PackagingUnitNotActiveError,
    PackagingUnitNotFoundError,
    PackSpecificationCommandReusedWithDifferentPayloadError,
    PackSpecificationNotFoundError,
    PackSpecificationVersionActivationReusedWithDifferentPayloadError,
    PackSpecificationVersionCommandReusedWithDifferentPayloadError,
    PackSpecificationVersionNotActiveError,
    PackSpecificationVersionNotDraftError,
    PackSpecificationVersionNotFoundError,
    PackSpecificationVersionRetirementReusedWithDifferentPayloadError,
    PackSpecificationVersionValidationError,
    VarietyCropMismatchError,
)

# --- Helpers -----------------------------------------------------------------------


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


def _create_version(db_session, tenant, spec, unit, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        pack_specification_id=spec.id, grade_definition_version_id=None, packaging_unit_id=unit.id,
        nominal_net_weight_kg=Decimal("5.000"), whole_units_per_pack=None, spec_notes=None,
    )
    defaults.update(overrides)
    return pack_specification_service.create_draft_version(db_session, **defaults)


def _activate(db_session, tenant, spec, version, effective_time=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        pack_specification_id=spec.id, version_id=version.id, effective_time=effective_time or _now(),
    )
    defaults.update(overrides)
    return pack_specification_service.activate_version(db_session, **defaults)


def _retire(db_session, tenant, spec, version, effective_time=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        pack_specification_id=spec.id, version_id=version.id, effective_time=effective_time or _now(),
    )
    defaults.update(overrides)
    return pack_specification_service.retire_version(db_session, **defaults)


def _second_tenant(db_session, *, code="pack-spec-tenant-b"):
    return tenant_service.create_tenant(db_session, code=code, name="Tenant B")


def _grade_version(db_session, tenant, crop, *, variety_id=None, status="active", code="GRADE-A"):
    """Creates a GradeDefinition (scoped to crop/variety_id) with one
    version at the requested lifecycle status ('draft' | 'active' |
    'retired')."""
    definition = grade_definition_service.register_grade_definition(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code=code,
        name=code, crop_id=crop.id, variety_id=variety_id, description=None,
    )
    version = grade_definition_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, spec_notes=None,
    )
    if status == "draft":
        return definition, version
    grade_definition_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, version_id=version.id, effective_time=_now() - timedelta(days=1),
    )
    if status == "active":
        return definition, version
    grade_definition_service.retire_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, version_id=version.id, effective_time=_now(),
    )
    return definition, version


def _audit_events(db_session, *, action, entity_id):
    return list(
        db_session.execute(
            select(AuditEvent).where(AuditEvent.action == action, AuditEvent.entity_id == entity_id)
        ).scalars()
    )


def _audit_count(db_session, *, action, entity_id):
    return len(_audit_events(db_session, action=action, entity_id=entity_id))


# --- PackSpecification identity (13-25) ----------------------------------------------


@pytest.mark.integration
def test_create_valid_pack_specification(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    assert spec.code == "SPEC-1"
    assert spec.crop_id == crop.id
    assert spec.variety_id is None


@pytest.mark.integration
def test_required_valid_crop(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    with pytest.raises(CropNotFoundError):
        _register_spec(db_session, tenant, crop=type("X", (), {"id": uuid.uuid4()})())


@pytest.mark.integration
def test_specific_valid_same_crop_variety(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    variety = _setup_variety(db_session, tenant, crop)
    spec = _register_spec(db_session, tenant, crop, variety_id=variety.id)
    assert spec.variety_id == variety.id


@pytest.mark.integration
def test_null_variety_allowed(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop, variety_id=None)
    assert spec.variety_id is None


@pytest.mark.integration
def test_wrong_crop_variety_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant, code="LET")
    crop_b = _setup_crop(db_session, tenant, code="TOM")
    variety_of_b = _setup_variety(db_session, tenant, crop_b)
    with pytest.raises(VarietyCropMismatchError):
        _register_spec(db_session, tenant, crop_a, variety_id=variety_of_b.id)


@pytest.mark.integration
def test_cross_tenant_crop_rejected(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = _second_tenant(db_session)
    crop_b = _setup_crop(db_session, tenant_b, code="LET-B")
    with pytest.raises(CropNotFoundError):
        _register_spec(db_session, tenant_a, crop_b)


@pytest.mark.integration
def test_cross_tenant_variety_rejected(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant_a)
    tenant_b = _second_tenant(db_session)
    crop_b = _setup_crop(db_session, tenant_b, code="LET-B")
    variety_b = _setup_variety(db_session, tenant_b, crop_b)
    with pytest.raises(VarietyCropMismatchError):
        _register_spec(db_session, tenant_a, crop_a, variety_id=variety_b.id)


@pytest.mark.integration
def test_tenant_unique_code_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    _register_spec(db_session, tenant, crop, code="DUPE")
    with pytest.raises(DuplicatePackSpecificationCodeError):
        _register_spec(db_session, tenant, crop, code="dupe", client_command_id=uuid.uuid4())


@pytest.mark.integration
def test_same_code_allowed_across_different_tenants(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant_a)
    _register_spec(db_session, tenant_a, crop_a, code="SHARED")
    tenant_b = _second_tenant(db_session)
    crop_b = _setup_crop(db_session, tenant_b, code="LET-B")
    spec_b = _register_spec(db_session, tenant_b, crop_b, code="SHARED")
    assert spec_b.tenant_id == tenant_b.id


@pytest.mark.integration
def test_pack_specification_hard_delete_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM pack_specifications WHERE id = :id"), {"id": spec.id})


@pytest.mark.integration
def test_pack_specification_scope_mutation_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("UPDATE pack_specifications SET code = 'CHANGED' WHERE id = :id"), {"id": spec.id})


@pytest.mark.integration
def test_exact_pack_specification_replay_returns_original(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    command_id = uuid.uuid4()
    first = _register_spec(db_session, tenant, crop, client_command_id=command_id)
    second = _register_spec(db_session, tenant, crop, client_command_id=command_id)
    assert first.id == second.id


@pytest.mark.integration
def test_mismatched_pack_specification_replay_conflicts(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    command_id = uuid.uuid4()
    _register_spec(db_session, tenant, crop, client_command_id=command_id, code="A")
    with pytest.raises(PackSpecificationCommandReusedWithDifferentPayloadError):
        _register_spec(db_session, tenant, crop, client_command_id=command_id, code="B")


# --- PackSpecVersion: numbering / measures (26-33) ------------------------------------


@pytest.mark.integration
def test_first_draft_version_is_number_1(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    assert version.version_number == 1
    assert version.status == "draft"


@pytest.mark.integration
def test_second_draft_version_is_number_2(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    _create_version(db_session, tenant, spec, unit)
    version_2 = _create_version(db_session, tenant, spec, unit)
    assert version_2.version_number == 2


@pytest.mark.integration
def test_weight_only_measure_valid(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(
        db_session, tenant, spec, unit, nominal_net_weight_kg=Decimal("2.500"), whole_units_per_pack=None
    )
    assert version.nominal_net_weight_kg == Decimal("2.500")
    assert version.whole_units_per_pack is None


@pytest.mark.integration
def test_whole_unit_only_measure_valid(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(
        db_session, tenant, spec, unit, nominal_net_weight_kg=None, whole_units_per_pack=12
    )
    assert version.nominal_net_weight_kg is None
    assert version.whole_units_per_pack == 12


@pytest.mark.integration
def test_both_measures_valid(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(
        db_session, tenant, spec, unit, nominal_net_weight_kg=Decimal("1.000"), whole_units_per_pack=6
    )
    assert version.nominal_net_weight_kg == Decimal("1.000")
    assert version.whole_units_per_pack == 6


@pytest.mark.integration
def test_both_measures_null_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    with pytest.raises(PackSpecificationVersionValidationError):
        _create_version(db_session, tenant, spec, unit, nominal_net_weight_kg=None, whole_units_per_pack=None)


@pytest.mark.integration
def test_zero_and_negative_nominal_weight_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    with pytest.raises(PackSpecificationVersionValidationError):
        _create_version(db_session, tenant, spec, unit, nominal_net_weight_kg=Decimal("0"), whole_units_per_pack=None)
    with pytest.raises(PackSpecificationVersionValidationError):
        _create_version(
            db_session, tenant, spec, unit, nominal_net_weight_kg=Decimal("-1.000"), whole_units_per_pack=None,
            client_command_id=uuid.uuid4(),
        )


@pytest.mark.integration
def test_zero_and_negative_whole_units_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    with pytest.raises(PackSpecificationVersionValidationError):
        _create_version(db_session, tenant, spec, unit, nominal_net_weight_kg=None, whole_units_per_pack=0)
    with pytest.raises(PackSpecificationVersionValidationError):
        _create_version(
            db_session, tenant, spec, unit, nominal_net_weight_kg=None, whole_units_per_pack=-3,
            client_command_id=uuid.uuid4(),
        )


# --- PackSpecVersion: PackagingUnit reference (34-36) --------------------------------


@pytest.mark.integration
def test_packaging_unit_must_be_same_tenant(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant_a)
    spec_a = _register_spec(db_session, tenant_a, crop_a)
    tenant_b = _second_tenant(db_session)
    unit_b = _register_unit(db_session, tenant_b)
    with pytest.raises(PackagingUnitNotFoundError):
        _create_version(db_session, tenant_a, spec_a, unit_b)


@pytest.mark.integration
def test_retired_packaging_unit_rejected_for_new_version(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    packaging_unit_service.retire_packaging_unit(
        db_session, tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        packaging_unit_id=unit.id,
    )
    with pytest.raises(PackagingUnitNotActiveError):
        _create_version(db_session, tenant, spec, unit)


@pytest.mark.integration
def test_cross_tenant_packaging_unit_rejected(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant_a)
    spec_a = _register_spec(db_session, tenant_a, crop_a)
    tenant_b = _second_tenant(db_session)
    unit_b = _register_unit(db_session, tenant_b)
    with pytest.raises(PackagingUnitNotFoundError):
        _create_version(db_session, tenant_a, spec_a, unit_b)


# --- PackSpecVersion: grade compatibility (37-44) -------------------------------------


@pytest.mark.integration
def test_grade_reference_null_valid(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit, grade_definition_version_id=None)
    assert version.grade_definition_version_id is None


@pytest.mark.integration
def test_same_crop_all_variety_grade_version_valid(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop, variety_id=None)
    unit = _register_unit(db_session, tenant)
    _definition, grade_version = _grade_version(db_session, tenant, crop, variety_id=None, status="active")
    version = _create_version(db_session, tenant, spec, unit, grade_definition_version_id=grade_version.id)
    assert version.grade_definition_version_id == grade_version.id


@pytest.mark.integration
def test_same_crop_exact_variety_grade_version_valid(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    variety = _setup_variety(db_session, tenant, crop)
    spec = _register_spec(db_session, tenant, crop, variety_id=variety.id)
    unit = _register_unit(db_session, tenant)
    _definition, grade_version = _grade_version(db_session, tenant, crop, variety_id=variety.id, status="active")
    version = _create_version(db_session, tenant, spec, unit, grade_definition_version_id=grade_version.id)
    assert version.grade_definition_version_id == grade_version.id


@pytest.mark.integration
def test_spec_variety_null_accepts_variety_specific_grade(db_session, active_context) -> None:
    """POSTHARVEST-OPS-001B frozen rule 2: a NULL-variety PackSpecification
    may still reference a variety-specific GradeDefinitionVersion -- the
    grade version deliberately narrows applicability."""
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    variety = _setup_variety(db_session, tenant, crop)
    spec = _register_spec(db_session, tenant, crop, variety_id=None)
    unit = _register_unit(db_session, tenant)
    _definition, grade_version = _grade_version(db_session, tenant, crop, variety_id=variety.id, status="active")
    version = _create_version(db_session, tenant, spec, unit, grade_definition_version_id=grade_version.id)
    assert version.grade_definition_version_id == grade_version.id


@pytest.mark.integration
def test_wrong_specific_variety_grade_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    variety_a = _setup_variety(db_session, tenant, crop, code="A")
    variety_b = _setup_variety(db_session, tenant, crop, code="B")
    spec = _register_spec(db_session, tenant, crop, variety_id=variety_a.id)
    unit = _register_unit(db_session, tenant)
    _definition, grade_version = _grade_version(db_session, tenant, crop, variety_id=variety_b.id, status="active")
    with pytest.raises(PackSpecificationVersionValidationError):
        _create_version(db_session, tenant, spec, unit, grade_definition_version_id=grade_version.id)


@pytest.mark.integration
def test_wrong_crop_grade_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant, code="LET")
    crop_b = _setup_crop(db_session, tenant, code="TOM")
    spec = _register_spec(db_session, tenant, crop_a)
    unit = _register_unit(db_session, tenant)
    _definition, grade_version = _grade_version(db_session, tenant, crop_b, variety_id=None, status="active")
    with pytest.raises(PackSpecificationVersionValidationError):
        _create_version(db_session, tenant, spec, unit, grade_definition_version_id=grade_version.id)


@pytest.mark.integration
def test_cross_tenant_grade_version_rejected(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant_a)
    spec_a = _register_spec(db_session, tenant_a, crop_a)
    unit_a = _register_unit(db_session, tenant_a)

    tenant_b = _second_tenant(db_session)
    crop_b = _setup_crop(db_session, tenant_b, code="LET-B")
    _definition_b, grade_version_b = _grade_version(db_session, tenant_b, crop_b, variety_id=None, status="active")

    with pytest.raises(GradeDefinitionVersionNotFoundError):
        _create_version(db_session, tenant_a, spec_a, unit_a, grade_definition_version_id=grade_version_b.id)


@pytest.mark.integration
def test_draft_grade_version_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    _definition, grade_version = _grade_version(db_session, tenant, crop, variety_id=None, status="draft")
    with pytest.raises(PackSpecificationVersionValidationError):
        _create_version(db_session, tenant, spec, unit, grade_definition_version_id=grade_version.id)


@pytest.mark.integration
def test_retired_grade_version_accepted(db_session, active_context) -> None:
    """A retired grade version may still describe already-graded inventory
    that must later be packed under its exact historical standard."""
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    _definition, grade_version = _grade_version(db_session, tenant, crop, variety_id=None, status="retired")
    version = _create_version(db_session, tenant, spec, unit, grade_definition_version_id=grade_version.id)
    assert version.grade_definition_version_id == grade_version.id


# --- PackSpecVersion: semantic immutability / hard delete (45-46) --------------------


@pytest.mark.integration
def test_version_semantic_field_mutation_rejected_by_postgres(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit, spec_notes="Original")
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE pack_specification_versions SET spec_notes = 'Changed' WHERE id = :id"),
                {"id": version.id},
            )


@pytest.mark.integration
def test_version_hard_delete_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM pack_specification_versions WHERE id = :id"), {"id": version.id})


# --- PackSpecVersion: lifecycle (47-53) -----------------------------------------------


@pytest.mark.integration
def test_first_activation(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    effective_time = _now()
    activated = _activate(db_session, tenant, spec, version, effective_time=effective_time)
    assert activated.status == "active"
    assert activated.effective_from == effective_time
    assert activated.effective_until is None


@pytest.mark.integration
def test_replacement_activation(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version_1 = _create_version(db_session, tenant, spec, unit)
    _activate(db_session, tenant, spec, version_1, effective_time=_now() - timedelta(days=1))
    version_2 = _create_version(db_session, tenant, spec, unit)
    activated_2 = _activate(db_session, tenant, spec, version_2, effective_time=_now())
    assert activated_2.status == "active"
    assert version_2.version_number == 2


@pytest.mark.integration
def test_previous_active_retired_with_correct_effective_until(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version_1 = _create_version(db_session, tenant, spec, unit)
    t1 = _now() - timedelta(days=1)
    _activate(db_session, tenant, spec, version_1, effective_time=t1)
    version_2 = _create_version(db_session, tenant, spec, unit)
    t2 = _now()
    _activate(db_session, tenant, spec, version_2, effective_time=t2)

    db_session.refresh(version_1)
    assert version_1.status == "retired"
    assert version_1.effective_until == t2
    assert version_1.retirement_client_command_id is None


@pytest.mark.integration
def test_only_one_active_version_remains(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version_1 = _create_version(db_session, tenant, spec, unit)
    _activate(db_session, tenant, spec, version_1, effective_time=_now() - timedelta(days=1))
    version_2 = _create_version(db_session, tenant, spec, unit)
    _activate(db_session, tenant, spec, version_2, effective_time=_now())

    active_count = db_session.execute(
        select(func.count()).select_from(PackSpecificationVersion).where(
            PackSpecificationVersion.pack_specification_id == spec.id,
            PackSpecificationVersion.status == "active",
        )
    ).scalar_one()
    assert active_count == 1


@pytest.mark.integration
def test_explicit_retire_without_replacement(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    t1 = _now() - timedelta(hours=1)
    _activate(db_session, tenant, spec, version, effective_time=t1)
    t2 = _now()
    retired = _retire(db_session, tenant, spec, version, effective_time=t2)
    assert retired.status == "retired"
    assert retired.effective_until == t2
    assert retired.retirement_client_command_id is not None


@pytest.mark.integration
def test_retired_version_cannot_reactivate(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    _activate(db_session, tenant, spec, version, effective_time=_now() - timedelta(hours=1))
    _retire(db_session, tenant, spec, version, effective_time=_now())
    with pytest.raises(PackSpecificationVersionNotDraftError):
        _activate(db_session, tenant, spec, version, effective_time=_now())


@pytest.mark.integration
def test_invalid_temporal_transition_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    with pytest.raises(InvalidPackSpecificationVersionEffectiveTimeError):
        _activate(db_session, tenant, spec, version, effective_time=_now() + timedelta(days=1))

    version_active = _create_version(db_session, tenant, spec, unit, client_command_id=uuid.uuid4())
    t1 = _now()
    _activate(db_session, tenant, spec, version_active, effective_time=t1)
    with pytest.raises(InvalidPackSpecificationVersionEffectiveTimeError):
        _retire(db_session, tenant, spec, version_active, effective_time=t1 - timedelta(hours=1))


@pytest.mark.integration
def test_retire_target_not_active_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    with pytest.raises(PackSpecificationVersionNotActiveError):
        _retire(db_session, tenant, spec, version)


# --- Audit (54-60) ---------------------------------------------------------------------


@pytest.mark.integration
def test_first_activation_creates_one_activated_audit_and_no_supersession_retired_audit(
    db_session, active_context
) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    _activate(db_session, tenant, spec, version, effective_time=_now())

    assert _audit_count(db_session, action="pack_specification_version.activated", entity_id=version.id) == 1
    retired_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "pack_specification_version.retired",
            AuditEvent.event_data["pack_specification_id"].astext == str(spec.id),
        )
    ).scalar_one()
    assert retired_count == 0


@pytest.mark.integration
def test_replacement_creates_both_lifecycle_audit_events(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version_1 = _create_version(db_session, tenant, spec, unit)
    _activate(db_session, tenant, spec, version_1, effective_time=_now() - timedelta(days=1))
    version_2 = _create_version(db_session, tenant, spec, unit)
    _activate(db_session, tenant, spec, version_2, effective_time=_now())

    activated_events = _audit_events(
        db_session, action="pack_specification_version.activated", entity_id=version_2.id
    )
    assert len(activated_events) == 1
    assert activated_events[0].event_data["replaced_version_id"] == str(version_1.id)

    retired_events = _audit_events(
        db_session, action="pack_specification_version.retired", entity_id=version_1.id
    )
    assert len(retired_events) == 1
    assert retired_events[0].event_data["reason"] == "superseded"
    assert retired_events[0].event_data["superseded_by_version_id"] == str(version_2.id)


@pytest.mark.integration
def test_replacement_replay_creates_no_duplicate_audit_events(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version_1 = _create_version(db_session, tenant, spec, unit)
    _activate(db_session, tenant, spec, version_1, effective_time=_now() - timedelta(days=1))
    version_2 = _create_version(db_session, tenant, spec, unit)

    command_id = uuid.uuid4()
    effective_time = _now()
    first = _activate(db_session, tenant, spec, version_2, effective_time=effective_time, client_command_id=command_id)
    second = _activate(db_session, tenant, spec, version_2, effective_time=effective_time, client_command_id=command_id)
    assert first.id == second.id

    assert _audit_count(db_session, action="pack_specification_version.activated", entity_id=version_2.id) == 1
    assert _audit_count(db_session, action="pack_specification_version.retired", entity_id=version_1.id) == 1


@pytest.mark.integration
def test_failed_replacement_activation_persists_no_audit_events(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version_1 = _create_version(db_session, tenant, spec, unit)
    t1 = _now()
    _activate(db_session, tenant, spec, version_1, effective_time=t1)
    version_2 = _create_version(db_session, tenant, spec, unit)

    with pytest.raises(InvalidPackSpecificationVersionEffectiveTimeError):
        _activate(db_session, tenant, spec, version_2, effective_time=t1 - timedelta(hours=1))

    db_session.refresh(version_1)
    db_session.refresh(version_2)
    assert version_1.status == "active"
    assert version_2.status == "draft"
    assert _audit_count(db_session, action="pack_specification_version.activated", entity_id=version_2.id) == 0
    assert _audit_count(db_session, action="pack_specification_version.retired", entity_id=version_1.id) == 0


@pytest.mark.integration
def test_explicit_retirement_audit_distinguishable_from_supersession(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    _activate(db_session, tenant, spec, version, effective_time=_now() - timedelta(hours=1))
    _retire(db_session, tenant, spec, version, effective_time=_now())

    retired_events = _audit_events(
        db_session, action="pack_specification_version.retired", entity_id=version.id
    )
    assert len(retired_events) == 1
    assert retired_events[0].event_data["reason"] == "explicit"
    assert "superseded_by_version_id" not in retired_events[0].event_data


@pytest.mark.integration
def test_pack_specification_and_version_create_audits(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    assert _audit_count(db_session, action="pack_specification.created", entity_id=spec.id) == 1
    assert _audit_count(db_session, action="pack_specification_version.created", entity_id=version.id) == 1


# --- Idempotency (61-64) ---------------------------------------------------------------


@pytest.mark.integration
def test_exact_create_version_replay_returns_original(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    command_id = uuid.uuid4()
    first = _create_version(db_session, tenant, spec, unit, client_command_id=command_id)
    second = _create_version(db_session, tenant, spec, unit, client_command_id=command_id)
    assert first.id == second.id
    count = db_session.execute(
        select(func.count()).select_from(PackSpecificationVersion).where(
            PackSpecificationVersion.pack_specification_id == spec.id
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.integration
def test_mismatched_create_version_replay_conflicts(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    command_id = uuid.uuid4()
    _create_version(db_session, tenant, spec, unit, client_command_id=command_id, spec_notes="A")
    with pytest.raises(PackSpecificationVersionCommandReusedWithDifferentPayloadError):
        _create_version(db_session, tenant, spec, unit, client_command_id=command_id, spec_notes="B")


@pytest.mark.integration
def test_exact_activation_replay_returns_original(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    command_id = uuid.uuid4()
    effective_time = _now()
    first = _activate(db_session, tenant, spec, version, effective_time=effective_time, client_command_id=command_id)
    second = _activate(db_session, tenant, spec, version, effective_time=effective_time, client_command_id=command_id)
    assert first.id == second.id
    assert second.status == "active"


@pytest.mark.integration
def test_mismatched_activation_replay_conflicts(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    command_id = uuid.uuid4()
    _activate(db_session, tenant, spec, version, effective_time=_now(), client_command_id=command_id)
    with pytest.raises(PackSpecificationVersionActivationReusedWithDifferentPayloadError):
        _activate(
            db_session, tenant, spec, version, effective_time=_now() + timedelta(seconds=-1),
            client_command_id=command_id,
        )


@pytest.mark.integration
def test_exact_retirement_replay_returns_original(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    _activate(db_session, tenant, spec, version, effective_time=_now() - timedelta(hours=1))
    command_id = uuid.uuid4()
    effective_time = _now()
    first = _retire(db_session, tenant, spec, version, effective_time=effective_time, client_command_id=command_id)
    second = _retire(db_session, tenant, spec, version, effective_time=effective_time, client_command_id=command_id)
    assert first.id == second.id
    assert second.status == "retired"


@pytest.mark.integration
def test_mismatched_retirement_replay_conflicts(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    spec = _register_spec(db_session, tenant, crop)
    unit = _register_unit(db_session, tenant)
    version = _create_version(db_session, tenant, spec, unit)
    _activate(db_session, tenant, spec, version, effective_time=_now() - timedelta(hours=1))
    command_id = uuid.uuid4()
    _retire(db_session, tenant, spec, version, effective_time=_now(), client_command_id=command_id)
    with pytest.raises(PackSpecificationVersionRetirementReusedWithDifferentPayloadError):
        _retire(
            db_session, tenant, spec, version, effective_time=_now() + timedelta(seconds=1),
            client_command_id=command_id,
        )


@pytest.mark.integration
def test_tenant_isolated_version_list(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant_a)
    spec_a = _register_spec(db_session, tenant_a, crop_a)
    unit_a = _register_unit(db_session, tenant_a)
    _create_version(db_session, tenant_a, spec_a, unit_a)

    tenant_b = _second_tenant(db_session)
    with pytest.raises(PackSpecificationNotFoundError):
        pack_specification_service.list_versions(db_session, tenant_id=tenant_b.id, pack_specification_id=spec_a.id)
