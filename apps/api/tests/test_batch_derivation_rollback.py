"""CMP-012 rollback proofs: a failure partway through the write phase must
leave no partial writes — no derivation event, no output batches, no
released source assignments, no superseded source batch."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.batch_assignment_transfer import BatchAssignmentTransfer
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_derivation_event import BatchDerivationEvent
from app.models.batch_derivation_source import BatchDerivationSource
from app.models.crop_batch import CropBatch
from app.services import (
    batch_derivation_service,
    carrier_service,
    crop_batch_service,
    crop_service,
    farm_service,
    membership_service,
    production_system_service,
    sowing_service,
    tenant_service,
    user_service,
    workflow_service,
)
from app.services.errors import DuplicateBatchCodeError
from tests.conftest import ensure_seed_tray_specification


def _now():
    return datetime.now(timezone.utc)


def _build_scenario(db_session, tenant, user, farm, *, carrier_count=2, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
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
        from_stage_id=seeding.id, to_stage_id=complete.id, code="ADV", name="Advance",
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
        for n in range(1, carrier_count + 1)
    ]
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[
            {"carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 20, "seed_count": 20, "line_note": None}
            for c in carriers
        ],
    )
    assignments = sowing_service.list_batch_carriers(db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_by_carrier = {a.carrier.code: a.id for a in assignments}
    aids = [assignment_by_carrier[c.code] for c in carriers]
    return {"batch": batch, "assignment_ids": aids}


def _assert_session_usable(db_session) -> None:
    db_session.execute(text("SELECT 1")).scalar_one()


@pytest.mark.integration
def test_duplicate_output_code_rolls_back_completely(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:6]
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=2, suffix=suffix)
    aids = s["assignment_ids"]

    # Pre-create a crop batch with the exact code the split will try to use
    # for its second output, forcing the output-batch insert to fail on the
    # tenant-wide case-insensitive code uniqueness constraint.
    colliding_code = f"OUT-B-{suffix}"
    crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=colliding_code, workflow_id=s["batch"].workflow_id, effective_time=_now(),
    )

    with pytest.raises(DuplicateBatchCodeError):
        batch_derivation_service.split_batch(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
            outputs=[
                {"output_batch_code": f"OUT-A-{suffix}", "source_assignment_ids": [aids[0]]},
                {"output_batch_code": colliding_code, "source_assignment_ids": [aids[1]]},
            ],
        )

    _assert_session_usable(db_session)

    event_count = db_session.execute(
        select(func.count()).select_from(BatchDerivationEvent).where(BatchDerivationEvent.tenant_id == tenant.id)
    ).scalar_one()
    assert event_count == 0, "a failed split must not leave a derivation event behind"

    source_line_count = db_session.execute(
        select(func.count()).select_from(BatchDerivationSource).where(BatchDerivationSource.tenant_id == tenant.id)
    ).scalar_one()
    assert source_line_count == 0

    output_a_count = db_session.execute(
        select(func.count()).select_from(CropBatch).where(
            CropBatch.tenant_id == tenant.id, CropBatch.code == f"OUT-A-{suffix}"
        )
    ).scalar_one()
    assert output_a_count == 0, "a failed split must not leave the other output batch behind either"

    db_session.refresh(s["batch"])
    assert s["batch"].state == "active", "the source batch must remain active after a failed split"

    for aid in aids:
        assignment = db_session.get(BatchCarrierAssignment, aid)
        assert assignment.released_effective_time is None, "source assignments must remain active after a failed split"


@pytest.mark.integration
def test_reused_command_id_after_rollback_is_a_genuine_new_attempt(db_session, active_context_with_farm) -> None:
    """A duplicate client_command_id whose first attempt failed (and rolled
    back) must not be treated as an idempotent replay of a nonexistent
    event — it is a genuinely new attempt and must run normally."""
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:6]
    s = _build_scenario(db_session, tenant, user, farm, carrier_count=2, suffix=suffix)
    aids = s["assignment_ids"]
    command_id = uuid.uuid4()

    colliding_code = f"OUT-B-{suffix}"
    crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=colliding_code, workflow_id=s["batch"].workflow_id, effective_time=_now(),
    )
    with pytest.raises(DuplicateBatchCodeError):
        batch_derivation_service.split_batch(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=command_id, effective_time=_now(), note=None,
            outputs=[
                {"output_batch_code": f"OUT-A-{suffix}", "source_assignment_ids": [aids[0]]},
                {"output_batch_code": colliding_code, "source_assignment_ids": [aids[1]]},
            ],
        )
    _assert_session_usable(db_session)

    # Retry with the SAME command id but non-colliding codes — must succeed
    # as a genuinely new command, not be rejected as a mismatched replay.
    event = batch_derivation_service.split_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=command_id, effective_time=_now(), note=None,
        outputs=[
            {"output_batch_code": f"OUT-C-{suffix}", "source_assignment_ids": [aids[0]]},
            {"output_batch_code": f"OUT-D-{suffix}", "source_assignment_ids": [aids[1]]},
        ],
    )
    assert event.derivation_kind == "split"
