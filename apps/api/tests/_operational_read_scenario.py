"""Shared, non-collected scenario helpers for CMP-FE-002A operational
read-model tests. Builds on `tests/_traceability_scenario.py`'s own
committed-connection scaffold (reused directly, not duplicated) and adds a
transplant-capable workflow, a small location tree, and split/quality-hold
convenience wrappers. Not a test file itself."""
import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from app.services import (
    batch_derivation_service,
    carrier_service,
    crop_batch_service,
    crop_service,
    location_service,
    movement_service,
    production_system_service,
    quality_hold_service,
    sowing_service,
    transplant_service,
    workflow_service,
)
from tests._traceability_scenario import (  # noqa: F401  re-exported for test files
    build_committed_tenant_farm,
    committed_connection,
    now,
)


def build_transplant_workflow_scaffold(db: Session, tenant, user, farm, *, suffix=None):
    """SEEDING(seed_tray) -> TRANSPLANTING(cultivation_plate) -> GROWING ->
    COMPLETE -- the minimum multi-stage graph that lets a test exercise
    sowing, transplant, and post-transplant stage progression."""
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg", scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Plate System", description=None,
    )
    workflow = workflow_service.register_workflow(
        db, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id)
    seeding = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    transplanting = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="TRANSPLANTING", name="Transplanting", display_order=1, stage_category="transplanting",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="cultivation_plate", is_start=False, is_terminal=False,
    )
    growing = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="GROWING", name="Growing", display_order=2, stage_category="production",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=3, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t_seed_to_transplant = workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=transplanting.id, code="ADV-1", name="Advance 1",
    )
    t_transplant_to_growing = workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=transplanting.id, to_stage_id=growing.id, code="ADV-2", name="Advance 2",
    )
    t_growing_to_complete = workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=growing.id, to_stage_id=complete.id, code="ADV-3", name="Advance 3",
    )
    workflow_service.publish_version(db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id)
    return {
        "crop": crop, "variety": variety, "workflow": workflow, "version": version,
        "t_seed_to_transplant": t_seed_to_transplant, "t_transplant_to_growing": t_transplant_to_growing,
        "t_growing_to_complete": t_growing_to_complete,
    }


def build_direct_placement_workflow_scaffold(db: Session, tenant, user, farm, *, suffix=None):
    """SEEDING(cultivation_plate) -> GROWING -> COMPLETE. Unlike
    `build_transplant_workflow_scaffold` (SEEDING requires `seed_tray`,
    which the seeded `occupancy_compatibility_rules` only ever permit at an
    asset `slot` position, never directly at a location), this scaffold's
    SEEDING stage requires `cultivation_plate` -- the carrier type actually
    compatible with `table_position` locations -- so `sow_batch`'s own
    carrier can be placed directly, with no intervening transplant. Used by
    placement-facts and subtree-occupancy tests, which care about location
    occupancy, not sowing-origin/transplant semantics."""
    suffix = suffix or uuid.uuid4().hex[:8]
    crop = crop_service.register_crop(
        db, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg", scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"MAM-{suffix}",
        name="Mamutik", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Plate System", description=None,
    )
    workflow = workflow_service.register_workflow(
        db, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id)
    seeding = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="cultivation_plate", is_start=True, is_terminal=False,
    )
    growing = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="GROWING", name="Growing", display_order=1, stage_category="production",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=growing.id, code="ADV-1", name="Advance 1",
    )
    workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=growing.id, to_stage_id=complete.id, code="ADV-2", name="Advance 2",
    )
    workflow_service.publish_version(db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id)
    return {"crop": crop, "variety": variety, "workflow": workflow, "version": version}


def sow_batch(db: Session, tenant, user, farm, scaffold: dict, *, effective_time, code_suffix=None, site_count=10, carrier_type_code="seed_tray"):
    code_suffix = code_suffix or uuid.uuid4().hex[:8]
    batch = crop_batch_service.create_batch(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{code_suffix}", workflow_id=scaffold["workflow"].id, effective_time=effective_time,
    )
    seed_lot = sowing_service.register_seed_lot(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=scaffold["crop"].id,
        variety_id=scaffold["variety"].id, code=f"SEED-{code_suffix}", supplier_name=None,
        supplier_lot_reference=None, received_date=None, expiry_date=None,
    )
    tray = carrier_service.register_carrier(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code=carrier_type_code, code=f"TRAY-{code_suffix}", issued_date=None,
    )
    sowing_service.sow_batch(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=effective_time, note=None,
        lines=[{"carrier_id": tray.id, "seed_lot_id": seed_lot.id, "sown_site_count": site_count, "seed_count": site_count, "line_note": None}],
    )
    assignments = sowing_service.list_batch_carriers(db, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_id = next(a.id for a in assignments if a.carrier.id == tray.id)
    return {"batch": batch, "seed_lot": seed_lot, "tray": tray, "assignment_id": assignment_id}


def sow_second_carrier(db: Session, tenant, user, farm, *, batch_id, seed_lot_id, effective_time, site_count=10, carrier_type_code="seed_tray", code_suffix=None):
    """Adds a second, independent carrier/assignment to an already-sown
    batch (still in its seeding stage) -- needed for split, since
    `batch_derivation_service.split_batch` requires >= 2 outputs, each with
    >= 1 assignment (`ck_batch_derivation_outputs_assignment_count_positive`),
    so a single-carrier batch cannot be split at all."""
    code_suffix = code_suffix or uuid.uuid4().hex[:8]
    tray2 = carrier_service.register_carrier(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code=carrier_type_code, code=f"TRAY2-{code_suffix}", issued_date=None,
    )
    sowing_service.sow_batch(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), effective_time=effective_time, note=None,
        lines=[{"carrier_id": tray2.id, "seed_lot_id": seed_lot_id, "sown_site_count": site_count, "seed_count": site_count, "line_note": None}],
    )
    assignments = sowing_service.list_batch_carriers(db, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch_id)
    assignment_id = next(a.id for a in assignments if a.carrier.id == tray2.id)
    return {"tray": tray2, "assignment_id": assignment_id}


def transition(db: Session, tenant, user, farm, *, batch_id, configured_transition_id, effective_time):
    return crop_batch_service.transition_stage(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), configured_transition_id=configured_transition_id,
        effective_time=effective_time, reason=None,
    )


def transplant_to_plate(db: Session, tenant, user, farm, *, batch_id, source_assignment_id, effective_time, plate_suffix=None):
    plate_suffix = plate_suffix or uuid.uuid4().hex[:8]
    plate = carrier_service.register_carrier(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="cultivation_plate", code=f"PLATE-{plate_suffix}", issued_date=None,
    )
    transplant_service.record_transplant(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), effective_time=effective_time, note=None,
        source_lines=[{"source_assignment_id": source_assignment_id, "source_plant_count": 10, "discarded_plant_count": 0, "note": None}],
        destination_lines=[{"destination_carrier_id": plate.id, "assigned_plant_count": 10, "note": None}],
        allocations=[{"source_assignment_id": source_assignment_id, "destination_carrier_id": plate.id, "allocated_plant_count": 10}],
    )
    assignments = sowing_service.list_batch_carriers(db, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch_id)
    new_assignment_id = next(a.id for a in assignments if a.carrier.id == plate.id)
    return {"plate": plate, "assignment_id": new_assignment_id}


def build_greenhouse_tree(db: Session, tenant, user, farm, *, suffix=None, position_count=2):
    """Greenhouse -> Zone -> Span -> Grow Table -> N Table Positions -- the
    real leafy-green hierarchy (matches the pilot seed script and the
    hierarchy rules actually enforced by `location_service`), exercising
    subtree occupancy aggregation across four structural levels."""
    suffix = suffix or uuid.uuid4().hex[:8]
    gh = location_service.create_location(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="greenhouse",
        code=f"GH-{suffix}", name="Greenhouse", parent_location_id=None,
        greenhouse_classification="leafy_greens", occupiable=None,
    )
    zone = location_service.create_location(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="zone",
        code=f"ZA-{suffix}", name="Zone A", parent_location_id=gh.id,
        greenhouse_classification=None, occupiable=None,
    )
    span = location_service.create_location(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="span",
        code=f"SP-{suffix}", name="Span 1", parent_location_id=zone.id,
        greenhouse_classification=None, occupiable=None,
    )
    table = location_service.create_location(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="grow_table",
        code=f"GT-{suffix}", name="Grow Table", parent_location_id=span.id,
        greenhouse_classification=None, occupiable=None,
    )
    positions = location_service.bulk_generate_children(
        db, tenant_id=tenant.id, farm_id=farm.id, parent_id=table.id, actor_user_id=user.id,
        location_type_code="table_position", code_prefix=f"P{suffix}-", start=1, end=position_count, pad_width=2, name_template=None,
    )
    return {"greenhouse": gh, "zone": zone, "span": span, "table": table, "positions": positions}


def place_carrier(db: Session, tenant, user, farm, *, carrier_id, location_id, effective_time):
    return movement_service.execute_movement(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=effective_time, occupant_kind="carrier", occupant_id=carrier_id,
        destination_kind="location", destination_id=location_id, reason=None,
    )


def split(db: Session, tenant, user, farm, *, batch_id, output_codes, source_assignment_ids, effective_time):
    """`batch_derivation_service.split_batch` requires >= 2 outputs, each
    with >= 1 assignment (`ck_batch_derivation_outputs_assignment_count_positive`),
    and every active source assignment on the batch mapped exactly once --
    callers must supply >= 2 (code, assignment_id) pairs covering every
    currently-active assignment on `batch_id` (see `sow_second_carrier` for
    building a splittable two-carrier batch)."""
    outputs = [
        {"output_batch_code": code, "source_assignment_ids": [aid]}
        for code, aid in zip(output_codes, source_assignment_ids)
    ]
    return batch_derivation_service.split_batch(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), effective_time=effective_time, note=None, outputs=outputs,
    )


def merge(db: Session, tenant, user, farm, *, source_batch_ids, output_code, effective_time):
    return batch_derivation_service.merge_batches(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, source_batch_ids=source_batch_ids,
        client_command_id=uuid.uuid4(), effective_time=effective_time, note=None, output_batch_code=output_code,
    )


def batch_id_by_code(db: Session, tenant, *, code):
    from sqlalchemy import text
    return db.execute(
        text("SELECT id FROM crop_batches WHERE tenant_id = :tid AND code = :code"),
        {"tid": tenant.id, "code": code},
    ).scalar_one()


def open_hold(db: Session, tenant, user, farm, *, batch_id, reason_code="TEST_REASON", effective_time):
    return quality_hold_service.place_quality_hold(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), effective_time=effective_time,
        source_observation_event_id=None, reason_code=reason_code, reason_text="Test reason.",
    )


def release_hold(db: Session, tenant, user, farm, *, batch_id, hold_id, effective_time):
    return quality_hold_service.release_quality_hold(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id, hold_id=hold_id,
        client_command_id=uuid.uuid4(), effective_time=effective_time, release_reason="Test release.",
    )


def minutes_after(base, n):
    return base + timedelta(minutes=n)
