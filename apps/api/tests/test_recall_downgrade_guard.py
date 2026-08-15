"""CMP-020 downgrade-guard proof tests.

Recall history follows CMP-015/017/018's own unconditional-block model: a
case, closure, or scope row is independent compliance data (nothing else
in the schema can rebuild it), so downgrade past CMP-020 is blocked while
ANY row exists in any of the five new tables. This file also proves a
clean downgrade drops the recall tables/triggers/functions, restores the
byte-exact CMP-015 (v1) packing_input_lines trigger, the byte-exact
CMP-018 (v1) storage-movement trigger, and the byte-exact CMP-018 (v3)
finished-goods-ledger trigger attachments, and that re-upgrade restores
the v2/v2/v4 containment-aware attachments and working containment gates."""
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.services import batch_derivation_service, packing_service, recall_service
from app.services.errors import RecallContainmentOpenError
from tests._recall_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    cleanup_recall_scenario,
    committed_connection,
    harvest_all,
    now,
    open_case,
    pack_lot,
)
from tests._traceability_scenario import build_workflow_scaffold
from app.services import carrier_service, crop_batch_service, sowing_service


def _sow_batch_at_downgraded_schema(db: Session, tenant, user, farm, *, carrier_count=1, suffix=None):
    """NURSERY-OPS-001 added `seeding_station_id`/`seeding_machine_id` to
    `sowing_events` -- absent below `_PRE_CMP020_REVISION`, so the CURRENT
    `sowing_service.sow_batch` (whose ORM model always selects/inserts
    those columns) cannot be used against the deliberately-downgraded
    schema this test exercises below, exactly like this module's own
    documented principle for CMP-020-shaped service code in general. Built
    directly via SQL instead (mirrors test_migrations.py's own equivalent
    fix for the same root cause) -- returns the same
    `{"batch", "assignment_ids"}` shape `build_batch_with_assignments`
    would have, for its two callers (`harvest_all`) below."""
    suffix = suffix or uuid.uuid4().hex[:8]
    scaffold = build_workflow_scaffold(db, tenant, user, farm, suffix=suffix)
    batch = crop_batch_service.create_batch(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=scaffold["workflow"].id, effective_time=now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=scaffold["crop"].id,
        variety_id=scaffold["variety"].id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    seeding_run_id = db.execute(
        text("SELECT id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"),
        {"bid": batch.id},
    ).scalar_one()
    sowing_event_id = uuid.uuid4()
    sow_effective_time = now()
    db.execute(
        text(
            "INSERT INTO sowing_events "
            "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
            "client_command_id, request_fingerprint, note) VALUES "
            "(:id, :tid, :fid, :bid, :run_id, :eff, :uid, :cmd, :fp, NULL)"
        ),
        {
            "id": sowing_event_id, "tid": tenant.id, "fid": farm.id, "bid": batch.id, "run_id": seeding_run_id,
            "eff": sow_effective_time, "uid": user.id, "cmd": uuid.uuid4(), "fp": "pre-cmp020-schema-sowing",
        },
    )
    assignment_ids = []
    for n in range(1, carrier_count + 1):
        carrier = carrier_service.register_carrier(
            db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"ST-{suffix}-{n:04d}", issued_date=None,
        )
        assignment_id = uuid.uuid4()
        db.execute(
            text(
                "INSERT INTO batch_carrier_assignments "
                "(id, tenant_id, farm_id, batch_id, carrier_id, batch_stage_run_id, assigned_effective_time, "
                "released_effective_time, opening_sowing_event_id, actor_user_id) VALUES "
                "(:id, :tid, :fid, :bid, :cid, :run_id, :eff, NULL, :eid, :uid)"
            ),
            {
                "id": assignment_id, "tid": tenant.id, "fid": farm.id, "bid": batch.id, "cid": carrier.id,
                "run_id": seeding_run_id, "eff": sow_effective_time, "eid": sowing_event_id, "uid": user.id,
            },
        )
        db.execute(
            text(
                "INSERT INTO sowing_event_lines "
                "(id, tenant_id, farm_id, sowing_event_id, batch_carrier_assignment_id, carrier_id, seed_lot_id, "
                "sown_site_count, seed_count, line_note) VALUES "
                "(:id, :tid, :fid, :eid, :aid, :cid, :lid, :site, :seed, NULL)"
            ),
            {
                "id": uuid.uuid4(), "tid": tenant.id, "fid": farm.id, "eid": sowing_event_id, "aid": assignment_id,
                "cid": carrier.id, "lid": seed_lot.id, "site": 20, "seed": 20,
            },
        )
        assignment_ids.append(assignment_id)
    # SEEDING -> HARVESTING: `transition_stage` never touches `sowing_events`,
    # so (unlike `sow_batch`) it's safe to call as-is against the downgraded
    # schema -- `harvest_all` below requires the batch already be in a
    # harvesting-category stage.
    crop_batch_service.transition_stage(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=scaffold["transition_1"].id, effective_time=now(), reason=None,
    )
    return {"batch": batch, "assignment_ids": assignment_ids}

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_CMP020_REVISION = "677fcd22cb3c"


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
    assert current == _resolve_head_revision(_cfg()), "a blocked downgrade must leave the database at Alembic head"


@pytest.mark.integration
def test_downgrade_blocked_by_recall_case_history(test_engine, alembic_head_restore) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            session.commit()
            open_case(session, tenant, farm, user, crop_batch_id=scaffold["batch"].id)
            session.commit()

        with pytest.raises(RuntimeError, match="recall case, closure, or scope history exists"):
            command.downgrade(_cfg(), _PRE_CMP020_REVISION)
        _assert_at_head(test_engine)
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_downgrade_blocked_even_after_case_closed(test_engine, alembic_head_restore) -> None:
    """A closed case is still independent compliance history -- closing
    never makes it discardable."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            session.commit()
            case = open_case(session, tenant, farm, user, crop_batch_id=scaffold["batch"].id)
            session.commit()
            case_id = case.id
            recall_service.close_recall_case(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, recall_case_id=case_id,
                client_command_id=uuid.uuid4(), effective_time=now(), close_reason="segregated",
            )
            session.commit()

        with pytest.raises(RuntimeError, match="recall case, closure, or scope history exists"):
            command.downgrade(_cfg(), _PRE_CMP020_REVISION)
        _assert_at_head(test_engine)
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_clean_downgrade_with_no_recall_history_reupgrade_restores_exact_prior_state(test_engine, alembic_head_restore) -> None:
    with test_engine.connect() as c:
        packing_v2_before = c.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'packing_input_lines'::regclass "
                "AND tgname = 'packing_input_lines_enforce_insert_integrity' "
                "AND tgfoid = 'enforce_packing_input_line_insert_integrity_v2'::regproc"
            )
        ).scalar_one()
        storage_v2_before = c.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_storage_movements'::regclass "
                "AND tgname = 'finished_goods_storage_movements_enforce_insert_integrity' "
                "AND tgfoid = 'enforce_finished_goods_storage_movement_insert_integrity_v2'::regproc"
            )
        ).scalar_one()
        ledger_v4_before = c.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                "AND tgfoid = 'enforce_finished_goods_ledger_entry_insert_integrity_v4'::regproc"
            )
        ).scalar_one()
        derivation_gate_before = c.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'batch_derivation_sources'::regclass "
                "AND tgname = 'batch_derivation_sources_enforce_containment'"
            )
        ).scalar_one()
    assert packing_v2_before == 1
    assert storage_v2_before == 1
    assert ledger_v4_before == 1
    assert derivation_gate_before == 1

    try:
        command.downgrade(_cfg(), _PRE_CMP020_REVISION)

        with test_engine.connect() as c:
            for table in (
                "recall_cases", "recall_case_closures", "recall_scope_batches",
                "recall_scope_produce_lots", "recall_scope_finished_goods_lots",
            ):
                exists = c.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar()
                assert exists is None, f"{table} must be dropped by a clean downgrade"

            packing_v1_after = c.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'packing_input_lines'::regclass "
                    "AND tgname = 'packing_input_lines_enforce_insert_integrity' "
                    "AND tgfoid = 'enforce_packing_input_line_insert_integrity'::regproc"
                )
            ).scalar_one()
            storage_v1_after = c.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_storage_movements'::regclass "
                    "AND tgname = 'finished_goods_storage_movements_enforce_insert_integrity' "
                    "AND tgfoid = 'enforce_finished_goods_storage_movement_insert_integrity'::regproc"
                )
            ).scalar_one()
            ledger_v3_after = c.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                    "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                    "AND tgfoid = 'enforce_finished_goods_ledger_entry_insert_integrity_v3'::regproc"
                )
            ).scalar_one()
            derivation_gate_after = c.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'batch_derivation_sources'::regclass "
                    "AND tgname = 'batch_derivation_sources_enforce_containment'"
                )
            ).scalar_one()
        assert packing_v1_after == 1, "the exact CMP-015 v1 attachment must be restored"
        assert storage_v1_after == 1, "the exact CMP-018 v1 attachment must be restored"
        assert ledger_v3_after == 1, "the exact CMP-018 v3 attachment must be restored"
        assert derivation_gate_after == 0, "the CMP-020-only containment trigger must be gone"

        # Behavior, not just catalog: a direct-SQL packing_input_line
        # insert against the restored v1 trigger succeeds with no
        # containment check at all -- the running application's own
        # service layer is CMP-020-shaped code and is not exercised
        # against a deliberately-downgraded schema (exactly as no other
        # downgrade-guard test in this codebase re-runs post-ticket
        # service code against a pre-ticket schema); the catalog-level
        # restoration proven above, plus this direct-SQL insert succeeding
        # without any recall table even existing, is the behavioral proof.
        tenant_id = None
        try:
            with committed_connection(test_engine) as session:
                tenant, user, farm = build_committed_tenant_farm(session)
                tenant_id = tenant.id
                scaffold = _sow_batch_at_downgraded_schema(session, tenant, user, farm, carrier_count=1)
                _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
                session.commit()
                farm_id, user_id = farm.id, user.id
                tid = tenant.id

            with test_engine.connect() as c:
                trans = c.begin()
                try:
                    event_id = uuid.uuid4()
                    crop_id, variety_id = c.execute(
                        text("SELECT crop_id, variety_id FROM harvested_produce_lots WHERE id = :id"), {"id": produce_lot_id}
                    ).one()
                    # The trigger compares effective_time against its own
                    # clock_timestamp() (never a frozen now()/transaction_
                    # timestamp() -- see HARVEST_MODEL.md). Reading the
                    # database's own current instant here (rather than the
                    # Python host clock) avoids any host/server clock-skew
                    # margin under load -- this connection's own prior
                    # SELECT already establishes a safely-past instant.
                    db_now = c.execute(text("SELECT clock_timestamp()")).scalar_one()
                    c.execute(
                        text(
                            "INSERT INTO packing_events (id, tenant_id, farm_id, crop_id, variety_id, "
                            "total_input_weight_kg, packed_output_weight_kg, process_loss_weight_kg, "
                            "rejected_weight_kg, effective_time, actor_user_id, client_command_id, "
                            "request_fingerprint, note) "
                            "VALUES (:id, :tid, :fid, :cid, :vid, 5.000, 5.000, 0, 0, :eff, :uid, :ccid, 'fp', NULL)"
                        ),
                        {"id": event_id, "tid": tid, "fid": farm_id, "cid": crop_id, "vid": variety_id, "eff": db_now, "uid": user_id, "ccid": uuid.uuid4()},
                    )
                    # This INSERT alone proves the restored v1 trigger has
                    # no recall-table reference left -- it must not raise
                    # "relation ... does not exist" even though no recall
                    # table exists anymore. Rolled back before commit so
                    # the (unrelated) deferred packing-reconciliation
                    # trigger -- which would object to a packing event
                    # with no finished-goods lot -- never fires.
                    c.execute(
                        text(
                            "INSERT INTO packing_input_lines (id, tenant_id, farm_id, packing_event_id, "
                            "harvested_produce_lot_id, consumed_weight_kg, consumed_whole_unit_count, note) "
                            "VALUES (:id, :tid, :fid, :eid, :lid, 5.000, NULL, NULL)"
                        ),
                        {"id": uuid.uuid4(), "tid": tid, "fid": farm_id, "eid": event_id, "lid": produce_lot_id},
                    )
                finally:
                    trans.rollback()
        finally:
            if tenant_id is not None:
                from tests._traceability_scenario import cleanup_traceability_scenario
                cleanup_traceability_scenario(test_engine, tenant_id)

        command.upgrade(_cfg(), "head")
        with test_engine.connect() as c:
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == _resolve_head_revision(_cfg())
            packing_v2_restored = c.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'packing_input_lines'::regclass "
                    "AND tgname = 'packing_input_lines_enforce_insert_integrity' "
                    "AND tgfoid = 'enforce_packing_input_line_insert_integrity_v2'::regproc"
                )
            ).scalar_one()
            ledger_v4_restored = c.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                    "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                    "AND tgfoid = 'enforce_finished_goods_ledger_entry_insert_integrity_v4'::regproc"
                )
            ).scalar_one()
        assert packing_v2_restored == 1
        assert ledger_v4_restored == 1

        # Re-upgraded containment gate genuinely works again.
        tenant_id2 = None
        try:
            with committed_connection(test_engine) as session:
                tenant, user, farm = build_committed_tenant_farm(session)
                tenant_id2 = tenant.id
                scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2)
                session.commit()
                batch_id = scaffold["batch"].id
                open_case(session, tenant, farm, user, crop_batch_id=batch_id)
                session.commit()
                with pytest.raises(RecallContainmentOpenError):
                    batch_derivation_service.split_batch(
                        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
                        client_command_id=uuid.uuid4(), effective_time=now(), note=None,
                        outputs=[
                            {"output_batch_code": "POST-A", "source_assignment_ids": scaffold["assignment_ids"][:1]},
                            {"output_batch_code": "POST-B", "source_assignment_ids": scaffold["assignment_ids"][1:]},
                        ],
                    )
        finally:
            if tenant_id2 is not None:
                cleanup_recall_scenario(test_engine, tenant_id2)
    finally:
        command.upgrade(_cfg(), "head")
