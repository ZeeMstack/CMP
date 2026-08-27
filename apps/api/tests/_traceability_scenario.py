"""Shared, non-collected scenario helpers for CMP-019 traceability tests.
Builds a full crop/variety/workflow/batch/seed-lot/carrier scaffold (mirrors
tests/test_batch_derivation.py's own `_build_batch_with_assignments`), plus
harvest/pack/storage/dispatch convenience wrappers. Not a test file itself
(pytest's default `test_*.py` discovery glob does not match this name)."""
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    carrier_service,
    crop_service,
    crop_batch_service,
    dispatch_service,
    farm_service,
    finished_goods_storage_service,
    grade_definition_service,
    grading_service,
    harvest_service,
    location_service,
    membership_service,
    pack_specification_service,
    packaging_unit_service,
    packing_service,
    production_system_service,
    sowing_service,
    tenant_service,
    user_service,
    workflow_service,
)
from tests._packing_scenario import require_cmp_test
from tests.conftest import ensure_seed_tray_specification


@contextmanager
def committed_connection(test_engine):
    """Yields a Session bound to a fresh connection, always closing both
    (session first, then connection) on the way out -- success or
    exception -- so a mid-scenario failure can never leave an open
    transaction behind to block a later `cleanup_traceability_scenario`
    call in the caller's own `finally`. Callers are still responsible for
    their own explicit `session.commit()` calls at whatever points their
    scenario needs them."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        yield session
    finally:
        session.close()
        conn.close()


def now():
    return datetime.now(timezone.utc)


def build_committed_tenant_farm(db: Session, *, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:10]
    tenant = tenant_service.create_tenant(db, code=f"trace-{suffix}", name="Traceability Tenant")
    user = user_service.create_user(
        db, oidc_issuer="trace", oidc_subject=suffix, email=f"trace-{suffix}@example.com", display_name="Trace User",
    )
    membership_service.add_membership(db, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
    farm = farm_service.create_farm(
        db, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Trace Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    return tenant, user, farm


def build_workflow_scaffold(db: Session, tenant, user, farm, *, suffix=None, carrier_type_code="seed_tray"):
    """Crop/variety/production-system/workflow (SEEDING -> HARVESTING ->
    COMPLETE) -- published, ready for batches. Returns a dict reusable by
    `sow_new_batch` for one or more independent batches sharing the same
    workflow/version (required for `merge_batches`, which rejects sources
    that don't share workflow, version, and current stage).

    CARRIER-CONFIG-001A: `carrier_type_code` defaults to "seed_tray"
    (unchanged behavior for every existing caller). A few downgrade-guard
    callers whose scenario needs "some sown carrier" as purely incidental
    setup (the guard under test never inspects carrier type) pass
    "grow_bag" instead, to avoid a committed carrier_specifications row
    that would otherwise make e5b8c3a72f04's own, unconditional, and
    correct guard fire before the guard they actually mean to exercise."""
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
        db, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Nursery Tray", description=None,
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
        required_carrier_type_code=carrier_type_code, is_start=True, is_terminal=False,
    )
    harvesting = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="HARVESTING", name="Harvesting", display_order=1, stage_category="harvesting",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=harvesting.id, code="ADV-1", name="Advance 1",
    )
    workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=harvesting.id, to_stage_id=complete.id, code="ADV-2", name="Advance 2",
    )
    workflow_service.publish_version(db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id)
    return {
        "crop": crop, "variety": variety, "workflow": workflow, "version": version, "transition_1": t1,
        "carrier_type_code": carrier_type_code,
    }


def sow_new_batch(db: Session, tenant, user, farm, scaffold: dict, *, carrier_count=2, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    crop, variety, workflow, t1 = scaffold["crop"], scaffold["variety"], scaffold["workflow"], scaffold["transition_1"]
    carrier_type_code = scaffold.get("carrier_type_code", "seed_tray")
    batch = crop_batch_service.create_batch(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    if carrier_type_code == "seed_tray":
        seed_tray_spec = ensure_seed_tray_specification(db, tenant_id=tenant.id, actor_user_id=user.id)
        carriers = [
            carrier_service.register_carrier(
                db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                specification_id=seed_tray_spec.id, code=f"ST-{suffix}-{n:04d}", issued_date=None,
            )
            for n in range(1, carrier_count + 1)
        ]
    else:
        carriers = [
            carrier_service.register_carrier(
                db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code=carrier_type_code, code=f"ST-{suffix}-{n:04d}", issued_date=None,
            )
            for n in range(1, carrier_count + 1)
        ]
    sowing_service.sow_batch(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=now(), note=None,
        lines=[{"carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 20, "seed_count": 20, "line_note": None} for c in carriers],
    )
    assignments = sowing_service.list_batch_carriers(db, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_by_carrier_code = {a.carrier.code: a.id for a in assignments}
    assignment_ids = [assignment_by_carrier_code[c.code] for c in carriers]
    crop_batch_service.transition_stage(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=now(), reason=None,
    )
    return {
        "batch": batch, "seed_lot": seed_lot, "carriers": carriers, "assignment_ids": assignment_ids,
        **scaffold,
    }


def build_batch_with_assignments(db: Session, tenant, user, farm, *, carrier_count=2, suffix=None, carrier_type_code="seed_tray"):
    """Convenience wrapper: a fresh workflow scaffold plus one batch sown
    under it -- the common single-batch case."""
    suffix = suffix or uuid.uuid4().hex[:8]
    scaffold = build_workflow_scaffold(db, tenant, user, farm, suffix=suffix, carrier_type_code=carrier_type_code)
    return sow_new_batch(db, tenant, user, farm, scaffold, carrier_count=carrier_count, suffix=suffix)


def harvest_all(db: Session, tenant, user, farm, *, batch_id, assignment_ids, weight_per_line=Decimal("5.000"), suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    event = harvest_service.record_harvest(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
        client_command_id=uuid.uuid4(), effective_time=now(), produce_lot_code=f"HLOT-{suffix}", note=None,
        source_lines=[
            {"batch_carrier_assignment_id": aid, "harvested_weight_kg": weight_per_line, "whole_unit_count": None, "note": None}
            for aid in assignment_ids
        ],
    )
    lot_id = db.execute(
        __import__("sqlalchemy").text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": event.id}
    ).scalar_one()
    return event, lot_id


def _build_packing_scaffold(db: Session, tenant, user, farm, *, crop_id, suffix):
    """POSTHARVEST-OPS-001E: the minimal Grading+PackSpec scaffold `pack_lot`/
    `pack_multi` need to route through the new GPL-based Packing contract
    -- a packing hall, one active GradeDefinitionVersion, one active
    PackagingUnit, and one active PackSpecificationVersion (variety_id=None,
    so it applies regardless of the scenario's own concrete variety)."""
    hall = location_service.create_location(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="packing_hall",
        code=f"pack-hall-{suffix}", name="Processing Hall", parent_location_id=None,
        greenhouse_classification=None, occupiable=False,
    )
    grade_definition = grade_definition_service.register_grade_definition(
        db, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"grade-{suffix}", name="Standard", crop_id=crop_id, variety_id=None, description=None,
    )
    grade_version = grade_definition_service.create_draft_version(
        db, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        grade_definition_id=grade_definition.id, spec_notes=None,
    )
    grade_definition_service.activate_version(
        db, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        grade_definition_id=grade_definition.id, version_id=grade_version.id,
        effective_time=now() - timedelta(days=30),
    )
    packaging_unit = packaging_unit_service.register_packaging_unit(
        db, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"unit-{suffix}", name="Carton",
    )
    pack_spec = pack_specification_service.register_pack_specification(
        db, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"spec-{suffix}", name="Standard Pack", crop_id=crop_id, variety_id=None, customer_reference=None,
    )
    pack_spec_version = pack_specification_service.create_draft_version(
        db, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        pack_specification_id=pack_spec.id, grade_definition_version_id=None,
        packaging_unit_id=packaging_unit.id, nominal_net_weight_kg=Decimal("1.000"), whole_units_per_pack=None,
        spec_notes=None,
    )
    pack_specification_service.activate_version(
        db, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        pack_specification_id=pack_spec.id, version_id=pack_spec_version.id,
        effective_time=now() - timedelta(days=30),
    )
    return {
        "packing_hall_location_id": hall.id, "grade_version_id": grade_version.id,
        "pack_specification_version_id": pack_spec_version.id,
    }


def _grade_entire_lot(db: Session, tenant, user, farm, *, produce_lot_id, weight, scaffold, suffix):
    """Grades the FULL requested `weight` from `produce_lot_id` into
    exactly one GradedProduceLot (no rejection/loss/sample/remainder) and
    returns its id -- the transparent intermediate step `pack_lot`/
    `pack_multi` insert so their own callers can keep saying "pack this
    HPL's material" without needing to know Packing no longer accepts an
    HPL id directly."""
    event = grading_service.record_grading(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_harvested_produce_lot_id=produce_lot_id,
        processing_hall_location_id=scaffold["packing_hall_location_id"], effective_time=now(), note=None,
        input_presented_weight_kg=weight, input_presented_whole_unit_count=None,
        rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
        loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
        sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
        remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=None,
        outputs=[
            {
                "grade_definition_version_id": scaffold["grade_version_id"], "code": f"GPL-{suffix}",
                "output_weight_kg": weight, "output_whole_unit_count": None,
            }
        ],
    )
    return db.execute(
        text("SELECT id FROM graded_produce_lots WHERE grading_event_id = :eid"), {"eid": event.id}
    ).scalar_one()


def pack_lot(db: Session, tenant, user, farm, *, produce_lot_id, weight=Decimal("5.000"), package_count=5, suffix=None):
    """POSTHARVEST-OPS-001E: Packing no longer accepts a HarvestedProduceLot
    directly -- this helper transparently grades the full `weight` from
    `produce_lot_id` into one GradedProduceLot first, then packs that GPL.
    External signature/behavior (HPL balance debited by `weight`, one FG
    lot of `weight`/`package_count` created) is unchanged for every one of
    this helper's many existing callers."""
    suffix = suffix or uuid.uuid4().hex[:8]
    crop_id, variety_id = db.execute(
        text("SELECT crop_id, variety_id FROM harvested_produce_lots WHERE id = :id"), {"id": produce_lot_id}
    ).one()
    scaffold = _build_packing_scaffold(db, tenant, user, farm, crop_id=crop_id, suffix=suffix)
    gpl_id = _grade_entire_lot(
        db, tenant, user, farm, produce_lot_id=produce_lot_id, weight=weight, scaffold=scaffold, suffix=suffix
    )
    event = packing_service.record_packing(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        pack_specification_version_id=scaffold["pack_specification_version_id"], effective_time=now(),
        finished_goods_lot_code=f"FG-{suffix}", package_count=package_count,
        packed_output_weight_kg=weight, process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"),
        note=None,
        input_lines=[{"graded_produce_lot_id": gpl_id, "consumed_weight_kg": weight, "consumed_whole_unit_count": None, "note": None}],
    )
    detail = packing_service.get_packing_event(db, tenant_id=tenant.id, farm_id=farm.id, packing_event_id=event.id)
    return detail.finished_goods_lot.id, event.id


def pack_multi(db: Session, tenant, user, farm, *, produce_lot_ids_and_weights: list[tuple], package_count=5, suffix=None):
    """POSTHARVEST-OPS-001E: grades each source HPL's own full requested
    weight into its own GradedProduceLot (same shared GradeDefinitionVersion
    across all of them, so the resulting GPLs satisfy Packing's exact-
    grade-match requirement), then packs every resulting GPL together into
    one FinishedGoodsLot -- preserves this helper's own "one FG lot from
    multiple HPL sources" external contract."""
    suffix = suffix or uuid.uuid4().hex[:8]
    total = sum(w for _, w in produce_lot_ids_and_weights)
    scaffold = None
    gpl_lines = []
    for idx, (lot_id, w) in enumerate(produce_lot_ids_and_weights):
        crop_id, variety_id = db.execute(
            text("SELECT crop_id, variety_id FROM harvested_produce_lots WHERE id = :id"), {"id": lot_id}
        ).one()
        if scaffold is None:
            scaffold = _build_packing_scaffold(db, tenant, user, farm, crop_id=crop_id, suffix=suffix)
        gpl_id = _grade_entire_lot(
            db, tenant, user, farm, produce_lot_id=lot_id, weight=w, scaffold=scaffold, suffix=f"{suffix}-{idx}"
        )
        gpl_lines.append((gpl_id, w))
    event = packing_service.record_packing(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        pack_specification_version_id=scaffold["pack_specification_version_id"], effective_time=now(),
        finished_goods_lot_code=f"FG-{suffix}", package_count=package_count,
        packed_output_weight_kg=total, process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"),
        note=None,
        input_lines=[
            {"graded_produce_lot_id": gid, "consumed_weight_kg": w, "consumed_whole_unit_count": None, "note": None}
            for gid, w in gpl_lines
        ],
    )
    detail = packing_service.get_packing_event(db, tenant_id=tenant.id, farm_id=farm.id, packing_event_id=event.id)
    return detail.finished_goods_lot.id, event.id


def create_cold_store_position(db: Session, tenant, user, farm, *, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    cold_store = location_service.create_location(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="cold_store",
        code=f"CS-{suffix}", name="Cold Store", parent_location_id=None, greenhouse_classification=None, occupiable=None,
    )
    return location_service.create_location(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="cold_store_position",
        code=f"POS-{suffix}", name="Position", parent_location_id=cold_store.id, greenhouse_classification=None, occupiable=None,
    )


def place(db: Session, tenant, user, farm, *, finished_goods_lot_id, destination_location_id, weight=Decimal("2.000"), count=2):
    return finished_goods_storage_service.record_movement(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=now(), finished_goods_lot_id=finished_goods_lot_id, movement_kind="place",
        source_location_id=None, destination_location_id=destination_location_id, moved_weight_kg=weight,
        moved_package_count=count, note=None,
    )


def dispatch(db: Session, tenant, user, farm, *, finished_goods_lot_id, weight=Decimal("1.000"), count=1, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    return dispatch_service.record_dispatch(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=now(), code=f"DISP-{suffix}", external_reference=None, note=None,
        lines=[{"finished_goods_lot_id": finished_goods_lot_id, "dispatched_weight_kg": weight, "dispatched_package_count": count}],
    )


def cleanup_traceability_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    """Like `_packing_scenario.cleanup_scenario`, extended with the
    batch-derivation (split/merge) tables that scenario never needed to
    know about."""
    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM finished_goods_ledger_entries WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM finished_goods_storage_movements WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM dispatch_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM dispatch_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM packing_input_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM finished_goods_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM packing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        # POSTHARVEST-OPS-001E: pack_lot/pack_multi now transparently grade
        # each source HPL first and pin a fresh PackSpecificationVersion --
        # existence-guarded (`to_regclass`) so this same cleanup keeps
        # working for a downgrade-guard test that runs it while cmp_test is
        # deliberately downgraded below the migration that creates these.
        for table in ("graded_produce_lot_ledger_entries", "graded_produce_lots", "grading_events"):
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        for table in (
            "pack_specification_versions", "pack_specifications", "packaging_units",
            "grade_definition_versions", "grade_definitions",
        ):
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        # HARVEST-OPS-001: harvest_population_events/harvest_source_line_
        # corrections are new to this shared cleanup -- must precede
        # harvest_source_lines/harvested_produce_lots/harvest_events and
        # batch_carrier_assignments below (all four reference at least one
        # of them). Existence-guarded for the same reason seedling_entries
        # above is: a downgrade-guard test may call this cleanup while
        # cmp_test is deliberately downgraded below the migration that
        # creates these two tables.
        for table in ("harvest_population_events", "harvest_source_line_corrections"):
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvested_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM quality_hold_releases WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM quality_holds WHERE tenant_id = :tid"), {"tid": tenant_id})
        # NURSERY-OPS-003A: seedling_entries/germination_outcome_snapshots/
        # observation_events are new to this shared cleanup -- earlier
        # scenarios never committed real (test_engine-backed) Germination-
        # outcome or Seedling-entry data. seedling_entries references
        # germination_outcome_snapshots and movements; germination_outcome_
        # snapshots (and the legacy germination_checks) reference
        # observation_events -- all three must precede batch_carrier_
        # assignments/movements/crop_batches below. Existence-guarded
        # (`to_regclass`) because some downgrade-guard tests (e.g.
        # test_recall_downgrade_guard.py) call this cleanup while cmp_test
        # is deliberately downgraded below the migration that creates
        # seedling_entries/germination_outcome_snapshots -- a bare DELETE
        # against a table that doesn't exist at that schema revision would
        # raise UndefinedTable and mask the test's own assertion.
        # NURSERY-OPS-004A: seedling_source_checkpoints is new to this
        # shared cleanup -- 004A's own transplant concurrency tests are the
        # first scenarios to commit real (test_engine-backed) checkpoint
        # rows. Must precede BOTH seedling_entries (below) and
        # transplant_source_lines (further below) -- it references both.
        if conn.execute(text("SELECT to_regclass('seedling_source_checkpoints')")).scalar() is not None:
            conn.execute(text("DELETE FROM seedling_source_checkpoints WHERE tenant_id = :tid"), {"tid": tenant_id})
        # NURSERY-OPS-005A: batch_carrier_population_checkpoints is new to
        # this shared cleanup -- 005A's own tests are the first scenarios to
        # commit real (test_engine-backed) chained Nursery Plate population
        # checkpoint rows. References BOTH batch_carrier_assignments and
        # transplant_source_lines, so it must precede both (deleted here,
        # ahead of the transplant_allocations/transplant_source_lines block
        # below, mirroring where seedling_source_checkpoints sits relative
        # to seedling_entries above it).
        if conn.execute(text("SELECT to_regclass('batch_carrier_population_checkpoints')")).scalar() is not None:
            conn.execute(
                text("DELETE FROM batch_carrier_population_checkpoints WHERE tenant_id = :tid"), {"tid": tenant_id}
            )
        # NURSERY-OPS-003B: seedling_disposition_events/_commands are new to
        # this shared cleanup -- 003B's own concurrency tests are the first
        # scenarios to commit real (test_engine-backed) disposition rows.
        # Without these deletes, leftover rows survive into later tests in
        # the same session and trip the NURSERY-OPS-003B downgrade guard
        # (which counts live seedling_disposition_events rows) for every
        # subsequent migration-downgrade test. Must precede seedling_entries
        # below (events/commands both reference it).
        for table in ("seedling_disposition_events", "seedling_disposition_commands"):
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        # LEAFY-OPS-001: production_disposition_events/_commands are new to
        # this shared cleanup, mirroring seedling_disposition_events/
        # _commands immediately above exactly -- must precede batch_carrier_
        # assignments below (both reference it).
        for table in ("production_disposition_events", "production_disposition_commands"):
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        for table in (
            "seedling_entries", "germination_outcome_snapshots", "germination_checks",
            "observation_values", "observation_events",
        ):
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_event_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        # CMP-FE-002A: transplant_* tables are new to this shared cleanup --
        # earlier CMP-019 scenarios never called transplant_service. Without
        # these deletes, transplant_events/lines/allocations survive the
        # (session_replication_role=replica, FK-checks-disabled)
        # batch_carrier_assignments delete below as orphaned rows, which
        # then fail test_migrations.py's CMP-011 downgrade guard (it counts
        # live transplant rows, oblivious to orphaning). Allocations must
        # precede source/destination lines; both must precede events; all
        # three must precede batch_carrier_assignments.
        conn.execute(text("DELETE FROM transplant_allocations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_destination_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_assignment_transfers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_carrier_assignments WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM seed_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        # CMP-FE-002A: occupancies/movements are new to this shared cleanup --
        # earlier CMP-019 scenarios never created crop-batch-carrier
        # occupancy (only finished_goods_storage_movements, already handled
        # above). occupancies must precede movements (opened_by_movement_id
        # FK); both must precede carriers/locations.
        conn.execute(text("DELETE FROM occupancies WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM movements WHERE tenant_id = :tid"), {"tid": tenant_id})
        if conn.execute(text("SELECT to_regclass('carrier_specifications')")).scalar() is not None:
            conn.execute(text("DELETE FROM carrier_specifications WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_runs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_derivation_sources WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_derivation_outputs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crop_batches WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_derivation_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_stages WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_versions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflows WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM production_systems WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM varieties WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crops WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        # NURSERY-OPS-004A: assets/asset_positions were a genuine, pre-
        # existing gap in this shared cleanup -- any Nursery scenario that
        # registers a germination trolley (asset) + positions (e.g.
        # test_seedling_disposition.py's own concurrency tests, and now
        # NURSERY-OPS-004A's transplant concurrency tests) leaked these
        # rows into cmp_test with no downstream check ever catching it,
        # unlike the workflow_stages leak that broke a downgrade guard.
        # asset_positions must precede assets (FK).
        conn.execute(
            text("DELETE FROM asset_positions WHERE asset_id IN (SELECT id FROM assets WHERE tenant_id = :tid)"),
            {"tid": tenant_id},
        )
        conn.execute(text("DELETE FROM assets WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM locations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    except Exception:
        trans.rollback()
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        raise
    else:
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()
