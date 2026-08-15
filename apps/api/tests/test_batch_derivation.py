import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models.batch_assignment_transfer import BatchAssignmentTransfer
from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.batch_derivation_event import BatchDerivationEvent
from app.models.crop_batch import CropBatch
from app.schemas.batch_derivation import BatchMergeCreate, BatchSplitCreate, SplitOutputIn
from app.services import (
    batch_derivation_service,
    carrier_service,
    crop_batch_service,
    crop_service,
    production_system_service,
    quality_hold_service,
    sowing_service,
    workflow_service,
)
from app.services.errors import (
    BatchAlreadySownError,
    BatchDerivationCommandReusedWithDifferentPayloadError,
    BatchDerivationValidationError,
    QualityHoldOpenError,
)


def _now():
    return datetime.now(timezone.utc)


def _build_batch_with_assignments(db_session, tenant, user, farm, *, carrier_count=4, suffix=None):
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
    growing = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="GROWING", name="Growing", display_order=1, stage_category="intermediate",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=growing.id, code="ADVANCE-1", name="Advance 1",
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=growing.id, to_stage_id=complete.id, code="ADVANCE-2", name="Advance 2",
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
    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, carrier_count + 1)
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
    assignment_ids = [assignment_by_carrier_code[c.code] for c in carriers]
    return {
        "crop": crop, "variety": variety, "workflow": workflow, "version": version,
        "stages": {"SEEDING": seeding, "GROWING": growing, "COMPLETE": complete}, "batch": batch, "seed_lot": seed_lot,
        "carriers": carriers, "assignment_ids": assignment_ids,
    }


@pytest.mark.integration
def test_split_creates_two_output_batches_and_supersedes_source(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_batch_with_assignments(db_session, tenant, user, farm, carrier_count=4)
    aids = s["assignment_ids"]
    suffix = uuid.uuid4().hex[:6]

    event = batch_derivation_service.split_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        outputs=[
            {"output_batch_code": f"OUT-A-{suffix}", "source_assignment_ids": aids[:2]},
            {"output_batch_code": f"OUT-B-{suffix}", "source_assignment_ids": aids[2:]},
        ],
    )
    assert event.derivation_kind == "split"

    db_session.refresh(s["batch"])
    assert s["batch"].state == "superseded"
    assert s["batch"].superseded_by_batch_derivation_event_id == event.id
    assert s["batch"].superseded_effective_time is not None

    outputs = db_session.execute(
        select(CropBatch).where(CropBatch.created_by_batch_derivation_event_id == event.id)
    ).scalars().all()
    assert {b.code for b in outputs} == {f"OUT-A-{suffix}", f"OUT-B-{suffix}"}
    for b in outputs:
        assert b.state == "active"
        assert b.workflow_version_id == s["batch"].workflow_version_id
        assert b.client_command_id is None
        assert b.request_fingerprint is None
        assert b.created_by_user_id == user.id

    for aid in aids:
        assignment = db_session.get(BatchCarrierAssignment, aid)
        assert assignment.released_effective_time is not None
        assert assignment.released_by_batch_derivation_event_id == event.id

    new_active = db_session.execute(
        select(func.count()).select_from(BatchCarrierAssignment).where(
            BatchCarrierAssignment.opening_batch_derivation_event_id == event.id,
            BatchCarrierAssignment.released_effective_time.is_(None),
        )
    ).scalar_one()
    assert new_active == 4

    transfers = db_session.execute(
        select(func.count()).select_from(BatchAssignmentTransfer).where(
            BatchAssignmentTransfer.derivation_event_id == event.id
        )
    ).scalar_one()
    assert transfers == 4


@pytest.mark.integration
def test_split_requires_complete_assignment_coverage(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_batch_with_assignments(db_session, tenant, user, farm, carrier_count=4)
    aids = s["assignment_ids"]
    suffix = uuid.uuid4().hex[:6]

    with pytest.raises(BatchDerivationValidationError):
        batch_derivation_service.split_batch(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
            outputs=[
                {"output_batch_code": f"OUT-A-{suffix}", "source_assignment_ids": aids[:1]},
                {"output_batch_code": f"OUT-B-{suffix}", "source_assignment_ids": aids[1:2]},
            ],
        )
    db_session.rollback()


@pytest.mark.integration
def test_split_exact_retry_returns_original_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_batch_with_assignments(db_session, tenant, user, farm, carrier_count=2)
    aids = s["assignment_ids"]
    suffix = uuid.uuid4().hex[:6]
    command_id = uuid.uuid4()
    effective_time = _now()

    first = batch_derivation_service.split_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=command_id, effective_time=effective_time, note=None,
        outputs=[
            {"output_batch_code": f"OUT-A-{suffix}", "source_assignment_ids": [aids[0]]},
            {"output_batch_code": f"OUT-B-{suffix}", "source_assignment_ids": [aids[1]]},
        ],
    )
    retry = batch_derivation_service.split_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=command_id, effective_time=effective_time, note=None,
        outputs=[
            {"output_batch_code": f"OUT-A-{suffix}", "source_assignment_ids": [aids[0]]},
            {"output_batch_code": f"OUT-B-{suffix}", "source_assignment_ids": [aids[1]]},
        ],
    )
    assert retry.id == first.id
    event_count = db_session.execute(
        select(func.count()).select_from(BatchDerivationEvent).where(BatchDerivationEvent.id == first.id)
    ).scalar_one()
    assert event_count == 1


@pytest.mark.integration
def test_derivation_reused_command_id_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_batch_with_assignments(db_session, tenant, user, farm, carrier_count=2)
    aids = s["assignment_ids"]
    suffix = uuid.uuid4().hex[:6]
    command_id = uuid.uuid4()

    batch_derivation_service.split_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=command_id, effective_time=_now(), note=None,
        outputs=[
            {"output_batch_code": f"OUT-A-{suffix}", "source_assignment_ids": [aids[0]]},
            {"output_batch_code": f"OUT-B-{suffix}", "source_assignment_ids": [aids[1]]},
        ],
    )
    with pytest.raises(BatchDerivationCommandReusedWithDifferentPayloadError):
        batch_derivation_service.split_batch(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=command_id, effective_time=_now(), note="different note",
            outputs=[
                {"output_batch_code": f"OUT-A-{suffix}", "source_assignment_ids": [aids[0]]},
                {"output_batch_code": f"OUT-B-{suffix}", "source_assignment_ids": [aids[1]]},
            ],
        )


@pytest.mark.integration
def test_superseded_source_batch_rejects_new_sowing(db_session, active_context_with_farm) -> None:
    """NURSERY-OPS-001: `_build_batch_with_assignments` already sows the
    source batch once (that's how it gets assignments to split at all), so
    a second sowing attempt is now rejected by the broader, unconditional
    BatchAlreadySownError rule (`ux_sowing_events_batch_id`) before the
    (still independently true) CropBatchClosedError check is ever reached
    -- both are correct here; BatchAlreadySownError is simply checked
    first. See test_sowing.py::test_sow_second_command_on_already_sown_batch_rejected
    for the rule in isolation, and test_sow_closed_batch_rejected in
    test_sowing.py for a closed-but-never-sown batch."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_batch_with_assignments(db_session, tenant, user, farm, carrier_count=2)
    aids = s["assignment_ids"]
    suffix = uuid.uuid4().hex[:6]

    batch_derivation_service.split_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        outputs=[
            {"output_batch_code": f"OUT-A-{suffix}", "source_assignment_ids": [aids[0]]},
            {"output_batch_code": f"OUT-B-{suffix}", "source_assignment_ids": [aids[1]]},
        ],
    )

    extra_carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="seed_tray", code=f"ST-extra-{suffix}", issued_date=None,
    )
    with pytest.raises(BatchAlreadySownError):
        sowing_service.sow_batch(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
            lines=[
                {
                    "carrier_id": extra_carrier.id, "seed_lot_id": s["seed_lot"].id, "sown_site_count": 10,
                    "seed_count": 10, "line_note": None,
                }
            ],
        )


@pytest.mark.integration
def test_merge_creates_one_output_and_supersedes_both_sources(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:6]
    s1 = _build_batch_with_assignments(db_session, tenant, user, farm, carrier_count=2, suffix=f"a{suffix}")
    # Reuse the same workflow/version for the second source so they're compatible.
    batch2 = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-b{suffix}", workflow_id=s1["workflow"].id, effective_time=_now(),
    )
    seed_lot2 = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=s1["crop"].id,
        variety_id=s1["variety"].id, code=f"LOT-b{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    carriers2 = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"ST-b{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, 3)
    ]
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch2.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[
            {"carrier_id": c.id, "seed_lot_id": seed_lot2.id, "sown_site_count": 150, "seed_count": 150, "line_note": None}
            for c in carriers2
        ],
    )

    event = batch_derivation_service.merge_batches(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        source_batch_ids=[s1["batch"].id, batch2.id], client_command_id=uuid.uuid4(), effective_time=_now(),
        note=None, output_batch_code=f"MERGED-{suffix}",
    )
    assert event.derivation_kind == "merge"

    db_session.refresh(s1["batch"])
    db_session.refresh(batch2)
    assert s1["batch"].state == "superseded"
    assert batch2.state == "superseded"

    output = db_session.execute(
        select(CropBatch).where(CropBatch.created_by_batch_derivation_event_id == event.id)
    ).scalar_one()
    assert output.code == f"MERGED-{suffix}"

    active_count = db_session.execute(
        select(func.count()).select_from(BatchCarrierAssignment).where(
            BatchCarrierAssignment.batch_id == output.id, BatchCarrierAssignment.released_effective_time.is_(None)
        )
    ).scalar_one()
    assert active_count == 4
    total_qty = db_session.execute(
        select(func.sum(BatchAssignmentTransfer.transferred_plant_count)).where(
            BatchAssignmentTransfer.derivation_event_id == event.id
        )
    ).scalar_one()
    assert total_qty == 200 + 200 + 150 + 150


@pytest.mark.integration
def test_merge_incompatible_workflow_version_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:6]
    s1 = _build_batch_with_assignments(db_session, tenant, user, farm, carrier_count=2, suffix=f"a{suffix}")
    s2 = _build_batch_with_assignments(db_session, tenant, user, farm, carrier_count=2, suffix=f"b{suffix}")

    with pytest.raises(BatchDerivationValidationError):
        batch_derivation_service.merge_batches(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            source_batch_ids=[s1["batch"].id, s2["batch"].id], client_command_id=uuid.uuid4(),
            effective_time=_now(), note=None, output_batch_code=f"MERGED-bad-{suffix}",
        )


@pytest.mark.integration
def test_merge_open_hold_blocks_and_release_unblocks(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:6]
    s1 = _build_batch_with_assignments(db_session, tenant, user, farm, carrier_count=1, suffix=f"a{suffix}")
    batch2 = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-b{suffix}", workflow_id=s1["workflow"].id, effective_time=_now(),
    )
    seed_lot2 = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=s1["crop"].id,
        variety_id=s1["variety"].id, code=f"LOT-b{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    carrier2 = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="seed_tray", code=f"ST-b{suffix}", issued_date=None,
    )
    sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch2.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[{"carrier_id": carrier2.id, "seed_lot_id": seed_lot2.id, "sown_site_count": 10, "seed_count": 10, "line_note": None}],
    )

    hold = quality_hold_service.place_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch2.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), source_observation_event_id=None,
        reason_code="pest", reason_text="aphids observed",
    )

    with pytest.raises(QualityHoldOpenError):
        batch_derivation_service.merge_batches(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            source_batch_ids=[s1["batch"].id, batch2.id], client_command_id=uuid.uuid4(), effective_time=_now(),
            note=None, output_batch_code=f"MERGED-held-{suffix}",
        )

    quality_hold_service.release_quality_hold(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch2.id,
        hold_id=hold.id, client_command_id=uuid.uuid4(), effective_time=_now(), release_reason="resolved",
    )
    event = batch_derivation_service.merge_batches(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        source_batch_ids=[s1["batch"].id, batch2.id], client_command_id=uuid.uuid4(), effective_time=_now(),
        note=None, output_batch_code=f"MERGED-held-{suffix}",
    )
    assert event.derivation_kind == "merge"


@pytest.mark.integration
def test_chained_split_then_merge_resolves_quantity_through_derivation_origin(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_batch_with_assignments(db_session, tenant, user, farm, carrier_count=2)
    aids = s["assignment_ids"]
    suffix = uuid.uuid4().hex[:6]

    split_event = batch_derivation_service.split_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        outputs=[
            {"output_batch_code": f"SPLIT-A-{suffix}", "source_assignment_ids": [aids[0]]},
            {"output_batch_code": f"SPLIT-B-{suffix}", "source_assignment_ids": [aids[1]]},
        ],
    )
    split_a = db_session.execute(
        select(CropBatch).where(CropBatch.code == f"SPLIT-A-{suffix}")
    ).scalar_one()
    split_b = db_session.execute(
        select(CropBatch).where(CropBatch.code == f"SPLIT-B-{suffix}")
    ).scalar_one()

    merge_event = batch_derivation_service.merge_batches(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        source_batch_ids=[split_a.id, split_b.id], client_command_id=uuid.uuid4(), effective_time=_now(),
        note=None, output_batch_code=f"REMERGED-{suffix}",
    )
    assert merge_event.derivation_kind == "merge"
    total_qty = db_session.execute(
        select(func.sum(BatchAssignmentTransfer.transferred_plant_count)).where(
            BatchAssignmentTransfer.derivation_event_id == merge_event.id
        )
    ).scalar_one()
    assert total_qty == 400
    assert split_event.id != merge_event.id


# --- Schema-level validation (no DB required) ---------------------------------------


def test_split_schema_requires_at_least_two_outputs() -> None:
    with pytest.raises(ValueError):
        BatchSplitCreate(
            client_command_id=uuid.uuid4(), effective_time=_now(),
            outputs=[SplitOutputIn(output_batch_code="ONLY-ONE", source_assignment_ids=[uuid.uuid4()])],
        )


def test_split_schema_rejects_duplicate_output_codes() -> None:
    aid1, aid2 = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(ValueError):
        BatchSplitCreate(
            client_command_id=uuid.uuid4(), effective_time=_now(),
            outputs=[
                SplitOutputIn(output_batch_code="DUP", source_assignment_ids=[aid1]),
                SplitOutputIn(output_batch_code="dup", source_assignment_ids=[aid2]),
            ],
        )


def test_merge_schema_requires_at_least_two_sources() -> None:
    with pytest.raises(ValueError):
        BatchMergeCreate(
            client_command_id=uuid.uuid4(), effective_time=_now(), source_batch_ids=[uuid.uuid4()],
            output_batch_code="OUT",
        )


def test_derivation_schemas_reject_extra_fields() -> None:
    with pytest.raises(ValueError):
        BatchMergeCreate(
            client_command_id=uuid.uuid4(), effective_time=_now(),
            source_batch_ids=[uuid.uuid4(), uuid.uuid4()], output_batch_code="OUT", extra_field=1,
        )
