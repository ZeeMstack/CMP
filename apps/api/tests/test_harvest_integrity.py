"""CMP-013 database-level integrity verification: proves the rules the
service already enforces are independently enforced by the database against
direct SQL, not only by the Python service layer. One committed scenario
(with one already-successful harvest event/lot/2 lines) is built once via a
module-scoped fixture; every test below attempts a direct-SQL statement that
must be rejected, and rolls its own connection back afterward, so the shared
baseline is never mutated between tests. Cleanup is guarded by the same
`cmp_test` + `session_replication_role = DEFAULT` restore discipline used
throughout the rest of the CMP-013 test suite."""
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
    harvest_service,
    membership_service,
    production_system_service,
    sowing_service,
    tenant_service,
    user_service,
    workflow_service,
)


def _now():
    from datetime import datetime, timezone

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
        conn.execute(text("DELETE FROM harvest_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM produce_lot_ledger_entries WHERE tenant_id = :tid"), {"tid": tenant_id})
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

    tenant = tenant_service.create_tenant(session, code=f"harv-int-{suffix}", name="Integrity Tenant")
    user = user_service.create_user(
        session, oidc_issuer="harv-int", oidc_subject=suffix, email=f"harv-int-{suffix}@example.com",
        display_name="Integrity User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Integrity Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm2-{suffix}", name="Other Farm",
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
    created_effective_time = batch.created_effective_time
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

    existing_event = harvest_service.record_harvest(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"BASE-{suffix}", note=None,
        source_lines=[
            {"batch_carrier_assignment_id": assignment_ids[0], "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None},
            {"batch_carrier_assignment_id": assignment_ids[1], "harvested_weight_kg": Decimal("2.000"), "whole_unit_count": None, "note": None},
        ],
    )
    existing_lot_id = session.execute(
        text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": existing_event.id}
    ).scalar_one()

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "other_farm_id": other_farm.id,
        "batch_id": batch.id, "workflow_id": workflow.id, "workflow_version_id": version.id, "crop_id": crop.id,
        "variety_id": variety.id, "assignment_ids": assignment_ids, "carrier_ids": carrier_ids,
        "active_stage_run_id": active_stage_run_id, "entered_effective_time": entered_effective_time,
        "created_effective_time": created_effective_time, "existing_event_id": existing_event.id,
        "existing_event_effective_time": existing_event.effective_time, "existing_lot_id": existing_lot_id,
        "suffix": suffix,
    }
    session.close()
    conn.close()
    yield result
    _cleanup_scenario(test_engine, tenant.id)


def _insert_event_sql(conn, scenario, *, effective_time, farm_id=None):
    conn.execute(
        text(
            "INSERT INTO harvest_events "
            "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
            "client_command_id, request_fingerprint, note) VALUES "
            "(:id, :tid, :fid, :bid, :run_id, :eff, :uid, :cmd, :fp, NULL)"
        ),
        {
            "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": farm_id or scenario["farm_id"],
            "bid": scenario["batch_id"], "run_id": scenario["active_stage_run_id"], "eff": effective_time,
            "uid": scenario["user_id"], "cmd": uuid.uuid4(), "fp": "direct-sql-test",
        },
    )


# --- Section 1: DB-level effective-time enforcement --------------------------------


@pytest.mark.integration
def test_direct_sql_future_effective_time_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        future_time = scenario["existing_event_effective_time"] + timedelta(days=1)
        with pytest.raises(Exception, match="cannot be in the future"):
            _insert_event_sql(conn, scenario, effective_time=future_time)
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_effective_time_before_batch_creation_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        before_creation = scenario["created_effective_time"] - timedelta(days=1)
        with pytest.raises(Exception, match="precedes the batch's creation effective time"):
            _insert_event_sql(conn, scenario, effective_time=before_creation)
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_effective_time_before_stage_run_entry_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        assert scenario["created_effective_time"] < scenario["entered_effective_time"], (
            "fixture invariant: the batch must be created strictly before it enters the harvesting stage "
            "for this test to isolate the stage-run-entry check from the batch-creation check"
        )
        with pytest.raises(Exception, match="precedes the current stage run's entry time"):
            _insert_event_sql(conn, scenario, effective_time=scenario["created_effective_time"])
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_tenant_farm_mismatch_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception, match="tenant/farm does not match"):
            _insert_event_sql(
                conn, scenario, effective_time=scenario["existing_event_effective_time"],
                farm_id=scenario["other_farm_id"],
            )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_source_line_before_assignment_time_rejected(test_engine, scenario) -> None:
    """The source-line trigger independently rejects an event effective time
    before the selected assignment's own `assigned_effective_time`. Under
    this workflow's natural ordering (sow, then transition into harvesting),
    every real assignment's `assigned_effective_time` already precedes the
    harvesting stage-run's own entry time, which every valid harvest event
    must already be at or after — so no legitimately-inserted event can
    ever violate this rule using an assignment from real sowing alone. To
    exercise the source-line trigger's *own* independent check in isolation,
    a second assignment row is crafted directly (bypassing triggers on
    `batch_carrier_assignments` for this one insert only, guarded by the
    same `cmp_test` check used elsewhere) with an `assigned_effective_time`
    deliberately after the existing event's own effective time."""
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged direct-SQL setup against database {current_db!r}; "
            f"this is only permitted against 'cmp_test'"
        )

    conn = test_engine.connect()
    new_carrier = None
    try:
        session = Session(bind=conn)
        # A fresh carrier is required: the active-assignment-per-carrier
        # uniqueness index is a real UNIQUE INDEX (not a user trigger), so
        # it is not bypassed by session_replication_role — reusing an
        # already-assigned carrier would fail on that index instead of
        # proving anything about the rule under test.
        new_carrier = carrier_service.register_carrier(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            carrier_type_code="seed_tray", code=f"late-carrier-{scenario['suffix']}", issued_date=None,
        )
        session.commit()

        source = conn.execute(
            text(
                "SELECT tenant_id, farm_id, batch_id, opening_sowing_event_id FROM batch_carrier_assignments "
                "WHERE id = :id"
            ),
            {"id": scenario["assignment_ids"][2]},
        ).one()

        late_assignment_id = uuid.uuid4()
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(
            text(
                "INSERT INTO batch_carrier_assignments "
                "(id, tenant_id, farm_id, batch_id, carrier_id, batch_stage_run_id, assigned_effective_time, "
                "released_effective_time, opening_sowing_event_id, actor_user_id) VALUES "
                "(:id, :tid, :fid, :bid, :cid, :run_id, :late, NULL, :sowing_id, :uid)"
            ),
            {
                "id": late_assignment_id, "tid": source.tenant_id, "fid": source.farm_id, "bid": source.batch_id,
                "cid": new_carrier.id, "run_id": scenario["active_stage_run_id"],
                "late": scenario["existing_event_effective_time"] + timedelta(days=1),
                "sowing_id": source.opening_sowing_event_id, "uid": scenario["user_id"],
            },
        )
        conn.execute(text("SET session_replication_role = DEFAULT"))

        with pytest.raises(Exception, match="precedes source assignment"):
            conn.execute(
                text(
                    "INSERT INTO harvest_source_lines "
                    "(id, tenant_id, farm_id, harvest_event_id, batch_carrier_assignment_id, carrier_id, "
                    "harvested_weight_kg, whole_unit_count, note) VALUES "
                    "(:id, :tid, :fid, :eid, :aid, :cid, :w, NULL, NULL)"
                ),
                {
                    "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                    "eid": scenario["existing_event_id"], "aid": late_assignment_id,
                    "cid": new_carrier.id, "w": Decimal("1.000"),
                },
            )
    finally:
        conn.rollback()
        conn.close()
        # The fresh carrier was committed outside the rolled-back
        # transaction above (a separate `session.commit()`), so it is
        # cleaned up explicitly rather than by the rollback.
        if new_carrier is not None:
            cleanup_conn = test_engine.connect()
            cleanup_trans = cleanup_conn.begin()
            try:
                cleanup_conn.execute(text("SET session_replication_role = replica"))
                cleanup_conn.execute(
                    text("DELETE FROM carriers WHERE id = :id"), {"id": new_carrier.id}
                )
            finally:
                cleanup_conn.execute(text("SET session_replication_role = DEFAULT"))
                cleanup_trans.commit()
                cleanup_conn.close()


# --- Section 2/3: Decimal and whole-unit-count envelope bypass via direct SQL ------


@pytest.mark.integration
def test_direct_sql_weight_excess_scale_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception, match="ck_harvest_source_lines_weight_envelope"):
            conn.execute(
                text(
                    "INSERT INTO harvest_source_lines "
                    "(id, tenant_id, farm_id, harvest_event_id, batch_carrier_assignment_id, carrier_id, "
                    "harvested_weight_kg, whole_unit_count, note) VALUES "
                    "(:id, :tid, :fid, :eid, :aid, :cid, :w, NULL, NULL)"
                ),
                {
                    "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                    "eid": scenario["existing_event_id"], "aid": scenario["assignment_ids"][2],
                    "cid": scenario["carrier_ids"][2], "w": Decimal("1.2345"),
                },
            )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_weight_at_or_above_max_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception, match="ck_harvest_source_lines_weight_envelope"):
            conn.execute(
                text(
                    "INSERT INTO harvest_source_lines "
                    "(id, tenant_id, farm_id, harvest_event_id, batch_carrier_assignment_id, carrier_id, "
                    "harvested_weight_kg, whole_unit_count, note) VALUES "
                    "(:id, :tid, :fid, :eid, :aid, :cid, :w, NULL, NULL)"
                ),
                {
                    "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                    "eid": scenario["existing_event_id"], "aid": scenario["assignment_ids"][2],
                    "cid": scenario["carrier_ids"][2], "w": Decimal("100000000000"),
                },
            )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_negative_count_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception, match="ck_harvest_source_lines_count_positive"):
            conn.execute(
                text(
                    "INSERT INTO harvest_source_lines "
                    "(id, tenant_id, farm_id, harvest_event_id, batch_carrier_assignment_id, carrier_id, "
                    "harvested_weight_kg, whole_unit_count, note) VALUES "
                    "(:id, :tid, :fid, :eid, :aid, :cid, :w, :c, NULL)"
                ),
                {
                    "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                    "eid": scenario["existing_event_id"], "aid": scenario["assignment_ids"][2],
                    "cid": scenario["carrier_ids"][2], "w": Decimal("1.000"), "c": -1,
                },
            )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_count_above_bigint_max_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception):
            conn.execute(
                text(
                    "INSERT INTO harvest_source_lines "
                    "(id, tenant_id, farm_id, harvest_event_id, batch_carrier_assignment_id, carrier_id, "
                    "harvested_weight_kg, whole_unit_count, note) VALUES "
                    "(:id, :tid, :fid, :eid, :aid, :cid, :w, :c, NULL)"
                ),
                {
                    "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                    "eid": scenario["existing_event_id"], "aid": scenario["assignment_ids"][2],
                    "cid": scenario["carrier_ids"][2], "w": Decimal("1.000"), "c": 9223372036854775808,
                },
            )
    finally:
        conn.rollback()
        conn.close()


# --- Section 4/10: append-only protection and reconciliation on late direct SQL ----


@pytest.mark.integration
def test_direct_sql_update_harvest_event_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception):
            conn.execute(
                text("UPDATE harvest_events SET note = 'tampered' WHERE id = :id"),
                {"id": scenario["existing_event_id"]},
            )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_delete_harvest_event_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception):
            conn.execute(text("DELETE FROM harvest_events WHERE id = :id"), {"id": scenario["existing_event_id"]})
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_update_produce_lot_rejected(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception):
            conn.execute(
                text("UPDATE harvested_produce_lots SET total_harvested_weight_kg = 999 WHERE id = :id"),
                {"id": scenario["existing_lot_id"]},
            )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_direct_sql_second_produce_lot_blocked_by_uniqueness(test_engine, scenario) -> None:
    conn = test_engine.connect()
    try:
        with pytest.raises(Exception, match="ux_harvested_produce_lots_event"):
            conn.execute(
                text(
                    "INSERT INTO harvested_produce_lots "
                    "(id, tenant_id, farm_id, code, harvest_event_id, batch_id, workflow_id, workflow_version_id, "
                    "crop_id, variety_id, total_harvested_weight_kg, total_whole_unit_count, effective_time) VALUES "
                    "(:id, :tid, :fid, :code, :eid, :bid, :wf, :wfv, :crop, :variety, :w, NULL, :eff)"
                ),
                {
                    "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                    "code": f"SECOND-{scenario['suffix']}", "eid": scenario["existing_event_id"],
                    "bid": scenario["batch_id"], "wf": scenario["workflow_id"], "wfv": scenario["workflow_version_id"],
                    "crop": scenario["crop_id"], "variety": scenario["variety_id"], "w": Decimal("1.000"),
                    "eff": scenario["existing_event_effective_time"],
                },
            )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_late_direct_sql_source_line_reruns_deferred_reconciliation(test_engine, scenario) -> None:
    """A separate, later transaction inserting a third source line against
    the already-committed event must fail at COMMIT — the deferred
    constraint trigger re-validates the event's complete reconciled state,
    catching that the produce lot's stored total no longer matches the sum
    of source lines, even though the immediate insert-integrity trigger (a
    genuinely valid assignment/carrier/time) raised nothing."""
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(
            text(
                "INSERT INTO harvest_source_lines "
                "(id, tenant_id, farm_id, harvest_event_id, batch_carrier_assignment_id, carrier_id, "
                "harvested_weight_kg, whole_unit_count, note) VALUES "
                "(:id, :tid, :fid, :eid, :aid, :cid, :w, NULL, NULL)"
            ),
            {
                "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                "eid": scenario["existing_event_id"], "aid": scenario["assignment_ids"][2],
                "cid": scenario["carrier_ids"][2], "w": Decimal("5.000"),
            },
        )
        # The insert itself succeeds (immediate trigger is satisfied); only
        # the deferred reconciliation trigger, firing at COMMIT, catches the
        # now-stale produce-lot total.
        with pytest.raises(Exception, match="does not reconcile"):
            trans.commit()
    finally:
        conn.rollback()
        conn.close()

    # Prove the baseline is genuinely unaffected by the failed late insert.
    with test_engine.connect() as verify_conn:
        line_count = verify_conn.execute(
            text("SELECT count(*) FROM harvest_source_lines WHERE harvest_event_id = :eid"),
            {"eid": scenario["existing_event_id"]},
        ).scalar_one()
    assert line_count == 2, "the failed late direct-SQL insert must not have persisted a third source line"


@pytest.mark.integration
def test_direct_sql_mixed_count_presence_rejected_by_deferred_trigger(test_engine, scenario) -> None:
    """A brand-new, fully isolated event/lot/2-lines triple inserted
    entirely via direct SQL in one transaction, with one line counted and
    one not — the mixed-presence rule is a same-event, cross-row rule an
    ordinary CHECK cannot express, so it is caught only by the deferred
    reconciliation trigger at COMMIT."""
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
                "eff": scenario["existing_event_effective_time"], "uid": scenario["user_id"],
                "cmd": uuid.uuid4(), "fp": "direct-sql-mixed-count-test",
            },
        )
        conn.execute(
            text(
                "INSERT INTO harvested_produce_lots "
                "(id, tenant_id, farm_id, code, harvest_event_id, batch_id, workflow_id, workflow_version_id, "
                "crop_id, variety_id, total_harvested_weight_kg, total_whole_unit_count, effective_time) VALUES "
                "(:id, :tid, :fid, :code, :eid, :bid, :wf, :wfv, :crop, :variety, :w, :c, :eff)"
            ),
            {
                "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                "code": f"MIXED-{scenario['suffix']}", "eid": new_event_id, "bid": scenario["batch_id"],
                "wf": scenario["workflow_id"], "wfv": scenario["workflow_version_id"], "crop": scenario["crop_id"],
                "variety": scenario["variety_id"], "w": Decimal("6.000"), "c": 5,
                "eff": scenario["existing_event_effective_time"],
            },
        )
        conn.execute(
            text(
                "INSERT INTO harvest_source_lines "
                "(id, tenant_id, farm_id, harvest_event_id, batch_carrier_assignment_id, carrier_id, "
                "harvested_weight_kg, whole_unit_count, note) VALUES "
                "(:id, :tid, :fid, :eid, :aid, :cid, :w, :c, NULL)"
            ),
            {
                "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                "eid": new_event_id, "aid": scenario["assignment_ids"][2], "cid": scenario["carrier_ids"][2],
                "w": Decimal("1.000"), "c": 5,
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
                "id": uuid.uuid4(), "tid": scenario["tenant_id"], "fid": scenario["farm_id"],
                "eid": new_event_id, "aid": scenario["assignment_ids"][3], "cid": scenario["carrier_ids"][3],
                "w": Decimal("5.000"),
            },
        )
        with pytest.raises(Exception, match="mixed whole_unit_count presence"):
            trans.commit()
    finally:
        conn.rollback()
        conn.close()
