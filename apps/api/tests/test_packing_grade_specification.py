"""POSTHARVEST-OPS-001E: GRADE/PACKSPEC-category coverage not already
exercised by the rewritten legacy packing suite -- PackSpecificationVersion
effective-time gating independent of current DRAFT/ACTIVE/RETIRED status,
crop/variety/grade-version pinning, and exact crop/variety/grade-version
equality among a packing event's own GPL inputs (including NULL variety
semantics). Builds directly on `tests._packing_scenario`'s own
`build_packing_scaffold`/`grade_entire_lot` helpers rather than
`build_committed_scenario`'s default scaffold, since every test here needs
its own precisely-controlled PackSpecificationVersion lifecycle timeline."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
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
    packing_service,
    production_system_service,
    sowing_service,
    tenant_service,
    user_service,
    workflow_service,
)
from app.services.errors import (
    PackingCropVarietyMismatchError,
    PackingGradeVersionMismatchError,
    PackSpecificationVersionNotUsableError,
)
from tests._packing_scenario import cleanup_scenario, now, require_cmp_test
from tests.conftest import ensure_seed_tray_specification


def _build_tenant_farm(session, *, suffix):
    tenant = tenant_service.create_tenant(session, code=f"gps-{suffix}", name="Grade/PackSpec Tenant")
    user = user_service.create_user(
        session, oidc_issuer="gps", oidc_subject=suffix, email=f"gps-{suffix}@example.com", display_name="GPS User",
    )
    membership_service.add_membership(session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="GPS Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    return tenant, user, farm


def _build_workflow_and_batch(session, tenant, user, farm, *, crop, variety, suffix, setup_time):
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ps-{suffix}", name="System", description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id if variety else None,
        production_system_id=ps.id, code=f"wf-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id)
    seeding = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
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
    workflow_service.publish_version(session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id)
    batch = crop_batch_service.create_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"batch-{suffix}", workflow_id=workflow.id, effective_time=setup_time,
    )
    return batch, t1


def _harvest_one(session, tenant, user, farm, *, crop, variety, suffix, weight, t_harvest):
    # sowing_service requires the batch's workflow to carry a real variety
    # (never None), and requires the seed lot's own variety_id to equal
    # that same workflow variety -- so HPL/GPL.variety_id, derived from the
    # workflow, is never reachably NULL via this real harvest path.
    #
    # The whole batch/sow/transition setup must happen at or before
    # t_harvest (harvest_service rejects an effective_time preceding the
    # batch's creation or the active stage run's entry) -- callers here
    # often need t_harvest deep in the past for PackSpec window testing, so
    # "now" cannot be used for setup.
    setup_time = t_harvest - timedelta(minutes=30)
    batch, t1 = _build_workflow_and_batch(session, tenant, user, farm, crop=crop, variety=variety, suffix=suffix, setup_time=setup_time)
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"lot-{suffix}", supplier_name=None,
        supplier_lot_reference=None, received_date=None, expiry_date=None,
    )
    seed_tray_spec = ensure_seed_tray_specification(session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier = carrier_service.register_carrier(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, specification_id=seed_tray_spec.id,
        code=f"tray-{suffix}", issued_date=None,
    )
    sowing_service.sow_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=setup_time, note=None,
        lines=[{"carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": 20, "seed_count": 20, "line_note": None}],
    )
    assignment = sowing_service.list_batch_carriers(session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)[0]
    crop_batch_service.transition_stage(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=setup_time, reason=None,
    )
    harvest = harvest_service.record_harvest(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=t_harvest, produce_lot_code=f"HLOT-{suffix}", note=None,
        source_lines=[{"batch_carrier_assignment_id": assignment.id, "harvested_weight_kg": weight, "whole_unit_count": None, "note": None}],
    )
    return session.execute(
        text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": harvest.id}
    ).scalar_one()


def _grade_one(session, tenant, user, farm, *, hpl_id, weight, grade_version_id, hall_id, t_grade, suffix):
    event = grading_service.record_grading(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_harvested_produce_lot_id=hpl_id, processing_hall_location_id=hall_id, effective_time=t_grade,
        note=None, input_presented_weight_kg=weight, input_presented_whole_unit_count=None,
        rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
        loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
        sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
        remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=None,
        outputs=[{"grade_definition_version_id": grade_version_id, "code": f"GPL-{suffix}", "output_weight_kg": weight, "output_whole_unit_count": None}],
    )
    return session.execute(
        text("SELECT id FROM graded_produce_lots WHERE grading_event_id = :eid"), {"eid": event.id}
    ).scalar_one()


def _active_grade_version(session, tenant, user, *, crop, variety_id, suffix):
    grade_def = grade_definition_service.register_grade_definition(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"grade-{suffix}", name="Standard", crop_id=crop.id, variety_id=variety_id, description=None,
    )
    version = grade_definition_service.create_draft_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        grade_definition_id=grade_def.id, spec_notes=None,
    )
    grade_definition_service.activate_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        grade_definition_id=grade_def.id, version_id=version.id, effective_time=now() - timedelta(days=30),
    )
    return version.id


def _pack_spec_version(session, tenant, user, *, crop, variety_id, grade_definition_version_id, suffix):
    packaging_unit = packaging_unit_service.register_packaging_unit(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"unit-{suffix}", name="Carton",
    )
    pack_spec = pack_specification_service.register_pack_specification(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"spec-{suffix}", name="Spec", crop_id=crop.id, variety_id=variety_id, customer_reference=None,
    )
    return pack_spec, packaging_unit


def _draft_version(session, tenant, user, *, pack_spec, packaging_unit, grade_definition_version_id=None):
    return pack_specification_service.create_draft_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        pack_specification_id=pack_spec.id, grade_definition_version_id=grade_definition_version_id,
        packaging_unit_id=packaging_unit.id, nominal_net_weight_kg=Decimal("1.000"), whole_units_per_pack=None,
        spec_notes=None,
    )


def _activate(session, tenant, user, *, pack_spec, version, effective_time):
    return pack_specification_service.activate_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        pack_specification_id=pack_spec.id, version_id=version.id, effective_time=effective_time,
    )


def _retire(session, tenant, user, *, pack_spec, version, effective_time):
    return pack_specification_service.retire_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        pack_specification_id=pack_spec.id, version_id=version.id, effective_time=effective_time,
    )


def _hall(session, tenant, user, farm, *, suffix):
    return location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="packing_hall",
        code=f"hall-{suffix}", name="Hall", parent_location_id=None, greenhouse_classification=None, occupiable=False,
    ).id


@pytest.mark.integration
def test_pack_specification_draft_rejected_outright(test_engine) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _build_tenant_farm(session, suffix=suffix)
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"v-{suffix}", name="V",
            supplier_reference=None,
        )
        hpl_id = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety, suffix=suffix, weight=Decimal("5.000"), t_harvest=now() - timedelta(days=2))
        grade_version_id = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=suffix)
        hall_id = _hall(session, tenant, user, farm, suffix=suffix)
        gpl_id = _grade_one(session, tenant, user, farm, hpl_id=hpl_id, weight=Decimal("5.000"), grade_version_id=grade_version_id, hall_id=hall_id, t_grade=now() - timedelta(days=2), suffix=suffix)
        pack_spec, packaging_unit = _pack_spec_version(session, tenant, user, crop=crop, variety_id=None, grade_definition_version_id=None, suffix=suffix)
        draft = _draft_version(session, tenant, user, pack_spec=pack_spec, packaging_unit=packaging_unit)
        session.commit()

        with pytest.raises(PackSpecificationVersionNotUsableError):
            packing_service.record_packing(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                pack_specification_version_id=draft.id, effective_time=now(), finished_goods_lot_code=f"FG-{suffix}",
                package_count=1, packed_output_weight_kg=Decimal("5.000"), process_loss_weight_kg=Decimal("0"),
                rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[{"graded_produce_lot_id": gpl_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
            )
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_pack_specification_retired_but_historically_valid_accepted(test_engine) -> None:
    """A RETIRED version is still usable if the packing event's own
    effective_time falls inside its historical [effective_from,
    effective_until) window -- current status alone is never the gate."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _build_tenant_farm(session, suffix=suffix)
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"v-{suffix}", name="V",
            supplier_reference=None,
        )
        t_harvest = now() - timedelta(days=10)
        hpl_id = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety, suffix=suffix, weight=Decimal("5.000"), t_harvest=t_harvest)
        grade_version_id = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=suffix)
        hall_id = _hall(session, tenant, user, farm, suffix=suffix)
        gpl_id = _grade_one(session, tenant, user, farm, hpl_id=hpl_id, weight=Decimal("5.000"), grade_version_id=grade_version_id, hall_id=hall_id, t_grade=t_harvest, suffix=suffix)

        pack_spec, packaging_unit = _pack_spec_version(session, tenant, user, crop=crop, variety_id=None, grade_definition_version_id=None, suffix=suffix)
        v1 = _draft_version(session, tenant, user, pack_spec=pack_spec, packaging_unit=packaging_unit)
        t1 = now() - timedelta(days=9)
        _activate(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=t1)
        t2 = now() - timedelta(days=8)
        _retire(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=t2)
        session.commit()

        # Inside [t1, t2): must succeed even though v1 is now retired.
        event = packing_service.record_packing(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            pack_specification_version_id=v1.id, effective_time=t1 + timedelta(hours=1),
            finished_goods_lot_code=f"FG-{suffix}", package_count=1, packed_output_weight_kg=Decimal("5.000"),
            process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"), note=None,
            input_lines=[{"graded_produce_lot_id": gpl_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
        )
        assert event.id is not None
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_pack_specification_before_effective_from_rejected(test_engine) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _build_tenant_farm(session, suffix=suffix)
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"v-{suffix}", name="V",
            supplier_reference=None,
        )
        t_harvest = now() - timedelta(days=10)
        hpl_id = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety, suffix=suffix, weight=Decimal("5.000"), t_harvest=t_harvest)
        grade_version_id = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=suffix)
        hall_id = _hall(session, tenant, user, farm, suffix=suffix)
        gpl_id = _grade_one(session, tenant, user, farm, hpl_id=hpl_id, weight=Decimal("5.000"), grade_version_id=grade_version_id, hall_id=hall_id, t_grade=t_harvest, suffix=suffix)

        pack_spec, packaging_unit = _pack_spec_version(session, tenant, user, crop=crop, variety_id=None, grade_definition_version_id=None, suffix=suffix)
        v1 = _draft_version(session, tenant, user, pack_spec=pack_spec, packaging_unit=packaging_unit)
        t1 = now() - timedelta(days=5)
        _activate(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=t1)
        session.commit()

        with pytest.raises(PackSpecificationVersionNotUsableError):
            packing_service.record_packing(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                pack_specification_version_id=v1.id, effective_time=t1 - timedelta(hours=1),
                finished_goods_lot_code=f"FG-{suffix}", package_count=1, packed_output_weight_kg=Decimal("5.000"),
                process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[{"graded_produce_lot_id": gpl_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
            )
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_pack_specification_after_effective_until_rejected(test_engine) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _build_tenant_farm(session, suffix=suffix)
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"v-{suffix}", name="V",
            supplier_reference=None,
        )
        t_harvest = now() - timedelta(days=10)
        hpl_id = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety, suffix=suffix, weight=Decimal("5.000"), t_harvest=t_harvest)
        grade_version_id = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=suffix)
        hall_id = _hall(session, tenant, user, farm, suffix=suffix)
        gpl_id = _grade_one(session, tenant, user, farm, hpl_id=hpl_id, weight=Decimal("5.000"), grade_version_id=grade_version_id, hall_id=hall_id, t_grade=t_harvest, suffix=suffix)

        pack_spec, packaging_unit = _pack_spec_version(session, tenant, user, crop=crop, variety_id=None, grade_definition_version_id=None, suffix=suffix)
        v1 = _draft_version(session, tenant, user, pack_spec=pack_spec, packaging_unit=packaging_unit)
        t1 = now() - timedelta(days=9)
        _activate(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=t1)
        t2 = now() - timedelta(days=8)
        _retire(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=t2)
        session.commit()

        with pytest.raises(PackSpecificationVersionNotUsableError):
            packing_service.record_packing(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                pack_specification_version_id=v1.id, effective_time=t2 + timedelta(hours=1),
                finished_goods_lot_code=f"FG-{suffix}", package_count=1, packed_output_weight_kg=Decimal("5.000"),
                process_loss_weight_kg=Decimal("0"), rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[{"graded_produce_lot_id": gpl_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
            )
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_pack_specification_crop_mismatch_rejected(test_engine) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _build_tenant_farm(session, suffix=suffix)
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        other_crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"other-{suffix}", common_name="Tomato",
            scientific_name=None, crop_category="vine",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"v-{suffix}", name="V",
            supplier_reference=None,
        )
        t_harvest = now() - timedelta(days=2)
        hpl_id = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety, suffix=suffix, weight=Decimal("5.000"), t_harvest=t_harvest)
        grade_version_id = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=suffix)
        hall_id = _hall(session, tenant, user, farm, suffix=suffix)
        gpl_id = _grade_one(session, tenant, user, farm, hpl_id=hpl_id, weight=Decimal("5.000"), grade_version_id=grade_version_id, hall_id=hall_id, t_grade=t_harvest, suffix=suffix)

        # PackSpec pinned to the OTHER crop.
        pack_spec, packaging_unit = _pack_spec_version(session, tenant, user, crop=other_crop, variety_id=None, grade_definition_version_id=None, suffix=suffix)
        v1 = _draft_version(session, tenant, user, pack_spec=pack_spec, packaging_unit=packaging_unit)
        _activate(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=now() - timedelta(days=1))
        session.commit()

        with pytest.raises(PackingCropVarietyMismatchError):
            packing_service.record_packing(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                pack_specification_version_id=v1.id, effective_time=now(), finished_goods_lot_code=f"FG-{suffix}",
                package_count=1, packed_output_weight_kg=Decimal("5.000"), process_loss_weight_kg=Decimal("0"),
                rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[{"graded_produce_lot_id": gpl_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
            )
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_pack_specification_variety_pin_mismatch_rejected(test_engine) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _build_tenant_farm(session, suffix=suffix)
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety_a = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"va-{suffix}", name="A",
            supplier_reference=None,
        )
        variety_b = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"vb-{suffix}", name="B",
            supplier_reference=None,
        )
        t_harvest = now() - timedelta(days=2)
        hpl_id = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety_a, suffix=suffix, weight=Decimal("5.000"), t_harvest=t_harvest)
        grade_version_id = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=suffix)
        hall_id = _hall(session, tenant, user, farm, suffix=suffix)
        gpl_id = _grade_one(session, tenant, user, farm, hpl_id=hpl_id, weight=Decimal("5.000"), grade_version_id=grade_version_id, hall_id=hall_id, t_grade=t_harvest, suffix=suffix)

        # PackSpec pinned to variety_b, but the GPL is variety_a.
        pack_spec, packaging_unit = _pack_spec_version(session, tenant, user, crop=crop, variety_id=variety_b.id, grade_definition_version_id=None, suffix=suffix)
        v1 = _draft_version(session, tenant, user, pack_spec=pack_spec, packaging_unit=packaging_unit)
        _activate(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=now() - timedelta(days=1))
        session.commit()

        with pytest.raises(PackingCropVarietyMismatchError):
            packing_service.record_packing(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                pack_specification_version_id=v1.id, effective_time=now(), finished_goods_lot_code=f"FG-{suffix}",
                package_count=1, packed_output_weight_kg=Decimal("5.000"), process_loss_weight_kg=Decimal("0"),
                rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[{"graded_produce_lot_id": gpl_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
            )
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_pack_specification_null_variety_pin_accepts_homogeneous_variety(test_engine) -> None:
    """PackSpec.variety_id IS NULL means "applies to any one homogeneous
    GPL variety" -- a real, non-null GPL variety must be accepted."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _build_tenant_farm(session, suffix=suffix)
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety_a = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"va-{suffix}", name="A",
            supplier_reference=None,
        )
        t_harvest = now() - timedelta(days=2)
        hpl_id = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety_a, suffix=suffix, weight=Decimal("5.000"), t_harvest=t_harvest)
        grade_version_id = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=suffix)
        hall_id = _hall(session, tenant, user, farm, suffix=suffix)
        gpl_id = _grade_one(session, tenant, user, farm, hpl_id=hpl_id, weight=Decimal("5.000"), grade_version_id=grade_version_id, hall_id=hall_id, t_grade=t_harvest, suffix=suffix)

        pack_spec, packaging_unit = _pack_spec_version(session, tenant, user, crop=crop, variety_id=None, grade_definition_version_id=None, suffix=suffix)
        v1 = _draft_version(session, tenant, user, pack_spec=pack_spec, packaging_unit=packaging_unit)
        _activate(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=now() - timedelta(days=1))
        session.commit()

        event = packing_service.record_packing(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            pack_specification_version_id=v1.id, effective_time=now(), finished_goods_lot_code=f"FG-{suffix}",
            package_count=1, packed_output_weight_kg=Decimal("5.000"), process_loss_weight_kg=Decimal("0"),
            rejected_weight_kg=Decimal("0"), note=None,
            input_lines=[{"graded_produce_lot_id": gpl_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
        )
        assert event.id is not None
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_two_gpl_inputs_different_variety_rejected(test_engine) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _build_tenant_farm(session, suffix=suffix)
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety_a = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"va-{suffix}", name="A",
            supplier_reference=None,
        )
        variety_b = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"vb-{suffix}", name="B",
            supplier_reference=None,
        )
        t_harvest = now() - timedelta(days=2)
        hpl_a = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety_a, suffix=f"{suffix}-a", weight=Decimal("5.000"), t_harvest=t_harvest)
        hpl_b = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety_b, suffix=f"{suffix}-b", weight=Decimal("5.000"), t_harvest=t_harvest)
        grade_version_id = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=suffix)
        hall_id = _hall(session, tenant, user, farm, suffix=suffix)
        gpl_a = _grade_one(session, tenant, user, farm, hpl_id=hpl_a, weight=Decimal("5.000"), grade_version_id=grade_version_id, hall_id=hall_id, t_grade=t_harvest, suffix=f"{suffix}-a")
        gpl_b = _grade_one(session, tenant, user, farm, hpl_id=hpl_b, weight=Decimal("5.000"), grade_version_id=grade_version_id, hall_id=hall_id, t_grade=t_harvest, suffix=f"{suffix}-b")

        pack_spec, packaging_unit = _pack_spec_version(session, tenant, user, crop=crop, variety_id=None, grade_definition_version_id=None, suffix=suffix)
        v1 = _draft_version(session, tenant, user, pack_spec=pack_spec, packaging_unit=packaging_unit)
        _activate(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=now() - timedelta(days=1))
        session.commit()

        with pytest.raises(PackingCropVarietyMismatchError):
            packing_service.record_packing(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                pack_specification_version_id=v1.id, effective_time=now(), finished_goods_lot_code=f"FG-{suffix}",
                package_count=1, packed_output_weight_kg=Decimal("10.000"), process_loss_weight_kg=Decimal("0"),
                rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[
                    {"graded_produce_lot_id": gpl_a, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None},
                    {"graded_produce_lot_id": gpl_b, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None},
                ],
            )
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_two_gpl_inputs_same_variety_accepted(test_engine) -> None:
    """Two GPL inputs sharing the SAME non-null variety_id (as well as
    crop and grade-version) must be accepted -- the equality rule, not
    just the mismatch rule, needs positive coverage. (A workflow with no
    variety cannot be sown in this codebase -- `sowing_service.sow_batch`
    unconditionally rejects a variety-less workflow -- so a real
    NULL-variety HPL/GPL is not a reachable state via the normal harvest
    path; NULL-variety coverage is instead exercised on the PackSpec side,
    see `test_pack_specification_null_variety_pin_accepts_homogeneous_variety`.)"""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _build_tenant_farm(session, suffix=suffix)
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"v-{suffix}", name="V",
            supplier_reference=None,
        )
        t_harvest = now() - timedelta(days=2)
        hpl_1 = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety, suffix=f"{suffix}-1", weight=Decimal("5.000"), t_harvest=t_harvest)
        hpl_2 = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety, suffix=f"{suffix}-2", weight=Decimal("5.000"), t_harvest=t_harvest)
        grade_version_id = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=suffix)
        hall_id = _hall(session, tenant, user, farm, suffix=suffix)
        gpl_1 = _grade_one(session, tenant, user, farm, hpl_id=hpl_1, weight=Decimal("5.000"), grade_version_id=grade_version_id, hall_id=hall_id, t_grade=t_harvest, suffix=f"{suffix}-1")
        gpl_2 = _grade_one(session, tenant, user, farm, hpl_id=hpl_2, weight=Decimal("5.000"), grade_version_id=grade_version_id, hall_id=hall_id, t_grade=t_harvest, suffix=f"{suffix}-2")

        pack_spec, packaging_unit = _pack_spec_version(session, tenant, user, crop=crop, variety_id=None, grade_definition_version_id=None, suffix=suffix)
        v1 = _draft_version(session, tenant, user, pack_spec=pack_spec, packaging_unit=packaging_unit)
        _activate(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=now() - timedelta(days=1))
        session.commit()

        event = packing_service.record_packing(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            pack_specification_version_id=v1.id, effective_time=now(), finished_goods_lot_code=f"FG-{suffix}",
            package_count=2, packed_output_weight_kg=Decimal("10.000"), process_loss_weight_kg=Decimal("0"),
            rejected_weight_kg=Decimal("0"), note=None,
            input_lines=[
                {"graded_produce_lot_id": gpl_1, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None},
                {"graded_produce_lot_id": gpl_2, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None},
            ],
        )
        assert event.id is not None
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_two_gpl_inputs_different_grade_version_rejected(test_engine) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _build_tenant_farm(session, suffix=suffix)
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"v-{suffix}", name="V",
            supplier_reference=None,
        )
        t_harvest = now() - timedelta(days=2)
        hpl_1 = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety, suffix=f"{suffix}-1", weight=Decimal("5.000"), t_harvest=t_harvest)
        hpl_2 = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety, suffix=f"{suffix}-2", weight=Decimal("5.000"), t_harvest=t_harvest)
        grade_version_1 = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=f"{suffix}-g1")
        grade_version_2 = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=f"{suffix}-g2")
        hall_id = _hall(session, tenant, user, farm, suffix=suffix)
        gpl_1 = _grade_one(session, tenant, user, farm, hpl_id=hpl_1, weight=Decimal("5.000"), grade_version_id=grade_version_1, hall_id=hall_id, t_grade=t_harvest, suffix=f"{suffix}-1")
        gpl_2 = _grade_one(session, tenant, user, farm, hpl_id=hpl_2, weight=Decimal("5.000"), grade_version_id=grade_version_2, hall_id=hall_id, t_grade=t_harvest, suffix=f"{suffix}-2")

        pack_spec, packaging_unit = _pack_spec_version(session, tenant, user, crop=crop, variety_id=None, grade_definition_version_id=None, suffix=suffix)
        v1 = _draft_version(session, tenant, user, pack_spec=pack_spec, packaging_unit=packaging_unit)
        _activate(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=now() - timedelta(days=1))
        session.commit()

        with pytest.raises(PackingGradeVersionMismatchError):
            packing_service.record_packing(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                pack_specification_version_id=v1.id, effective_time=now(), finished_goods_lot_code=f"FG-{suffix}",
                package_count=2, packed_output_weight_kg=Decimal("10.000"), process_loss_weight_kg=Decimal("0"),
                rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[
                    {"graded_produce_lot_id": gpl_1, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None},
                    {"graded_produce_lot_id": gpl_2, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None},
                ],
            )
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_pack_specification_grade_pin_mismatch_rejected(test_engine) -> None:
    """PackSpecificationVersion.grade_definition_version_id, when set,
    must equal every GPL input's own grade version -- not merely be
    internally consistent among the inputs themselves."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _build_tenant_farm(session, suffix=suffix)
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"v-{suffix}", name="V",
            supplier_reference=None,
        )
        t_harvest = now() - timedelta(days=2)
        hpl_id = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety, suffix=suffix, weight=Decimal("5.000"), t_harvest=t_harvest)
        grade_version_used = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=f"{suffix}-used")
        grade_version_pinned = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=f"{suffix}-pinned")
        hall_id = _hall(session, tenant, user, farm, suffix=suffix)
        gpl_id = _grade_one(session, tenant, user, farm, hpl_id=hpl_id, weight=Decimal("5.000"), grade_version_id=grade_version_used, hall_id=hall_id, t_grade=t_harvest, suffix=suffix)

        pack_spec, packaging_unit = _pack_spec_version(session, tenant, user, crop=crop, variety_id=None, grade_definition_version_id=grade_version_pinned, suffix=suffix)
        v1 = _draft_version(session, tenant, user, pack_spec=pack_spec, packaging_unit=packaging_unit, grade_definition_version_id=grade_version_pinned)
        _activate(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=now() - timedelta(days=1))
        session.commit()

        with pytest.raises(PackingGradeVersionMismatchError):
            packing_service.record_packing(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                pack_specification_version_id=v1.id, effective_time=now(), finished_goods_lot_code=f"FG-{suffix}",
                package_count=1, packed_output_weight_kg=Decimal("5.000"), process_loss_weight_kg=Decimal("0"),
                rejected_weight_kg=Decimal("0"), note=None,
                input_lines=[{"graded_produce_lot_id": gpl_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
            )
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_pack_specification_grade_pin_match_accepted(test_engine) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _build_tenant_farm(session, suffix=suffix)
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"v-{suffix}", name="V",
            supplier_reference=None,
        )
        t_harvest = now() - timedelta(days=2)
        hpl_id = _harvest_one(session, tenant, user, farm, crop=crop, variety=variety, suffix=suffix, weight=Decimal("5.000"), t_harvest=t_harvest)
        grade_version_id = _active_grade_version(session, tenant, user, crop=crop, variety_id=None, suffix=suffix)
        hall_id = _hall(session, tenant, user, farm, suffix=suffix)
        gpl_id = _grade_one(session, tenant, user, farm, hpl_id=hpl_id, weight=Decimal("5.000"), grade_version_id=grade_version_id, hall_id=hall_id, t_grade=t_harvest, suffix=suffix)

        pack_spec, packaging_unit = _pack_spec_version(session, tenant, user, crop=crop, variety_id=None, grade_definition_version_id=grade_version_id, suffix=suffix)
        v1 = _draft_version(session, tenant, user, pack_spec=pack_spec, packaging_unit=packaging_unit, grade_definition_version_id=grade_version_id)
        _activate(session, tenant, user, pack_spec=pack_spec, version=v1, effective_time=now() - timedelta(days=1))
        session.commit()

        event = packing_service.record_packing(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            pack_specification_version_id=v1.id, effective_time=now(), finished_goods_lot_code=f"FG-{suffix}",
            package_count=1, packed_output_weight_kg=Decimal("5.000"), process_loss_weight_kg=Decimal("0"),
            rejected_weight_kg=Decimal("0"), note=None,
            input_lines=[{"graded_produce_lot_id": gpl_id, "consumed_weight_kg": Decimal("5.000"), "consumed_whole_unit_count": None, "note": None}],
        )
        assert event.id is not None
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_scenario(test_engine, tenant_id)
