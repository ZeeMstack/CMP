"""NURSERY-OPS-005A migration proof: revision 283bad02bb69
(batch_carrier_population_checkpoints).

Mirrors the established per-ticket migration-proof conventions already used
by test_transplant_downgrade_guard.py (dedicated downgrade-guard file,
`alembic_head_restore` fixture, dynamically-resolved head) and
test_migrations.py's per-revision schema-shape assertions. Functional
behavior of the checkpoint mechanism itself (chaining, exhaustion,
correction, production-entry guard) is covered by
test_batch_carrier_population_checkpoint.py and
test_batch_carrier_population_checkpoint_correction.py -- this file proves
only the migration's own DDL/trigger/downgrade-guard contract.

Isolation follows the same discipline as test_transplant_downgrade_guard.py:
every test uses its own fresh tenant, scopes assertions to its own rows, and
cleans up everything it commits (via `cleanup_traceability_scenario`, which
NURSERY-OPS-005A extended to also delete
`batch_carrier_population_checkpoints` rows) so no test in this file --
including the "downgrade blocked when non-empty" test -- permanently blocks
downgrades on the shared `cmp_test` database, and no test here assumes a
particular collection order relative to any other file."""

import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from tests._traceability_scenario import cleanup_traceability_scenario
from tests._transplant_scenario import build_transplant_ready_scenario

API_ROOT = Path(__file__).resolve().parent.parent
# Never hardcode "current head" -- resolved dynamically, same rationale as
# test_transplant_downgrade_guard.py's own _PRE_CMP011_REVISION.
_PRE_005A_REVISION = "e2a7c9f4b816"


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_head_revision(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_current_head()


def _assert_at_head(test_engine) -> None:
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    expected_head = _resolve_head_revision(_cfg())
    assert current == expected_head, "a blocked downgrade must leave the database at Alembic head"


def _assert_operating_on_cmp_test_database(test_engine) -> None:
    with test_engine.connect() as conn:
        current_db = conn.execute(text("SELECT current_database()")).scalar_one()
    assert current_db == "cmp_test", (
        f"refusing destructive migration downgrade/upgrade against database {current_db!r} -- "
        "expected exactly 'cmp_test'"
    )


def _create_minimal_tenant_farm(session, *, code_suffix: str):
    from app.services import farm_service, membership_service, tenant_service, user_service

    tenant = tenant_service.create_tenant(session, code=f"pcmig-{code_suffix}", name="Population Checkpoint Migration Tenant")
    user = user_service.create_user(
        session, oidc_issuer="pcmig", oidc_subject=code_suffix, email=f"pcmig-{code_suffix}@example.com",
        display_name="Migration User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{code_suffix}", name="Migration Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    return tenant, user, farm


def _build_chained_nursery_plate_checkpoint(session, tenant, user, farm, *, suffix: str):
    """Commits a real, valid, chained Nursery-Plate-to-Nursery-Plate
    Transplant: Seed Tray -> Plate1 (opens Plate1, no checkpoint yet -- its
    opening population is derived), then Plate1 -> Plate2 (the chained
    consumption, which writes Plate1's own first
    `batch_carrier_population_checkpoints` row). Returns everything a
    caller needs to both inspect that real checkpoint row and to attempt
    direct-SQL negative-path inserts referencing the same, real
    transplant_source_line_id."""
    from app.services import carrier_specification_service, transplant_service

    spec = carrier_specification_service.register_carrier_specification(
        session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="nursery_cultivation_plate",
        code=f"NP-SPEC-{suffix}", name=f"NP-SPEC-{suffix}", length_mm=300, width_mm=200, height_mm=50,
        biological_position_count=200,
    )
    s = build_transplant_ready_scenario(
        session, tenant, user, farm, suffix=suffix, tray_count=1, normal=200, abnormal=0,
        transplanting_required_type="nursery_cultivation_plate", destination_specification_id=spec.id,
    )
    source_assignment_id = s["source_assignment_ids"][0]
    plate1 = s["destination_carriers"][0]
    opening_event = transplant_service.record_transplant(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=1), note=None,
        source_lines=[
            {
                "source_assignment_id": source_assignment_id, "transplant_damage_count": 0,
                "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0, "other_loss_note": None,
                "note": None,
            }
        ],
        destination_lines=[{"destination_carrier_id": plate1.id, "assigned_plant_count": 200, "note": None}],
        allocations=[
            {
                "source_assignment_id": source_assignment_id, "destination_carrier_id": plate1.id,
                "allocated_plant_count": 200,
            }
        ],
    )
    session.commit()

    plate1_assignment_id = session.execute(
        text("SELECT id FROM batch_carrier_assignments WHERE opening_transplant_event_id = :eid"),
        {"eid": opening_event.id},
    ).scalar_one()

    spec2 = carrier_specification_service.register_carrier_specification(
        session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="nursery_cultivation_plate",
        code=f"NP-SPEC2-{suffix}", name=f"NP-SPEC2-{suffix}", length_mm=300, width_mm=200, height_mm=50,
        biological_position_count=200,
    )
    from app.services import carrier_service

    plate2 = carrier_service.register_carrier(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="nursery_cultivation_plate", code=f"NP2-{suffix}", issued_date=None,
        specification_id=spec2.id,
    )
    # Deliberately PARTIAL (150 of Plate1's 200): keeps Plate1's own
    # assignment ACTIVE (remainder=50, not released) so a caller's
    # subsequent direct-SQL "invalid remainder" insert attempt reaches the
    # arithmetic check itself, rather than being shadowed by the earlier
    # "source assignment has already been released" check a full-exhaustion
    # consumption would trigger.
    chained_event = transplant_service.record_transplant(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
        source_lines=[
            {
                "source_assignment_id": plate1_assignment_id, "transplant_damage_count": 0,
                "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0, "other_loss_note": None,
                "note": None,
            }
        ],
        destination_lines=[{"destination_carrier_id": plate2.id, "assigned_plant_count": 150, "note": None}],
        allocations=[
            {
                "source_assignment_id": plate1_assignment_id, "destination_carrier_id": plate2.id,
                "allocated_plant_count": 150,
            }
        ],
    )
    session.commit()

    checkpoint_row = session.execute(
        text(
            "SELECT id, tenant_id, farm_id, batch_id, batch_carrier_assignment_id, transplant_source_line_id, "
            "previous_checkpoint_id, remainder_after, effective_time "
            "FROM batch_carrier_population_checkpoints WHERE batch_carrier_assignment_id = :aid"
        ),
        {"aid": plate1_assignment_id},
    ).one()

    return {
        "tenant": tenant, "batch_id": s["batch_id"], "plate1_assignment_id": plate1_assignment_id,
        "checkpoint_row": checkpoint_row, "opening_event_id": opening_event.id, "plate1_carrier_id": plate1.id,
        "active_batch_stage_run_id": chained_event.active_batch_stage_run_id,
    }


@pytest.mark.integration
def test_migration_creates_table_fks_indexes_trigger_with_no_backfill(test_engine, alembic_head_restore) -> None:
    _assert_operating_on_cmp_test_database(test_engine)
    command.downgrade(_cfg(), _PRE_005A_REVISION)
    with test_engine.connect() as conn:
        table_exists = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'batch_carrier_population_checkpoints'")
        ).first()
        trigger_exists = conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgname = "
                "'batch_carrier_population_checkpoints_enforce_insert_integrity'"
            )
        ).first()
        function_exists = conn.execute(
            text("SELECT 1 FROM pg_proc WHERE proname = 'enforce_batch_carrier_population_checkpoint_insert_integrity'")
        ).first()
    assert table_exists is None
    assert trigger_exists is None
    assert function_exists is None

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'batch_carrier_population_checkpoints'"
                )
            ).all()
        }
        fks = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid = "
                    "'batch_carrier_population_checkpoints'::regclass AND contype = 'f'"
                )
            ).all()
        }
        check_exists = conn.execute(
            text(
                "SELECT 1 FROM pg_constraint WHERE conname = "
                "'ck_batch_carrier_population_checkpoints_remainder_non_negative'"
            )
        ).first()
        unique_source_line = conn.execute(
            text(
                "SELECT 1 FROM pg_constraint WHERE conname = "
                "'ux_batch_carrier_population_checkpoints_source_line'"
            )
        ).first()
        unique_previous_index = conn.execute(
            text(
                "SELECT 1 FROM pg_indexes WHERE indexname = "
                "'ux_batch_carrier_population_checkpoints_previous_once'"
            )
        ).first()
        assignment_effective_index = conn.execute(
            text(
                "SELECT 1 FROM pg_indexes WHERE indexname = "
                "'ix_batch_carrier_population_checkpoints_assignment_effective'"
            )
        ).first()
        triggers = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT tgname FROM pg_trigger WHERE tgrelid = "
                    "'batch_carrier_population_checkpoints'::regclass AND NOT tgisinternal"
                )
            ).all()
        }
        row_count = conn.execute(text("SELECT count(*) FROM batch_carrier_population_checkpoints")).scalar_one()

    expected_columns = {
        "id", "tenant_id", "farm_id", "batch_id", "batch_carrier_assignment_id", "transplant_source_line_id",
        "previous_checkpoint_id", "remainder_after", "effective_time", "recorded_at",
    }
    assert expected_columns <= columns
    assert "fk_batch_carrier_population_checkpoints_tenant_farm_batch" in fks
    assert "fk_batch_carrier_population_checkpoints_tenant_farm_assignment" in fks
    assert "fk_batch_carrier_population_checkpoints_tenant_farm_source_line" in fks
    assert check_exists is not None
    assert unique_source_line is not None
    assert unique_previous_index is not None
    assert assignment_effective_index is not None
    assert {
        "batch_carrier_population_checkpoints_enforce_insert_integrity",
        "batch_carrier_population_checkpoints_no_update",
        "batch_carrier_population_checkpoints_no_delete",
        "batch_carrier_population_checkpoints_enforce_reconciliation",
    } <= triggers
    # No backfill DML: the table must start genuinely empty on a fresh
    # empty-to-head upgrade -- historical chained Nursery Plate consumption
    # could not previously exist (the prior guard made it categorically
    # impossible), so there is nothing to backfill.
    assert row_count == 0


@pytest.mark.integration
def test_migration_downgrade_allowed_when_table_empty(test_engine, alembic_head_restore) -> None:
    _assert_operating_on_cmp_test_database(test_engine)
    with test_engine.connect() as conn:
        row_count = conn.execute(text("SELECT count(*) FROM batch_carrier_population_checkpoints")).scalar_one()
    assert row_count == 0, "this test assumes no other test left committed checkpoint rows behind"

    command.downgrade(_cfg(), _PRE_005A_REVISION)
    with test_engine.connect() as conn:
        table_exists = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'batch_carrier_population_checkpoints'")
        ).first()
    assert table_exists is None, "downgrade must actually remove the table when it was empty"

    command.upgrade(_cfg(), "head")
    _assert_at_head(test_engine)


@pytest.mark.integration
def test_migration_downgrade_blocked_when_table_non_empty(test_engine, alembic_head_restore) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        _assert_operating_on_cmp_test_database(test_engine)
        tenant, user, farm = _create_minimal_tenant_farm(session, code_suffix=f"blk-{suffix}")
        tenant_id = tenant.id
        built = _build_chained_nursery_plate_checkpoint(session, tenant, user, farm, suffix=suffix)
        checkpoint_id = built["checkpoint_row"].id

        with pytest.raises(RuntimeError, match="batch_carrier_population_checkpoints"):
            command.downgrade(_cfg(), _PRE_005A_REVISION)

        _assert_at_head(test_engine)
        with test_engine.connect() as verify_conn:
            table_still_present = verify_conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'batch_carrier_population_checkpoints'")
            ).first()
            this_checkpoint_intact = verify_conn.execute(
                text("SELECT count(*) FROM batch_carrier_population_checkpoints WHERE id = :id"),
                {"id": checkpoint_id},
            ).scalar_one()
        assert table_still_present is not None, "a blocked downgrade must leave the NURSERY-OPS-005A schema untouched"
        assert this_checkpoint_intact == 1, "a blocked downgrade must leave this test's own checkpoint row untouched"
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_migration_trigger_rejects_cross_tenant_checkpoint_insert(test_engine, alembic_head_restore) -> None:
    """Exercises the FIRST line of defense the migration's own BEFORE INSERT
    trigger (`enforce_batch_carrier_population_checkpoint_insert_integrity`)
    provides -- its very first check compares the checkpoint's claimed
    tenant_id/farm_id against the referenced transplant_source_line's own
    tenant_id/farm_id and raises before any further validation (including
    the composite FK, which sits strictly behind this trigger for any
    INSERT that reaches it -- structural tenant isolation is proven
    unbypassable at this boundary regardless of which specific mechanism is
    first to fire)."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    other_tenant_id = None
    try:
        _assert_operating_on_cmp_test_database(test_engine)
        tenant, user, farm = _create_minimal_tenant_farm(session, code_suffix=f"xten-{suffix}")
        tenant_id = tenant.id
        other_tenant, _other_user, _other_farm = _create_minimal_tenant_farm(session, code_suffix=f"xten2-{suffix}")
        other_tenant_id = other_tenant.id
        built = _build_chained_nursery_plate_checkpoint(session, tenant, user, farm, suffix=suffix)
        row = built["checkpoint_row"]

        with pytest.raises(Exception, match="does not belong to this tenant"):
            session.execute(
                text(
                    "INSERT INTO batch_carrier_population_checkpoints "
                    "(id, tenant_id, farm_id, batch_id, batch_carrier_assignment_id, transplant_source_line_id, "
                    "previous_checkpoint_id, remainder_after, effective_time) VALUES "
                    "(:id, :tid, :fid, :bid, :aid, :slid, :prev, :rem, :eff)"
                ),
                {
                    "id": uuid.uuid4(), "tid": other_tenant_id, "fid": row.farm_id, "bid": row.batch_id,
                    "aid": row.batch_carrier_assignment_id, "slid": row.transplant_source_line_id,
                    "prev": row.id, "rem": row.remainder_after, "eff": row.effective_time,
                },
            )
        session.rollback()
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
        if other_tenant_id is not None:
            cleanup_traceability_scenario(test_engine, other_tenant_id)


@pytest.mark.integration
def test_migration_trigger_rejects_invalid_remainder_arithmetic(test_engine, alembic_head_restore) -> None:
    """Isolates the arithmetic check specifically. The real, committed
    checkpoint from `_build_chained_nursery_plate_checkpoint` already
    occupies its own transplant_source_line's UNIQUE checkpoint slot, and
    any second attempt on that SAME line -- for any other RECORD/REPLACEMENT
    -kind source line anchored to the SAME real transplant event -- would be
    caught by the (correctly stricter) equal-effective-time check first,
    never reaching the arithmetic check this test targets. A REVERSAL-kind
    transplant_source_line is deliberately lightly validated by
    `enforce_transplant_source_line_insert_integrity` (it trusts the
    correction SERVICE layer, not the trigger, to have computed
    `source_plant_count` correctly) and by `enforce_transplant_reconciliation`
    (a REVERSAL's own structural-only check never requires a checkpoint to
    exist) -- so a hand-crafted, but otherwise fully real and FK-valid,
    REVERSAL transplant_event + transplant_source_line pair against Plate1's
    real assignment gives a genuinely fresh, uncheckpointed, valid
    `transplant_source_line_id` to attach the checkpoint arithmetic negative
    test to, with every other check (tenant/farm, assignment, event
    effective_time, previous_checkpoint_id) satisfied on purpose."""
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        _assert_operating_on_cmp_test_database(test_engine)
        tenant, user, farm = _create_minimal_tenant_farm(session, code_suffix=f"badrem-{suffix}")
        tenant_id = tenant.id
        built = _build_chained_nursery_plate_checkpoint(session, tenant, user, farm, suffix=suffix)
        row = built["checkpoint_row"]

        reversal_event_id = uuid.uuid4()
        session.execute(
            text(
                "INSERT INTO transplant_events "
                "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
                "client_command_id, request_fingerprint, note, event_kind, reverses_transplant_event_id, "
                "correction_reason) VALUES "
                "(:id, :tid, :fid, :bid, :run_id, :eff, :uid, :cmd, :fp, NULL, 'REVERSAL', :reverses, :reason)"
            ),
            {
                "id": reversal_event_id, "tid": row.tenant_id, "fid": row.farm_id, "bid": row.batch_id,
                "run_id": built["active_batch_stage_run_id"], "eff": row.effective_time, "uid": user.id,
                "cmd": uuid.uuid4(), "fp": "migration-test-reversal-fingerprint",
                "reverses": built["opening_event_id"], "reason": "migration test isolation reversal",
            },
        )
        fresh_source_line_id = uuid.uuid4()
        session.execute(
            text(
                "INSERT INTO transplant_source_lines "
                "(id, tenant_id, farm_id, transplant_event_id, source_batch_carrier_assignment_id, "
                "source_carrier_id, source_plant_count, discarded_plant_count, transplant_damage_count, "
                "qc_rejection_count, sample_count, other_loss_count, other_loss_note, note) VALUES "
                "(:id, :tid, :fid, :eid, :aid, :cid, :spc, 0, 0, 0, 0, 0, NULL, NULL)"
            ),
            {
                "id": fresh_source_line_id, "tid": row.tenant_id, "fid": row.farm_id, "eid": reversal_event_id,
                "aid": row.batch_carrier_assignment_id, "cid": built["plate1_carrier_id"], "spc": 50,
            },
        )
        session.commit()

        with pytest.raises(Exception, match="remainder_after does not match"):
            session.execute(
                text(
                    "INSERT INTO batch_carrier_population_checkpoints "
                    "(id, tenant_id, farm_id, batch_id, batch_carrier_assignment_id, transplant_source_line_id, "
                    "previous_checkpoint_id, remainder_after, effective_time) VALUES "
                    "(:id, :tid, :fid, :bid, :aid, :slid, :prev, :rem, :eff)"
                ),
                {
                    "id": uuid.uuid4(), "tid": row.tenant_id, "fid": row.farm_id, "bid": row.batch_id,
                    "aid": row.batch_carrier_assignment_id, "slid": fresh_source_line_id,
                    "prev": row.id, "rem": 51, "eff": row.effective_time,
                },
            )
        session.rollback()
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
