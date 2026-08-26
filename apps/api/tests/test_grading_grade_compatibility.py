"""POSTHARVEST-OPS-001C: grade-version applicability and effective-time
compatibility coverage."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services import grade_definition_service, grading_service
from app.services.errors import GradeDefinitionVersionNotFoundError, GradingValidationError
from tests._grading_scenario import build_committed_scenario, cleanup_scenario, now
from tests.test_grading import _grade, _output, _session


def _grade_version(session, scenario, *, crop_id=None, variety_id=None, status="active", code=None):
    definition = grade_definition_service.register_grade_definition(
        session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), code=code or f"g-{uuid.uuid4().hex[:8]}", name="Grade",
        crop_id=crop_id or scenario["crop_id"], variety_id=variety_id, description=None,
    )
    version = grade_definition_service.create_draft_version(
        session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), grade_definition_id=definition.id, spec_notes=None,
    )
    if status == "draft":
        return definition, version
    grade_definition_service.activate_version(
        session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), grade_definition_id=definition.id, version_id=version.id,
        effective_time=now() - timedelta(days=20),
    )
    if status == "active":
        return definition, version
    grade_definition_service.retire_version(
        session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), grade_definition_id=definition.id, version_id=version.id,
        effective_time=now() - timedelta(days=10),
    )
    return definition, version


@pytest.mark.integration
def test_exact_active_grade_version_accepted(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        event = _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000")],
        )
        assert event.id is not None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_retired_grade_version_accepted_for_backdated_event(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        # Retired at now()-10d, activated at now()-20d -- effective window
        # is [now()-20d, now()-10d). An event at now()-15d falls inside it.
        _definition, version = _grade_version(session, scenario, status="retired")
        event = _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000", grade_version_id=version.id)],
            effective_time=now() - timedelta(days=15),
        )
        assert event.id is not None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_retired_grade_version_rejected_after_its_effective_until(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _definition, version = _grade_version(session, scenario, status="retired")
        with pytest.raises(GradingValidationError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="10.000", grade_version_id=version.id)],
                effective_time=now(),
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_draft_grade_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        _definition, version = _grade_version(session, scenario, status="draft")
        with pytest.raises(GradingValidationError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="10.000", grade_version_id=version.id)],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_wrong_crop_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        from app.services import crop_service

        other_crop = crop_service.register_crop(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            code=f"other-{scenario['suffix']}", common_name="Tomato", scientific_name=None, crop_category="vine",
        )
        _definition, version = _grade_version(session, scenario, crop_id=other_crop.id, status="active")
        with pytest.raises(GradingValidationError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="10.000", grade_version_id=version.id)],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_wrong_specific_variety_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        from app.services import crop_service

        other_variety = crop_service.register_variety(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            crop_id=scenario["crop_id"], code=f"var2-{scenario['suffix']}", name="Other Variety",
            supplier_reference=None,
        )
        _definition, version = _grade_version(session, scenario, variety_id=other_variety.id, status="active")
        with pytest.raises(GradingValidationError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="10.000", grade_version_id=version.id)],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_all_variety_grade_accepted(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        # scenario's own grade_definition_version already has variety_id=None
        # (applies to all varieties) -- reuse it directly.
        event = _grade(
            scenario, db=session, input_presented="10.000", remainder="0",
            outputs=[_output(scenario, weight="10.000")],
        )
        assert event.id is not None
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_cross_tenant_grade_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    other_scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(GradeDefinitionVersionNotFoundError):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[
                    _output(
                        scenario, weight="10.000",
                        grade_version_id=other_scenario["grade_definition_version_id"],
                    )
                ],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
        cleanup_scenario(test_engine, other_scenario["tenant_id"])


@pytest.mark.integration
def test_duplicate_grade_version_in_same_event_rejected(test_engine) -> None:
    scenario = build_committed_scenario(test_engine, lot_a_weight="10.000", lot_a_count=None)
    session, conn = _session(test_engine)
    try:
        with pytest.raises(Exception):
            _grade(
                scenario, db=session, input_presented="10.000", remainder="0",
                outputs=[_output(scenario, weight="6.000"), _output(scenario, weight="4.000")],
            )
    finally:
        session.close()
        conn.close()
        cleanup_scenario(test_engine, scenario["tenant_id"])
