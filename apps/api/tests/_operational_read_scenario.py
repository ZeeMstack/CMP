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
    SEEDING stage requires `cultivation_plate` -- a carrier type directly
    compatible with a location (`table_position`, and, since DOMAIN-FARM-001,
    `grow_table` too -- see that migration's own compatibility-rule addition)
    -- so `sow_batch`'s own carrier can be placed directly, with no
    intervening transplant. Used by placement-facts and subtree-occupancy
    tests, which care about location occupancy, not sowing-origin/transplant
    semantics."""
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


def build_harvest_ready_workflow_scaffold(db: Session, tenant, user, farm, *, suffix=None):
    """CMP-FE-002A.1: SEEDING -> GROWING -> `Q7`/"Zulu Phase" (stage_category
    `harvest_ready`) -> COMPLETE. The harvest_ready-category stage is
    deliberately given a code/name with no hint of "harvest" in it, so a
    test built on this scaffold proves `stage_category` is read from the
    authoritative `workflow_stages.stage_category` column, never inferred
    from stage name/code string-matching."""
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
    growing = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="GROWING", name="Growing", display_order=1, stage_category="production",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    ready = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="Q7", name="Zulu Phase", display_order=2, stage_category="harvest_ready",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=3, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t_seed_to_growing = workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=growing.id, code="ADV-1", name="Advance 1",
    )
    t_growing_to_ready = workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=growing.id, to_stage_id=ready.id, code="ADV-2", name="Advance 2",
    )
    t_ready_to_complete = workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=ready.id, to_stage_id=complete.id, code="ADV-3", name="Advance 3",
    )
    workflow_service.publish_version(db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id)
    return {
        "crop": crop, "variety": variety, "workflow": workflow, "version": version,
        "t_seed_to_growing": t_seed_to_growing, "t_growing_to_ready": t_growing_to_ready,
        "t_ready_to_complete": t_ready_to_complete,
    }


def sow_batch(
    db: Session, tenant, user, farm, scaffold: dict, *, effective_time, code_suffix=None, site_count=10,
    carrier_type_code="seed_tray", carrier_count=1,
):
    """NURSERY-OPS-001: a Crop Batch may have at most one Sowing Event,
    ever (`ux_sowing_events_batch_id`) -- a scenario needing >1 carrier on
    one batch (e.g. `batch_derivation_service.split_batch` requires >= 2
    outputs, each with >= 1 assignment) now gets them all from this ONE
    call (`carrier_count`), not a second, separate sowing command. Returns
    both the original singular `tray`/`assignment_id` (the first carrier,
    for every existing single-carrier caller) and the plural
    `trays`/`assignment_ids` (for callers that need more than one)."""
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
    trays = [
        carrier_service.register_carrier(
            db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code=carrier_type_code, code=f"TRAY-{code_suffix}-{n}", issued_date=None,
        )
        for n in range(carrier_count)
    ]
    sowing_service.sow_batch(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=effective_time, note=None,
        lines=[
            {"carrier_id": tray.id, "seed_lot_id": seed_lot.id, "sown_site_count": site_count, "seed_count": site_count, "line_note": None}
            for tray in trays
        ],
    )
    assignments = sowing_service.list_batch_carriers(db, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_by_carrier = {a.carrier.id: a.id for a in assignments}
    assignment_ids = [assignment_by_carrier[tray.id] for tray in trays]
    return {
        "batch": batch, "seed_lot": seed_lot, "tray": trays[0], "assignment_id": assignment_ids[0],
        "trays": trays, "assignment_ids": assignment_ids,
    }


def transition(db: Session, tenant, user, farm, *, batch_id, configured_transition_id, effective_time):
    return crop_batch_service.transition_stage(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), configured_transition_id=configured_transition_id,
        effective_time=effective_time, reason=None,
    )


def build_greenhouse_tree(db: Session, tenant, user, farm, *, suffix=None, position_count=2):
    """Greenhouse -> Zone -> Span -> N sibling Grow Tables -- the
    authoritative Leafy Greens hierarchy per DOMAIN-FARM-001: production
    Cultivation Plates are Carriers, not Locations, so the Table itself is
    the occupiable leaf -- there is no further numbered "table position"
    level under it. Exercises subtree occupancy aggregation across three
    structural ancestor levels (greenhouse/zone/span) with N occupiable
    leaves (each Grow Table can hold at most one occupant in this ticket's
    scope, since capacity-aware occupancy, DOMAIN-FARM-002, does not exist
    yet -- `occupiable=True` is set per-instance, an already-supported
    override, not a change to `grow_table`'s own type default)."""
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
    positions = [
        location_service.create_location(
            db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="grow_table",
            code=f"GT-{suffix}-{n:02d}", name=f"Grow Table {n}", parent_location_id=span.id,
            greenhouse_classification=None, occupiable=True,
        )
        for n in range(1, position_count + 1)
    ]
    return {"greenhouse": gh, "zone": zone, "span": span, "positions": positions}


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
