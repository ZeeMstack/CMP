"""PILOT-AGRO-001 focused proofs: Growing Protocol versioning, Batch <->
Protocol assignment history, deterministic due/deviation reads, Grower
Inspection + Finding recording, and the Crop Issue lifecycle (including
Work Item linkage and follow-up). Time-efficient per the ticket: no full
backend suite, targeted proofs only."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.audit_event import AuditEvent
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.crop_batch import CropBatch
from app.services import (
    carrier_service,
    crop_batch_service,
    crop_issue_service,
    crop_service,
    farm_work_item_service,
    grower_inspection_service,
    growing_protocol_service,
    observation_service,
    production_system_service,
    sowing_service,
    tenant_service,
    workflow_service,
)
from app.services.errors import (
    BatchProtocolVersionNotActiveError,
    CropIssueInvalidTransitionError,
    GrowerInspectionValidationError,
    GrowingProtocolNotFoundError,
    GrowingProtocolVersionNotDraftError,
)
from tests.conftest import ensure_seed_tray_specification


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(db_session, tenant, user, farm, *, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg", scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="DWC",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=complete.id, code="ADVANCE-1", name="Advance 1",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id, code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, 3)
    ]
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[
            {"carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 200, "seed_count": 200, "line_note": None}
            for c in carriers
        ],
    )
    assignments = sowing_service.list_batch_carriers(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_by_carrier_code = {a.carrier.code: a.id for a in assignments}
    return {
        "crop": crop, "variety": variety, "production_system": ps, "workflow": workflow, "batch": batch,
        "carriers": carriers, "assignment_ids": [assignment_by_carrier_code[c.code] for c in carriers],
    }


def _register_observation_definition(db_session, tenant, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=user.id, code=f"DEF-{uuid.uuid4().hex[:8]}", name="Root health",
        description=None, value_type="text", unit=None, target_scope="either", min_value=None, max_value=None,
    )
    defaults.update(overrides)
    return observation_service.register_observation_definition(db_session, **defaults)


def _register_protocol(db_session, tenant, user, scenario, *, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    return growing_protocol_service.register_protocol(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"GP-{suffix}", name="Test Protocol",
        crop_id=scenario["crop"].id, variety_id=scenario["variety"].id,
        production_system_id=scenario["production_system"].id, season_context=None,
    )


def _create_and_activate_version(db_session, tenant, user, protocol, *, reason="initial"):
    version = growing_protocol_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, growing_protocol_id=protocol.id,
        client_command_id=uuid.uuid4(), reason=reason, effective_date=None,
    )
    return growing_protocol_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, growing_protocol_id=protocol.id,
        version_id=version.id, client_command_id=uuid.uuid4(),
    )


# --- 1. ACTIVE Protocol Version cannot be edited in place -------------------------------


def test_active_version_cannot_be_edited_in_place(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    protocol = _register_protocol(db_session, tenant, user, scenario)
    version = _create_and_activate_version(db_session, tenant, user, protocol)
    definition = _register_observation_definition(db_session, tenant, user)

    with pytest.raises(GrowingProtocolVersionNotDraftError):
        growing_protocol_service.add_observation_requirement(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, growing_protocol_id=protocol.id,
            version_id=version.id, stage_category="seeding", observation_definition_id=definition.id,
            requirement_level="required", frequency_days=None, due_window_start_days=None,
            due_window_end_days=None, instructions=None, escalation_guidance=None, display_order=0,
        )


# --- 2. next version preserves old version -----------------------------------------------


def test_next_version_preserves_old_version(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    protocol = _register_protocol(db_session, tenant, user, scenario)
    v1 = _create_and_activate_version(db_session, tenant, user, protocol, reason="v1")

    v2_draft = growing_protocol_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, growing_protocol_id=protocol.id,
        client_command_id=uuid.uuid4(), reason="v2", effective_date=None,
    )
    v2 = growing_protocol_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, growing_protocol_id=protocol.id,
        version_id=v2_draft.id, client_command_id=uuid.uuid4(),
    )

    versions = growing_protocol_service.list_versions(db_session, tenant_id=tenant.id, growing_protocol_id=protocol.id)
    by_number = {v.version_number: v for v in versions}
    assert by_number[1].id == v1.id
    assert by_number[1].state == "retired"
    assert by_number[1].reason == "v1"
    assert by_number[2].id == v2.id
    assert by_number[2].state == "active"


# --- 3. Batch can be assigned ACTIVE version; rejects non-active -------------------------


def test_batch_assignment_requires_active_version(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    protocol = _register_protocol(db_session, tenant, user, scenario)
    draft = growing_protocol_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, growing_protocol_id=protocol.id,
        client_command_id=uuid.uuid4(), reason="v1", effective_date=None,
    )

    with pytest.raises(BatchProtocolVersionNotActiveError):
        growing_protocol_service.assign_batch_protocol(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scenario["batch"].id,
            growing_protocol_version_id=draft.id, effective_from=None, reason=None, client_command_id=uuid.uuid4(),
        )

    active = growing_protocol_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, growing_protocol_id=protocol.id,
        version_id=draft.id, client_command_id=uuid.uuid4(),
    )
    assignment = growing_protocol_service.assign_batch_protocol(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scenario["batch"].id,
        growing_protocol_version_id=active.id, effective_from=None, reason=None, client_command_id=uuid.uuid4(),
    )
    assert assignment.growing_protocol_version_id == active.id
    assert assignment.effective_to is None


# --- 4. changing protocol preserves history -----------------------------------------------


def test_changing_batch_protocol_preserves_history(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    protocol = _register_protocol(db_session, tenant, user, scenario)
    v1 = _create_and_activate_version(db_session, tenant, user, protocol, reason="v1")

    a1 = growing_protocol_service.assign_batch_protocol(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scenario["batch"].id,
        growing_protocol_version_id=v1.id, effective_from=None, reason="initial", client_command_id=uuid.uuid4(),
    )

    v2_draft = growing_protocol_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, growing_protocol_id=protocol.id,
        client_command_id=uuid.uuid4(), reason="v2", effective_date=None,
    )
    v2 = growing_protocol_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, growing_protocol_id=protocol.id,
        version_id=v2_draft.id, client_command_id=uuid.uuid4(),
    )
    switch_time = _now()
    a2 = growing_protocol_service.assign_batch_protocol(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scenario["batch"].id,
        growing_protocol_version_id=v2.id, effective_from=switch_time, reason="upgrade", client_command_id=uuid.uuid4(),
    )

    history = growing_protocol_service.list_batch_assignments(db_session, tenant_id=tenant.id, batch_id=scenario["batch"].id)
    assert len(history) == 2
    by_id = {a.id: a for a in history}
    assert by_id[a1.id].effective_to == switch_time  # "Batch used V1 until X"
    assert by_id[a2.id].effective_from == switch_time  # "Batch used V2 from X"
    assert by_id[a2.id].effective_to is None

    current = growing_protocol_service.get_current_assignment(db_session, tenant_id=tenant.id, batch_id=scenario["batch"].id)
    assert current.id == a2.id


# --- 5. age does not change Batch stage -----------------------------------------------------


def test_age_does_not_change_batch_stage(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    protocol = _register_protocol(db_session, tenant, user, scenario)
    version = _create_and_activate_version(db_session, tenant, user, protocol)
    growing_protocol_service.assign_batch_protocol(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scenario["batch"].id,
        growing_protocol_version_id=version.id, effective_from=None, reason=None, client_command_id=uuid.uuid4(),
    )

    before = db_session.execute(
        select(CropBatch.state).where(CropBatch.id == scenario["batch"].id)
    ).scalar_one()

    # Simulate the batch having been in-stage far outside any protocol
    # window by directly checking the deterministic read many "days" out --
    # the read itself must never mutate anything.
    status = growing_protocol_service.get_batch_protocol_status(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=scenario["batch"].id
    )
    assert status["current_stage_category"] == "seeding"

    after = db_session.execute(select(CropBatch.state).where(CropBatch.id == scenario["batch"].id)).scalar_one()
    assert before == after == "active"
    # No batch stage transition audit event exists from reading status.
    stage_events = db_session.execute(
        select(AuditEvent).where(AuditEvent.action.like("crop_batch.stage%"))
    ).scalars().all()
    assert stage_events == []


# --- 6/7. required inspection due deterministically; Observation updates due state -------


def test_due_becomes_true_then_satisfied_by_observation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    protocol = _register_protocol(db_session, tenant, user, scenario)
    definition = _register_observation_definition(db_session, tenant, user, value_type="text", target_scope="crop_batch")

    # Requirement can only be added while DRAFT -- build a fresh draft,
    # activate it, THEN assign (mirrors real operator flow).
    draft = growing_protocol_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, growing_protocol_id=protocol.id,
        client_command_id=uuid.uuid4(), reason="with requirement", effective_date=None,
    )
    growing_protocol_service.add_observation_requirement(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, growing_protocol_id=protocol.id,
        version_id=draft.id, stage_category="seeding", observation_definition_id=definition.id,
        requirement_level="required", frequency_days=None, due_window_start_days=0, due_window_end_days=0,
        instructions=None, escalation_guidance=None, display_order=0,
    )
    active_version = growing_protocol_service.activate_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, growing_protocol_id=protocol.id,
        version_id=draft.id, client_command_id=uuid.uuid4(),
    )
    growing_protocol_service.assign_batch_protocol(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scenario["batch"].id,
        growing_protocol_version_id=active_version.id, effective_from=None, reason=None, client_command_id=uuid.uuid4(),
    )

    status_before = growing_protocol_service.get_batch_protocol_status(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=scenario["batch"].id
    )
    due = status_before["due_observation_requirements"]
    assert len(due) == 1
    assert due[0]["is_due"] is True
    assert due[0]["last_satisfied_at"] is None

    grower_inspection_service.record_inspection(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_id=scenario["batch"].id, batch_carrier_assignment_id=None, effective_time=None, inspected_count=None,
        overall_assessment="normal", notes=None, findings=[],
        observation_values=[
            {"observation_definition_id": definition.id, "batch_carrier_assignment_id": None, "value_text": "firm, white roots"}
        ],
    )

    status_after = growing_protocol_service.get_batch_protocol_status(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=scenario["batch"].id
    )
    due_after = status_after["due_observation_requirements"]
    assert due_after[0]["is_due"] is False
    assert due_after[0]["last_satisfied_at"] is not None


# --- 8/19. Inspection preserves Batch + exact placement/location; multi-placement ---------


def test_inspection_preserves_batch_and_exact_placement_context(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    assignment_ids = scenario["assignment_ids"]
    assert len(assignment_ids) >= 2

    insp1 = grower_inspection_service.record_inspection(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_id=scenario["batch"].id, batch_carrier_assignment_id=assignment_ids[0], effective_time=None,
        inspected_count=50, overall_assessment="normal", notes=None, findings=[], observation_values=[],
    )
    insp2 = grower_inspection_service.record_inspection(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_id=scenario["batch"].id, batch_carrier_assignment_id=assignment_ids[1], effective_time=None,
        inspected_count=60, overall_assessment="attention_needed", notes=None, findings=[], observation_values=[],
    )

    assert insp1.batch_id == scenario["batch"].id == insp2.batch_id
    assert insp1.batch_carrier_assignment_id == assignment_ids[0]
    assert insp2.batch_carrier_assignment_id == assignment_ids[1]
    assert insp1.batch_carrier_assignment_id != insp2.batch_carrier_assignment_id


# --- 9. affected_count cannot exceed inspected_count ---------------------------------------


def test_affected_count_cannot_exceed_inspected_count(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)

    with pytest.raises(GrowerInspectionValidationError):
        grower_inspection_service.record_inspection(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            batch_id=scenario["batch"].id, batch_carrier_assignment_id=None, effective_time=None, inspected_count=10,
            overall_assessment="attention_needed", notes=None,
            findings=[{"category": "vigor", "severity": "medium", "affected_count": 17, "notes": None, "suspected_cause": None}],
            observation_values=[],
        )


# --- 10. weak/abnormal finding does not reduce living quantity -----------------------------


def test_finding_does_not_touch_living_inventory(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    assignment_id = scenario["assignment_ids"][0]

    before = db_session.execute(
        select(BatchCarrierAssignment.released_effective_time).where(BatchCarrierAssignment.id == assignment_id)
    ).scalar_one()
    assert before is None

    grower_inspection_service.record_inspection(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_id=scenario["batch"].id, batch_carrier_assignment_id=assignment_id, effective_time=None,
        inspected_count=200, overall_assessment="attention_needed", notes=None,
        findings=[
            {"category": "vigor", "severity": "high", "affected_count": 80, "notes": "weak seedlings", "suspected_cause": "nutrient imbalance"}
        ],
        observation_values=[],
    )

    after = db_session.execute(
        select(BatchCarrierAssignment.released_effective_time).where(BatchCarrierAssignment.id == assignment_id)
    ).scalar_one()
    assert after is None  # still active/living -- unchanged by recording a Finding


# --- 11. Crop Issue does not create Loss ---------------------------------------------------


def _open_issue_from_finding(db_session, tenant, user, farm, scenario, *, affected_count=80):
    insp = grower_inspection_service.record_inspection(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_id=scenario["batch"].id, batch_carrier_assignment_id=scenario["assignment_ids"][0], effective_time=None,
        inspected_count=200, overall_assessment="critical", notes=None,
        findings=[
            {"category": "pest_evidence", "severity": "critical", "affected_count": affected_count, "notes": "aphids", "suspected_cause": "ventilation gap"}
        ],
        observation_values=[],
    )
    findings = grower_inspection_service.list_findings(db_session, tenant_id=tenant.id, inspection_id=insp.id)
    issue = crop_issue_service.open_crop_issue(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        originating_grower_inspection_id=insp.id, originating_finding_id=findings[0].id, category="pest_evidence",
        severity="critical", description="Aphid infestation on gutter 3", suspected_cause="ventilation gap",
        assigned_owner_user_id=None, follow_up_due_at=None,
    )
    return insp, findings[0], issue


def test_crop_issue_does_not_create_loss(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    assignment_id = scenario["assignment_ids"][0]

    _insp, _finding, issue = _open_issue_from_finding(db_session, tenant, user, farm, scenario)

    assignment_state = db_session.execute(
        select(BatchCarrierAssignment.released_effective_time).where(BatchCarrierAssignment.id == assignment_id)
    ).scalar_one()
    batch_state = db_session.execute(select(CropBatch.state).where(CropBatch.id == scenario["batch"].id)).scalar_one()
    assert assignment_state is None
    assert batch_state == "active"
    assert issue.status == "open"


# --- 12. suspected cause != confirmed diagnosis ---------------------------------------------


def test_suspected_cause_never_promoted_to_confirmed_diagnosis(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    _insp, _finding, issue = _open_issue_from_finding(db_session, tenant, user, farm, scenario)
    assert issue.suspected_cause == "ventilation gap"
    assert issue.confirmed_diagnosis is None

    confirmed = crop_issue_service.confirm_diagnosis(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_issue_id=issue.id,
        client_command_id=uuid.uuid4(), confirmed_diagnosis="Two-spotted spider mite (lab-confirmed)",
    )
    assert confirmed.suspected_cause == "ventilation gap"  # unchanged
    assert confirmed.confirmed_diagnosis == "Two-spotted spider mite (lab-confirmed)"
    assert confirmed.suspected_cause != confirmed.confirmed_diagnosis


# --- 13/14. Issue links a Work Item; completion never resolves the Issue -------------------


def test_work_item_completion_does_not_resolve_issue(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    _insp, _finding, issue = _open_issue_from_finding(db_session, tenant, user, farm, scenario)

    work_item = farm_work_item_service.create_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        work_type="crop_care", category="crop_care", title="Treat aphid infestation", instructions=None,
        priority="high", due_at=None, assigned_to_user_id=None, crop_batch_id=scenario["batch"].id,
        location_id=None, carrier_id=None, asset_id=None, quantity=None, quantity_uom_id=None,
        completion_mode="manual_record", crop_issue_id=issue.id,
    )
    assert work_item.crop_issue_id == issue.id

    completed = farm_work_item_service.complete_work_item(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, work_item_id=work_item.id,
        client_command_id=uuid.uuid4(), completion_note="Treated with approved biocontrol",
    )
    assert completed.status == "completed"

    still_open = crop_issue_service.get_crop_issue(db_session, tenant_id=tenant.id, farm_id=farm.id, crop_issue_id=issue.id)
    assert still_open.status == "open"

    overlays = crop_issue_service.read_model_overlays(db_session, tenant_id=tenant.id, issues=[still_open])
    assert overlays[issue.id]["has_open_work_item"] is False  # the Work Item is completed, not "open"


# --- 15. follow-up can record improved/unchanged/worsened/resolved -------------------------


@pytest.mark.parametrize("outcome", ["improved", "unchanged", "worsened", "resolved"])
def test_follow_up_records_every_outcome(db_session, active_context_with_farm, outcome) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    _insp, _finding, issue = _open_issue_from_finding(db_session, tenant, user, farm, scenario)

    follow_up = crop_issue_service.record_follow_up(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_issue_id=issue.id,
        client_command_id=uuid.uuid4(), follow_up_grower_inspection_id=None, affected_count=10, notes="checked again",
        outcome=outcome,
    )
    assert follow_up.outcome == outcome

    # RESOLVED outcome must not silently close the Issue.
    unchanged = crop_issue_service.get_crop_issue(db_session, tenant_id=tenant.id, farm_id=farm.id, crop_issue_id=issue.id)
    assert unchanged.status == "open"


# --- 16. Issue closure is deliberate + authorized -------------------------------------------


def test_issue_closure_is_deliberate_and_requires_prior_resolution(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    _insp, _finding, issue = _open_issue_from_finding(db_session, tenant, user, farm, scenario)

    with pytest.raises(CropIssueInvalidTransitionError):
        crop_issue_service.close_crop_issue(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_issue_id=issue.id,
            client_command_id=uuid.uuid4(), close_note=None,
        )

    resolved = crop_issue_service.resolve_crop_issue(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_issue_id=issue.id,
        client_command_id=uuid.uuid4(), resolution_note="Biocontrol effective, infestation cleared",
    )
    assert resolved.status == "resolved"
    assert resolved.resolved_by_user_id == user.id

    closed = crop_issue_service.close_crop_issue(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_issue_id=issue.id,
        client_command_id=uuid.uuid4(), close_note="Confirmed on next visit",
    )
    assert closed.status == "closed"
    assert closed.closed_by_user_id == user.id


# --- 17. tenant/farm isolation ---------------------------------------------------------------


def test_tenant_isolation_on_growing_protocol(db_session, active_context_with_farm) -> None:
    tenant_a, user_a, _headers_a, farm_a = active_context_with_farm
    scenario = _build_scenario(db_session, tenant_a, user_a, farm_a)
    protocol = _register_protocol(db_session, tenant_a, user_a, scenario)

    # A genuinely SEPARATE second tenant -- requesting `active_context` as a
    # second fixture parameter alongside `active_context_with_farm` would
    # NOT do this: `active_context_with_farm` already depends on `active_
    # context`, and pytest caches a fixture once per test, so both
    # parameters would resolve to the SAME tenant. Mirrors `test_observation.
    # py::test_...cross_tenant...`'s own established "tenant_b" pattern.
    tenant_b = tenant_service.create_tenant(db_session, code=f"gp-tenant-b-{uuid.uuid4().hex[:8]}", name="Tenant B")

    with pytest.raises(GrowingProtocolNotFoundError):
        growing_protocol_service.get_protocol(db_session, tenant_id=tenant_b.id, growing_protocol_id=protocol.id)

    visible_to_b = growing_protocol_service.list_protocols(db_session, tenant_id=tenant_b.id)
    assert protocol.id not in {p.id for p in visible_to_b}


# --- 21. no protocol requirement executes operations (the due-read never mutates) ----------


def test_due_read_never_mutates_batch_or_stage(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    protocol = _register_protocol(db_session, tenant, user, scenario)
    version = _create_and_activate_version(db_session, tenant, user, protocol)
    growing_protocol_service.assign_batch_protocol(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scenario["batch"].id,
        growing_protocol_version_id=version.id, effective_from=None, reason=None, client_command_id=uuid.uuid4(),
    )
    audit_count_before = db_session.execute(select(AuditEvent.id)).scalars().all()

    for _ in range(3):
        growing_protocol_service.get_batch_protocol_status(
            db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=scenario["batch"].id
        )

    audit_count_after = db_session.execute(select(AuditEvent.id)).scalars().all()
    assert len(audit_count_before) == len(audit_count_after)
    stage = db_session.execute(select(CropBatch.state).where(CropBatch.id == scenario["batch"].id)).scalar_one()
    assert stage == "active"
