"""UX-OPS-001C/R1 (N05): Grower Inspection + its Observation values are ONE
atomic command. `record_inspection` composes the non-committing
`observation_service.record_observation_in_transaction` and owns a single
commit covering the ObservationEvent, ObservationValues, GrowerInspection,
InspectionFindings, and both audit events -- so any failure after the
Observation write rolls the whole command back (no orphaned
ObservationEvent), while the standalone Observation command still commits
on its own."""
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.audit_event import AuditEvent
from app.models.grower_inspection import GrowerInspection
from app.models.inspection_finding import InspectionFinding
from app.models.observation_event import ObservationEvent
from app.models.observation_value import ObservationValue
from app.services import grower_inspection_service, observation_service
from tests.test_growing_protocol_and_crop_issue import _build_scenario, _register_observation_definition


def _record(db_session, tenant, user, farm, scenario, definition, client_command_id, *, findings=None):
    return grower_inspection_service.record_inspection(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=client_command_id,
        batch_id=scenario["batch"].id, batch_carrier_assignment_id=None, effective_time=None, inspected_count=None,
        overall_assessment="attention_needed", notes="crop walk", findings=findings or [],
        observation_values=[
            {"observation_definition_id": definition.id, "batch_carrier_assignment_id": None, "value_text": "brown tips"}
        ],
    )


def _counts(db_session, tenant_id, client_command_id):
    event_ids = list(
        db_session.execute(
            select(ObservationEvent.id).where(
                ObservationEvent.tenant_id == tenant_id, ObservationEvent.client_command_id == client_command_id
            )
        ).scalars()
    )
    inspection_ids = list(
        db_session.execute(
            select(GrowerInspection.id).where(
                GrowerInspection.tenant_id == tenant_id, GrowerInspection.client_command_id == client_command_id
            )
        ).scalars()
    )
    values = db_session.execute(
        select(func.count()).select_from(ObservationValue).where(ObservationValue.observation_event_id.in_(event_ids))
    ).scalar_one()
    findings = db_session.execute(
        select(func.count())
        .select_from(InspectionFinding)
        .where(InspectionFinding.grower_inspection_id.in_(inspection_ids))
    ).scalar_one()
    observation_audits = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "crop_batch.observation_recorded", AuditEvent.entity_id.in_(event_ids))
    ).scalar_one()
    inspection_audits = db_session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "grower_inspection.recorded", AuditEvent.entity_id.in_(inspection_ids))
    ).scalar_one()
    return {
        "events": len(event_ids), "values": values, "inspections": len(inspection_ids), "findings": findings,
        "observation_audits": observation_audits, "inspection_audits": inspection_audits,
    }


NOTHING = {"events": 0, "values": 0, "inspections": 0, "findings": 0, "observation_audits": 0, "inspection_audits": 0}


def test_success_commits_observation_inspection_findings_and_both_audits_together(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    definition = _register_observation_definition(db_session, tenant, user, target_scope="crop_batch")
    command_id = uuid.uuid4()

    inspection = _record(
        db_session, tenant, user, farm, scenario, definition, command_id,
        findings=[{"category": "leaf_condition", "severity": "low", "affected_count": 3}],
    )

    assert inspection.observation_event_id is not None
    assert _counts(db_session, tenant.id, command_id) == {
        "events": 1, "values": 1, "inspections": 1, "findings": 1, "observation_audits": 1, "inspection_audits": 1,
    }

    # Exact replay returns the same inspection and never writes a second
    # ObservationEvent.
    replay = _record(
        db_session, tenant, user, farm, scenario, definition, command_id,
        findings=[{"category": "leaf_condition", "severity": "low", "affected_count": 3}],
    )
    assert replay.id == inspection.id
    assert _counts(db_session, tenant.id, command_id)["events"] == 1


def test_application_failure_after_observation_write_rolls_back_everything(
    db_session, active_context_with_farm, monkeypatch
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    definition = _register_observation_definition(db_session, tenant, user, target_scope="crop_batch")
    command_id = uuid.uuid4()

    # Fails at the inspection's own audit write -- after the Observation
    # event/values/audit AND the inspection/findings are already flushed.
    def boom(*_args, **_kwargs):
        raise RuntimeError("injected failure after the observation write")

    monkeypatch.setattr(grower_inspection_service, "append_audit_event", boom)
    with pytest.raises(RuntimeError):
        _record(
            db_session, tenant, user, farm, scenario, definition, command_id,
            findings=[{"category": "roots", "severity": "medium", "affected_count": None}],
        )
    monkeypatch.undo()

    assert _counts(db_session, tenant.id, command_id) == NOTHING

    # The session is usable and the same command can then succeed cleanly.
    inspection = _record(db_session, tenant, user, farm, scenario, definition, command_id)
    assert inspection.observation_event_id is not None
    assert _counts(db_session, tenant.id, command_id)["events"] == 1


def test_database_failure_on_findings_rolls_back_the_observation_too(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    definition = _register_observation_definition(db_session, tenant, user, target_scope="crop_batch")
    command_id = uuid.uuid4()

    # inspected_count is None, so the service-level affected<=inspected
    # check does not apply; the DB CHECK (affected_count >= 0) rejects the
    # finding at flush time -- after the Observation was already flushed.
    with pytest.raises(IntegrityError):
        _record(
            db_session, tenant, user, farm, scenario, definition, command_id,
            findings=[{"category": "vigor", "severity": "low", "affected_count": -1}],
        )

    assert _counts(db_session, tenant.id, command_id) == NOTHING


def test_standalone_observation_command_still_commits_on_its_own(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    definition = _register_observation_definition(db_session, tenant, user, target_scope="crop_batch")
    command_id = uuid.uuid4()

    event = observation_service.record_observation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scenario["batch"].id,
        client_command_id=command_id, effective_time=None, note=None,
        values=[{"observation_definition_id": definition.id, "batch_carrier_assignment_id": None, "value_text": "ok"}],
        germination_checks=[],
    )
    # Committed: a rollback of the session cannot remove it.
    db_session.rollback()
    counts = _counts(db_session, tenant.id, command_id)
    assert counts["events"] == 1 and counts["values"] == 1 and counts["observation_audits"] == 1
    assert counts["inspections"] == 0

    replay = observation_service.record_observation(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scenario["batch"].id,
        client_command_id=command_id, effective_time=None, note=None,
        values=[{"observation_definition_id": definition.id, "batch_carrier_assignment_id": None, "value_text": "ok"}],
        germination_checks=[],
    )
    assert replay.id == event.id
