"""NURSERY-OPS-003B: Seedling Biological Dispositions & Current Living
Quantity. Tests `seedling_disposition_service.py` (`seedling_disposition_
commands`/`seedling_disposition_events` tables) -- the immutable, insert-only
quantity-reducing ledger recorded AFTER `SeedlingEntry` (NURSERY-OPS-003A).
Not re-testing SeedlingEntry/Movement/Germination mechanics already proven in
test_seedling_entry.py/test_movement*.py/test_germination_outcome.py."""
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.schemas.farm_setup import (
    GerminationChamberSetupConfig,
    GreenhouseSetupCreate,
    NurserySectionConfig,
    NurserySetupConfig,
    TableGeneratorConfig,
)
from app.services import (
    asset_service,
    carrier_service,
    crop_service,
    farm_setup_service,
    germination_outcome_service,
    germination_service,
    membership_service,
    nursery_service,
    production_system_service,
    seedling_disposition_service,
    seedling_entry_service,
    sowing_service,
    user_service,
    workflow_service,
)
from app.services.errors import (
    InvalidSeedlingDispositionEffectiveTimeError,
    InvalidSeedlingDispositionReasonError,
    NoSeedlingEntryError,
    SeedlingDispositionAlreadyCorrectedError,
    SeedlingDispositionAssignmentReleasedError,
    SeedlingDispositionBalanceError,
    SeedlingDispositionCommandReusedWithDifferentPayloadError,
    SeedlingDispositionEventNotFoundError,
    SeedlingDispositionNotReductionError,
    SeedlingDispositionValidationError,
)
from tests._traceability_scenario import cleanup_traceability_scenario
from tests.conftest import ensure_seed_tray_specification, migrations_alembic_config, resolve_dynamic_alembic_head


def _now():
    return datetime.now(timezone.utc)


# =====================================================================
# Scenario builder
# =====================================================================


def _build_entered_scenario(
    db_session, tenant, user, farm, *, suffix=None, tray_count=1, table_count=2, table_capacity=None,
    normal=190, abnormal=6, entered_count=None,
):
    """A Batch with `tray_count` Seed Trays, the first `entered_count` (default
    all) already through SeedlingEntry (frozen starting_living_seedling_count
    = normal + abnormal), sitting on distinct Seedling Tables. Any remaining
    Trays are sown and placed in Germination but deliberately left WITHOUT a
    SeedlingEntry, for section 5's "no SeedlingEntry yet" test. Returns
    everything needed to record/correct dispositions against them."""
    entered_count = tray_count if entered_count is None else entered_count
    suffix = suffix or uuid.uuid4().hex[:8]

    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ICE-{suffix}",
        common_name="Iceberg Lettuce", scientific_name=None, crop_category="leafy_green",
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
        production_system_id=ps.id, code=f"WF-{suffix}", name="Iceberg Nursery",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding_stage = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete_stage = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding_stage.id, to_stage_id=complete_stage.id, code="ADVANCE-1", name="Advance 1",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )

    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name="Rijk Zwaan", supplier_lot_reference="RZ-001",
        received_date=None, expiry_date=None,
    )

    setup = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"NUR-{suffix}", name="Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(
                seeding_station=NurserySectionConfig(code=f"SEED-{suffix}"),
                germination_chamber=GerminationChamberSetupConfig(code=f"GC-{suffix}", trolley_capacity=None),
                seedling_tables=TableGeneratorConfig(
                    code_prefix=f"ST{suffix[:4]}", start=1, end=table_count, pad_width=2, capacity=table_capacity
                ),
            ),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    seeding_station_id = structure.nursery_seeding_stations[0].id
    chamber_id = structure.nursery_germination_chamber.id
    table_ids = [t.id for t in structure.nursery_seedling.tables]

    trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=f"GT-{suffix}", name="Trolley", commissioned_date=None,
    )
    asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=2, slots_per_shelf=4, shelf_prefix=f"SH-{suffix}-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )

    seed_tray_spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carriers = [
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id, code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        for n in range(1, tray_count + 1)
    ]

    sow_time = _now() - timedelta(days=5)
    event = nursery_service.sow_new_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        seed_lot_id=seed_lot.id, seeding_station_id=seeding_station_id, seeding_machine_id=None,
        effective_time=sow_time, note=None,
        trays=[{"carrier_id": c.id, "sown_site_count": 200, "seeds_sown": 200} for c in carriers],
    )
    germination_service.place_trolley_in_chamber(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        trolley_id=trolley.id, chamber_id=chamber_id, effective_time=sow_time + timedelta(minutes=5), reason=None,
    )
    slots = list(
        db_session.execute(
            text("SELECT id FROM asset_positions WHERE asset_id = :aid AND position_kind = 'slot' ORDER BY code"),
            {"aid": trolley.id},
        ).scalars()
    )

    assignments = sowing_service.list_batch_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=event.batch_id
    )
    assignment_by_carrier_code = {a.carrier.code: a.id for a in assignments}
    assignment_ids = [assignment_by_carrier_code[c.code] for c in carriers]

    germination_time = sow_time + timedelta(days=1)
    entry_time = sow_time + timedelta(days=4)
    entry_ids = []
    for i, carrier in enumerate(carriers):
        germination_service.place_tray(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            tray_id=carrier.id, trolley_id=trolley.id, asset_position_id=slots[i], effective_time=germination_time,
            reason=None,
        )
        germination_outcome_service.record_germination_outcomes(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=event.batch_id,
            client_command_id=uuid.uuid4(), effective_time=germination_time + timedelta(hours=1), note=None,
            outcomes=[
                {
                    "batch_carrier_assignment_id": assignment_ids[i], "normal_seedling_count": normal,
                    "abnormal_seedling_count": abnormal, "assessment_complete": True, "note": None,
                }
            ],
        )
        if i < entered_count:
            entry = seedling_entry_service.record_seedling_entry(
                db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                batch_carrier_assignment_id=assignment_ids[i], destination_seedling_table_id=table_ids[i % len(table_ids)],
                effective_time=entry_time, reason=None,
            )
            entry_ids.append(entry.id)

    return {
        "batch_id": event.batch_id, "carriers": carriers, "assignment_ids": assignment_ids,
        "table_ids": table_ids, "entry_ids": entry_ids, "entry_time": entry_time, "sow_time": sow_time,
        "starting": normal + abnormal,
    }


def _record(
    db_session, tenant, user, farm, *, assignment_id, quantity, reason_code="WEAK_SEEDLING", effective_time=None,
    note=None, client_command_id=None,
):
    return seedling_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=client_command_id or uuid.uuid4(), batch_carrier_assignment_id=assignment_id,
        quantity=quantity, reason_code=reason_code, effective_time=effective_time or _now(), note=note,
    )


def _correct(
    db_session, tenant, user, farm, *, target_event_id, corrected=None, client_command_id=None,
):
    return seedling_disposition_service.correct_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=client_command_id or uuid.uuid4(), target_event_id=target_event_id, corrected=corrected,
    )


def _reduction_event_id(db_session, command_id):
    return db_session.execute(
        text("SELECT id FROM seedling_disposition_events WHERE command_id = :cid AND event_kind = 'REDUCTION'"),
        {"cid": command_id},
    ).scalar_one()


def _current_balance_for_entry(db_session, seedling_entry_id):
    starting = db_session.execute(
        text("SELECT starting_living_seedling_count FROM seedling_entries WHERE id = :eid"),
        {"eid": seedling_entry_id},
    ).scalar_one()
    delta_sum = db_session.execute(
        text("SELECT COALESCE(SUM(quantity_delta), 0) FROM seedling_disposition_events WHERE seedling_entry_id = :eid"),
        {"eid": seedling_entry_id},
    ).scalar_one()
    return starting + delta_sum


def _audit_count(db_session, tenant_id, action):
    return db_session.execute(
        text("SELECT count(*) FROM audit_events WHERE tenant_id = :tid AND action = :action"),
        {"tid": tenant_id, "action": action},
    ).scalar_one()


def _release_assignment_via_split(db_session, tenant, user, farm, s, *, assignment_index=0, other_index=1, effective_time=None):
    """Genuinely releases `s['assignment_ids'][assignment_index]`.

    `batch_derivation_service.split_batch` and `transplant_service` were
    both tried first and both genuinely cannot release a nursery-sown Seed
    Tray's assignment: NURSERY-OPS-001.1 deliberately records nursery
    sowing lines with `sown_site_count=NULL` ("sown site/cell count is a
    separately-observed fact this command never asks for" -- seed_count is
    the only quantity supplied), and both `_derive_transferred_quantity`
    (batch_derivation_service.py) and the transplant source-line check
    (transplant_service.py) require a non-NULL `sown_site_count` to resolve
    a transferred/source quantity. This is a genuine, real gap: as of this
    ticket, no domain command in the codebase can release a nursery Tray's
    BatchCarrierAssignment (matches section 1.E's own premise that release
    of a Seedling Tray assignment awaits a future InterSalads/InterVines
    handoff ticket).

    So this constructs the minimal valid `batch_derivation_events` row the
    DB's `enforce_batch_carrier_assignment_closure_only_v2` trigger requires
    for its non-transplant release branch (existence + matching
    `effective_time` only -- full source/output reconciliation is a
    DEFERRED constraint trigger that only fires at real COMMIT, which these
    SAVEPOINT-scoped tests never reach), then releases the assignment
    directly. This is test-fixture plumbing to reach an otherwise-legitimate
    DB/service state, not a simulated business transaction."""
    eff = effective_time or _now()
    stage_row = db_session.execute(
        text(
            "SELECT wv.workflow_id, bsr.workflow_version_id, bsr.workflow_stage_id "
            "FROM batch_stage_runs bsr JOIN workflow_versions wv ON wv.id = bsr.workflow_version_id "
            "WHERE bsr.batch_id = :bid AND bsr.exited_effective_time IS NULL"
        ),
        {"bid": s["batch_id"]},
    ).one()
    event_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO batch_derivation_events "
            "(id, tenant_id, farm_id, derivation_kind, workflow_id, workflow_version_id, "
            "inherited_workflow_stage_id, effective_time, actor_user_id, client_command_id, request_fingerprint) "
            "VALUES (:id, :tid, :fid, 'split', :wf, :wfv, :stage, :eff, :uid, :ccid, 'x')"
        ),
        {
            "id": event_id, "tid": tenant.id, "fid": farm.id, "wf": stage_row.workflow_id,
            "wfv": stage_row.workflow_version_id, "stage": stage_row.workflow_stage_id, "eff": eff,
            "uid": user.id, "ccid": uuid.uuid4(),
        },
    )
    db_session.execute(
        text(
            "UPDATE batch_carrier_assignments SET released_effective_time = :eff, "
            "released_by_batch_derivation_event_id = :evid WHERE id = :aid"
        ),
        {"eff": eff, "evid": event_id, "aid": s["assignment_ids"][assignment_index]},
    )
    db_session.flush()


# =====================================================================
# Reason catalog (section 10/13/14)
# =====================================================================


@pytest.mark.integration
def test_approved_reasons_seeded_exactly(db_session) -> None:
    codes = set(
        db_session.execute(text("SELECT code FROM seedling_disposition_reasons")).scalars()
    )
    assert codes == {
        "WEAK_SEEDLING", "DISEASE", "PEST_DAMAGE", "PHYSICAL_DAMAGE", "MORTALITY", "QC_REJECTION", "SAMPLE", "OTHER",
    }
    assert "NON_GERMINATION" not in codes
    assert "TRANSPLANT_DAMAGE" not in codes


# =====================================================================
# Record (section 77)
# =====================================================================


@pytest.mark.integration
def test_record_sequence_matches_ticket_example(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    t1 = s["entry_time"] + timedelta(hours=1)
    r1 = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=4, reason_code="WEAK_SEEDLING", effective_time=t1)
    result1 = seedling_disposition_service.describe_record_result(db_session, command=r1)
    assert result1.resulting_living_seedling_count == 192

    t2 = t1 + timedelta(hours=1)
    r2 = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=3, reason_code="DISEASE", effective_time=t2)
    result2 = seedling_disposition_service.describe_record_result(db_session, command=r2)
    assert result2.resulting_living_seedling_count == 189


@pytest.mark.integration
def test_mortality_reduces_without_movement(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=2, reason_code="MORTALITY", effective_time=s["entry_time"] + timedelta(hours=1))
    result = seedling_disposition_service.describe_record_result(db_session, command=command)
    assert result.resulting_living_seedling_count == s["starting"] - 2


@pytest.mark.integration
def test_sample_reduces_balance(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=2, reason_code="SAMPLE", effective_time=s["entry_time"] + timedelta(hours=1))
    result = seedling_disposition_service.describe_record_result(db_session, command=command)
    assert result.resulting_living_seedling_count == s["starting"] - 2


@pytest.mark.integration
def test_qc_rejection_explicit_event_reduces_balance(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=5, reason_code="QC_REJECTION", effective_time=s["entry_time"] + timedelta(hours=1))
    result = seedling_disposition_service.describe_record_result(db_session, command=command)
    assert result.resulting_living_seedling_count == s["starting"] - 5


@pytest.mark.integration
def test_other_requires_note(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    with pytest.raises(SeedlingDispositionValidationError):
        _record(db_session, tenant, user, farm, assignment_id=aid, quantity=1, reason_code="OTHER", effective_time=s["entry_time"] + timedelta(hours=1), note=None)
    with pytest.raises(SeedlingDispositionValidationError):
        _record(db_session, tenant, user, farm, assignment_id=aid, quantity=1, reason_code="OTHER", effective_time=s["entry_time"] + timedelta(hours=1), note="   ")
    command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=1, reason_code="OTHER", effective_time=s["entry_time"] + timedelta(hours=1), note="genuinely unusual case")
    assert command is not None


@pytest.mark.integration
def test_excluded_reasons_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    for bad_code in ("NON_GERMINATION", "TRANSPLANT_DAMAGE", "NOT_A_REAL_CODE"):
        with pytest.raises(InvalidSeedlingDispositionReasonError):
            _record(db_session, tenant, user, farm, assignment_id=aid, quantity=1, reason_code=bad_code, effective_time=s["entry_time"] + timedelta(hours=1))


@pytest.mark.integration
def test_quantity_zero_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    with pytest.raises(Exception):
        seedling_disposition_service.record_disposition(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            batch_carrier_assignment_id=aid, quantity=0, reason_code="WEAK_SEEDLING",
            effective_time=s["entry_time"] + timedelta(hours=1), note=None,
        )


@pytest.mark.integration
def test_quantity_exceeding_remaining_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    with pytest.raises(SeedlingDispositionBalanceError):
        _record(db_session, tenant, user, farm, assignment_id=aid, quantity=s["starting"] + 1, effective_time=s["entry_time"] + timedelta(hours=1))


@pytest.mark.integration
def test_quantity_exactly_remaining_reaches_zero(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    effective_time = s["entry_time"] + timedelta(hours=1)
    command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=s["starting"], effective_time=effective_time)
    result = seedling_disposition_service.describe_record_result(db_session, command=command)
    assert result.resulting_living_seedling_count == 0

    # SEEDLING-DISPOSITION-LIFECYCLE-001: exact exhaustion now releases the
    # current active assignment, typed by exactly this REDUCTION.
    assignment = db_session.execute(
        text(
            "SELECT released_effective_time, released_by_seedling_disposition_event_id "
            "FROM batch_carrier_assignments WHERE id = :aid"
        ),
        {"aid": aid},
    ).mappings().first()
    assert assignment["released_effective_time"] == effective_time
    assert assignment["released_by_seedling_disposition_event_id"] == result.event.id


@pytest.mark.integration
def test_partial_disposition_does_not_release(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, normal=10, abnormal=0)
    aid = s["assignment_ids"][0]
    _record(db_session, tenant, user, farm, assignment_id=aid, quantity=5, effective_time=s["entry_time"] + timedelta(hours=1))
    assignment = db_session.execute(
        text("SELECT released_effective_time FROM batch_carrier_assignments WHERE id = :aid"), {"aid": aid}
    ).mappings().first()
    assert assignment["released_effective_time"] is None


@pytest.mark.integration
def test_exact_replay_of_exhausting_record_does_not_double_release(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, normal=10, abnormal=0)
    aid = s["assignment_ids"][0]
    et = s["entry_time"] + timedelta(hours=1)
    ccid = uuid.uuid4()
    first = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=10, effective_time=et, client_command_id=ccid)
    replay = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=10, effective_time=et, client_command_id=ccid)
    assert replay.id == first.id

    events = db_session.execute(
        text("SELECT count(*) FROM seedling_disposition_events WHERE command_id = :cid"), {"cid": first.id}
    ).scalar_one()
    assert events == 1
    assignment = db_session.execute(
        text("SELECT released_effective_time FROM batch_carrier_assignments WHERE id = :aid"), {"aid": aid}
    ).mappings().first()
    assert assignment["released_effective_time"] == et


@pytest.mark.integration
def test_no_seedling_entry_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, tray_count=2, entered_count=1)
    not_entered_assignment_id = s["assignment_ids"][1]
    with pytest.raises(NoSeedlingEntryError):
        _record(db_session, tenant, user, farm, assignment_id=not_entered_assignment_id, quantity=1, effective_time=s["entry_time"] + timedelta(hours=1))


# =====================================================================
# Observation separation (section 78)
# =====================================================================


@pytest.mark.integration
def test_germination_reassessment_after_entry_does_not_change_disposition_balance(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=4, effective_time=s["entry_time"] + timedelta(hours=1))
    result = seedling_disposition_service.describe_record_result(db_session, command=command)
    assert result.resulting_living_seedling_count == s["starting"] - 4

    # A later completed Germination reassessment (legal under 002B/003A's
    # own historical model) must never rewrite the frozen SeedlingEntry or
    # the disposition balance built on top of it.
    germination_outcome_service.record_germination_outcomes(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=s["entry_time"] - timedelta(hours=1), note=None,
        outcomes=[{"batch_carrier_assignment_id": aid, "normal_seedling_count": 200, "abnormal_seedling_count": 0, "assessment_complete": True, "note": None}],
    )
    starting = db_session.execute(text("SELECT starting_living_seedling_count FROM seedling_entries WHERE id = :id"), {"id": s["entry_ids"][0]}).scalar_one()
    total_delta = db_session.execute(text("SELECT COALESCE(SUM(quantity_delta), 0) FROM seedling_disposition_events WHERE seedling_entry_id = :id"), {"id": s["entry_ids"][0]}).scalar_one()
    assert starting + total_delta == s["starting"] - 4


# =====================================================================
# Correction / void (section 79/80)
# =====================================================================


@pytest.mark.integration
def test_correction_replaces_with_new_quantity(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    t1 = s["entry_time"] + timedelta(hours=1)
    r_command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=10, reason_code="WEAK_SEEDLING", effective_time=t1)
    e1_id = _reduction_event_id(db_session, r_command.id)
    result1 = seedling_disposition_service.describe_record_result(db_session, command=r_command)
    assert result1.resulting_living_seedling_count == s["starting"] - 10

    c_command = _correct(db_session, tenant, user, farm, target_event_id=e1_id, corrected={"quantity": 6, "reason_code": "WEAK_SEEDLING", "effective_time": t1, "note": None})
    correct_result = seedling_disposition_service.describe_correct_result(db_session, command=c_command)
    assert correct_result.resulting_living_seedling_count == s["starting"] - 6
    assert correct_result.target_event.id == e1_id
    assert correct_result.reversal_event.reverses_event_id == e1_id
    assert correct_result.reversal_event.quantity_delta == 10
    assert correct_result.replacement_event.corrects_event_id == e1_id
    assert correct_result.replacement_event.quantity_delta == -6

    # E1 unchanged.
    e1_delta = db_session.execute(text("SELECT quantity_delta FROM seedling_disposition_events WHERE id = :id"), {"id": e1_id}).scalar_one()
    assert e1_delta == -10

    # E2 (replacement) can later itself be corrected once.
    e2_id = correct_result.replacement_event.id
    c2_command = _correct(db_session, tenant, user, farm, target_event_id=e2_id, corrected={"quantity": 4, "reason_code": "DISEASE", "effective_time": t1, "note": None})
    correct_result2 = seedling_disposition_service.describe_correct_result(db_session, command=c2_command)
    assert correct_result2.resulting_living_seedling_count == s["starting"] - 4

    # E1 cannot be corrected again.
    with pytest.raises(SeedlingDispositionAlreadyCorrectedError):
        _correct(db_session, tenant, user, farm, target_event_id=e1_id, corrected={"quantity": 1, "reason_code": "WEAK_SEEDLING", "effective_time": t1, "note": None})

    # R1 (the first reversal) cannot itself be corrected.
    r1_id = correct_result.reversal_event.id
    with pytest.raises(SeedlingDispositionNotReductionError):
        _correct(db_session, tenant, user, farm, target_event_id=r1_id, corrected=None)


@pytest.mark.integration
def test_void_creates_reversal_only(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    t1 = s["entry_time"] + timedelta(hours=1)
    r_command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=10, effective_time=t1)
    e1_id = _reduction_event_id(db_session, r_command.id)

    c_command = _correct(db_session, tenant, user, farm, target_event_id=e1_id, corrected=None)
    result = seedling_disposition_service.describe_correct_result(db_session, command=c_command)
    assert result.resulting_living_seedling_count == s["starting"]
    assert result.replacement_event is None

    # No zero-quantity event was created.
    zero_events = db_session.execute(
        text("SELECT count(*) FROM seedling_disposition_events WHERE quantity_delta = 0")
    ).scalar_one()
    assert zero_events == 0
    total_events = db_session.execute(
        text("SELECT count(*) FROM seedling_disposition_events WHERE command_id = :cid"), {"cid": c_command.id}
    ).scalar_one()
    assert total_events == 1


# =====================================================================
# Same-time group / historical prefix (section 81/82)
# =====================================================================


@pytest.mark.integration
def test_same_effective_time_group_nets_regardless_of_order(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    t1 = s["entry_time"] + timedelta(hours=1)
    r_command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=10, effective_time=t1)
    e1_id = _reduction_event_id(db_session, r_command.id)
    # Correction shares E1's own effective_time (reversal is required to).
    c_command = _correct(db_session, tenant, user, farm, target_event_id=e1_id, corrected={"quantity": 6, "reason_code": "WEAK_SEEDLING", "effective_time": t1, "note": None})
    result = seedling_disposition_service.describe_correct_result(db_session, command=c_command)
    # Net for the t1 group: -10 (E1) +10 (R1) -6 (E2) = -6, regardless of
    # insertion order (E1 before R1 before E2 -- verified this still nets
    # correctly, proving group-based, not order-based, validity).
    assert result.resulting_living_seedling_count == s["starting"] - 6


@pytest.mark.integration
def test_late_historical_reduction_rejected_when_it_would_overdraw(db_session, active_context_with_farm) -> None:
    """Section 27/82: a late-entered historical REDUCTION, dated BEFORE an
    already-recorded later REDUCTION, is rejected once the combined
    chronological sequence would ever go negative -- proven via the full
    grouped/chronological walk (not a naive order-insensitive sum), even
    though (as it happens here) the resulting aggregate is negative too:
    the walk is what proves it correctly regardless of insertion order."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, normal=10, abnormal=0)
    aid = s["assignment_ids"][0]
    t1 = s["entry_time"] + timedelta(hours=1)
    _record(db_session, tenant, user, farm, assignment_id=aid, quantity=8, effective_time=t1)  # -> 2
    t0 = s["entry_time"] + timedelta(minutes=30)
    with pytest.raises(SeedlingDispositionBalanceError):
        _record(db_session, tenant, user, farm, assignment_id=aid, quantity=5, effective_time=t0)


@pytest.mark.integration
def test_late_reduction_after_correction_succeeds_when_truthfully_nonnegative(db_session, active_context_with_farm) -> None:
    """Section 27's own 'harder' example, resolved by this ticket's own
    explicit mechanics (section 0.D/19): a REVERSAL always shares its
    target's own effective_time exactly, so a corrected REDUCTION's history
    collapses to plain chronological arithmetic -- there is no separate
    'restoration time' capable of masking an intermediate dip. start=10,
    remove 8 at T1, corrected down to 3 at T1 (still T1, per section 0.D) ->
    current=7; a later historical removal of 4 dated between T1 and now is
    genuinely safe (10-3-4=7-4=3, non-negative at every chronological
    point) and must succeed -- proving the design doesn't over-reject a
    truthfully valid late entry just because a correction touched this Tray."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, normal=10, abnormal=0)
    aid = s["assignment_ids"][0]
    t1 = s["entry_time"] + timedelta(hours=1)
    t1_5 = s["entry_time"] + timedelta(hours=12)

    r_command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=8, effective_time=t1)
    e1_id = _reduction_event_id(db_session, r_command.id)
    _correct(db_session, tenant, user, farm, target_event_id=e1_id, corrected={"quantity": 3, "reason_code": "WEAK_SEEDLING", "effective_time": t1, "note": None})
    # current = 10 - 3 = 7

    command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=4, effective_time=t1_5)
    result = seedling_disposition_service.describe_record_result(db_session, command=command)
    assert result.resulting_living_seedling_count == 3


# =====================================================================
# DB direct-write integrity (section 76)
# =====================================================================


def _raw_command(db_session, tenant, farm, s, *, operation_kind="RECORD", target_event_id=None, assignment_index=0):
    # SEEDLING-DISPOSITION-LIFECYCLE-001: every new command requires a valid
    # active_batch_stage_run_id -- resolved inline via the batch's own
    # currently-open BatchStageRun, exactly what the service layer does.
    cid = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO seedling_disposition_commands "
            "(id, tenant_id, farm_id, batch_id, seedling_entry_id, operation_kind, target_event_id, "
            "actor_user_id, client_command_id, request_fingerprint, active_batch_stage_run_id) "
            "VALUES (:id, :tid, :fid, :bid, :eid, :kind, :tgt, NULL, :ccid, 'x', "
            "(SELECT id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL))"
        ),
        {
            "id": cid, "tid": tenant.id, "fid": farm.id, "bid": s["batch_id"],
            "eid": s["entry_ids"][assignment_index], "kind": operation_kind, "tgt": target_event_id, "ccid": uuid.uuid4(),
        },
    )
    db_session.flush()
    return cid


def _raw_event(db_session, tenant, farm, s, *, command_id, event_kind="REDUCTION", reason_code="WEAK_SEEDLING", quantity_delta=-1, effective_time=None, note=None, reverses_event_id=None, corrects_event_id=None, entry_index=0):
    eid = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO seedling_disposition_events "
            "(id, tenant_id, farm_id, command_id, seedling_entry_id, event_kind, reason_code, quantity_delta, "
            "effective_time, note, reverses_event_id, corrects_event_id) "
            "VALUES (:id, :tid, :fid, :cid, :eid, :kind, :reason, :qd, :eff, :note, :rev, :cor)"
        ),
        {
            "id": eid, "tid": tenant.id, "fid": farm.id, "cid": command_id, "eid": s["entry_ids"][entry_index],
            "kind": event_kind, "reason": reason_code, "qd": quantity_delta,
            "eff": effective_time or (s["entry_time"] + timedelta(hours=1)), "note": note,
            "rev": reverses_event_id, "cor": corrects_event_id,
        },
    )
    db_session.flush()
    return eid


@pytest.mark.integration
def test_direct_write_negative_balance_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, normal=10, abnormal=0)
    cid = _raw_command(db_session, tenant, farm, s)
    with pytest.raises(DBAPIError, match="chronological balance violated"):
        _raw_event(db_session, tenant, farm, s, command_id=cid, quantity_delta=-11)
    db_session.rollback()


# Note: an ">starting quantity" chronological-balance violation is not
# independently direct-SQL-reachable in this design without ALSO tripping
# the reversal-exact-negation check first (the only way to insert a
# positive delta is a REVERSAL, and REVERSAL is pinned to exactly negate
# its named target -- proven by `test_direct_write_mismatched_reversal_
# amount_rejected` below). The upper-bound branch in the trigger remains
# defense-in-depth for a future design change, not independently testable
# via a realistic bypass today.


@pytest.mark.integration
def test_direct_write_wrong_seedling_entry_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, tray_count=2)
    cid = _raw_command(db_session, tenant, farm, s, assignment_index=0)
    with pytest.raises(DBAPIError, match="does not belong to the same seedling entry"):
        db_session.execute(
            text(
                "INSERT INTO seedling_disposition_events "
                "(id, tenant_id, farm_id, command_id, seedling_entry_id, event_kind, reason_code, quantity_delta, effective_time) "
                "VALUES (gen_random_uuid(), :tid, :fid, :cid, :eid, 'REDUCTION', 'WEAK_SEEDLING', -1, :eff)"
            ),
            {"tid": tenant.id, "fid": farm.id, "cid": cid, "eid": s["entry_ids"][1], "eff": s["entry_time"] + timedelta(hours=1)},
        )
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_predates_seedling_entry_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    cid = _raw_command(db_session, tenant, farm, s)
    with pytest.raises(DBAPIError, match="precedes the SeedlingEntry"):
        _raw_event(db_session, tenant, farm, s, command_id=cid, effective_time=s["entry_time"] - timedelta(hours=1))
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_after_assignment_release_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, tray_count=2)
    _release_assignment_via_split(db_session, tenant, user, farm, s, assignment_index=0, other_index=1)
    # The command-level trigger already rejects a NEW command targeting a
    # released assignment's SeedlingEntry -- proven here directly (this
    # also implicitly proves no event insert could ever be attempted).
    with pytest.raises(DBAPIError, match="already been released"):
        _raw_command(db_session, tenant, farm, s, assignment_index=0)
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_other_without_note_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    cid = _raw_command(db_session, tenant, farm, s)
    with pytest.raises(DBAPIError):
        _raw_event(db_session, tenant, farm, s, command_id=cid, reason_code="OTHER", note=None)
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_arbitrary_positive_reduction_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    cid = _raw_command(db_session, tenant, farm, s)
    with pytest.raises(DBAPIError):
        _raw_event(db_session, tenant, farm, s, command_id=cid, event_kind="REDUCTION", quantity_delta=5)
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_reversal_without_target_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    cid = _raw_command(db_session, tenant, farm, s)
    with pytest.raises(DBAPIError):
        _raw_event(db_session, tenant, farm, s, command_id=cid, event_kind="REVERSAL", quantity_delta=5, reverses_event_id=None)
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_reverse_a_reversal_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    r_command = _record(db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], quantity=5, effective_time=s["entry_time"] + timedelta(hours=1))
    e1_id = _reduction_event_id(db_session, r_command.id)
    c_command = _correct(db_session, tenant, user, farm, target_event_id=e1_id, corrected=None)
    r1_id = db_session.execute(text("SELECT id FROM seedling_disposition_events WHERE command_id = :cid"), {"cid": c_command.id}).scalar_one()

    cid = _raw_command(db_session, tenant, farm, s, operation_kind="CORRECT", target_event_id=r1_id)
    with pytest.raises(DBAPIError, match="only a REDUCTION event may be reversed"):
        _raw_event(db_session, tenant, farm, s, command_id=cid, event_kind="REVERSAL", quantity_delta=-5, effective_time=s["entry_time"] + timedelta(hours=1), reverses_event_id=r1_id)
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_reverse_same_event_twice_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    r_command = _record(db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], quantity=5, effective_time=s["entry_time"] + timedelta(hours=1))
    e1_id = _reduction_event_id(db_session, r_command.id)
    _correct(db_session, tenant, user, farm, target_event_id=e1_id, corrected=None)

    cid = _raw_command(db_session, tenant, farm, s, operation_kind="CORRECT", target_event_id=e1_id)
    with pytest.raises(DBAPIError):
        _raw_event(db_session, tenant, farm, s, command_id=cid, event_kind="REVERSAL", quantity_delta=5, effective_time=s["entry_time"] + timedelta(hours=1), reverses_event_id=e1_id)
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_mismatched_reversal_amount_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    r_command = _record(db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], quantity=5, effective_time=s["entry_time"] + timedelta(hours=1))
    e1_id = _reduction_event_id(db_session, r_command.id)
    cid = _raw_command(db_session, tenant, farm, s, operation_kind="CORRECT", target_event_id=e1_id)
    with pytest.raises(DBAPIError, match="exact negation"):
        _raw_event(db_session, tenant, farm, s, command_id=cid, event_kind="REVERSAL", quantity_delta=4, effective_time=s["entry_time"] + timedelta(hours=1), reverses_event_id=e1_id)
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_mismatched_reversal_reason_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    r_command = _record(db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], quantity=5, reason_code="WEAK_SEEDLING", effective_time=s["entry_time"] + timedelta(hours=1))
    e1_id = _reduction_event_id(db_session, r_command.id)
    cid = _raw_command(db_session, tenant, farm, s, operation_kind="CORRECT", target_event_id=e1_id)
    with pytest.raises(DBAPIError, match="must match the target event"):
        _raw_event(db_session, tenant, farm, s, command_id=cid, event_kind="REVERSAL", reason_code="DISEASE", quantity_delta=5, effective_time=s["entry_time"] + timedelta(hours=1), reverses_event_id=e1_id)
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_mismatched_reversal_effective_time_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    r_command = _record(db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], quantity=5, effective_time=s["entry_time"] + timedelta(hours=1))
    e1_id = _reduction_event_id(db_session, r_command.id)
    cid = _raw_command(db_session, tenant, farm, s, operation_kind="CORRECT", target_event_id=e1_id)
    with pytest.raises(DBAPIError, match="must match the target event"):
        _raw_event(db_session, tenant, farm, s, command_id=cid, event_kind="REVERSAL", quantity_delta=5, effective_time=s["entry_time"] + timedelta(hours=2), reverses_event_id=e1_id)
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_cross_entry_correction_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, tray_count=2)
    r_command = _record(db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], quantity=5, effective_time=s["entry_time"] + timedelta(hours=1))
    e1_id = _reduction_event_id(db_session, r_command.id)
    # A command scoped to the SECOND tray's seedling_entry, but targeting
    # the FIRST tray's event -- rejected at the COMMAND-integrity trigger
    # itself, before any event could ever be attempted.
    with pytest.raises(DBAPIError, match="does not belong to this seedling entry"):
        _raw_command(db_session, tenant, farm, s, operation_kind="CORRECT", target_event_id=e1_id, assignment_index=1)
    db_session.rollback()


@pytest.mark.integration
def test_direct_write_update_and_delete_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    r_command = _record(db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], quantity=5, effective_time=s["entry_time"] + timedelta(hours=1))
    e1_id = _reduction_event_id(db_session, r_command.id)
    with pytest.raises(DBAPIError):
        db_session.execute(text("UPDATE seedling_disposition_events SET quantity_delta = -1 WHERE id = :id"), {"id": e1_id})
        db_session.flush()
    db_session.rollback()
    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM seedling_disposition_events WHERE id = :id"), {"id": e1_id})
        db_session.flush()
    db_session.rollback()
    with pytest.raises(DBAPIError):
        db_session.execute(text("UPDATE seedling_disposition_commands SET operation_kind = 'CORRECT' WHERE id = :id"), {"id": r_command.id})
        db_session.flush()
    db_session.rollback()


# =====================================================================
# Active/released assignment (section 83)
# =====================================================================


@pytest.mark.integration
def test_active_assignment_allows_new_disposition(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    command = _record(db_session, tenant, user, farm, assignment_id=s["assignment_ids"][0], quantity=1, effective_time=s["entry_time"] + timedelta(hours=1))
    assert command is not None


@pytest.mark.integration
def test_released_assignment_rejects_new_record_even_with_historical_time(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, tray_count=2)
    aid = s["assignment_ids"][0]
    historical_time = s["entry_time"] + timedelta(hours=1)
    _release_assignment_via_split(db_session, tenant, user, farm, s, assignment_index=0, other_index=1)
    with pytest.raises(SeedlingDispositionAssignmentReleasedError):
        _record(db_session, tenant, user, farm, assignment_id=aid, quantity=1, effective_time=historical_time)


@pytest.mark.integration
def test_released_assignment_rejects_new_correction(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, tray_count=2)
    aid = s["assignment_ids"][0]
    r_command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=5, effective_time=s["entry_time"] + timedelta(hours=1))
    e1_id = _reduction_event_id(db_session, r_command.id)
    _release_assignment_via_split(db_session, tenant, user, farm, s, assignment_index=0, other_index=1)
    with pytest.raises(SeedlingDispositionAssignmentReleasedError):
        _correct(db_session, tenant, user, farm, target_event_id=e1_id, corrected=None)


@pytest.mark.integration
def test_replay_of_pre_release_record_succeeds_after_release(db_session, active_context_with_farm) -> None:
    """NURSERY-OPS-003B.1 section 3: exact replay after release must return
    the ORIGINAL command/event verbatim -- same command id, same event id,
    event count and audit trail unchanged, no biological history change --
    never fail the new current-assignment-active safeguard."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, tray_count=2)
    aid = s["assignment_ids"][0]
    ccid = uuid.uuid4()
    original = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=5, effective_time=s["entry_time"] + timedelta(hours=1), client_command_id=ccid)
    original_event_id = _reduction_event_id(db_session, original.id)
    balance_before = _current_balance_for_entry(db_session, s["entry_ids"][0])
    audit_before = _audit_count(db_session, tenant.id, "crop_batch.seedling_disposition_recorded")

    _release_assignment_via_split(db_session, tenant, user, farm, s, assignment_index=0, other_index=1)

    replay = seedling_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        batch_carrier_assignment_id=aid, quantity=5, reason_code="WEAK_SEEDLING",
        effective_time=s["entry_time"] + timedelta(hours=1), note=None,
    )
    assert replay.id == original.id
    assert _reduction_event_id(db_session, replay.id) == original_event_id
    event_count = db_session.execute(
        text("SELECT count(*) FROM seedling_disposition_events WHERE seedling_entry_id = :eid"),
        {"eid": s["entry_ids"][0]},
    ).scalar_one()
    assert event_count == 1
    assert _current_balance_for_entry(db_session, s["entry_ids"][0]) == balance_before
    assert _audit_count(db_session, tenant.id, "crop_batch.seedling_disposition_recorded") == audit_before


@pytest.mark.integration
def test_replay_of_pre_release_correction_succeeds_after_release(db_session, active_context_with_farm) -> None:
    """NURSERY-OPS-003B.1 section 5: exact correction replay after release
    must return the ORIGINAL reversal (and replacement, if any) verbatim --
    same command id, same reversal id, no second reversal, no new audit
    event -- despite the assignment now being released."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, tray_count=2)
    aid = s["assignment_ids"][0]
    r_command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=5, effective_time=s["entry_time"] + timedelta(hours=1))
    e1_id = _reduction_event_id(db_session, r_command.id)
    ccid = uuid.uuid4()
    original = _correct(db_session, tenant, user, farm, target_event_id=e1_id, corrected=None, client_command_id=ccid)
    original_reversal_id = db_session.execute(
        text("SELECT id FROM seedling_disposition_events WHERE command_id = :cid AND event_kind = 'REVERSAL'"),
        {"cid": original.id},
    ).scalar_one()
    balance_before = _current_balance_for_entry(db_session, s["entry_ids"][0])
    audit_before = _audit_count(db_session, tenant.id, "crop_batch.seedling_disposition_corrected")

    _release_assignment_via_split(db_session, tenant, user, farm, s, assignment_index=0, other_index=1)

    replay = seedling_disposition_service.correct_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        target_event_id=e1_id, corrected=None,
    )
    assert replay.id == original.id
    replay_reversal_id = db_session.execute(
        text("SELECT id FROM seedling_disposition_events WHERE command_id = :cid AND event_kind = 'REVERSAL'"),
        {"cid": replay.id},
    ).scalar_one()
    assert replay_reversal_id == original_reversal_id
    reversal_count = db_session.execute(
        text("SELECT count(*) FROM seedling_disposition_events WHERE reverses_event_id = :eid"), {"eid": e1_id}
    ).scalar_one()
    assert reversal_count == 1
    assert _current_balance_for_entry(db_session, s["entry_ids"][0]) == balance_before
    assert _audit_count(db_session, tenant.id, "crop_batch.seedling_disposition_corrected") == audit_before


# =====================================================================
# Idempotency (section 38/39)
# =====================================================================


@pytest.mark.integration
def test_record_exact_replay_returns_same_command(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    ccid = uuid.uuid4()
    eff = s["entry_time"] + timedelta(hours=1)
    audit_before = _audit_count(db_session, tenant.id, "crop_batch.seedling_disposition_recorded")
    first = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=4, effective_time=eff, client_command_id=ccid)
    first_event_id = _reduction_event_id(db_session, first.id)
    second = seedling_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        batch_carrier_assignment_id=aid, quantity=4, reason_code="WEAK_SEEDLING", effective_time=eff, note=None,
    )
    assert first.id == second.id
    assert _reduction_event_id(db_session, second.id) == first_event_id
    count = db_session.execute(text("SELECT count(*) FROM seedling_disposition_events WHERE command_id = :cid"), {"cid": first.id}).scalar_one()
    assert count == 1
    # Replaying an already-successful RECORD must never emit a second audit
    # event -- the replay branch (fingerprint match) returns before
    # `append_audit_event` is ever reached a second time.
    assert _audit_count(db_session, tenant.id, "crop_batch.seedling_disposition_recorded") == audit_before + 1


@pytest.mark.integration
def test_record_reused_command_id_different_payload_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    ccid = uuid.uuid4()
    eff = s["entry_time"] + timedelta(hours=1)
    _record(db_session, tenant, user, farm, assignment_id=aid, quantity=4, effective_time=eff, client_command_id=ccid)
    with pytest.raises(SeedlingDispositionCommandReusedWithDifferentPayloadError):
        seedling_disposition_service.record_disposition(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
            batch_carrier_assignment_id=aid, quantity=5, reason_code="WEAK_SEEDLING", effective_time=eff, note=None,
        )


@pytest.mark.integration
def test_correction_exact_replay_returns_same_command_no_duplicate_rows(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    r_command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=10, effective_time=s["entry_time"] + timedelta(hours=1))
    e1_id = _reduction_event_id(db_session, r_command.id)
    ccid = uuid.uuid4()
    corrected = {"quantity": 6, "reason_code": "WEAK_SEEDLING", "effective_time": s["entry_time"] + timedelta(hours=1), "note": None}
    audit_before = _audit_count(db_session, tenant.id, "crop_batch.seedling_disposition_corrected")
    first = _correct(db_session, tenant, user, farm, target_event_id=e1_id, corrected=corrected, client_command_id=ccid)
    first_reversal_id = db_session.execute(
        text("SELECT id FROM seedling_disposition_events WHERE command_id = :cid AND event_kind = 'REVERSAL'"), {"cid": first.id}
    ).scalar_one()
    first_replacement_id = db_session.execute(
        text("SELECT id FROM seedling_disposition_events WHERE command_id = :cid AND event_kind = 'REDUCTION'"), {"cid": first.id}
    ).scalar_one()
    second = seedling_disposition_service.correct_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        target_event_id=e1_id, corrected=corrected,
    )
    assert first.id == second.id
    second_reversal_id = db_session.execute(
        text("SELECT id FROM seedling_disposition_events WHERE command_id = :cid AND event_kind = 'REVERSAL'"), {"cid": second.id}
    ).scalar_one()
    second_replacement_id = db_session.execute(
        text("SELECT id FROM seedling_disposition_events WHERE command_id = :cid AND event_kind = 'REDUCTION'"), {"cid": second.id}
    ).scalar_one()
    assert second_reversal_id == first_reversal_id
    assert second_replacement_id == first_replacement_id
    count = db_session.execute(text("SELECT count(*) FROM seedling_disposition_events WHERE command_id = :cid"), {"cid": first.id}).scalar_one()
    assert count == 2
    assert _audit_count(db_session, tenant.id, "crop_batch.seedling_disposition_corrected") == audit_before + 1


@pytest.mark.integration
def test_correction_reused_command_id_different_payload_conflicts(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    r_command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=10, effective_time=s["entry_time"] + timedelta(hours=1))
    e1_id = _reduction_event_id(db_session, r_command.id)
    ccid = uuid.uuid4()
    _correct(db_session, tenant, user, farm, target_event_id=e1_id, corrected=None, client_command_id=ccid)
    with pytest.raises(SeedlingDispositionCommandReusedWithDifferentPayloadError):
        seedling_disposition_service.correct_disposition(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
            target_event_id=e1_id,
            corrected={"quantity": 3, "reason_code": "WEAK_SEEDLING", "effective_time": s["entry_time"] + timedelta(hours=1), "note": None},
        )


@pytest.mark.integration
def test_record_replay_succeeds_even_when_fresh_attempt_would_now_fail_balance(db_session, active_context_with_farm) -> None:
    """Section 2.D: exact replay must resolve on the fingerprint match alone
    -- before ANY balance recomputation. Proven by making a genuinely fresh
    attempt with the SAME payload provably impossible (the Tray is fully
    depleted by a second, independent command in between), then showing the
    original command_id still replays cleanly and changes nothing further."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm, normal=10, abnormal=0)
    aid = s["assignment_ids"][0]
    eff = s["entry_time"] + timedelta(hours=1)
    ccid = uuid.uuid4()
    original = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=6, effective_time=eff, client_command_id=ccid)
    # A second, independent command depletes the remaining balance to zero --
    # SEEDLING-DISPOSITION-LIFECYCLE-001: this now also releases the
    # assignment (exact exhaustion), which is what makes the fresh attempt
    # below impossible even before reaching the balance check.
    _record(db_session, tenant, user, farm, assignment_id=aid, quantity=4, effective_time=eff + timedelta(minutes=1))
    assert _current_balance_for_entry(db_session, s["entry_ids"][0]) == 0

    # A genuinely fresh command with this same payload would now fail --
    # confirms the scenario is real, not vacuous.
    with pytest.raises(SeedlingDispositionAssignmentReleasedError):
        _record(db_session, tenant, user, farm, assignment_id=aid, quantity=6, effective_time=eff)

    replay = seedling_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=ccid,
        batch_carrier_assignment_id=aid, quantity=6, reason_code="WEAK_SEEDLING", effective_time=eff, note=None,
    )
    assert replay.id == original.id
    assert _current_balance_for_entry(db_session, s["entry_ids"][0]) == 0
    count = db_session.execute(
        text("SELECT count(*) FROM seedling_disposition_events WHERE command_id = :cid"), {"cid": original.id}
    ).scalar_one()
    assert count == 1


# =====================================================================
# No side effects (batch/assignment/workflow untouched)
# =====================================================================


@pytest.mark.integration
def test_no_side_effects_on_batch_assignment_or_workflow(db_session, active_context_with_farm) -> None:
    """NURSERY-OPS-003B.1 section 15: RECORD and CORRECT must not create or
    modify any row outside the disposition tables themselves -- checked
    against every table the closure ticket names: SeedlingEntry itself,
    GerminationOutcomeSnapshot, Movement, Occupancy, BatchCarrierAssignment
    (including its release columns), CropBatch identity/state,
    BatchDerivationEvent, TransplantEvent, and BatchStageTransition (a
    proxy for workflow auto-transition -- CMP has no other stage-mutating
    mechanism)."""
    tenant, user, _headers, farm = active_context_with_farm
    s = _build_entered_scenario(db_session, tenant, user, farm)
    aid = s["assignment_ids"][0]
    entry_id = s["entry_ids"][0]

    def snapshot():
        return {
            "assignment": dict(db_session.execute(text("SELECT batch_id, carrier_id, released_effective_time, released_by_transplant_event_id, released_by_batch_derivation_event_id FROM batch_carrier_assignments WHERE id = :aid"), {"aid": aid}).mappings().first()),
            "batch": dict(db_session.execute(text("SELECT state, code, superseded_effective_time FROM crop_batches WHERE id = :id"), {"id": s["batch_id"]}).mappings().first()),
            "entry": dict(db_session.execute(text("SELECT starting_living_seedling_count, effective_time, movement_id, source_germination_outcome_snapshot_id FROM seedling_entries WHERE id = :id"), {"id": entry_id}).mappings().first()),
            "transitions": db_session.execute(text("SELECT count(*) FROM batch_stage_transitions WHERE batch_id = :bid"), {"bid": s["batch_id"]}).scalar_one(),
            "germination_snapshots": db_session.execute(text("SELECT count(*) FROM germination_outcome_snapshots WHERE batch_carrier_assignment_id = :aid"), {"aid": aid}).scalar_one(),
            "movements": db_session.execute(text("SELECT count(*) FROM movements WHERE tenant_id = :tid"), {"tid": tenant.id}).scalar_one(),
            "occupancies": db_session.execute(text("SELECT count(*) FROM occupancies WHERE tenant_id = :tid"), {"tid": tenant.id}).scalar_one(),
            "derivation_events": db_session.execute(text("SELECT count(*) FROM batch_derivation_events WHERE tenant_id = :tid"), {"tid": tenant.id}).scalar_one(),
            "transplant_events": db_session.execute(text("SELECT count(*) FROM transplant_events WHERE tenant_id = :tid"), {"tid": tenant.id}).scalar_one(),
        }

    before = snapshot()
    r_command = _record(db_session, tenant, user, farm, assignment_id=aid, quantity=4, effective_time=s["entry_time"] + timedelta(hours=1))
    after_record = snapshot()
    assert before == after_record

    e1_id = _reduction_event_id(db_session, r_command.id)
    _correct(db_session, tenant, user, farm, target_event_id=e1_id, corrected={"quantity": 2, "reason_code": "DISEASE", "effective_time": s["entry_time"] + timedelta(hours=1), "note": None})
    after_correct = snapshot()
    assert before == after_correct


# =====================================================================
# Concurrency (section 84) -- separate committed sessions
# =====================================================================


def _build_committed_scenario(test_engine, *, tray_count=1, normal=190, abnormal=6):
    conn = test_engine.connect()
    session = Session(bind=conn)
    from app.services import farm_service, membership_service, tenant_service, user_service

    suffix = uuid.uuid4().hex[:10]
    tenant = tenant_service.create_tenant(session, code=f"disp-conc-{suffix}", name="Disposition Concurrency Tenant")
    user = user_service.create_user(
        session, oidc_issuer="disp-conc", oidc_subject=suffix, email=f"disp-conc-{suffix}@example.com",
        display_name="Disposition Conc User",
    )
    membership_service.add_membership(session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Disposition Conc Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s = _build_entered_scenario(session, tenant, user, farm, suffix=suffix, tray_count=tray_count, normal=normal, abnormal=abnormal)
    session.commit()
    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id,
        "assignment_ids": s["assignment_ids"], "entry_ids": s["entry_ids"], "entry_time": s["entry_time"],
        "starting": s["starting"],
    }
    session.close()
    conn.close()
    return result


def _record_worker(test_engine, results, name, *, tenant_id, farm_id, user_id, client_command_id, assignment_id, quantity, effective_time, barrier):
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        command = seedling_disposition_service.record_disposition(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=client_command_id,
            batch_carrier_assignment_id=assignment_id, quantity=quantity, reason_code="WEAK_SEEDLING",
            effective_time=effective_time, note=None,
        )
        results[name] = ("ok", command.id)
    except SeedlingDispositionBalanceError as exc:
        session.rollback()
        results[name] = ("balance_error", str(exc))
    except Exception as exc:  # pragma: no cover
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


def _correct_worker(test_engine, results, name, *, tenant_id, farm_id, user_id, client_command_id, target_event_id, barrier):
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        barrier.wait(timeout=10)
        command = seedling_disposition_service.correct_disposition(
            session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, client_command_id=client_command_id,
            target_event_id=target_event_id, corrected=None,
        )
        results[name] = ("ok", command.id)
    except SeedlingDispositionAlreadyCorrectedError as exc:
        session.rollback()
        results[name] = ("already_corrected", str(exc))
    except Exception as exc:  # pragma: no cover
        session.rollback()
        results[name] = ("error", repr(exc))
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_concurrent_removals_race_final_balance_only_one_succeeds(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, normal=6, abnormal=0)
    try:
        aid = scenario["assignment_ids"][0]
        eff = scenario["entry_time"] + timedelta(hours=1)
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}
        threads = [
            threading.Thread(
                target=_record_worker, args=(test_engine, results, name),
                kwargs=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"], client_command_id=uuid.uuid4(), assignment_id=aid, quantity=4, effective_time=eff, barrier=barrier),
            )
            for name in ("a", "b")
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("balance_error") == 1, results

        check_conn = test_engine.connect()
        try:
            event_count = check_conn.execute(text("SELECT count(*) FROM seedling_disposition_events WHERE seedling_entry_id = :eid"), {"eid": scenario["entry_ids"][0]}).scalar_one()
        finally:
            check_conn.close()
        assert event_count == 1
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_corrections_race_same_target_only_one_succeeds(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, normal=190, abnormal=6)
    try:
        aid = scenario["assignment_ids"][0]
        eff = scenario["entry_time"] + timedelta(hours=1)
        conn = test_engine.connect()
        session = Session(bind=conn)
        command = seedling_disposition_service.record_disposition(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), batch_carrier_assignment_id=aid, quantity=10, reason_code="WEAK_SEEDLING",
            effective_time=eff, note=None,
        )
        target_event_id = _reduction_event_id(session, command.id)
        session.commit()
        session.close()
        conn.close()

        barrier = threading.Barrier(2)
        results: dict[str, object] = {}
        threads = [
            threading.Thread(
                target=_correct_worker, args=(test_engine, results, name),
                kwargs=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"], client_command_id=uuid.uuid4(), target_event_id=target_event_id, barrier=barrier),
            )
            for name in ("a", "b")
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("already_corrected") == 1, results

        check_conn = test_engine.connect()
        try:
            reversal_count = check_conn.execute(text("SELECT count(*) FROM seedling_disposition_events WHERE reverses_event_id = :eid"), {"eid": target_event_id}).scalar_one()
        finally:
            check_conn.close()
        assert reversal_count == 1
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_record_and_correction_no_lock_order_regression(test_engine) -> None:
    """Section 84.5: proves record_disposition/correct_disposition follow
    the same CropBatch-first lock order established (and deadlock-tested)
    by seedling_entry_service -- racing a brand-new RECORD against a
    CORRECT of an earlier event on the SAME Tray must serialize cleanly,
    never deadlock."""
    scenario = _build_committed_scenario(test_engine, normal=190, abnormal=6)
    try:
        aid = scenario["assignment_ids"][0]
        eff = scenario["entry_time"] + timedelta(hours=1)
        conn = test_engine.connect()
        session = Session(bind=conn)
        command = seedling_disposition_service.record_disposition(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), batch_carrier_assignment_id=aid, quantity=10, reason_code="WEAK_SEEDLING",
            effective_time=eff, note=None,
        )
        target_event_id = _reduction_event_id(session, command.id)
        session.commit()
        session.close()
        conn.close()

        barrier = threading.Barrier(2)
        results: dict[str, object] = {}
        t_record = threading.Thread(
            target=_record_worker, args=(test_engine, results, "record"),
            kwargs=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"], client_command_id=uuid.uuid4(), assignment_id=aid, quantity=3, effective_time=eff + timedelta(hours=1), barrier=barrier),
        )
        t_correct = threading.Thread(
            target=_correct_worker, args=(test_engine, results, "correct"),
            kwargs=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"], client_command_id=uuid.uuid4(), target_event_id=target_event_id, barrier=barrier),
        )
        t_record.start()
        t_correct.start()
        t_record.join(timeout=15)
        t_correct.join(timeout=15)
        assert not t_record.is_alive() and not t_correct.is_alive(), "no deadlock: both threads must complete"
        assert results["record"][0] == "ok", results
        assert results["correct"][0] == "ok", results
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_identical_record_command_id_yields_one_command_one_reduction(test_engine) -> None:
    """NURSERY-OPS-003B.1 section 2.C: two threads racing the SAME
    client_command_id and SAME payload against the SAME Tray (therefore the
    SAME CropBatch row lock) must resolve to one logical command. The
    CropBatch-first lock fully serializes the two attempts: the losing
    thread blocks on `SELECT ... FOR UPDATE`, and once it acquires the lock
    its own post-lock idempotency recheck (`record_disposition`'s second
    `_find_existing_command` call) finds the winner's already-committed row
    and returns it directly -- it never reaches its own INSERT, let alone
    the IntegrityError-catch fallback (which exists as a separate backstop
    for a narrower race, not exercised by this specific scenario)."""
    scenario = _build_committed_scenario(test_engine, normal=190, abnormal=6)
    try:
        aid = scenario["assignment_ids"][0]
        eff = scenario["entry_time"] + timedelta(hours=1)
        shared_ccid = uuid.uuid4()
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}
        threads = [
            threading.Thread(
                target=_record_worker, args=(test_engine, results, name),
                kwargs=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"], client_command_id=shared_ccid, assignment_id=aid, quantity=4, effective_time=eff, barrier=barrier),
            )
            for name in ("a", "b")
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert results["a"][0] == "ok" and results["b"][0] == "ok", results
        assert results["a"][1] == results["b"][1], "both threads must observe the same logical command id"

        check_conn = test_engine.connect()
        try:
            command_count = check_conn.execute(
                text("SELECT count(*) FROM seedling_disposition_commands WHERE client_command_id = :ccid"),
                {"ccid": shared_ccid},
            ).scalar_one()
            event_count = check_conn.execute(
                text("SELECT count(*) FROM seedling_disposition_events WHERE seedling_entry_id = :eid"),
                {"eid": scenario["entry_ids"][0]},
            ).scalar_one()
        finally:
            check_conn.close()
        assert command_count == 1
        assert event_count == 1
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_identical_correction_command_id_yields_one_correction(test_engine) -> None:
    """NURSERY-OPS-003B.1 section 4.C: two threads racing the SAME
    client_command_id against the SAME target event (therefore the SAME
    CropBatch row lock) must resolve to one logical correction -- exactly
    one REVERSAL, never two. The CropBatch-first lock serializes the two
    attempts; the losing thread's own post-lock idempotency recheck finds
    the winner's already-committed correction and returns it directly."""
    scenario = _build_committed_scenario(test_engine, normal=190, abnormal=6)
    try:
        aid = scenario["assignment_ids"][0]
        eff = scenario["entry_time"] + timedelta(hours=1)
        conn = test_engine.connect()
        session = Session(bind=conn)
        command = seedling_disposition_service.record_disposition(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), batch_carrier_assignment_id=aid, quantity=10, reason_code="WEAK_SEEDLING",
            effective_time=eff, note=None,
        )
        target_event_id = _reduction_event_id(session, command.id)
        session.commit()
        session.close()
        conn.close()

        shared_ccid = uuid.uuid4()
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}
        threads = [
            threading.Thread(
                target=_correct_worker, args=(test_engine, results, name),
                kwargs=dict(tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], user_id=scenario["user_id"], client_command_id=shared_ccid, target_event_id=target_event_id, barrier=barrier),
            )
            for name in ("a", "b")
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert results["a"][0] == "ok" and results["b"][0] == "ok", results
        assert results["a"][1] == results["b"][1], "both threads must observe the same logical correction command id"

        check_conn = test_engine.connect()
        try:
            command_count = check_conn.execute(
                text("SELECT count(*) FROM seedling_disposition_commands WHERE client_command_id = :ccid"),
                {"ccid": shared_ccid},
            ).scalar_one()
            reversal_count = check_conn.execute(
                text("SELECT count(*) FROM seedling_disposition_events WHERE reverses_event_id = :eid"),
                {"eid": target_event_id},
            ).scalar_one()
        finally:
            check_conn.close()
        assert command_count == 1
        assert reversal_count == 1
    finally:
        cleanup_traceability_scenario(test_engine, scenario["tenant_id"])


# =====================================================================
# Authz (section 85)
# =====================================================================


def _membership_headers(db_session, *, tenant_id, role_code: str) -> dict[str, str]:
    """Creates a brand-new user for `role_code` rather than re-membering the
    fixture's own tenant_admin user, which already holds a single active
    membership per `ux_tenant_memberships_active_tenant_user` -- matches
    the established pattern in test_authz_observation_permission_split_http.py."""
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject=f"seedling-disposition-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Seedling Disposition Test User",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None
    )
    db_session.commit()
    return {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}


@pytest.mark.integration
def test_biological_disposition_manage_required_for_mutation(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm

    s = _build_entered_scenario(db_session, tenant, user, farm)
    db_session.commit()

    operator_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="operator")

    payload = {
        "client_command_id": str(uuid.uuid4()), "batch_carrier_assignment_id": str(s["assignment_ids"][0]),
        "quantity": 1, "reason_code": "WEAK_SEEDLING", "effective_time": (s["entry_time"] + timedelta(hours=1)).isoformat(), "note": None,
    }
    response = client.post(f"/farms/{farm.id}/nursery/seedling/dispositions", json=payload, headers=operator_headers)
    assert response.status_code == 201, response.text


@pytest.mark.integration
def test_observation_entry_manage_alone_cannot_mutate_disposition(client, active_context_with_farm, db_session) -> None:
    tenant, user, headers, farm = active_context_with_farm

    s = _build_entered_scenario(db_session, tenant, user, farm)
    db_session.commit()

    qc_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="qc_officer")

    payload = {
        "client_command_id": str(uuid.uuid4()), "batch_carrier_assignment_id": str(s["assignment_ids"][0]),
        "quantity": 1, "reason_code": "WEAK_SEEDLING", "effective_time": (s["entry_time"] + timedelta(hours=1)).isoformat(), "note": None,
    }
    response = client.post(f"/farms/{farm.id}/nursery/seedling/dispositions", json=payload, headers=qc_headers)
    assert response.status_code == 403, response.text


# =====================================================================
# Migration / downgrade guard
# =====================================================================

# The revision immediately before NURSERY-OPS-003B -- 003A's own head.
# Fixed on purpose (not "resolve dynamically"): this is a specific
# historical anchor point this test downgrades TO, not "current head",
# mirroring _PRE_CMP011_REVISION's own established precedent in
# test_transplant_downgrade_guard.py.
_PRE_003B_REVISION = "a3f7c9d2e0b1"


@pytest.mark.integration
def test_migration_downgrade_blocked_when_disposition_events_exist(test_engine, alembic_head_restore) -> None:
    """Proves migration b4e8a1f0d6c2's own downgrade guard: a real,
    committed `seedling_disposition_events` row must block a downgrade past
    NURSERY-OPS-003B, exactly like every other ticket's downgrade guard in
    this codebase (see test_transplant_downgrade_guard.py). Uses
    `test_engine` directly (not `db_session`'s savepoint-scoped connection)
    because the guard only fires against genuinely committed rows, and
    `alembic_head_restore` guarantees cmp_test ends this test at head
    regardless of outcome."""
    scenario = _build_committed_scenario(test_engine, normal=6, abnormal=0)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        seedling_disposition_service.record_disposition(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), batch_carrier_assignment_id=scenario["assignment_ids"][0],
            quantity=2, reason_code="WEAK_SEEDLING", effective_time=scenario["entry_time"] + timedelta(hours=1),
            note=None,
        )
    finally:
        session.close()
        conn.close()

    # SEEDLING-DISPOSITION-LIFECYCLE-001 now sits above both CARRIER-CONFIG-001
    # (e5b8c3a72f04) and NURSERY-OPS-003B (b4e8a1f0d6c2) in the migration
    # chain, and its own downgrade guard unconditionally blocks whenever ANY
    # seedling_disposition_commands row carries active_batch_stage_run_id --
    # which every command created via the service (as above) now always
    # does. It therefore always fires first for any downgrade attempt that
    # crosses it, making this the correct, permanent expectation rather than
    # the original CARRIER-CONFIG-001 message (itself the ripple-updated
    # successor of NURSERY-OPS-003B's own original message).
    cfg = migrations_alembic_config()
    with pytest.raises(Exception, match="Cannot downgrade past SEEDLING-DISPOSITION-LIFECYCLE-001"):
        command.downgrade(cfg, _PRE_003B_REVISION)

    with test_engine.connect() as check_conn:
        current = check_conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert current == resolve_dynamic_alembic_head(cfg), "a blocked downgrade must leave the database at head"

    cleanup_traceability_scenario(test_engine, scenario["tenant_id"])
