import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.models.germination_check import GerminationCheck
from app.models.sowing_event_line import SowingEventLine
from app.schemas.observation_event import GerminationCheckIn, ObservationEventCreate
from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    observation_service,
    production_system_service,
    sowing_service,
    workflow_service,
)
from app.services.errors import ObservationValidationError
from tests.conftest import ensure_seed_tray_specification

# --- Application-level (Pydantic) validation — no DB required ---


def test_germination_check_categories_exceeding_inspected_rejected() -> None:
    with pytest.raises(ValueError):
        GerminationCheckIn(
            batch_carrier_assignment_id=uuid.uuid4(), inspected_site_count=10,
            normal_germinated_site_count=8, abnormal_germinated_site_count=2, failed_site_count=1,
        )


def test_germination_check_non_positive_inspected_rejected() -> None:
    with pytest.raises(ValueError):
        GerminationCheckIn(
            batch_carrier_assignment_id=uuid.uuid4(), inspected_site_count=0,
            normal_germinated_site_count=0, abnormal_germinated_site_count=0, failed_site_count=0,
        )


def test_germination_check_negative_category_rejected() -> None:
    with pytest.raises(ValueError):
        GerminationCheckIn(
            batch_carrier_assignment_id=uuid.uuid4(), inspected_site_count=10,
            normal_germinated_site_count=-1, abnormal_germinated_site_count=0, failed_site_count=0,
        )


def test_event_duplicate_germination_assignment_rejected() -> None:
    assignment_id = uuid.uuid4()
    check = GerminationCheckIn(
        batch_carrier_assignment_id=assignment_id, inspected_site_count=10,
        normal_germinated_site_count=5, abnormal_germinated_site_count=0, failed_site_count=0,
    )
    with pytest.raises(ValueError):
        ObservationEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            germination_checks=[check, check],
        )


# --- Integration helpers ----------------------------------------------------------


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
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Nursery Tray",
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
        from_stage_id=seeding.id, to_stage_id=complete.id, code="ADVANCE", name="Advance",
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
            {
                "carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 200, "seed_count": 220,
                "line_note": None,
            }
            for c in carriers
        ],
    )
    assignments = sowing_service.list_batch_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
    )
    assignment_by_carrier_code = {a.carrier.code: a.id for a in assignments}
    return {
        "batch": batch, "carriers": carriers,
        "assignment_ids": [assignment_by_carrier_code[c.code] for c in carriers],
    }


def _record(db_session, tenant, user, farm, batch, germination_checks, **overrides):
    defaults = dict(
        tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None, values=[],
    )
    defaults.update(overrides)
    return observation_service.record_observation(
        db_session, germination_checks=germination_checks, **defaults
    )


def _check(assignment_id, **overrides):
    defaults = dict(
        batch_carrier_assignment_id=assignment_id, inspected_site_count=200,
        normal_germinated_site_count=180, abnormal_germinated_site_count=10, failed_site_count=5,
    )
    defaults.update(overrides)
    return defaults


# --- Core behavior --------------------------------------------------------------


@pytest.mark.integration
def test_germination_check_recorded_and_percentage_derived(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    event = _record(db_session, tenant, user, farm, s["batch"], [_check(s["assignment_ids"][0])])

    assert db_session.execute(select(func.count()).select_from(GerminationCheck)).scalar_one() == 1
    read = observation_service.get_observation_event(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, observation_event_id=event.id
    )
    check = read.germination_checks[0]
    assert check.total_germinated_site_count == 190
    assert check.unresolved_site_count == 5
    assert check.germination_percentage == Decimal("95")


@pytest.mark.integration
def test_germination_percentage_not_persisted_as_column(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _record(db_session, tenant, user, farm, s["batch"], [_check(s["assignment_ids"][0])])
    columns = {
        r[0]
        for r in db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'germination_checks'"
            )
        ).all()
    }
    assert "germination_percentage" not in columns


@pytest.mark.integration
def test_sowing_quantities_unchanged_by_germination_check(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    line_before = db_session.execute(
        select(SowingEventLine).where(SowingEventLine.batch_carrier_assignment_id == s["assignment_ids"][0])
    ).scalar_one()
    sown_before, seed_before = line_before.sown_site_count, line_before.seed_count

    _record(db_session, tenant, user, farm, s["batch"], [_check(s["assignment_ids"][0])])

    db_session.refresh(line_before)
    assert line_before.sown_site_count == sown_before == 200
    assert line_before.seed_count == seed_before == 220


@pytest.mark.integration
def test_inspected_exceeds_sown_site_count_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    with pytest.raises(ObservationValidationError):
        _record(
            db_session, tenant, user, farm, s["batch"],
            [_check(s["assignment_ids"][0], inspected_site_count=201, normal_germinated_site_count=0,
                     abnormal_germinated_site_count=0, failed_site_count=0)],
        )


@pytest.mark.integration
def test_assignment_from_another_batch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s1 = _build_scenario(db_session, tenant, user, farm)
    s2 = _build_scenario(db_session, tenant, user, farm)
    with pytest.raises(ObservationValidationError):
        _record(db_session, tenant, user, farm, s1["batch"], [_check(s2["assignment_ids"][0])])


@pytest.mark.integration
def test_multiple_checks_for_one_assignment_across_events_allowed(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _record(db_session, tenant, user, farm, s["batch"], [_check(s["assignment_ids"][0])])
    _record(
        db_session, tenant, user, farm, s["batch"],
        [_check(s["assignment_ids"][0], normal_germinated_site_count=190, abnormal_germinated_site_count=5)],
    )
    assert db_session.execute(select(func.count()).select_from(GerminationCheck)).scalar_one() == 2


@pytest.mark.integration
def test_duplicate_check_for_same_assignment_in_one_event_rejected() -> None:
    assignment_id = uuid.uuid4()
    with pytest.raises(ValueError):
        ObservationEventCreate(
            client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc),
            germination_checks=[
                GerminationCheckIn(
                    batch_carrier_assignment_id=assignment_id, inspected_site_count=10,
                    normal_germinated_site_count=5, abnormal_germinated_site_count=0, failed_site_count=0,
                ),
                GerminationCheckIn(
                    batch_carrier_assignment_id=assignment_id, inspected_site_count=10,
                    normal_germinated_site_count=3, abnormal_germinated_site_count=0, failed_site_count=0,
                ),
            ],
        )


@pytest.mark.integration
def test_germination_check_direct_sql_update_and_delete_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    _record(db_session, tenant, user, farm, s["batch"], [_check(s["assignment_ids"][0])])
    check_row = db_session.execute(select(GerminationCheck)).scalars().first()

    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE germination_checks SET failed_site_count = 999 WHERE id = :id"), {"id": check_row.id}
        )
        db_session.flush()
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM germination_checks WHERE id = :id"), {"id": check_row.id})
        db_session.flush()
    db_session.rollback()


# --- API ------------------------------------------------------------------------


@pytest.mark.integration
def test_germination_check_api_smoke(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm
    s = _build_scenario(db_session, tenant, user, farm)
    db_session.commit()

    resp = client.post(
        f"/farms/{farm.id}/crop-batches/{s['batch'].id}/observations", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": datetime.now(timezone.utc).isoformat(),
            "germination_checks": [
                {
                    "batch_carrier_assignment_id": str(s["assignment_ids"][0]), "inspected_site_count": 200,
                    "normal_germinated_site_count": 180, "abnormal_germinated_site_count": 10,
                    "failed_site_count": 5,
                }
            ],
        },
    )
    assert resp.status_code == 201
    event = resp.json()
    assert len(event["germination_checks"]) == 1
    assert Decimal(event["germination_checks"][0]["germination_percentage"]) == Decimal("95")
