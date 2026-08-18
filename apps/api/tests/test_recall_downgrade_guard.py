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
    now,
    open_case,
    pack_lot,
)
from app.services import crop_batch_service, sowing_service


def _build_workflow_scaffold_at_downgraded_schema(db: Session, tenant, user, farm, *, suffix=None):
    """Local, revision-compatible substitute for
    `tests/_traceability_scenario.py::build_workflow_scaffold` -- that
    shared helper is correct for its many normal, at-head callers and is
    deliberately left untouched here. It cannot be used below
    `_PRE_CMP020_REVISION` because its SEEDING stage goes through
    `workflow_service.add_stage`, whose ORM model always selects
    `carrier_types.requires_specification`/`biological_position_label`
    (added by CARRIER-CONFIG-001) -- absent at that schema era. Built
    directly via SQL for the SEEDING stage and the publish step only
    (mirrors this file's own `_sow_batch_at_downgraded_schema` and
    `test_migrations.py`'s equivalent fix for the same root cause);
    HARVESTING/COMPLETE have no required carrier type, so `add_stage` never
    touches `carrier_types` for them and stays on the normal ORM path.
    Returns the same `{"crop", "variety", "workflow", "version",
    "transition_1"}` shape `build_workflow_scaffold` does, for this
    function's one caller below."""
    from app.services import crop_service, production_system_service, workflow_service

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
    version = workflow_service.create_draft_version(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )

    seeding_carrier_type_id = db.execute(
        text("SELECT id FROM carrier_types WHERE code = 'seed_tray'")
    ).scalar_one()
    seeding_stage_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO workflow_stages "
            "(id, tenant_id, workflow_version_id, code, name, display_order, stage_category, "
            "required_carrier_type_id, is_start, is_terminal) VALUES "
            "(:id, :tid, :vid, 'SEEDING', 'Seeding', 0, 'seeding', :ctid, true, false)"
        ),
        {"id": seeding_stage_id, "tid": tenant.id, "vid": version.id, "ctid": seeding_carrier_type_id},
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
        from_stage_id=seeding_stage_id, to_stage_id=harvesting.id, code="ADV-1", name="Advance 1",
    )
    workflow_service.add_transition(
        db, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=harvesting.id, to_stage_id=complete.id, code="ADV-2", name="Advance 2",
    )
    # `publish_version`'s own publication-graph validation re-resolves
    # every stage's `required_carrier_type_id` via `db.get(CarrierType,
    # ...)` -- broken at this deliberately-downgraded schema level for the
    # same reason as the SEEDING stage's own insert above. `crop_batch_
    # service.create_batch` only ever checks `WorkflowVersion.state ==
    # 'published'` as a plain row read (confirmed from source, matching
    # `test_migrations.py`'s own established rationale for this exact
    # substitution), so publishing directly via SQL is a faithful, minimal
    # substitute.
    db.execute(
        text("UPDATE workflow_versions SET state = 'published', published_at = now() WHERE id = :vid"),
        {"vid": version.id},
    )
    return {"crop": crop, "variety": variety, "workflow": workflow, "version": version, "transition_1": t1}


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
    would have, for `_harvest_all_at_downgraded_schema` below."""
    suffix = suffix or uuid.uuid4().hex[:8]
    scaffold = _build_workflow_scaffold_at_downgraded_schema(db, tenant, user, farm, suffix=suffix)
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
    # CARRIER-CONFIG-001 added `carrier_types.requires_specification`/
    # `biological_position_label` and `carriers.specification_id` -- absent
    # below `_PRE_CMP020_REVISION` (a schema era from well before that
    # ticket), so `carrier_service.register_carrier`'s current, full-entity
    # ORM select of `CarrierType` cannot run here either, for the same
    # reason `sowing_service.sow_batch` can't (see this function's own
    # docstring above). Built directly via SQL instead.
    seed_tray_type_id = db.execute(
        text("SELECT id FROM carrier_types WHERE code = 'seed_tray'")
    ).scalar_one()
    assignment_ids = []
    for n in range(1, carrier_count + 1):
        carrier_id = uuid.uuid4()
        db.execute(
            text(
                "INSERT INTO carriers (id, tenant_id, farm_id, carrier_type_id, code, status, issued_date, "
                "retired_date) VALUES (:id, :tid, :fid, :ctid, :code, 'active', NULL, NULL)"
            ),
            {
                "id": carrier_id, "tid": tenant.id, "fid": farm.id, "ctid": seed_tray_type_id,
                "code": f"ST-{suffix}-{n:04d}",
            },
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
                "id": assignment_id, "tid": tenant.id, "fid": farm.id, "bid": batch.id, "cid": carrier_id,
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
                "cid": carrier_id, "lid": seed_lot.id, "site": 20, "seed": 20,
            },
        )
        assignment_ids.append(assignment_id)
    # SEEDING -> HARVESTING: `transition_stage` never touches `sowing_events`,
    # so (unlike `sow_batch`) it's safe to call as-is against the downgraded
    # schema -- `_harvest_all_at_downgraded_schema` below requires the batch
    # already be in a harvesting-category stage.
    crop_batch_service.transition_stage(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=scaffold["transition_1"].id, effective_time=now(), reason=None,
    )
    return {"batch": batch, "assignment_ids": assignment_ids}


def _harvest_all_at_downgraded_schema(
    db: Session, tenant, user, farm, *, batch_id, assignment_ids, weight_per_line=Decimal("5.000"), suffix=None
):
    """Local, revision-compatible substitute for
    `tests/_traceability_scenario.py::harvest_all` -- that shared helper is
    correct for its many normal, at-head callers and is deliberately left
    untouched. It cannot be used below `_PRE_CMP020_REVISION` because
    `harvest_service.record_harvest` locks `Carrier` rows via a full-entity
    `select(Carrier)...with_for_update()`, whose ORM model always selects
    `carriers.specification_id` (added by CARRIER-CONFIG-001) -- absent at
    this schema era, for the same root cause already documented above for
    `sowing_service.sow_batch`/`carrier_service.register_carrier`.

    Builds the same four-row write footprint `record_harvest` does
    (`harvest_events`, `harvest_source_lines`, `harvested_produce_lots`,
    `produce_lot_ledger_entries`) directly via SQL. This is NOT an
    optional-minimalism shortcut: CMP-013's immediate (BEFORE INSERT)
    integrity triggers and CMP-013/CMP-014's deferred (constraint-trigger)
    reconciliation checks on these four tables are schema-level invariants,
    not merely service-layer validation -- a raw insert of any subset of
    these rows fails at INSERT or COMMIT time regardless of caller intent,
    so all four are required to reach a valid, committable state, even
    though this test's own remaining assertions only read
    `harvested_produce_lots.crop_id`/`variety_id` and the returned
    `produce_lot_id`. `effective_time`/`recorded_time` are each computed
    once and reused across every row that must match them exactly (the
    ledger reconciliation trigger requires byte-exact equality, not just
    closeness) rather than relying on two separate `now()` server defaults
    that could otherwise differ by microseconds. Returns only
    `produce_lot_id` -- the `event` half of `harvest_all`'s `(event,
    lot_id)` return is unused by this test."""
    suffix = suffix or uuid.uuid4().hex[:8]

    workflow_id, workflow_version_id = db.execute(
        text("SELECT workflow_id, workflow_version_id FROM crop_batches WHERE id = :bid"), {"bid": batch_id}
    ).one()
    crop_id, variety_id = db.execute(
        text("SELECT crop_id, variety_id FROM workflows WHERE id = :wid"), {"wid": workflow_id}
    ).one()
    active_run_id = db.execute(
        text("SELECT id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"),
        {"bid": batch_id},
    ).scalar_one()

    eff = now()
    recorded = now()
    event_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO harvest_events "
            "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, recorded_time, "
            "actor_user_id, client_command_id, request_fingerprint, note) VALUES "
            "(:id, :tid, :fid, :bid, :run_id, :eff, :rec, :uid, :cmd, :fp, NULL)"
        ),
        {
            "id": event_id, "tid": tenant.id, "fid": farm.id, "bid": batch_id, "run_id": active_run_id,
            "eff": eff, "rec": recorded, "uid": user.id, "cmd": uuid.uuid4(),
            "fp": f"pre-cmp020-schema-harvest-{suffix}",
        },
    )

    total_weight = Decimal("0")
    for aid in assignment_ids:
        carrier_id = db.execute(
            text("SELECT carrier_id FROM batch_carrier_assignments WHERE id = :aid"), {"aid": aid}
        ).scalar_one()
        db.execute(
            text(
                "INSERT INTO harvest_source_lines "
                "(id, tenant_id, farm_id, harvest_event_id, batch_carrier_assignment_id, carrier_id, "
                "harvested_weight_kg, whole_unit_count, note) VALUES "
                "(:id, :tid, :fid, :eid, :aid, :cid, :weight, NULL, NULL)"
            ),
            {
                "id": uuid.uuid4(), "tid": tenant.id, "fid": farm.id, "eid": event_id, "aid": aid,
                "cid": carrier_id, "weight": weight_per_line,
            },
        )
        total_weight += weight_per_line

    lot_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO harvested_produce_lots "
            "(id, tenant_id, farm_id, code, harvest_event_id, batch_id, workflow_id, workflow_version_id, "
            "crop_id, variety_id, total_harvested_weight_kg, total_whole_unit_count, effective_time, "
            "recorded_at) VALUES "
            "(:id, :tid, :fid, :code, :eid, :bid, :wid, :wvid, :cid, :vid, :weight, NULL, :eff, :rec)"
        ),
        {
            "id": lot_id, "tid": tenant.id, "fid": farm.id, "code": f"HLOT-{suffix}", "eid": event_id,
            "bid": batch_id, "wid": workflow_id, "wvid": workflow_version_id, "cid": crop_id, "vid": variety_id,
            "weight": total_weight, "eff": eff, "rec": recorded,
        },
    )

    # CMP-014's deferred `harvested_produce_lots_enforce_ledger_reconciliation`
    # requires exactly one matching `harvest_receipt` ledger entry per lot,
    # with every field an exact match to the lot/event -- see this
    # function's own docstring.
    db.execute(
        text(
            "INSERT INTO produce_lot_ledger_entries "
            "(id, tenant_id, farm_id, produce_lot_id, harvest_event_id, entry_kind, weight_delta_kg, "
            "whole_unit_count_delta, effective_time, recorded_time, actor_user_id, note) VALUES "
            "(:id, :tid, :fid, :lid, :eid, 'harvest_receipt', :weight, NULL, :eff, :rec, :uid, NULL)"
        ),
        {
            "id": lot_id, "tid": tenant.id, "fid": farm.id, "lid": lot_id, "eid": event_id,
            "weight": total_weight, "eff": eff, "rec": recorded, "uid": user.id,
        },
    )

    return lot_id


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
            # CARRIER-CONFIG-001A: recall history existence is unrelated to
            # carrier type -- grow_bag keeps the scenario free of a
            # carrier_specifications row, which would otherwise
            # unconditionally block via e5b8c3a72f04's own, earlier-in-chain
            # guard before CMP-020's own guard is ever reached.
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1, carrier_type_code="grow_bag")
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
            # CARRIER-CONFIG-001A: recall history existence is unrelated to
            # carrier type -- grow_bag keeps the scenario free of a
            # carrier_specifications row, which would otherwise
            # unconditionally block via e5b8c3a72f04's own, earlier-in-chain
            # guard before CMP-020's own guard is ever reached.
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1, carrier_type_code="grow_bag")
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
                produce_lot_id = _harvest_all_at_downgraded_schema(
                    session, tenant, user, farm, batch_id=scaffold["batch"].id,
                    assignment_ids=scaffold["assignment_ids"],
                )
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
                scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2, carrier_type_code="grow_bag")
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
