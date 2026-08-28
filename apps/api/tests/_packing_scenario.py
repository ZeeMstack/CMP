"""Shared, non-collected scenario builder for CMP-015/POSTHARVEST-OPS-001E
packing tests. Builds a committed tenant/farm/crop/variety/workflow/batch
with two independent harvested produce lots of the same crop/variety (same
committed-connection pattern as test_produce_lot_ledger_concurrency.py's
own `_build_committed_scenario`), plus the identical `cmp_test`-guarded
`session_replication_role` cleanup used across CMP-013/014's own test
files. Not a test file itself (pytest's default `test_*.py` discovery
glob does not match this name).

POSTHARVEST-OPS-001E: Packing no longer accepts a HarvestedProduceLot
directly -- `build_committed_scenario` now also grades each of lot_a/lot_b's
FULL weight/count into its own GradedProduceLot (same shared
GradeDefinitionVersion, so they satisfy Packing's exact-grade-match rule)
and activates one PackSpecificationVersion (variety_id=None, so it applies
regardless of the scenario's own concrete variety), returned as
`gpl_a_id`/`gpl_b_id`/`pack_specification_version_id`/`grade_definition_
version_id`/`packaging_unit_id`. `lot_a_id`/`lot_b_id` still refer to the
underlying HarvestedProduceLot (still a real entity, just no longer
Packing's own input) for callers that need to assert HPL-level ledger/
balance is untouched by Packing post-001E."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    farm_service,
    grade_definition_service,
    grading_service,
    harvest_service,
    location_service,
    membership_service,
    packaging_unit_service,
    pack_specification_service,
    production_system_service,
    sowing_service,
    tenant_service,
    user_service,
    workflow_service,
)
from tests.conftest import ensure_seed_tray_specification


def now():
    return datetime.now(timezone.utc)


def build_packing_scaffold(session: Session, tenant, user, farm, *, crop_id, suffix):
    """POSTHARVEST-OPS-001E: the minimal Grading+PackSpec scaffold needed to
    route a HarvestedProduceLot through the new GPL-based Packing contract
    -- a packing hall, one active GradeDefinitionVersion, one active
    PackagingUnit, and one active PackSpecificationVersion (variety_id=None,
    so it applies regardless of the scenario's own concrete variety).
    Mirrors `tests._traceability_scenario._build_packing_scaffold` exactly."""
    hall = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="packing_hall",
        code=f"pack-hall-{suffix}", name="Processing Hall", parent_location_id=None,
        greenhouse_classification=None, occupiable=False,
    )
    grade_definition = grade_definition_service.register_grade_definition(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"grade-{suffix}", name="Standard", crop_id=crop_id, variety_id=None, description=None,
    )
    grade_version = grade_definition_service.create_draft_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        grade_definition_id=grade_definition.id, spec_notes=None,
    )
    grade_definition_service.activate_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        grade_definition_id=grade_definition.id, version_id=grade_version.id,
        effective_time=now() - timedelta(days=30),
    )
    packaging_unit = packaging_unit_service.register_packaging_unit(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"unit-{suffix}", name="Carton",
    )
    pack_spec = pack_specification_service.register_pack_specification(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"spec-{suffix}", name="Standard Pack", crop_id=crop_id, variety_id=None, customer_reference=None,
    )
    pack_spec_version = pack_specification_service.create_draft_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        pack_specification_id=pack_spec.id, grade_definition_version_id=None,
        packaging_unit_id=packaging_unit.id, nominal_net_weight_kg=Decimal("1.000"), whole_units_per_pack=None,
        spec_notes=None,
    )
    pack_specification_service.activate_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        pack_specification_id=pack_spec.id, version_id=pack_spec_version.id,
        effective_time=now() - timedelta(days=30),
    )
    return {
        "packing_hall_location_id": hall.id, "grade_definition_version_id": grade_version.id,
        "packaging_unit_id": packaging_unit.id, "pack_specification_version_id": pack_spec_version.id,
    }


def grade_entire_lot(session: Session, tenant, user, farm, *, produce_lot_id, weight, count, scaffold, suffix):
    """Grades the FULL requested `weight`/`count` from `produce_lot_id` into
    exactly one GradedProduceLot (no rejection/loss/sample/remainder) and
    returns its id."""
    event = grading_service.record_grading(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_harvested_produce_lot_id=produce_lot_id,
        processing_hall_location_id=scaffold["packing_hall_location_id"], effective_time=now(), note=None,
        input_presented_weight_kg=weight, input_presented_whole_unit_count=count,
        rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=(0 if count is not None else None),
        loss_weight_kg=Decimal("0"), loss_whole_unit_count=(0 if count is not None else None),
        sample_weight_kg=Decimal("0"), sample_whole_unit_count=(0 if count is not None else None),
        remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=(0 if count is not None else None),
        outputs=[
            {
                "grade_definition_version_id": scaffold["grade_definition_version_id"], "code": f"GPL-{suffix}",
                "output_weight_kg": weight, "output_whole_unit_count": count,
            }
        ],
    )
    return session.execute(
        text("SELECT id FROM graded_produce_lots WHERE grading_event_id = :eid"), {"eid": event.id}
    ).scalar_one()


def build_committed_scenario(test_engine, *, carrier_count: int = 2, lot_a_weight="10.000", lot_a_count=40,
                              lot_b_weight="5.000", lot_b_count=20, carrier_type_code="seed_tray",
                              grade_and_pack_spec: bool = True):
    """Returns a dict with tenant_id/user_id/farm_id/batch_id/assignment_ids
    plus lot_a_id/lot_b_id (two harvested produce lots, same crop/variety,
    same batch, independent harvest events) and their weights/counts.

    CARRIER-CONFIG-001A: `carrier_type_code` defaults to "seed_tray"
    (unchanged behavior for every existing caller). A handful of downgrade-
    guard callers, whose scenario needs "some sown carrier" as purely
    incidental setup for a domain (packing/dispatch/ledger/storage/
    traceability) that never inspects carrier type, pass "grow_bag"
    instead -- avoiding a committed carrier_specifications row so their
    own downgrade attempt exercises the guard they actually target instead
    of being masked by e5b8c3a72f04's unconditional, and correct, global
    guard on any live specification."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"pack-{suffix}", name="Packing Tenant")
    user = user_service.create_user(
        session, oidc_issuer="pack", oidc_subject=suffix, email=f"pack-{suffix}@example.com", display_name="Pack User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Pack Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"var-{suffix}",
        name="Variety", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ps-{suffix}", name="System", description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"wf-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code=carrier_type_code, is_start=True, is_terminal=False,
    )
    harvesting = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="HARVESTING", name="Harvesting", display_order=1, stage_category="harvesting",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    t1 = workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=harvesting.id, code="ADV-1", name="Advance 1",
    )
    workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=harvesting.id, to_stage_id=complete.id, code="ADV-2", name="Advance 2",
    )
    workflow_service.publish_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"batch-{suffix}", workflow_id=workflow.id, effective_time=now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"lot-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    if carrier_type_code == "seed_tray":
        seed_tray_spec = ensure_seed_tray_specification(session, tenant_id=tenant.id, actor_user_id=user.id)
        carriers = [
            carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                specification_id=seed_tray_spec.id, code=f"tray-{suffix}-{n}", issued_date=None,
            )
            for n in range(carrier_count)
        ]
    else:
        carriers = [
            carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code=carrier_type_code, code=f"tray-{suffix}-{n}", issued_date=None,
            )
            for n in range(carrier_count)
        ]
    sowing_service.sow_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=now(), note=None,
        lines=[
            {"carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 50, "seed_count": 50, "line_note": None}
            for c in carriers
        ],
    )
    assignments = sowing_service.list_batch_carriers(session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_by_carrier = {a.carrier.code: a.id for a in assignments}
    assignment_ids = [assignment_by_carrier[c.code] for c in carriers]

    crop_batch_service.transition_stage(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=now(), reason=None,
    )

    harvest_a = harvest_service.record_harvest(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=now(), produce_lot_code=f"LOTA-{suffix}", note=None,
        source_lines=[
            {
                "batch_carrier_assignment_id": assignment_ids[0], "harvested_weight_kg": Decimal(lot_a_weight),
                "whole_unit_count": lot_a_count, "note": None,
            }
        ],
    )
    harvest_b = harvest_service.record_harvest(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=now(), produce_lot_code=f"LOTB-{suffix}", note=None,
        source_lines=[
            {
                "batch_carrier_assignment_id": assignment_ids[1], "harvested_weight_kg": Decimal(lot_b_weight),
                "whole_unit_count": lot_b_count, "note": None,
            }
        ],
    )
    lot_a_id = session.execute(
        text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": harvest_a.id}
    ).scalar_one()
    lot_b_id = session.execute(
        text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": harvest_b.id}
    ).scalar_one()

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": batch.id,
        "assignment_ids": assignment_ids, "suffix": suffix,
        "harvest_a_id": harvest_a.id, "harvest_b_id": harvest_b.id, "lot_a_id": lot_a_id, "lot_b_id": lot_b_id,
        "lot_a_weight": Decimal(lot_a_weight), "lot_a_count": lot_a_count,
        "lot_b_weight": Decimal(lot_b_weight), "lot_b_count": lot_b_count,
    }

    if grade_and_pack_spec:
        # POSTHARVEST-OPS-001E: grade each of lot_a/lot_b's FULL weight/count
        # into its own GradedProduceLot (same shared GradeDefinitionVersion,
        # so they satisfy Packing's exact-grade-match rule) and activate one
        # PackSpecificationVersion -- opted OUT of by callers (e.g. the
        # downgrade-guard scenario) that need the bare pre-001E HPL-only
        # scenario against a deliberately downgraded schema.
        scaffold = build_packing_scaffold(session, tenant, user, farm, crop_id=crop.id, suffix=suffix)
        gpl_a_id = grade_entire_lot(
            session, tenant, user, farm, produce_lot_id=lot_a_id, weight=Decimal(lot_a_weight), count=lot_a_count,
            scaffold=scaffold, suffix=f"{suffix}-a",
        )
        gpl_b_id = grade_entire_lot(
            session, tenant, user, farm, produce_lot_id=lot_b_id, weight=Decimal(lot_b_weight), count=lot_b_count,
            scaffold=scaffold, suffix=f"{suffix}-b",
        )
        result.update(
            {
                "gpl_a_id": gpl_a_id, "gpl_b_id": gpl_b_id,
                "packing_hall_location_id": scaffold["packing_hall_location_id"],
                "grade_definition_version_id": scaffold["grade_definition_version_id"],
                "packaging_unit_id": scaffold["packaging_unit_id"],
                "pack_specification_version_id": scaffold["pack_specification_version_id"],
            }
        )

    session.close()
    conn.close()
    return result


def require_cmp_test(test_engine) -> None:
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup (session_replication_role) against "
            f"database {current_db!r}; this cleanup is only permitted against 'cmp_test'"
        )


def cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        # POSTHARVEST-OPS-001H: reversal tables, existence-guarded the same
        # way as every other post-CMP-013 table in this cleanup so it keeps
        # working for the downgrade-guard scenario that runs it while
        # cmp_test is deliberately downgraded below this ticket's migration.
        for table in ("packing_reversal_inputs", "packing_reversal_events", "grading_reversal_outputs", "grading_reversal_events"):
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM finished_goods_ledger_entries WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM finished_goods_storage_movements WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM dispatch_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM dispatch_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM packing_input_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM finished_goods_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM packing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        # POSTHARVEST-OPS-001E: build_committed_scenario now transparently
        # grades each source lot and activates a fresh PackSpecificationVersion
        # -- existence-guarded (`to_regclass`) so this same cleanup keeps
        # working for the downgrade-guard scenario that runs it while
        # cmp_test is deliberately downgraded below the migration that
        # creates these tables.
        for table in ("graded_produce_lot_ledger_entries", "graded_produce_lots", "grading_events"):
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        for table in (
            "pack_specification_versions", "pack_specifications", "packaging_units",
            "grade_definition_versions", "grade_definitions",
        ):
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvested_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM quality_hold_releases WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM quality_holds WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_event_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_carrier_assignments WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM seed_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        if conn.execute(text("SELECT to_regclass('carrier_specifications')")).scalar() is not None:
            conn.execute(text("DELETE FROM carrier_specifications WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_runs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crop_batches WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_stages WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_versions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflows WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM production_systems WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM varieties WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crops WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
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
