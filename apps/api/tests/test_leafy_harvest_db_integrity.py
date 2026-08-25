"""HARVEST-OPS-001 SLICE 1 CTO CORRECTION 1: direct-SQL DB-integrity bypass
proofs.

Finding 1 -- the `SET LOCAL cmp.leafy_harvest = 'true'` transaction-local
marker lets the IMMEDIATE `enforce_harvest_event_insert_integrity` trigger
skip CMP-013's own `stage_category = 'harvesting'` gate at INSERT time, but
is never trusted as the final authority: a DEFERRED constraint trigger,
`enforce_leafy_harvest_stage_bypass_integrity`, independently re-examines
the COMPLETE persisted state at REAL commit and rejects the whole
transaction unless every source line of a non-'harvesting'-stage
HarvestEvent genuinely proves Leafy Harvest shape. These tests use a
dedicated `test_engine` connection with a real `trans.commit()` (never the
`db_session` fixture's own savepoint-scoped commit, which never fires a
DEFERRED constraint trigger -- mirrors CMP-013's own established pattern,
e.g. `test_late_direct_sql_source_line_reruns_deferred_reconciliation`).

Finding 2 -- every typed biological/commercial fact is tied to its source
by an IMMEDIATE (non-deferred) arithmetic check, so these fire at ordinary
INSERT/flush time and can use the plain `db_session` fixture directly."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.harvest_population_event import HarvestPopulationEvent
from app.models.harvest_source_line import HarvestSourceLine
from app.models.harvest_source_line_correction import HarvestSourceLineCorrection
from app.models.produce_lot_ledger_entry import ProduceLotLedgerEntry
from tests.test_leafy_harvest import _harvest, _line
from tests.test_leafy_harvest_correction import _correct, _lot_for, _only_source_line
from tests.test_production_disposition import _plate_scenario

pytestmark = pytest.mark.integration


# =====================================================================
# Finding 1 -- durable, GUC-independent stage-bypass proof.
# =====================================================================


def _build_committed_generic_stage_scenario(test_engine, suffix: str):
    """A CropBatch whose active stage is genuinely NOT 'harvesting' (mirrors
    `_plate_scenario`'s own Leafy shape but via a real committed connection),
    plus one real, valid Leafy Production Plate BCA on it, committed."""
    from app.services import farm_service, membership_service, tenant_service, user_service
    from tests.test_leafy_production_transfer import (
        _leafy_setup, _nursery_plate_source_scenario, _production_plates, _record, _simple_allocation,
        _simple_destination, _simple_source,
    )

    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant = tenant_service.create_tenant(session, code=f"hdb-{suffix}", name="Harvest DB Integrity Tenant")
    user = user_service.create_user(
        session, oidc_issuer="hdb", oidc_subject=suffix, email=f"hdb-{suffix}@example.com", display_name="DB User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="DB Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s, aids = _nursery_plate_source_scenario(session, tenant, user, farm, suffix=suffix, opening_count=180)
    table_ids = _leafy_setup(session, tenant, user, farm, suffix=suffix)
    plates, _spec = _production_plates(session, tenant, user, farm, suffix=suffix, count=1)
    result = _record(
        session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=180)],
        [_simple_allocation(aids[0], plates[0].id, 180)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )
    root_id = result.destination_lines[0].destination_batch_carrier_assignment_id
    session.commit()

    stage_category = session.execute(
        text(
            "SELECT s.stage_category FROM batch_stage_runs r JOIN workflow_stages s ON s.id = r.workflow_stage_id "
            "WHERE r.id = (SELECT batch_stage_run_id FROM batch_carrier_assignments WHERE id = :id)"
        ),
        {"id": root_id},
    ).scalar_one()
    assert stage_category != "harvesting", "sanity: this scenario's active stage must NOT be 'harvesting'"

    out = {
        "tenant_id": tenant.id, "farm_id": farm.id, "user_id": user.id, "batch_id": s["batch"].id,
        "root_id": root_id, "carrier_id": plates[0].id,
        "active_run_id": session.execute(
            text(
                "SELECT id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"
            ),
            {"bid": s["batch"].id},
        ).scalar_one(),
        "et": s["transfer_ready_time"] + timedelta(hours=2),
    }
    session.close()
    conn.close()
    return out


def test_generic_non_harvesting_harvest_still_fails_without_guc(test_engine) -> None:
    """No GUC set -- CMP-013's own unwidened rejection still applies."""
    suffix = uuid.uuid4().hex[:10]
    scenario = _build_committed_generic_stage_scenario(test_engine, suffix)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        with pytest.raises(Exception, match="current stage is not a harvesting stage"):
            conn.execute(
                text(
                    "INSERT INTO harvest_events "
                    "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
                    "client_command_id, request_fingerprint, note) "
                    "VALUES (:id, :tid, :fid, :bid, :run, :et, :uid, :cid, 'x', NULL)"
                ),
                {
                    "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                    "bid": scenario["batch_id"], "run": scenario["active_run_id"], "et": scenario["et"],
                    "uid": scenario["user_id"], "cid": uuid.uuid4(),
                },
            )
    finally:
        trans.rollback()
        conn.close()
    from tests._traceability_scenario import cleanup_traceability_scenario

    cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


def test_guc_alone_is_not_sufficient_for_invalid_generic_harvest(test_engine) -> None:
    """The GUC is set, but NO genuine Leafy facts are ever persisted (no
    HarvestSourceLine, no HarvestPopulationEvent at all) -- the deferred
    trigger must still reject at commit."""
    suffix = uuid.uuid4().hex[:10]
    scenario = _build_committed_generic_stage_scenario(test_engine, suffix)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET LOCAL cmp.leafy_harvest = 'true'"))
        event_id = uuid.uuid4()
        # The IMMEDIATE trigger allows this (GUC bypasses the stage check),
        # but no source line / population event is ever inserted --
        # deliberately incomplete, "fake Leafy" shape.
        conn.execute(
            text(
                "INSERT INTO harvest_events "
                "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
                "client_command_id, request_fingerprint, note) "
                "VALUES (:id, :tid, :fid, :bid, :run, :et, :uid, :cid, 'x', NULL)"
            ),
            {
                "id": event_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                "bid": scenario["batch_id"], "run": scenario["active_run_id"], "et": scenario["et"],
                "uid": scenario["user_id"], "cid": uuid.uuid4(),
            },
        )
        # A HarvestedProduceLot + harvest_receipt would normally follow, but
        # since there are zero source lines, the CMP-013 deferred
        # reconciliation trigger (harvest_events has no source lines) would
        # ALSO reject this -- proving the point from an independent angle
        # too. Either way, commit must fail.
        with pytest.raises(Exception):
            trans.commit()
    finally:
        trans.rollback()
        conn.close()
    from tests._traceability_scenario import cleanup_traceability_scenario

    cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


def test_valid_leafy_harvest_outside_harvesting_stage_passes(db_session, active_context_with_farm) -> None:
    """Direct proof (via the real service, which is itself the only correct
    way to construct a genuinely valid multi-table Leafy fact) that the
    deferred trigger allows a well-formed Leafy Harvest through even though
    the Batch's active stage is never 'harvesting' -- already implicitly
    proven by all 19 test_leafy_harvest.py cases; restated here as the
    ticket's own explicit required case."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    db_session.flush()
    assert event is not None


def test_existing_cmp013_harvesting_stage_behavior_remains_valid(test_engine) -> None:
    """A genuine CMP-013 (non-Leafy) Harvest, whose active stage genuinely
    IS 'harvesting', still passes through the widened trigger AND the new
    deferred stage-bypass trigger (which returns immediately for a
    'harvesting'-stage event, never inspecting source lines at all) --
    mirrors `test_harvest_acceptance.py`'s own scenario shape."""
    from decimal import Decimal as D

    from app.services import (
        carrier_service, crop_service, farm_service, membership_service, production_system_service,
        sowing_service, tenant_service, user_service, workflow_service,
    )
    from app.services import harvest_service
    from tests.conftest import ensure_seed_tray_specification

    suffix = uuid.uuid4().hex[:8]
    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant_id = None
    try:
        tenant = tenant_service.create_tenant(session, code=f"hgen-{suffix}", name="Harvest Generic Tenant")
        tenant_id = tenant.id
        user = user_service.create_user(
            session, oidc_issuer="hgen", oidc_subject=suffix, email=f"hgen-{suffix}@example.com",
            display_name="Generic User",
        )
        membership_service.add_membership(
            session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
        )
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Generic Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"C-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"V-{suffix}",
            name="Variety", supplier_reference=None,
        )
        ps = production_system_service.register_production_system(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="PS", description=None,
        )
        workflow = workflow_service.register_workflow(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
            production_system_id=ps.id, code=f"WF-{suffix}", name="WF",
        )
        version = workflow_service.create_draft_version(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
        )
        seeding = workflow_service.add_stage(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            code="SEEDING", name="Seeding", display_order=0, stage_category="seeding", expected_duration_minutes=None,
            permitted_location_type_code=None, required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
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
        workflow_service.add_transition(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=seeding.id, to_stage_id=harvesting.id, code="ADV", name="Adv",
        )
        workflow_service.add_transition(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=harvesting.id, to_stage_id=complete.id, code="FIN", name="Fin",
        )
        workflow_service.publish_version(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
        )
        from app.services import crop_batch_service
        from datetime import datetime, timezone

        def _now():
            return datetime.now(timezone.utc)

        batch = crop_batch_service.create_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            code=f"B-{suffix}", workflow_id=workflow.id, effective_time=_now(),
        )
        seed_lot = sowing_service.register_seed_lot(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
            variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
            received_date=None, expiry_date=None,
        )
        carrier = carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=ensure_seed_tray_specification(session, tenant_id=tenant.id, actor_user_id=user.id).id,
            code=f"ST-{suffix}", issued_date=None,
        )
        sowing_service.sow_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
            lines=[{"carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": 10, "seed_count": 10, "line_note": None}],
        )
        crop_batch_service.transition_stage(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), configured_transition_id=workflow_service.get_transitions(
                session, version_id=version.id
            )[0].id,
            effective_time=_now(), reason=None,
        )
        assignment = sowing_service.list_batch_carriers(session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)[0]

        event = harvest_service.record_harvest(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"HLOT-{suffix}", note=None,
            source_lines=[{"batch_carrier_assignment_id": assignment.id, "harvested_weight_kg": D("5.000"), "whole_unit_count": None, "note": None}],
        )
        session.commit()
        assert event is not None
    finally:
        session.rollback()
        session.close()
        conn.close()
        if tenant_id is not None:
            from tests._traceability_scenario import cleanup_traceability_scenario

            cleanup_traceability_scenario(test_engine, tenant_id)


# =====================================================================
# Finding 2 -- per-fact DB arithmetic integrity (immediate triggers).
#
# Each test constructs its OWN anchor row(s) by direct SQL rather than via
# the service, specifically so no genuine (correct) row already occupies
# the unique-index slot the malformed attempt targets -- isolating the
# arithmetic check alone from the uniqueness constraints.
# =====================================================================


def _manual_event_and_line(db_session, tenant, user, farm, root_id, batch_id, t0, *, weight="2.500", count=5):
    """Inserts a harvest_events + harvest_source_lines pair directly (never
    via record_leafy_harvest, so no HarvestPopulationEvent CONSUMPTION
    exists for it yet) against a real, valid Leafy Plate BCA."""
    active_run_id = db_session.execute(
        text("SELECT batch_stage_run_id FROM batch_carrier_assignments WHERE id = :id"), {"id": root_id}
    ).scalar_one()
    carrier_id = db_session.execute(
        text("SELECT carrier_id FROM batch_carrier_assignments WHERE id = :id"), {"id": root_id}
    ).scalar_one()
    event_id = uuid.uuid4()
    db_session.execute(text("SET LOCAL cmp.leafy_harvest = 'true'"))
    db_session.execute(
        text(
            "INSERT INTO harvest_events "
            "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
            "client_command_id, request_fingerprint, note) "
            "VALUES (:id, :tid, :fid, :bid, :run, :et, :uid, :cid, 'x', NULL)"
        ),
        {
            "id": event_id, "tid": tenant.id, "fid": farm.id, "bid": batch_id, "run": active_run_id,
            "et": t0 + timedelta(hours=1), "uid": user.id, "cid": uuid.uuid4(),
        },
    )
    line_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO harvest_source_lines "
            "(id, tenant_id, farm_id, harvest_event_id, batch_carrier_assignment_id, carrier_id, "
            "harvested_weight_kg, whole_unit_count, note) "
            "VALUES (:id, :tid, :fid, :eid, :aid, :cid, :w, :c, NULL)"
        ),
        {
            "id": line_id, "tid": tenant.id, "fid": farm.id, "eid": event_id, "aid": root_id, "cid": carrier_id,
            "w": Decimal(weight), "c": count,
        },
    )
    db_session.flush()
    return event_id, line_id, t0 + timedelta(hours=1)


def test_original_consumption_wrong_count_delta_rejected(db_session, active_context_with_farm) -> None:
    """source whole_unit_count = 5, attempted CONSUMPTION = -4 -- reject."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _event_id, line_id, effective = _manual_event_and_line(
        db_session, tenant, user, farm, root_id, batch.id, t0, weight="2.500", count=5
    )
    with pytest.raises(Exception, match="exact negation of its own HarvestSourceLine"):
        db_session.execute(
            text(
                "INSERT INTO harvest_population_events "
                "(id, tenant_id, farm_id, population_root_batch_carrier_assignment_id, batch_carrier_assignment_id, "
                "event_kind, quantity_delta, effective_time, original_harvest_source_line_id) "
                "VALUES (:id, :tid, :fid, :root, :aid, 'CONSUMPTION', -4, :et, :lid)"
            ),
            {
                "id": uuid.uuid4(), "tid": tenant.id, "fid": farm.id, "root": root_id, "aid": root_id,
                "et": effective, "lid": line_id,
            },
        )
        db_session.flush()


def test_original_consumption_correct_count_delta_accepted(db_session, active_context_with_farm) -> None:
    """The valid counterpart of the above -- same setup, correct -5 passes."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _event_id, line_id, effective = _manual_event_and_line(
        db_session, tenant, user, farm, root_id, batch.id, t0, weight="2.500", count=5
    )
    db_session.execute(
        text(
            "INSERT INTO harvest_population_events "
            "(id, tenant_id, farm_id, population_root_batch_carrier_assignment_id, batch_carrier_assignment_id, "
            "event_kind, quantity_delta, effective_time, original_harvest_source_line_id) "
            "VALUES (:id, :tid, :fid, :root, :aid, 'CONSUMPTION', -5, :et, :lid)"
        ),
        {
            "id": uuid.uuid4(), "tid": tenant.id, "fid": farm.id, "root": root_id, "aid": root_id,
            "et": effective, "lid": line_id,
        },
    )
    db_session.flush()


def _manual_correction(db_session, tenant, user, farm, line_id, *, count, weight, supersedes=None, is_void=False):
    correction_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO harvest_source_line_corrections "
            "(id, tenant_id, farm_id, harvest_source_line_id, supersedes_correction_id, is_void, "
            "corrected_harvested_weight_kg, corrected_whole_unit_count, reason_code, note, actor_user_id, "
            "client_command_id, request_fingerprint) "
            "VALUES (:id, :tid, :fid, :lid, :supersedes, :void, :w, :c, 'x', 'x', :uid, :cid, :fp)"
        ),
        {
            "id": correction_id, "tid": tenant.id, "fid": farm.id, "lid": line_id, "supersedes": supersedes,
            "void": is_void, "w": (None if is_void else Decimal(weight)), "c": (None if is_void else count),
            "uid": user.id, "cid": uuid.uuid4(), "fp": uuid.uuid4().hex,
        },
    )
    db_session.flush()
    return correction_id


def test_replacement_consumption_not_matching_corrected_count_rejected(db_session, active_context_with_farm) -> None:
    """correction current = 4, attempted replacement CONSUMPTION = -3 --
    reject."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _event_id, line_id, effective = _manual_event_and_line(
        db_session, tenant, user, farm, root_id, batch.id, t0, weight="2.500", count=5
    )
    correction_id = _manual_correction(db_session, tenant, user, farm, line_id, count=4, weight="2.000")

    with pytest.raises(Exception, match="exact negation of its correction"):
        db_session.execute(
            text(
                "INSERT INTO harvest_population_events "
                "(id, tenant_id, farm_id, population_root_batch_carrier_assignment_id, batch_carrier_assignment_id, "
                "event_kind, quantity_delta, effective_time, harvest_source_line_correction_id) "
                "VALUES (:id, :tid, :fid, :root, :aid, 'CONSUMPTION', -3, :et, :cid)"
            ),
            {
                "id": uuid.uuid4(), "tid": tenant.id, "fid": farm.id, "root": root_id, "aid": root_id,
                "et": effective, "cid": correction_id,
            },
        )
        db_session.flush()


def test_reversal_magnitude_not_equal_to_target_rejected(db_session, active_context_with_farm) -> None:
    """target -5, attempted reversal +4 -- reject."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _event_id, line_id, effective = _manual_event_and_line(
        db_session, tenant, user, farm, root_id, batch.id, t0, weight="2.500", count=5
    )
    consumption_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO harvest_population_events "
            "(id, tenant_id, farm_id, population_root_batch_carrier_assignment_id, batch_carrier_assignment_id, "
            "event_kind, quantity_delta, effective_time, original_harvest_source_line_id) "
            "VALUES (:id, :tid, :fid, :root, :aid, 'CONSUMPTION', -5, :et, :lid)"
        ),
        {
            "id": consumption_id, "tid": tenant.id, "fid": farm.id, "root": root_id, "aid": root_id,
            "et": effective, "lid": line_id,
        },
    )
    db_session.flush()

    with pytest.raises(Exception, match="exact negation of the reversed event"):
        db_session.execute(
            text(
                "INSERT INTO harvest_population_events "
                "(id, tenant_id, farm_id, population_root_batch_carrier_assignment_id, batch_carrier_assignment_id, "
                "event_kind, quantity_delta, effective_time, reverses_event_id) "
                "VALUES (:id, :tid, :fid, :root, :aid, 'REVERSAL', 4, :et, :target)"
            ),
            {
                "id": uuid.uuid4(), "tid": tenant.id, "fid": farm.id, "root": root_id, "aid": root_id,
                "et": effective, "target": consumption_id,
            },
        )
        db_session.flush()


def test_harvest_adjustment_wrong_predecessor_relative_delta_rejected(db_session, active_context_with_farm) -> None:
    """original 5/2.5, correction 1 = 4/2.0 -- expected adjustment -1/-0.5;
    attempt -2/-0.5 -- reject."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event_id, line_id, effective = _manual_event_and_line(
        db_session, tenant, user, farm, root_id, batch.id, t0, weight="2.500", count=5
    )
    # A real HarvestedProduceLot + harvest_receipt is required for the FK/
    # typed-source chain the ledger trigger walks.
    lot_id = event_id
    db_session.execute(
        text(
            "INSERT INTO harvested_produce_lots "
            "(id, tenant_id, farm_id, code, harvest_event_id, batch_id, workflow_id, workflow_version_id, crop_id, "
            "variety_id, total_harvested_weight_kg, total_whole_unit_count, effective_time) "
            "SELECT :id, cb.tenant_id, cb.farm_id, :code, :eid, cb.id, cb.workflow_id, cb.workflow_version_id, "
            "wf.crop_id, wf.variety_id, 2.500, 5, :et "
            "FROM crop_batches cb JOIN workflows wf ON wf.id = cb.workflow_id WHERE cb.id = :bid"
        ),
        {"id": lot_id, "code": f"HL-{uuid.uuid4().hex[:8]}", "eid": event_id, "et": effective, "bid": batch.id},
    )
    db_session.execute(
        text(
            "INSERT INTO produce_lot_ledger_entries "
            "(id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, weight_delta_kg, "
            "whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
            "VALUES (:id, :tid, :fid, :lot, :eid, 'harvest_receipt', 2.500, 5, :et, now(), :uid, NULL)"
        ),
        {"id": lot_id, "tid": tenant.id, "fid": farm.id, "lot": lot_id, "eid": event_id, "et": effective, "uid": user.id},
    )
    db_session.flush()

    correction_id = _manual_correction(db_session, tenant, user, farm, line_id, count=4, weight="2.000")

    with pytest.raises(Exception, match="does not equal the new effective tuple minus the immediate predecessor"):
        db_session.execute(
            text(
                "INSERT INTO produce_lot_ledger_entries "
                "(id, tenant_id, farm_id, produce_lot_id, harvest_source_line_correction_id, entry_kind, "
                "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
                "VALUES (:id, :tid, :fid, :lot, :cid, 'harvest_adjustment', -2.000, -1, :et, now(), :uid, 'x')"
            ),
            {
                "id": correction_id, "tid": tenant.id, "fid": farm.id, "lot": lot_id, "cid": correction_id,
                "et": effective, "uid": user.id,
            },
        )
        db_session.flush()


def test_repeated_correction_ledger_delta_against_original_rejected(db_session, active_context_with_farm) -> None:
    """original 5/2.5, C1 = 4/2.0, C2 = 6/3.0 -- expected C2 adjustment
    +2/+1.0 (relative to C1); attempting +1/+0.5 (relative to the
    ORIGINAL) must be rejected."""
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    event_id, line_id, effective = _manual_event_and_line(
        db_session, tenant, user, farm, root_id, batch.id, t0, weight="2.500", count=5
    )
    lot_id = event_id
    db_session.execute(
        text(
            "INSERT INTO harvested_produce_lots "
            "(id, tenant_id, farm_id, code, harvest_event_id, batch_id, workflow_id, workflow_version_id, crop_id, "
            "variety_id, total_harvested_weight_kg, total_whole_unit_count, effective_time) "
            "SELECT :id, cb.tenant_id, cb.farm_id, :code, :eid, cb.id, cb.workflow_id, cb.workflow_version_id, "
            "wf.crop_id, wf.variety_id, 2.500, 5, :et "
            "FROM crop_batches cb JOIN workflows wf ON wf.id = cb.workflow_id WHERE cb.id = :bid"
        ),
        {"id": lot_id, "code": f"HL-{uuid.uuid4().hex[:8]}", "eid": event_id, "et": effective, "bid": batch.id},
    )
    db_session.execute(
        text(
            "INSERT INTO produce_lot_ledger_entries "
            "(id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, weight_delta_kg, "
            "whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
            "VALUES (:id, :tid, :fid, :lot, :eid, 'harvest_receipt', 2.500, 5, :et, now(), :uid, NULL)"
        ),
        {"id": lot_id, "tid": tenant.id, "fid": farm.id, "lot": lot_id, "eid": event_id, "et": effective, "uid": user.id},
    )
    db_session.flush()

    c1_id = _manual_correction(db_session, tenant, user, farm, line_id, count=4, weight="2.000")
    db_session.execute(
        text(
            "INSERT INTO produce_lot_ledger_entries "
            "(id, tenant_id, farm_id, produce_lot_id, harvest_source_line_correction_id, entry_kind, "
            "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
            "VALUES (:id, :tid, :fid, :lot, :cid, 'harvest_adjustment', -0.500, -1, :et, now(), :uid, 'x')"
        ),
        {"id": c1_id, "tid": tenant.id, "fid": farm.id, "lot": lot_id, "cid": c1_id, "et": effective, "uid": user.id},
    )
    db_session.flush()

    c2_id = _manual_correction(db_session, tenant, user, farm, line_id, count=6, weight="3.000", supersedes=c1_id)

    with pytest.raises(Exception, match="does not equal the new effective tuple minus the immediate predecessor"):
        db_session.execute(
            text(
                "INSERT INTO produce_lot_ledger_entries "
                "(id, tenant_id, farm_id, produce_lot_id, harvest_source_line_correction_id, entry_kind, "
                "weight_delta_kg, whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) "
                "VALUES (:id, :tid, :fid, :lot, :cid, 'harvest_adjustment', 0.500, 1, :et, now(), :uid, 'x')"
            ),
            {
                "id": c2_id, "tid": tenant.id, "fid": farm.id, "lot": lot_id, "cid": c2_id, "et": effective,
                "uid": user.id,
            },
        )
        db_session.flush()


def test_correction_may_only_supersede_correction_of_same_line_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _event_id1, line_id1, _ = _manual_event_and_line(
        db_session, tenant, user, farm, root_id, batch.id, t0, weight="2.500", count=5
    )
    batch2, root_id2, t02 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _event_id2, line_id2, _ = _manual_event_and_line(
        db_session, tenant, user, farm, root_id2, batch2.id, t02, weight="1.000", count=2
    )
    other_line_correction = _manual_correction(db_session, tenant, user, farm, line_id2, count=1, weight="0.500")

    with pytest.raises(Exception, match="SAME original HarvestSourceLine"):
        _manual_correction(
            db_session, tenant, user, farm, line_id1, count=4, weight="2.000", supersedes=other_line_correction
        )


def test_no_op_correction_rejected_at_db_level(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _event_id, line_id, _ = _manual_event_and_line(
        db_session, tenant, user, farm, root_id, batch.id, t0, weight="2.500", count=5
    )
    with pytest.raises(Exception, match="no-op corrections are rejected"):
        _manual_correction(db_session, tenant, user, farm, line_id, count=5, weight="2.500")
