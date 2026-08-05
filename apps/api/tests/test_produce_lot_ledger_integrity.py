"""CMP-014 database-level integrity verification: proves the ledger's
insert-integrity and deferred-reconciliation rules are independently
enforced by the database against direct SQL, not only by the Python
service layer. One committed scenario (two already-successful harvests,
each with its own lot/receipt, plus two free assignments) is built once
via a module-scoped fixture; every test attempts a direct-SQL statement
that must be rejected and rolls its own connection back afterward, so the
shared baseline is never mutated between tests. Cleanup is guarded by the
same `cmp_test` + `session_replication_role = DEFAULT` restore discipline
used throughout the rest of the CMP-013/CMP-014 test suite."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    carrier_service,
    crop_batch_service,
    crop_service,
    farm_service,
    harvest_service,
    membership_service,
    production_system_service,
    sowing_service,
    tenant_service,
    user_service,
    workflow_service,
)


def _now():
    return datetime.now(timezone.utc)


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup (session_replication_role) against "
            f"database {current_db!r}; this cleanup is only permitted against 'cmp_test'"
        )

    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvested_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM harvest_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_event_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_carrier_assignments WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM seed_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
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


@pytest.fixture(scope="module")
def scenario(test_engine):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"ledger-int-{suffix}", name="Ledger Integrity Tenant")
    user = user_service.create_user(
        session, oidc_issuer="ledger-int", oidc_subject=suffix, email=f"ledger-int-{suffix}@example.com",
        display_name="Integrity User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Integrity Farm",
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
    workflow_service.publish_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    batch = crop_batch_service.create_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"batch-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"lot-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    carriers = [
        carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"tray-{suffix}-{n}", issued_date=None,
        )
        for n in range(4)
    ]
    sowing_service.sow_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[
            {"carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 50, "seed_count": 50, "line_note": None}
            for c in carriers
        ],
    )
    assignments = sowing_service.list_batch_carriers(session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
    assignment_by_carrier = {a.carrier.code: a.id for a in assignments}
    assignment_ids = [assignment_by_carrier[c.code] for c in carriers]
    carrier_ids = [c.id for c in carriers]

    crop_batch_service.transition_stage(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=_now(), reason=None,
    )
    stage_run_row = session.execute(
        text(
            "SELECT id, entered_effective_time FROM batch_stage_runs "
            "WHERE batch_id = :bid AND exited_effective_time IS NULL"
        ),
        {"bid": batch.id},
    ).one()
    active_stage_run_id, entered_effective_time = stage_run_row

    event_a = harvest_service.record_harvest(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"A-{suffix}", note=None,
        source_lines=[{"batch_carrier_assignment_id": assignment_ids[0], "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
    )
    lot_a_id, lot_a_recorded_at = session.execute(
        text("SELECT id, recorded_at FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": event_a.id}
    ).one()

    event_b = harvest_service.record_harvest(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"B-{suffix}", note=None,
        source_lines=[{"batch_carrier_assignment_id": assignment_ids[1], "harvested_weight_kg": Decimal("2.000"), "whole_unit_count": None, "note": None}],
    )
    lot_b_id = session.execute(
        text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": event_b.id}
    ).scalar_one()

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": batch.id,
        "workflow_id": workflow.id, "workflow_version_id": version.id, "crop_id": crop.id, "variety_id": variety.id,
        "assignment_ids": assignment_ids, "carrier_ids": carrier_ids, "active_stage_run_id": active_stage_run_id,
        "event_a_id": event_a.id, "lot_a_id": lot_a_id, "event_a_effective_time": event_a.effective_time,
        "lot_a_recorded_at": lot_a_recorded_at, "event_b_id": event_b.id, "lot_b_id": lot_b_id, "suffix": suffix,
    }
    session.close()
    conn.close()
    yield result
    _cleanup_scenario(test_engine, tenant.id)


def _receipt_values(scenario, *, overrides=None):
    """A perfectly valid harvest_receipt row for lot A, as a dict, with any
    single field overridden by the caller to prove that field's own check."""
    values = {
        "id": scenario["lot_a_id"],
        "tenant_id": scenario["tenant_id"],
        "farm_id": scenario["farm_id"],
        "produce_lot_id": scenario["lot_a_id"],
        "harvest_event_id": scenario["event_a_id"],
        "entry_kind": "harvest_receipt",
        "weight_delta_kg": Decimal("1.000"),
        "whole_unit_count_delta": None,
        "effective_time": scenario["event_a_effective_time"],
        "recorded_time": scenario["lot_a_recorded_at"],
        "actor_user_id": scenario["user_id"],
        "note": None,
    }
    if overrides:
        values.update(overrides)
    return values


_INSERT_SQL = text(
    "INSERT INTO produce_lot_ledger_entries "
    "(id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, weight_delta_kg, "
    "whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) VALUES "
    "(:id, :tenant_id, :farm_id, :produce_lot_id, :harvest_event_id, :entry_kind, :weight_delta_kg, "
    ":whole_unit_count_delta, :effective_time, :recorded_time, :actor_user_id, :note)"
)


@pytest.mark.integration
def test_direct_sql_wrong_deterministic_id_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception, match="id must equal its produce lot id"):
            conn.execute(_INSERT_SQL, _receipt_values(scenario, overrides={"id": uuid.uuid4()}))
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_wrong_event_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception, match="does not match the produce lot's own event"):
            conn.execute(_INSERT_SQL, _receipt_values(scenario, overrides={"harvest_event_id": scenario["event_b_id"]}))
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_wrong_weight_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception, match="weight does not match"):
            conn.execute(_INSERT_SQL, _receipt_values(scenario, overrides={"weight_delta_kg": Decimal("9.999")}))
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_wrong_count_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception, match="count does not match"):
            conn.execute(_INSERT_SQL, _receipt_values(scenario, overrides={"whole_unit_count_delta": 5}))
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_wrong_actor_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception, match="actor does not match"):
            conn.execute(_INSERT_SQL, _receipt_values(scenario, overrides={"actor_user_id": uuid.uuid4()}))
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_wrong_effective_time_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        wrong_time = scenario["event_a_effective_time"] + timedelta(hours=1)
        with pytest.raises(Exception, match="effective time does not match"):
            conn.execute(_INSERT_SQL, _receipt_values(scenario, overrides={"effective_time": wrong_time}))
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_wrong_recorded_time_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        wrong_time = scenario["event_a_effective_time"] + timedelta(hours=1)
        with pytest.raises(Exception, match="recorded time does not match"):
            conn.execute(_INSERT_SQL, _receipt_values(scenario, overrides={"recorded_time": wrong_time}))
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_non_null_note_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception, match="note must be null"):
            conn.execute(_INSERT_SQL, _receipt_values(scenario, overrides={"note": "not allowed"}))
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_duplicate_receipt_id_rejected(test_engine, scenario) -> None:
    """A perfect clone of the already-committed receipt (every field
    correct, including the deterministic id) still cannot be inserted a
    second time — the primary key alone rejects it."""
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception):
            conn.execute(_INSERT_SQL, _receipt_values(scenario))
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_update_receipt_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception):
            conn.execute(
                text("UPDATE produce_lot_ledger_entries SET note = 'tampered' WHERE id = :id"),
                {"id": scenario["lot_a_id"]},
            )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_delete_receipt_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception):
            conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE id = :id"), {"id": scenario["lot_a_id"]})
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_produce_lot_without_receipt_fails_at_commit(test_engine, scenario) -> None:
    """A fresh, otherwise entirely valid harvest event/lot/source-line
    triple (satisfying every CMP-013 immediate check) still cannot commit
    if no harvest receipt is inserted for the lot — CMP-014's deferred
    trigger, attached to `harvested_produce_lots` INSERT, catches it."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        new_event_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO harvest_events "
                "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
                "client_command_id, request_fingerprint, note) VALUES "
                "(:id, :tid, :fid, :bid, :run_id, :eff, :uid, :cmd, :fp, NULL)"
            ),
            {
                "id": new_event_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                "bid": scenario["batch_id"], "run_id": scenario["active_stage_run_id"],
                "eff": scenario["event_a_effective_time"], "uid": scenario["user_id"], "cmd": uuid.uuid4(),
                "fp": "direct-sql-no-receipt-test",
            },
        )
        conn.execute(
            text(
                "INSERT INTO harvest_source_lines "
                "(id, tenant_id, farm_id, harvest_event_id, batch_carrier_assignment_id, carrier_id, "
                "harvested_weight_kg, whole_unit_count, note) VALUES "
                "(:id, :tid, :fid, :eid, :aid, :cid, :w, NULL, NULL)"
            ),
            {
                "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "eid": new_event_id,
                "aid": scenario["assignment_ids"][2], "cid": scenario["carrier_ids"][2], "w": Decimal("3.000"),
            },
        )
        new_lot_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO harvested_produce_lots "
                "(id, tenant_id, farm_id, code, harvest_event_id, batch_id, workflow_id, workflow_version_id, "
                "crop_id, variety_id, total_harvested_weight_kg, total_whole_unit_count, effective_time) VALUES "
                "(:id, :tid, :fid, :code, :eid, :bid, :wf, :wfv, :crop, :variety, :w, NULL, :eff)"
            ),
            {
                "id": new_lot_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                "code": f"NORECEIPT-{scenario['suffix']}", "eid": new_event_id, "bid": scenario["batch_id"],
                "wf": scenario["workflow_id"], "wfv": scenario["workflow_version_id"], "crop": scenario["crop_id"],
                "variety": scenario["variety_id"], "w": Decimal("3.000"), "eff": scenario["event_a_effective_time"],
            },
        )
        # No INSERT INTO produce_lot_ledger_entries — deliberately.
        with pytest.raises(Exception, match="must have exactly one harvest receipt"):
            trans.commit()
    finally:
        conn.rollback()
        conn.close()

    with test_engine.connect() as verify_conn:
        lot_count = verify_conn.execute(
            text("SELECT count(*) FROM harvested_produce_lots WHERE code = :code"),
            {"code": f"NORECEIPT-{scenario['suffix']}"},
        ).scalar_one()
    assert lot_count == 0, "the failed commit must not have persisted the receipt-less lot"


@pytest.mark.integration
def test_late_correct_receipt_insertion_completes_reconciliation_at_commit(test_engine, scenario) -> None:
    """The lot and its receipt inserted as two separate, later statements
    within one transaction (not simultaneously) still reconcile correctly
    at commit — `produce_lot_ledger_entries`' own deferred trigger, not
    only the one attached to `harvested_produce_lots`, independently
    validates the final state."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        new_event_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO harvest_events "
                "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
                "client_command_id, request_fingerprint, note) VALUES "
                "(:id, :tid, :fid, :bid, :run_id, :eff, :uid, :cmd, :fp, NULL)"
            ),
            {
                "id": new_event_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                "bid": scenario["batch_id"], "run_id": scenario["active_stage_run_id"],
                "eff": scenario["event_a_effective_time"], "uid": scenario["user_id"], "cmd": uuid.uuid4(),
                "fp": "direct-sql-late-receipt-test",
            },
        )
        conn.execute(
            text(
                "INSERT INTO harvest_source_lines "
                "(id, tenant_id, farm_id, harvest_event_id, batch_carrier_assignment_id, carrier_id, "
                "harvested_weight_kg, whole_unit_count, note) VALUES "
                "(:id, :tid, :fid, :eid, :aid, :cid, :w, NULL, NULL)"
            ),
            {
                "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"], "eid": new_event_id,
                "aid": scenario["assignment_ids"][3], "cid": scenario["carrier_ids"][3], "w": Decimal("4.000"),
            },
        )
        new_lot_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO harvested_produce_lots "
                "(id, tenant_id, farm_id, code, harvest_event_id, batch_id, workflow_id, workflow_version_id, "
                "crop_id, variety_id, total_harvested_weight_kg, total_whole_unit_count, effective_time) VALUES "
                "(:id, :tid, :fid, :code, :eid, :bid, :wf, :wfv, :crop, :variety, :w, NULL, :eff)"
            ),
            {
                "id": new_lot_id, "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                "code": f"LATEOK-{scenario['suffix']}", "eid": new_event_id, "bid": scenario["batch_id"],
                "wf": scenario["workflow_id"], "wfv": scenario["workflow_version_id"], "crop": scenario["crop_id"],
                "variety": scenario["variety_id"], "w": Decimal("4.000"), "eff": scenario["event_a_effective_time"],
            },
        )
        new_lot_recorded_at = conn.execute(
            text("SELECT recorded_at FROM harvested_produce_lots WHERE id = :id"), {"id": new_lot_id}
        ).scalar_one()
        # The receipt is inserted as a later, separate statement.
        conn.execute(
            _INSERT_SQL,
            {
                "id": new_lot_id, "tenant_id": scenario["tenant_id"], "farm_id": scenario["farm_id"],
                "produce_lot_id": new_lot_id, "harvest_event_id": new_event_id, "entry_kind": "harvest_receipt",
                "weight_delta_kg": Decimal("4.000"), "whole_unit_count_delta": None,
                "effective_time": scenario["event_a_effective_time"], "recorded_time": new_lot_recorded_at,
                "actor_user_id": scenario["user_id"], "note": None,
            },
        )
        trans.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    with test_engine.connect() as verify_conn:
        receipt_count = verify_conn.execute(
            text("SELECT count(*) FROM produce_lot_ledger_entries WHERE produce_lot_id = :lid"), {"lid": new_lot_id}
        ).scalar_one()
    assert receipt_count == 1
