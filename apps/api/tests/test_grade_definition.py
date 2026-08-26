"""POSTHARVEST-OPS-001A: GradeDefinition / GradeDefinitionVersion model,
service, and idempotency tests. Mirrors test_workflow_publish.py's own
fixture/helper conventions (db_session, active_context, tenant_service/
crop_service direct service calls) since GradeDefinition is this ticket's
own closest sibling to Workflow -- a tenant-scoped, versioned
configuration entity with no farm_id."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.models.grade_definition_version import GradeDefinitionVersion
from app.services import crop_service, grade_definition_service, tenant_service
from app.services.errors import (
    CropNotFoundError,
    DuplicateGradeDefinitionCodeError,
    GradeDefinitionCommandReusedWithDifferentPayloadError,
    GradeDefinitionNotFoundError,
    GradeDefinitionVersionActivationReusedWithDifferentPayloadError,
    GradeDefinitionVersionCommandReusedWithDifferentPayloadError,
    GradeDefinitionVersionNotActiveError,
    GradeDefinitionVersionNotDraftError,
    GradeDefinitionVersionNotFoundError,
    GradeDefinitionVersionRetirementReusedWithDifferentPayloadError,
    InvalidGradeDefinitionVersionEffectiveTimeError,
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


def _register_definition(db_session, tenant, crop, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="PREMIUM",
        name="Premium", crop_id=crop.id, variety_id=None, description=None,
    )
    defaults.update(overrides)
    return grade_definition_service.register_grade_definition(db_session, **defaults)


def _create_version(db_session, tenant, definition, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, spec_notes=None,
    )
    defaults.update(overrides)
    return grade_definition_service.create_draft_version(db_session, **defaults)


def _activate(db_session, tenant, definition, version, effective_time=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, version_id=version.id, effective_time=effective_time or _now(),
    )
    defaults.update(overrides)
    return grade_definition_service.activate_version(db_session, **defaults)


def _retire(db_session, tenant, definition, version, effective_time=None, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(),
        grade_definition_id=definition.id, version_id=version.id, effective_time=effective_time or _now(),
    )
    defaults.update(overrides)
    return grade_definition_service.retire_version(db_session, **defaults)


def _second_tenant(db_session, *, code="grade-tenant-b"):
    return tenant_service.create_tenant(db_session, code=code, name="Tenant B")


# --- 1-8: GradeDefinition creation / integrity --------------------------------------


@pytest.mark.integration
def test_create_grade_definition(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    assert definition.code == "PREMIUM"
    assert definition.crop_id == crop.id
    assert definition.variety_id is None


@pytest.mark.integration
def test_tenant_unique_code_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    _register_definition(db_session, tenant, crop, code="DUPE")
    with pytest.raises(DuplicateGradeDefinitionCodeError):
        _register_definition(db_session, tenant, crop, code="dupe", client_command_id=uuid.uuid4())


@pytest.mark.integration
def test_same_code_allowed_across_different_tenants(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant_a)
    _register_definition(db_session, tenant_a, crop_a, code="SHARED")

    tenant_b = _second_tenant(db_session)
    crop_b = _setup_crop(db_session, tenant_b, code="LET-B")
    definition_b = _register_definition(db_session, tenant_b, crop_b, code="SHARED")
    assert definition_b.tenant_id == tenant_b.id


@pytest.mark.integration
def test_required_valid_crop(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    with pytest.raises(CropNotFoundError):
        _register_definition(db_session, tenant, crop=type("X", (), {"id": uuid.uuid4()})())


@pytest.mark.integration
def test_optional_valid_same_crop_variety(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    variety = _setup_variety(db_session, tenant, crop)
    definition = _register_definition(db_session, tenant, crop, variety_id=variety.id)
    assert definition.variety_id == variety.id


@pytest.mark.integration
def test_wrong_crop_variety_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant, code="LET")
    crop_b = _setup_crop(db_session, tenant, code="TOM")
    variety_of_b = _setup_variety(db_session, tenant, crop_b)
    with pytest.raises(VarietyCropMismatchError):
        _register_definition(db_session, tenant, crop_a, variety_id=variety_of_b.id)


@pytest.mark.integration
def test_cross_tenant_crop_rejected(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = _second_tenant(db_session)
    crop_b = _setup_crop(db_session, tenant_b, code="LET-B")
    with pytest.raises(CropNotFoundError):
        _register_definition(db_session, tenant_a, crop_b)


@pytest.mark.integration
def test_cross_tenant_variety_rejected(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant_a)

    tenant_b = _second_tenant(db_session)
    crop_b = _setup_crop(db_session, tenant_b, code="LET-B")
    variety_b = _setup_variety(db_session, tenant_b, crop_b)

    with pytest.raises(VarietyCropMismatchError):
        _register_definition(db_session, tenant_a, crop_a, variety_id=variety_b.id)


# --- 9-12: version creation / immutability / delete ---------------------------------


@pytest.mark.integration
def test_first_draft_version_is_number_1(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    assert version.version_number == 1
    assert version.status == "draft"


@pytest.mark.integration
def test_second_draft_version_is_number_2(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    _create_version(db_session, tenant, definition)
    version_2 = _create_version(db_session, tenant, definition)
    assert version_2.version_number == 2


@pytest.mark.integration
def test_semantic_version_field_mutation_rejected_by_postgres(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition, spec_notes="Original criteria")

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE grade_definition_versions SET spec_notes = 'Changed' WHERE id = :id"),
                {"id": version.id},
            )


@pytest.mark.integration
def test_hard_delete_rejected_via_orm(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.delete(version)
            db_session.flush()


# --- 13-19: lifecycle -----------------------------------------------------------------


@pytest.mark.integration
def test_activate_first_version(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    effective_time = _now()
    activated = _activate(db_session, tenant, definition, version, effective_time=effective_time)
    assert activated.status == "active"
    assert activated.effective_from == effective_time
    assert activated.effective_until is None


@pytest.mark.integration
def test_create_and_activate_replacement_version(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version_1 = _create_version(db_session, tenant, definition)
    _activate(db_session, tenant, definition, version_1, effective_time=_now() - timedelta(days=1))

    version_2 = _create_version(db_session, tenant, definition)
    activated_2 = _activate(db_session, tenant, definition, version_2, effective_time=_now())
    assert activated_2.status == "active"
    assert version_2.version_number == 2


@pytest.mark.integration
def test_prior_active_retired_with_correct_effective_until(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version_1 = _create_version(db_session, tenant, definition)
    t1 = _now() - timedelta(days=1)
    _activate(db_session, tenant, definition, version_1, effective_time=t1)

    version_2 = _create_version(db_session, tenant, definition)
    t2 = _now()
    _activate(db_session, tenant, definition, version_2, effective_time=t2)

    db_session.refresh(version_1)
    assert version_1.status == "retired"
    assert version_1.effective_until == t2
    assert version_1.retirement_client_command_id is None, (
        "retirement-by-replacement must not populate the explicit retirement idempotency key"
    )


@pytest.mark.integration
def test_only_one_active_version_remains(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version_1 = _create_version(db_session, tenant, definition)
    _activate(db_session, tenant, definition, version_1, effective_time=_now() - timedelta(days=1))
    version_2 = _create_version(db_session, tenant, definition)
    _activate(db_session, tenant, definition, version_2, effective_time=_now())

    active_count = db_session.execute(
        select(func.count()).select_from(GradeDefinitionVersion).where(
            GradeDefinitionVersion.grade_definition_id == definition.id,
            GradeDefinitionVersion.status == "active",
        )
    ).scalar_one()
    assert active_count == 1


@pytest.mark.integration
def test_explicit_retire_without_replacement(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    t1 = _now() - timedelta(hours=1)
    _activate(db_session, tenant, definition, version, effective_time=t1)

    t2 = _now()
    retired = _retire(db_session, tenant, definition, version, effective_time=t2)
    assert retired.status == "retired"
    assert retired.effective_until == t2
    assert retired.retirement_client_command_id is not None


@pytest.mark.integration
def test_retired_version_cannot_reactivate(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    _activate(db_session, tenant, definition, version, effective_time=_now() - timedelta(hours=1))
    _retire(db_session, tenant, definition, version, effective_time=_now())

    with pytest.raises(GradeDefinitionVersionNotDraftError):
        _activate(db_session, tenant, definition, version, effective_time=_now())


@pytest.mark.integration
def test_retire_target_not_active_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    with pytest.raises(GradeDefinitionVersionNotActiveError):
        _retire(db_session, tenant, definition, version)


@pytest.mark.integration
def test_activation_effective_time_in_future_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    with pytest.raises(InvalidGradeDefinitionVersionEffectiveTimeError):
        _activate(db_session, tenant, definition, version, effective_time=_now() + timedelta(days=1))


@pytest.mark.integration
def test_retirement_before_own_activation_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    t1 = _now()
    _activate(db_session, tenant, definition, version, effective_time=t1)
    with pytest.raises(InvalidGradeDefinitionVersionEffectiveTimeError):
        _retire(db_session, tenant, definition, version, effective_time=t1 - timedelta(hours=1))


@pytest.mark.integration
def test_replacement_activation_before_predecessor_start_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version_1 = _create_version(db_session, tenant, definition)
    t1 = _now()
    _activate(db_session, tenant, definition, version_1, effective_time=t1)

    version_2 = _create_version(db_session, tenant, definition)
    with pytest.raises(InvalidGradeDefinitionVersionEffectiveTimeError):
        _activate(db_session, tenant, definition, version_2, effective_time=t1 - timedelta(hours=1))


@pytest.mark.integration
def test_tenant_isolation_read(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop_a = _setup_crop(db_session, tenant_a)
    definition = _register_definition(db_session, tenant_a, crop_a)

    tenant_b = _second_tenant(db_session)
    with pytest.raises(GradeDefinitionNotFoundError):
        grade_definition_service.get_grade_definition(
            db_session, tenant_id=tenant_b.id, grade_definition_id=definition.id
        )


# --- Idempotency ---------------------------------------------------------------------


@pytest.mark.integration
def test_exact_create_definition_replay_returns_original(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    command_id = uuid.uuid4()
    first = _register_definition(db_session, tenant, crop, client_command_id=command_id)
    second = _register_definition(db_session, tenant, crop, client_command_id=command_id)
    assert first.id == second.id


@pytest.mark.integration
def test_mismatched_create_definition_replay_conflicts(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    command_id = uuid.uuid4()
    _register_definition(db_session, tenant, crop, client_command_id=command_id, code="A")
    with pytest.raises(GradeDefinitionCommandReusedWithDifferentPayloadError):
        _register_definition(db_session, tenant, crop, client_command_id=command_id, code="B")


@pytest.mark.integration
def test_exact_create_version_replay_returns_original(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    command_id = uuid.uuid4()
    first = _create_version(db_session, tenant, definition, client_command_id=command_id)
    second = _create_version(db_session, tenant, definition, client_command_id=command_id)
    assert first.id == second.id
    count = db_session.execute(
        select(func.count()).select_from(GradeDefinitionVersion).where(
            GradeDefinitionVersion.grade_definition_id == definition.id
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.integration
def test_mismatched_create_version_replay_conflicts(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    command_id = uuid.uuid4()
    _create_version(db_session, tenant, definition, client_command_id=command_id, spec_notes="A")
    with pytest.raises(GradeDefinitionVersionCommandReusedWithDifferentPayloadError):
        _create_version(db_session, tenant, definition, client_command_id=command_id, spec_notes="B")


@pytest.mark.integration
def test_exact_activation_replay_returns_original(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    command_id = uuid.uuid4()
    effective_time = _now()
    first = _activate(db_session, tenant, definition, version, effective_time=effective_time, client_command_id=command_id)
    second = _activate(db_session, tenant, definition, version, effective_time=effective_time, client_command_id=command_id)
    assert first.id == second.id
    assert second.status == "active"


@pytest.mark.integration
def test_mismatched_activation_replay_conflicts(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    command_id = uuid.uuid4()
    _activate(db_session, tenant, definition, version, effective_time=_now(), client_command_id=command_id)
    with pytest.raises(GradeDefinitionVersionActivationReusedWithDifferentPayloadError):
        _activate(
            db_session, tenant, definition, version, effective_time=_now() + timedelta(seconds=-1),
            client_command_id=command_id,
        )


@pytest.mark.integration
def test_exact_retirement_replay_returns_original(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    _activate(db_session, tenant, definition, version, effective_time=_now() - timedelta(hours=1))
    command_id = uuid.uuid4()
    effective_time = _now()
    first = _retire(db_session, tenant, definition, version, effective_time=effective_time, client_command_id=command_id)
    second = _retire(db_session, tenant, definition, version, effective_time=effective_time, client_command_id=command_id)
    assert first.id == second.id
    assert second.status == "retired"


@pytest.mark.integration
def test_mismatched_retirement_replay_conflicts(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    _activate(db_session, tenant, definition, version, effective_time=_now() - timedelta(hours=1))
    command_id = uuid.uuid4()
    _retire(db_session, tenant, definition, version, effective_time=_now(), client_command_id=command_id)
    with pytest.raises(GradeDefinitionVersionRetirementReusedWithDifferentPayloadError):
        _retire(
            db_session, tenant, definition, version, effective_time=_now() + timedelta(seconds=1),
            client_command_id=command_id,
        )


# --- Audit ------------------------------------------------------------------------


def _audit_events(db_session, *, action, entity_id):
    return list(
        db_session.execute(
            select(AuditEvent).where(AuditEvent.action == action, AuditEvent.entity_id == entity_id)
        ).scalars()
    )


def _audit_count(db_session, *, action, entity_id):
    return len(_audit_events(db_session, action=action, entity_id=entity_id))


@pytest.mark.integration
def test_creation_activation_retirement_each_create_one_audit_event(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    _activate(db_session, tenant, definition, version, effective_time=_now() - timedelta(hours=1))
    _retire(db_session, tenant, definition, version, effective_time=_now())

    assert _audit_count(db_session, action="grade_definition.created", entity_id=definition.id) == 1
    assert _audit_count(db_session, action="grade_definition_version.created", entity_id=version.id) == 1
    assert _audit_count(db_session, action="grade_definition_version.activated", entity_id=version.id) == 1
    assert _audit_count(db_session, action="grade_definition_version.retired", entity_id=version.id) == 1


@pytest.mark.integration
def test_first_activation_creates_one_activated_audit_and_no_supersession_retired_audit(
    db_session, active_context
) -> None:
    """PRE-COMMIT CORRECTION item 1: a first-ever activation (no previous
    active version to replace) must never fabricate a supersession-retired
    audit event for anything."""
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    _activate(db_session, tenant, definition, version, effective_time=_now())

    assert _audit_count(db_session, action="grade_definition_version.activated", entity_id=version.id) == 1
    # No retired audit exists for ANY version of this definition -- there
    # was nothing to supersede.
    retired_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "grade_definition_version.retired",
            AuditEvent.event_data["grade_definition_id"].astext == str(definition.id),
        )
    ).scalar_one()
    assert retired_count == 0


@pytest.mark.integration
def test_replacement_activation_creates_both_lifecycle_audit_events(db_session, active_context) -> None:
    """PRE-COMMIT CORRECTION item 2: a replacement activation is TWO
    independently meaningful lifecycle transitions (previous ACTIVE ->
    RETIRED, selected draft DRAFT -> ACTIVE) and must emit one normal audit
    event for each, cross-referencing each other."""
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version_1 = _create_version(db_session, tenant, definition)
    _activate(db_session, tenant, definition, version_1, effective_time=_now() - timedelta(days=1))
    version_2 = _create_version(db_session, tenant, definition)
    _activate(db_session, tenant, definition, version_2, effective_time=_now())

    activated_events = _audit_events(
        db_session, action="grade_definition_version.activated", entity_id=version_2.id
    )
    assert len(activated_events) == 1
    assert activated_events[0].event_data["replaced_version_id"] == str(version_1.id)

    retired_events = _audit_events(
        db_session, action="grade_definition_version.retired", entity_id=version_1.id
    )
    assert len(retired_events) == 1
    assert retired_events[0].event_data["reason"] == "superseded"
    assert retired_events[0].event_data["superseded_by_version_id"] == str(version_2.id)

    # The previous version's own activation audit is untouched -- exactly
    # one activated event for it too, unaffected by its later retirement.
    assert _audit_count(db_session, action="grade_definition_version.activated", entity_id=version_1.id) == 1


@pytest.mark.integration
def test_replacement_activation_replay_creates_no_duplicate_audit_events(db_session, active_context) -> None:
    """PRE-COMMIT CORRECTION item 3: an exact replay of the replacement
    ACTIVATE command must not create a second activated audit for the new
    version, nor a second retired/superseded audit for the previous one."""
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version_1 = _create_version(db_session, tenant, definition)
    _activate(db_session, tenant, definition, version_1, effective_time=_now() - timedelta(days=1))
    version_2 = _create_version(db_session, tenant, definition)

    command_id = uuid.uuid4()
    effective_time = _now()
    first = _activate(
        db_session, tenant, definition, version_2, effective_time=effective_time, client_command_id=command_id
    )
    second = _activate(
        db_session, tenant, definition, version_2, effective_time=effective_time, client_command_id=command_id
    )
    assert first.id == second.id

    assert _audit_count(db_session, action="grade_definition_version.activated", entity_id=version_2.id) == 1
    assert _audit_count(db_session, action="grade_definition_version.retired", entity_id=version_1.id) == 1


@pytest.mark.integration
def test_failed_replacement_activation_persists_no_audit_events(db_session, active_context) -> None:
    """PRE-COMMIT CORRECTION item 4: a replacement activation that fails
    validation (here: effective_time precedes the currently active
    version's own effective_from) must leave neither lifecycle mutation
    nor either audit event behind -- the previous version must still read
    ACTIVE, and the attempted new version must still read DRAFT."""
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version_1 = _create_version(db_session, tenant, definition)
    t1 = _now()
    _activate(db_session, tenant, definition, version_1, effective_time=t1)
    version_2 = _create_version(db_session, tenant, definition)

    with pytest.raises(InvalidGradeDefinitionVersionEffectiveTimeError):
        _activate(db_session, tenant, definition, version_2, effective_time=t1 - timedelta(hours=1))

    db_session.refresh(version_1)
    db_session.refresh(version_2)
    assert version_1.status == "active"
    assert version_1.effective_until is None
    assert version_2.status == "draft"

    assert _audit_count(db_session, action="grade_definition_version.activated", entity_id=version_2.id) == 0
    assert _audit_count(db_session, action="grade_definition_version.retired", entity_id=version_1.id) == 0


@pytest.mark.integration
def test_explicit_retirement_audit_distinguishable_from_supersession(db_session, active_context) -> None:
    """PRE-COMMIT CORRECTION item 5: the existing explicit-retire command
    must keep emitting grade_definition_version.retired, distinguishable
    from a supersession-retirement via the same "reason" audit-metadata
    convention used for the replacement case."""
    tenant, _user, _headers = active_context
    crop = _setup_crop(db_session, tenant)
    definition = _register_definition(db_session, tenant, crop)
    version = _create_version(db_session, tenant, definition)
    _activate(db_session, tenant, definition, version, effective_time=_now() - timedelta(hours=1))
    _retire(db_session, tenant, definition, version, effective_time=_now())

    retired_events = _audit_events(db_session, action="grade_definition_version.retired", entity_id=version.id)
    assert len(retired_events) == 1
    assert retired_events[0].event_data["reason"] == "explicit"
    assert "superseded_by_version_id" not in retired_events[0].event_data
