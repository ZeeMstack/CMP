import threading
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.workflow_version import WorkflowVersion
from app.schemas.workflow import WorkflowCreate
from app.schemas.workflow_stage import WorkflowStageCreate
from app.schemas.workflow_transition import WorkflowTransitionCreate
from app.services import crop_service, production_system_service, tenant_service, workflow_service
from app.services.errors import (
    CarrierTypeReferenceNotFoundError,
    CropNotFoundError,
    DuplicateStageCodeError,
    DuplicateTransitionCodeError,
    DuplicateTransitionPairError,
    DuplicateWorkflowCodeError,
    LocationTypeReferenceNotFoundError,
    ProductionSystemNotFoundError,
    SelfTransitionError,
    VarietyCropMismatchError,
    WorkflowStageNotFoundError,
    WorkflowVersionNotDraftError,
)

# --- Application-level (Pydantic) validation — no DB required ---


def test_workflow_code_trimmed_and_uppercased() -> None:
    payload = WorkflowCreate(
        crop_id=uuid.uuid4(), production_system_id=uuid.uuid4(), code="  iceberg-nursery  ", name="Iceberg Nursery"
    )
    assert payload.code == "ICEBERG-NURSERY"


def test_invalid_stage_category_rejected() -> None:
    with pytest.raises(ValueError):
        WorkflowStageCreate(code="S1", name="Stage 1", display_order=0, stage_category="not_a_category")


def test_negative_display_order_rejected() -> None:
    with pytest.raises(ValueError):
        WorkflowStageCreate(code="S1", name="Stage 1", display_order=-1, stage_category="seeding")


def test_zero_display_order_accepted() -> None:
    payload = WorkflowStageCreate(code="S1", name="Stage 1", display_order=0, stage_category="seeding")
    assert payload.display_order == 0


def test_non_positive_expected_duration_rejected() -> None:
    with pytest.raises(ValueError):
        WorkflowStageCreate(
            code="S1", name="Stage 1", display_order=0, stage_category="seeding", expected_duration_minutes=0
        )


def test_self_transition_schema_allows_construction_service_rejects() -> None:
    # The schema does not forbid identical ids — the service layer does.
    stage_id = uuid.uuid4()
    payload = WorkflowTransitionCreate(from_stage_id=stage_id, to_stage_id=stage_id, code="T1", name="T1")
    assert payload.from_stage_id == payload.to_stage_id


# --- Integration (DB) helpers ---


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


@pytest.mark.integration
def test_workflow_creation(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    assert workflow.status == "active"
    assert workflow.crop_id == crop.id


@pytest.mark.integration
def test_workflow_tenant_scoped_uniqueness(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    _register_workflow(db_session, tenant, crop, production_system, code="ICE-NUR")
    with pytest.raises(DuplicateWorkflowCodeError):
        _register_workflow(db_session, tenant, crop, production_system, code="ice-nur")


@pytest.mark.integration
def test_workflow_crop_must_belong_to_same_tenant(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = tenant_service.create_tenant(db_session, code="wf-tenant-b", name="Tenant B")
    crop_b, production_system_b = _setup(db_session, tenant_b)
    with pytest.raises(CropNotFoundError):
        _register_workflow(db_session, tenant_a, crop_b, production_system_b)


@pytest.mark.integration
def test_workflow_production_system_must_belong_to_same_tenant(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = tenant_service.create_tenant(db_session, code="wf-tenant-c", name="Tenant C")
    crop_a, _ps_a = _setup(db_session, tenant_a)
    _crop_b, production_system_b = _setup(db_session, tenant_b)
    with pytest.raises(ProductionSystemNotFoundError):
        _register_workflow(db_session, tenant_a, crop_a, production_system_b)


@pytest.mark.integration
def test_workflow_variety_must_belong_to_selected_crop(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop_a, production_system = _setup(db_session, tenant, crop_category="leafy_green")
    crop_b = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="TOM", common_name="Tomato",
        scientific_name=None, crop_category="vine",
    )
    variety_of_b = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=None, crop_id=crop_b.id, code="CHERRY",
        name="Cherry Tomato", supplier_reference=None,
    )
    with pytest.raises(VarietyCropMismatchError):
        _register_workflow(db_session, tenant, crop_a, production_system, variety_id=variety_of_b.id)


@pytest.mark.integration
def test_workflow_cross_tenant_crop_reference_rejected_by_postgres(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = tenant_service.create_tenant(db_session, code="wf-tenant-d", name="Tenant D")
    crop_a, _ps_a = _setup(db_session, tenant_a)
    _crop_b, production_system_b = _setup(db_session, tenant_b, crop_category="vine")
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO workflows "
                    "(id, tenant_id, crop_id, production_system_id, code, name) "
                    "VALUES (:id, :tenant_id, :crop_id, :ps_id, 'BAD', 'Bad')"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_a.id,
                    "crop_id": crop_a.id,
                    "ps_id": production_system_b.id,
                },
            )


@pytest.mark.integration
def test_draft_version_numbers_are_sequential(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    v1 = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id
    )
    v2 = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id
    )
    assert v1.version_number == 1
    assert v2.version_number == 2


@pytest.mark.integration
def test_duplicate_version_number_rejected_by_postgres(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id
    )
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO workflow_versions (id, tenant_id, workflow_id, version_number, state) "
                    "VALUES (:id, :tenant_id, :workflow_id, 1, 'draft')"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant.id, "workflow_id": workflow.id},
            )


@pytest.mark.integration
def test_version_tenant_consistency_enforced_by_postgres(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = tenant_service.create_tenant(db_session, code="wf-tenant-e", name="Tenant E")
    crop, production_system = _setup(db_session, tenant_a)
    workflow = _register_workflow(db_session, tenant_a, crop, production_system)
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO workflow_versions (id, tenant_id, workflow_id, version_number, state) "
                    "VALUES (:id, :tenant_id, :workflow_id, 1, 'draft')"
                ),
                {"id": uuid.uuid4(), "tenant_id": tenant_b.id, "workflow_id": workflow.id},
            )


@pytest.mark.integration
def test_concurrent_draft_creation_produces_distinct_version_numbers(test_engine) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]
    tenant = tenant_service.create_tenant(session, code=f"wf-race-{suffix}", name="Race Tenant")
    crop, production_system = _setup(session, tenant)
    workflow = _register_workflow(session, tenant, crop, production_system, code=f"WF-{suffix}")
    tenant_id, workflow_id = tenant.id, workflow.id
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def worker(name: str) -> None:
        thread_conn = test_engine.connect()
        thread_session = Session(bind=thread_conn)
        try:
            barrier.wait(timeout=10)
            version = workflow_service.create_draft_version(
                thread_session, tenant_id=tenant_id, actor_user_id=None, workflow_id=workflow_id
            )
            results[name] = version.version_number
        except Exception as exc:  # pragma: no cover - surfaced via assertion below
            results[name] = repr(exc)
        finally:
            thread_session.close()
            thread_conn.close()

    t_a = threading.Thread(target=worker, args=("a",))
    t_b = threading.Thread(target=worker, args=("b",))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        assert {results["a"], results["b"]} == {1, 2}, results
    finally:
        cleanup_conn = test_engine.connect()
        trans = cleanup_conn.begin()
        cleanup_conn.execute(text("SET session_replication_role = replica"))
        cleanup_conn.execute(text("DELETE FROM workflow_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        cleanup_conn.execute(text("DELETE FROM workflow_stages WHERE tenant_id = :tid"), {"tid": tenant_id})
        cleanup_conn.execute(text("DELETE FROM workflow_versions WHERE tenant_id = :tid"), {"tid": tenant_id})
        cleanup_conn.execute(text("DELETE FROM workflows WHERE tenant_id = :tid"), {"tid": tenant_id})
        cleanup_conn.execute(text("DELETE FROM production_systems WHERE tenant_id = :tid"), {"tid": tenant_id})
        cleanup_conn.execute(text("DELETE FROM crops WHERE tenant_id = :tid"), {"tid": tenant_id})
        cleanup_conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        cleanup_conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
        cleanup_conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
        cleanup_conn.close()


# --- Stages ------------------------------------------------------------------


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


@pytest.mark.integration
def test_stage_creation(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version = _draft_version(db_session, tenant, workflow)
    stage = _add_stage(db_session, tenant, workflow, version)
    assert stage.workflow_version_id == version.id
    assert stage.is_start is True


@pytest.mark.integration
def test_duplicate_stage_code_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="SEED")
    with pytest.raises(DuplicateStageCodeError):
        _add_stage(db_session, tenant, workflow, version, code="seed", is_start=False)


@pytest.mark.integration
def test_stage_location_type_reference_accepted(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version = _draft_version(db_session, tenant, workflow)
    stage = _add_stage(db_session, tenant, workflow, version, permitted_location_type_code="chamber_position")
    assert stage.permitted_location_type_id is not None


@pytest.mark.integration
def test_stage_invalid_location_type_reference_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version = _draft_version(db_session, tenant, workflow)
    with pytest.raises(LocationTypeReferenceNotFoundError):
        _add_stage(db_session, tenant, workflow, version, permitted_location_type_code="not_a_location_type")


@pytest.mark.integration
def test_stage_carrier_type_reference_accepted(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version = _draft_version(db_session, tenant, workflow)
    stage = _add_stage(db_session, tenant, workflow, version, required_carrier_type_code="seed_tray")
    assert stage.required_carrier_type_id is not None


@pytest.mark.integration
def test_stage_invalid_carrier_type_reference_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version = _draft_version(db_session, tenant, workflow)
    with pytest.raises(CarrierTypeReferenceNotFoundError):
        _add_stage(db_session, tenant, workflow, version, required_carrier_type_code="not_a_carrier_type")


@pytest.mark.integration
def test_stage_creation_rejected_for_non_draft_version(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version = _draft_version(db_session, tenant, workflow)
    _add_stage(db_session, tenant, workflow, version, code="SEED", is_start=True, is_terminal=True)
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id
    )
    with pytest.raises(WorkflowVersionNotDraftError):
        _add_stage(db_session, tenant, workflow, version, code="EXTRA", is_start=False)


# --- Transitions ---------------------------------------------------------------


def _two_stage_draft(db_session, tenant, workflow, version):
    start = _add_stage(db_session, tenant, workflow, version, code="SEED", is_start=True, is_terminal=False)
    end = _add_stage(
        db_session, tenant, workflow, version, code="DONE", name="Done", display_order=1,
        stage_category="completed", is_start=False, is_terminal=True,
    )
    return start, end


@pytest.mark.integration
def test_transition_creation(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version = _draft_version(db_session, tenant, workflow)
    start, end = _two_stage_draft(db_session, tenant, workflow, version)
    transition = workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=start.id, to_stage_id=end.id, code="ADVANCE", name="Advance",
    )
    assert transition.from_stage_id == start.id
    assert transition.to_stage_id == end.id


@pytest.mark.integration
def test_self_transition_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version = _draft_version(db_session, tenant, workflow)
    start, _end = _two_stage_draft(db_session, tenant, workflow, version)
    with pytest.raises(SelfTransitionError):
        workflow_service.add_transition(
            db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=start.id, to_stage_id=start.id, code="LOOP", name="Loop",
        )


@pytest.mark.integration
def test_duplicate_transition_code_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version = _draft_version(db_session, tenant, workflow)
    start, end = _two_stage_draft(db_session, tenant, workflow, version)
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=start.id, to_stage_id=end.id, code="ADVANCE", name="Advance",
    )
    third = _add_stage(
        db_session, tenant, workflow, version, code="EXTRA", name="Extra", display_order=2,
        stage_category="intermediate", is_start=False, is_terminal=True,
    )
    with pytest.raises(DuplicateTransitionCodeError):
        workflow_service.add_transition(
            db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=start.id, to_stage_id=third.id, code="advance", name="Advance Again",
        )


@pytest.mark.integration
def test_duplicate_transition_pair_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version = _draft_version(db_session, tenant, workflow)
    start, end = _two_stage_draft(db_session, tenant, workflow, version)
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=start.id, to_stage_id=end.id, code="ADVANCE", name="Advance",
    )
    with pytest.raises(DuplicateTransitionPairError):
        workflow_service.add_transition(
            db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=start.id, to_stage_id=end.id, code="ADVANCE-2", name="Advance Again",
        )


@pytest.mark.integration
def test_cross_version_transition_rejected_by_service(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version_1 = _draft_version(db_session, tenant, workflow)
    start_1, end_1 = _two_stage_draft(db_session, tenant, workflow, version_1)
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version_1.id,
        from_stage_id=start_1.id, to_stage_id=end_1.id, code="ADVANCE", name="Advance",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version_1.id
    )
    version_2 = _draft_version(db_session, tenant, workflow)
    start_2 = _add_stage(db_session, tenant, workflow, version_2, code="SEED", is_start=True, is_terminal=False)

    with pytest.raises(WorkflowStageNotFoundError):
        workflow_service.add_transition(
            db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version_2.id,
            from_stage_id=start_2.id, to_stage_id=end_1.id, code="CROSS", name="Cross Version",
        )


@pytest.mark.integration
def test_cross_version_transition_rejected_by_postgres(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version_1 = _draft_version(db_session, tenant, workflow)
    _start_1, end_1 = _two_stage_draft(db_session, tenant, workflow, version_1)
    version_2 = _draft_version(db_session, tenant, workflow)
    start_2 = _add_stage(db_session, tenant, workflow, version_2, code="SEED", is_start=True, is_terminal=False)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO workflow_transitions "
                    "(id, tenant_id, workflow_version_id, from_stage_id, to_stage_id, code, name) "
                    "VALUES (:id, :tenant_id, :version_id, :from_id, :to_id, 'BAD', 'Bad')"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant.id,
                    "version_id": version_2.id,
                    "from_id": start_2.id,
                    "to_id": end_1.id,
                },
            )


@pytest.mark.integration
def test_cross_tenant_transition_rejected_by_postgres(db_session, active_context) -> None:
    tenant_a, _user, _headers = active_context
    tenant_b = tenant_service.create_tenant(db_session, code="wf-tenant-f", name="Tenant F")
    crop_a, ps_a = _setup(db_session, tenant_a)
    workflow_a = _register_workflow(db_session, tenant_a, crop_a, ps_a)
    version_a = _draft_version(db_session, tenant_a, workflow_a)
    start_a, end_a = _two_stage_draft(db_session, tenant_a, workflow_a, version_a)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO workflow_transitions "
                    "(id, tenant_id, workflow_version_id, from_stage_id, to_stage_id, code, name) "
                    "VALUES (:id, :tenant_id, :version_id, :from_id, :to_id, 'BAD', 'Bad')"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_b.id,
                    "version_id": version_a.id,
                    "from_id": start_a.id,
                    "to_id": end_a.id,
                },
            )


@pytest.mark.integration
def test_transition_creation_rejected_for_non_draft_version(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    crop, production_system = _setup(db_session, tenant)
    workflow = _register_workflow(db_session, tenant, crop, production_system)
    version = _draft_version(db_session, tenant, workflow)
    start, end = _two_stage_draft(db_session, tenant, workflow, version)
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=start.id, to_stage_id=end.id, code="ADVANCE", name="Advance",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id
    )
    with pytest.raises(WorkflowVersionNotDraftError):
        workflow_service.add_transition(
            db_session, tenant_id=tenant.id, actor_user_id=None, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=start.id, to_stage_id=end.id, code="EXTRA", name="Extra",
        )


# --- API smoke test ---------------------------------------------------------------


@pytest.mark.integration
def test_create_workflow_and_publish_via_api(client, active_context) -> None:
    _tenant, _user, headers = active_context
    crop_id = client.post(
        "/crops", headers=headers, json={"code": "let", "common_name": "Lettuce", "crop_category": "leafy_green"}
    ).json()["id"]
    ps_id = client.post(
        "/production-systems", headers=headers, json={"code": "nursery-tray", "name": "Nursery Tray"}
    ).json()["id"]
    workflow = client.post(
        "/workflows",
        headers=headers,
        json={"crop_id": crop_id, "production_system_id": ps_id, "code": "iceberg-nursery", "name": "Iceberg Nursery"},
    ).json()
    version = client.post(f"/workflows/{workflow['id']}/versions", headers=headers).json()
    client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages",
        headers=headers,
        json={"code": "seed", "name": "Seeding", "display_order": 0, "stage_category": "seeding", "is_start": True, "is_terminal": True},
    )
    publish_resp = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/publish", headers=headers
    )
    assert publish_resp.status_code == 200
    assert publish_resp.json()["state"] == "published"
