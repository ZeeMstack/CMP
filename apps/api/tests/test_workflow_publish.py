import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.models.workflow_version import WorkflowVersion
from app.services import crop_service, production_system_service, tenant_service, workflow_service
from app.services.errors import WorkflowPublicationValidationError, WorkflowVersionNotDraftError

# --- Helpers -------------------------------------------------------------------


def _setup(db_session, tenant, *, crop_category="leafy_green"):
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="LET", common_name="Lettuce",
        scientific_name=None, crop_category=crop_category,
    )
    production_system = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="NURSERY-TRAY", name="Nursery Tray",
        description=None,
    )
    return crop, production_system


def _register_workflow(db_session, tenant, crop, production_system, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, crop_id=crop.id, variety_id=None,
        production_system_id=production_system.id, code="ICEBERG-NURSERY", name="Iceberg Nursery Workflow",
    )
    defaults.update(overrides)
    return workflow_service.register_workflow(db_session, **defaults)


def _draft_version(db_session, tenant, workflow):
    return workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id
    )


def _add_stage(db_session, tenant, workflow, version, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
        code="SEED", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=True, is_terminal=False,
    )
    defaults.update(overrides)
    return workflow_service.add_stage(db_session, **defaults)


def _add_transition(db_session, tenant, workflow, version, from_stage, to_stage, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=from_stage.id, to_stage_id=to_stage.id, code="ADVANCE", name="Advance",
    )
    defaults.update(overrides)
    return workflow_service.add_transition(db_session, **defaults)


def _publish(db_session, tenant, workflow, version):
    return workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id
    )


def _full_setup(db_session, tenant):
    crop, ps = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, ps)
    return crop, ps, workflow


# --- Graph validation --------------------------------------------------------------


@pytest.mark.integration
def test_publish_valid_one_stage_workflow(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    published = _publish(db_session, tenant, workflow, version)
    assert published.state == "published"


@pytest.mark.integration
def test_publish_valid_multi_stage_workflow(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    start = _add_stage(db_session, tenant, workflow, version, code="SEED", is_start=True, is_terminal=False)
    end = _add_stage(
        db_session, tenant, workflow, version, code="DONE", display_order=1, stage_category="completed",
        is_start=False, is_terminal=True,
    )
    _add_transition(db_session, tenant, workflow, version, start, end)
    published = _publish(db_session, tenant, workflow, version)
    assert published.state == "published"


@pytest.mark.integration
def test_publish_without_stages_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    with pytest.raises(WorkflowPublicationValidationError):
        _publish(db_session, tenant, workflow, version)


@pytest.mark.integration
def test_publish_without_exactly_one_start_stage_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="A", is_start=True, is_terminal=True)
    _add_stage(db_session, tenant, workflow, version, code="B", display_order=1, is_start=True, is_terminal=True)
    with pytest.raises(WorkflowPublicationValidationError):
        _publish(db_session, tenant, workflow, version)


@pytest.mark.integration
def test_publish_without_terminal_stage_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    start = _add_stage(db_session, tenant, workflow, version, code="SEED", is_start=True, is_terminal=False)
    other = _add_stage(
        db_session, tenant, workflow, version, code="MID", display_order=1, stage_category="intermediate",
        is_start=False, is_terminal=False,
    )
    _add_transition(db_session, tenant, workflow, version, start, other)
    with pytest.raises(WorkflowPublicationValidationError):
        _publish(db_session, tenant, workflow, version)


@pytest.mark.integration
def test_publish_unreachable_stage_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="SEED", is_start=True, is_terminal=True)
    _add_stage(
        db_session, tenant, workflow, version, code="ORPHAN", display_order=1, stage_category="completed",
        is_start=False, is_terminal=True,
    )
    with pytest.raises(WorkflowPublicationValidationError):
        _publish(db_session, tenant, workflow, version)


@pytest.mark.integration
def test_publish_non_terminal_stage_without_outgoing_transition_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="SEED", is_start=True, is_terminal=False)
    _add_stage(
        db_session, tenant, workflow, version, code="DONE", display_order=1, stage_category="completed",
        is_start=False, is_terminal=True,
    )
    # no transition connecting them: SEED (non-terminal) has no outgoing transition
    with pytest.raises(WorkflowPublicationValidationError):
        _publish(db_session, tenant, workflow, version)


@pytest.mark.integration
def test_publish_terminal_stage_with_outgoing_transition_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    start = _add_stage(db_session, tenant, workflow, version, code="SEED", is_start=True, is_terminal=True)
    end = _add_stage(
        db_session, tenant, workflow, version, code="DONE", display_order=1, stage_category="completed",
        is_start=False, is_terminal=True,
    )
    _add_transition(db_session, tenant, workflow, version, start, end)
    with pytest.raises(WorkflowPublicationValidationError):
        _publish(db_session, tenant, workflow, version)


@pytest.mark.integration
def test_publish_cyclic_graph_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    a = _add_stage(db_session, tenant, workflow, version, code="A", is_start=True, is_terminal=False)
    b = _add_stage(
        db_session, tenant, workflow, version, code="B", display_order=1, stage_category="intermediate",
        is_start=False, is_terminal=False,
    )
    c = _add_stage(
        db_session, tenant, workflow, version, code="C", display_order=2, stage_category="completed",
        is_start=False, is_terminal=True,
    )
    _add_transition(db_session, tenant, workflow, version, a, b, code="A-B")
    _add_transition(db_session, tenant, workflow, version, b, a, code="B-A")
    _add_transition(db_session, tenant, workflow, version, b, c, code="B-C")
    with pytest.raises(WorkflowPublicationValidationError):
        _publish(db_session, tenant, workflow, version)


@pytest.mark.integration
def test_publish_inactive_crop_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    crop.status = "inactive"
    db_session.flush()
    with pytest.raises(WorkflowPublicationValidationError):
        _publish(db_session, tenant, workflow, version)


@pytest.mark.integration
def test_publish_inactive_variety_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, ps = _setup(db_session, tenant)
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=None, crop_id=crop.id, code="MAM",
        name="Mamutik RZ", supplier_reference=None,
    )
    workflow = _register_workflow(db_session, tenant, crop, ps, variety_id=variety.id, code="WITH-VARIETY")
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    variety.status = "inactive"
    db_session.flush()
    with pytest.raises(WorkflowPublicationValidationError):
        _publish(db_session, tenant, workflow, version)


@pytest.mark.integration
def test_publish_inactive_production_system_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    ps.status = "inactive"
    db_session.flush()
    with pytest.raises(WorkflowPublicationValidationError):
        _publish(db_session, tenant, workflow, version)


# --- Publication lifecycle ----------------------------------------------------------


@pytest.mark.integration
def test_publishing_new_version_retires_previous_and_updates_timestamps(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version_1 = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version_1, code="ONLY", is_start=True, is_terminal=True)
    published_1 = _publish(db_session, tenant, workflow, version_1)
    assert published_1.published_at is not None

    version_2 = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version_2, code="ONLY", is_start=True, is_terminal=True)
    published_2 = _publish(db_session, tenant, workflow, version_2)

    db_session.refresh(published_1)
    assert published_1.state == "retired"
    assert published_1.retired_at is not None
    assert published_2.state == "published"
    assert published_2.published_at is not None

    published_count = db_session.execute(
        select(func.count()).select_from(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow.id, WorkflowVersion.state == "published"
        )
    ).scalar_one()
    assert published_count == 1


@pytest.mark.integration
def test_failed_publication_leaves_version_in_draft_and_no_audit_event(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    with pytest.raises(WorkflowPublicationValidationError):
        _publish(db_session, tenant, workflow, version)

    db_session.refresh(version)
    assert version.state == "draft"
    count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "workflow.published", AuditEvent.entity_id == version.id
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.integration
def test_successful_publication_creates_one_audit_event(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version)

    count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "workflow.published", AuditEvent.entity_id == version.id
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.integration
def test_repeated_publication_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version)
    with pytest.raises(WorkflowVersionNotDraftError):
        _publish(db_session, tenant, workflow, version)


@pytest.mark.integration
def test_draft_to_retired_transition_rejected_by_postgres(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "UPDATE workflow_versions SET state = 'retired', published_at = now(), retired_at = now() "
                    "WHERE id = :id"
                ),
                {"id": version.id},
            )


@pytest.mark.integration
def test_retired_to_published_transition_rejected_by_postgres(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version)
    version_2 = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version_2, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version_2)
    db_session.refresh(version)
    assert version.state == "retired"

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE workflow_versions SET state = 'published' WHERE id = :id"), {"id": version.id}
            )


@pytest.mark.integration
def test_published_to_draft_transition_rejected_by_postgres(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE workflow_versions SET state = 'draft', published_at = NULL WHERE id = :id"),
                {"id": version.id},
            )


# --- Immutability --------------------------------------------------------------------


@pytest.mark.integration
def test_published_stage_insert_rejected_by_postgres(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO workflow_stages "
                    "(id, tenant_id, workflow_version_id, code, name, display_order, stage_category, is_start, is_terminal) "
                    "VALUES (:id, :tenant_id, :version_id, 'NEW', 'New', 5, 'intermediate', false, false)"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant.id, "version_id": version.id},
            )


@pytest.mark.integration
def test_published_stage_update_rejected_by_postgres(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    stage = _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE workflow_stages SET name = 'Changed' WHERE id = :id"), {"id": stage.id}
            )


@pytest.mark.integration
def test_published_stage_delete_rejected_by_postgres(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    stage = _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM workflow_stages WHERE id = :id"), {"id": stage.id})


@pytest.mark.integration
def test_published_transition_insert_update_delete_rejected_by_postgres(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    start = _add_stage(db_session, tenant, workflow, version, code="SEED", is_start=True, is_terminal=False)
    end = _add_stage(
        db_session, tenant, workflow, version, code="DONE", display_order=1, stage_category="completed",
        is_start=False, is_terminal=True,
    )
    transition = _add_transition(db_session, tenant, workflow, version, start, end)
    _publish(db_session, tenant, workflow, version)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO workflow_transitions "
                    "(id, tenant_id, workflow_version_id, from_stage_id, to_stage_id, code, name) "
                    "VALUES (:id, :tenant_id, :version_id, :from_id, :to_id, 'NEW', 'New')"
                ),
                {
                    "id": uuid.uuid4(), "tenant_id": tenant.id, "version_id": version.id,
                    "from_id": end.id, "to_id": start.id,
                },
            )
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE workflow_transitions SET name = 'Changed' WHERE id = :id"), {"id": transition.id}
            )
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM workflow_transitions WHERE id = :id"), {"id": transition.id})


@pytest.mark.integration
def test_retired_stage_and_transition_mutation_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version_1 = _draft_version(db_session, tenant, workflow)
    stage = _add_stage(db_session, tenant, workflow, version_1, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version_1)
    version_2 = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version_2, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version_2)
    db_session.refresh(version_1)
    assert version_1.state == "retired"

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM workflow_stages WHERE id = :id"), {"id": stage.id})


@pytest.mark.integration
def test_published_version_identity_mutation_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE workflow_versions SET version_number = 99 WHERE id = :id"), {"id": version.id}
            )


@pytest.mark.integration
def test_published_version_deletion_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM workflow_versions WHERE id = :id"), {"id": version.id})


@pytest.mark.integration
def test_retired_version_deletion_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version_1 = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version_1, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version_1)
    version_2 = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version_2, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version_2)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM workflow_versions WHERE id = :id"), {"id": version_1.id})


@pytest.mark.integration
def test_workflow_identity_mutation_rejected_after_publication(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version)

    other_crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="TOM", common_name="Tomato",
        scientific_name=None, crop_category="vine",
    )
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE workflows SET crop_id = :crop_id WHERE id = :id"),
                {"crop_id": other_crop.id, "id": workflow.id},
            )


@pytest.mark.integration
def test_published_version_remains_readable(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    _crop, _ps, workflow = _full_setup(db_session, tenant)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="ONLY", is_start=True, is_terminal=True)
    _publish(db_session, tenant, workflow, version)

    fetched = workflow_service.get_workflow_version(
        db_session, tenant_id=tenant.id, workflow_id=workflow.id, version_id=version.id
    )
    assert fetched.state == "published"
    stages = workflow_service.get_stages(db_session, version_id=version.id)
    assert len(stages) == 1


# --- Security / infra ----------------------------------------------------------------


@pytest.mark.integration
def test_cross_tenant_workflow_version_access_rejected_via_api(client, db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    crop, ps, workflow = _full_setup(db_session, tenant_a)
    version = _draft_version(db_session, tenant_a, workflow)
    _add_stage(db_session, tenant_a, workflow, version, code="ONLY", is_start=True, is_terminal=True)

    tenant_b = tenant_service.create_tenant(db_session, code="wf-pub-tenant-b", name="Tenant B")
    from app.services import membership_service, user_service

    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="wf-pub-b", email="wfpb@example.com", display_name="B"
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}

    response = client.get(f"/workflows/{workflow.id}/versions/{version.id}", headers=headers_b)
    assert response.status_code == 404
