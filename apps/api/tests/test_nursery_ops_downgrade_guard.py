"""NURSERY-OPS-001 downgrade-guard proof test (migration a7e4f2c9b381).

A committed Sowing command populates `sowing_events.seeding_station_id`
(and, when a Seeding Machine is used, `seeding_machine_id`) -- provenance
data this migration's downgrade must refuse to silently discard. Mirrors
test_batch_derivation_downgrade_guard.py's hardened isolation/cleanup
pattern."""
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_NURSERY_OPS_REVISION = "f91c366cfe57"


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_head_revision(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_current_head()


def _now():
    return datetime.now(timezone.utc)


def _assert_at_head(test_engine) -> None:
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    expected_head = _resolve_head_revision(_cfg())
    assert current == expected_head, "a blocked downgrade must leave the database at Alembic head"


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
        conn.execute(text("DELETE FROM sowing_event_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_carrier_assignments WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM seed_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        if conn.execute(text("SELECT to_regclass('carrier_specifications')")).scalar() is not None:
            conn.execute(text("DELETE FROM carrier_specifications WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM assets WHERE tenant_id = :tid"), {"tid": tenant_id})
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


@pytest.mark.integration
def test_migration_downgrade_blocked_when_seeding_provenance_exists(test_engine, alembic_head_restore) -> None:
    from app.schemas.farm_setup import GreenhouseSetupCreate, NurserySectionConfig, NurserySetupConfig
    from app.services import (
        carrier_service,
        crop_service,
        farm_service,
        farm_setup_service,
        membership_service,
        nursery_service,
        production_system_service,
        sowing_service,
        tenant_service,
        user_service,
        workflow_service,
    )

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant = tenant_service.create_tenant(session, code=f"nurs-guard-{suffix}", name="Nursery Guard Tenant")
        tenant_id = tenant.id
        user = user_service.create_user(
            session, oidc_issuer="nurs-guard", oidc_subject=suffix, email=f"nurs-guard-{suffix}@example.com",
            display_name="Guard User",
        )
        membership_service.add_membership(session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Guard Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"CROP-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"VAR-{suffix}",
            name="Variety", supplier_reference=None,
        )
        ps = production_system_service.register_production_system(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="System", description=None,
        )
        workflow = workflow_service.register_workflow(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
            production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
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
        complete = workflow_service.add_stage(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
            expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
            is_start=False, is_terminal=True,
        )
        workflow_service.add_transition(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=seeding.id, to_stage_id=complete.id, code="ADV", name="Advance",
        )
        workflow_service.publish_version(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
        )
        seed_lot = sowing_service.register_seed_lot(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
            variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
            received_date=None, expiry_date=None,
        )
        setup = farm_setup_service.create_greenhouse_setup(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            payload=GreenhouseSetupCreate(
                code=f"NUR-{suffix}", name="Nursery", classification="nursery", client_command_id=uuid.uuid4(),
                nursery=NurserySetupConfig(seeding_station=NurserySectionConfig(code=f"SEED-{suffix}")),
            ),
        )
        structure = farm_setup_service.get_greenhouse_structure(
            session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
        )
        from tests.conftest import ensure_seed_tray_specification
        seed_tray_spec = ensure_seed_tray_specification(session, tenant_id=tenant.id, actor_user_id=user.id)
        carrier = carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=seed_tray_spec.id,
            code=f"ST-{suffix}", issued_date=None,
        )
        event = nursery_service.sow_new_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            seed_lot_id=seed_lot.id, seeding_station_id=structure.nursery_seeding_stations[0].id,
            seeding_machine_id=None, effective_time=_now(), note=None,
            trays=[{"carrier_id": carrier.id, "seeds_sown": 100}],
        )
        event_id = event.id

        # CARRIER-CONFIG-001A: nursery_service.sow_new_batch requires a
        # workflow whose SEEDING stage's required_carrier_type is exactly
        # seed_tray (see nursery_service.SEED_TRAY_CARRIER_TYPE_CODE), so
        # this scenario cannot avoid registering a seed_tray Carrier --
        # which, since 001A, always carries a carrier_specifications row.
        # e5b8c3a72f04 (CARRIER-CONFIG-001) sits between head and
        # _PRE_NURSERY_OPS_REVISION in the migration chain and its own
        # downgrade guard unconditionally blocks on ANY carrier_specifications
        # row -- it now always fires before NURSERY-OPS-001's own guard is
        # ever reached, making this the correct, permanent expectation
        # rather than the original NURSERY-OPS-001-specific message.
        with pytest.raises(RuntimeError, match="Cannot downgrade past CARRIER-CONFIG-001"):
            command.downgrade(_cfg(), _PRE_NURSERY_OPS_REVISION)

        _assert_at_head(test_engine)
        with test_engine.connect() as verify_conn:
            column_still_present = verify_conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'sowing_events' AND column_name = 'seeding_station_id'"
                )
            ).first()
            event_still_present = verify_conn.execute(
                text("SELECT count(*) FROM sowing_events WHERE id = :id AND seeding_station_id IS NOT NULL"),
                {"id": event_id},
            ).scalar_one()
        assert column_still_present is not None, "a blocked downgrade must leave the seeding_station_id column intact"
        assert event_still_present == 1, "a blocked downgrade must leave this test's own provenance data untouched"
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_migration_downgrade_blocked_when_sown_site_count_unrecorded(test_engine, alembic_head_restore) -> None:
    """NURSERY-OPS-001.1: a Sowing Event recorded with NO seeding-station/
    machine provenance (so the ORIGINAL NURSERY-OPS-001 guard above does
    not itself fire) but WITH an honestly-unrecorded `sown_site_count`
    (NULL) must still block downgrade on its own -- restoring NOT NULL
    would otherwise silently force a fabricated site count. Built via the
    general/legacy `sowing_service.sow_batch` path (whose
    `seeding_station_id`/`seeding_machine_id` are optional and left NULL
    here), with `sown_site_count` explicitly passed as None -- proving the
    two new guards are independent, not just piggybacking on the first."""
    from app.services import (
        carrier_service, crop_service, farm_service, membership_service, production_system_service,
        sowing_service, tenant_service, user_service, workflow_service, crop_batch_service,
    )

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant = tenant_service.create_tenant(session, code=f"nurs-site-{suffix}", name="Site Count Guard Tenant")
        tenant_id = tenant.id
        user = user_service.create_user(
            session, oidc_issuer="nurs-site", oidc_subject=suffix, email=f"nurs-site-{suffix}@example.com",
            display_name="Guard User",
        )
        membership_service.add_membership(session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Guard Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"CROP-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"VAR-{suffix}",
            name="Variety", supplier_reference=None,
        )
        ps = production_system_service.register_production_system(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="System", description=None,
        )
        workflow = workflow_service.register_workflow(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
            production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
        )
        version = workflow_service.create_draft_version(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
        )
        # CARRIER-CONFIG-001A: this test exercises NURSERY-OPS-001.1's own
        # sown_site_count guard via the generic sowing_service.sow_batch
        # path (unlike the seeding-provenance test above, this one does not
        # need nursery_service.sow_new_batch), so it uses grow_bag (still
        # requires_specification=false) to avoid ever creating a
        # carrier_specifications row -- otherwise e5b8c3a72f04's own,
        # stricter, later-in-chain guard would fire first and mask the
        # NURSERY-OPS-001.1 guard this test is actually about.
        seeding = workflow_service.add_stage(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
            expected_duration_minutes=None, permitted_location_type_code=None,
            required_carrier_type_code="grow_bag", is_start=True, is_terminal=False,
        )
        complete = workflow_service.add_stage(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
            expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
            is_start=False, is_terminal=True,
        )
        workflow_service.add_transition(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=seeding.id, to_stage_id=complete.id, code="ADV", name="Advance",
        )
        workflow_service.publish_version(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
        )
        seed_lot = sowing_service.register_seed_lot(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
            variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
            received_date=None, expiry_date=None,
        )
        batch = crop_batch_service.create_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
        )
        carrier = carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="grow_bag",
            code=f"ST-{suffix}", issued_date=None,
        )
        sowing_service.sow_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
            lines=[
                {
                    "carrier_id": carrier.id, "seed_lot_id": seed_lot.id,
                    "sown_site_count": None, "seed_count": 100, "line_note": None,
                }
            ],
        )

        with pytest.raises(RuntimeError, match="Cannot downgrade past NURSERY-OPS-001.1"):
            command.downgrade(_cfg(), _PRE_NURSERY_OPS_REVISION)
        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_migration_upgrade_blocked_by_pre_existing_mixed_seed_lot_lines(test_engine, alembic_head_restore) -> None:
    """NURSERY-OPS-001.1: simulates data that pre-dates this migration --
    downgrades to the pre-ticket revision, hand-inserts a legacy-shaped
    Sowing Event whose two lines already reference two DIFFERENT Seed
    Lots (legal under the OLD trigger, which never compared across
    lines), then proves the upgrade itself refuses to silently backfill
    `sowing_events.seed_lot_id` by guessing one of the two -- it must fail
    loudly instead."""
    from app.services import (
        crop_service, farm_service, membership_service, production_system_service,
        sowing_service, tenant_service, user_service, workflow_service, crop_batch_service,
    )

    command.downgrade(_cfg(), _PRE_NURSERY_OPS_REVISION)
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant = tenant_service.create_tenant(session, code=f"nurs-mix-{suffix}", name="Mixed Lot Guard Tenant")
        tenant_id = tenant.id
        user = user_service.create_user(
            session, oidc_issuer="nurs-mix", oidc_subject=suffix, email=f"nurs-mix-{suffix}@example.com",
            display_name="Guard User",
        )
        membership_service.add_membership(session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Guard Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"CROP-{suffix}", common_name="Iceberg",
            scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"VAR-{suffix}",
            name="Variety", supplier_reference=None,
        )
        ps = production_system_service.register_production_system(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="System", description=None,
        )
        workflow = workflow_service.register_workflow(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
            production_system_id=ps.id, code=f"WF-{suffix}", name="Workflow",
        )
        version = workflow_service.create_draft_version(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
        )
        # CARRIER-CONFIG-001 added `carrier_types.requires_specification`/
        # `biological_position_label` -- absent at this deliberately-
        # downgraded (pre-NURSERY-OPS-001) schema level, so the CURRENT
        # `workflow_service.add_stage` (whose ORM model always selects
        # those columns to resolve `required_carrier_type_code`) cannot be
        # used for the SEEDING stage here. Built directly via SQL instead,
        # matching the same established pattern `test_migrations.py` already
        # uses for its own equivalent SEEDING-stage fixtures -- the carrier
        # registration below reuses this same resolved id.
        seeding_carrier_type_id = session.execute(
            text("SELECT id FROM carrier_types WHERE code = 'seed_tray'")
        ).scalar_one()
        seeding_stage_id = uuid.uuid4()
        session.execute(
            text(
                "INSERT INTO workflow_stages "
                "(id, tenant_id, workflow_version_id, code, name, display_order, stage_category, "
                "required_carrier_type_id, is_start, is_terminal) VALUES "
                "(:id, :tid, :vid, 'SEEDING', 'Seeding', 0, 'seeding', :ctid, true, false)"
            ),
            {"id": seeding_stage_id, "tid": tenant.id, "vid": version.id, "ctid": seeding_carrier_type_id},
        )
        # COMPLETE has no required carrier type, so `add_stage` never
        # queries `carrier_types` for it -- safe to build via the normal
        # ORM path.
        complete = workflow_service.add_stage(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
            expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
            is_start=False, is_terminal=True,
        )
        workflow_service.add_transition(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=seeding_stage_id, to_stage_id=complete.id, code="ADV", name="Advance",
        )
        # `publish_version`'s own publication-graph validation re-resolves
        # every stage's `required_carrier_type_id` via `db.get(CarrierType,
        # ...)` -- broken at this deliberately-downgraded schema level for
        # the same reason as the SEEDING stage's own insert above.
        # `crop_batch_service.create_batch` only ever checks
        # `WorkflowVersion.state == 'published'` as a plain row read
        # (confirmed from source, matching `test_migrations.py`'s own
        # established rationale for this exact substitution), so publishing
        # directly via SQL is a faithful, minimal substitute -- no previous
        # published version exists yet to retire, and no audit event is
        # needed for what this test actually verifies (the mixed-Seed-Lot
        # upgrade guard).
        session.execute(
            text("UPDATE workflow_versions SET state = 'published', published_at = now() WHERE id = :vid"),
            {"vid": version.id},
        )
        seed_lot_a = sowing_service.register_seed_lot(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
            variety_id=variety.id, code=f"LOT-A-{suffix}", supplier_name=None, supplier_lot_reference=None,
            received_date=None, expiry_date=None,
        )
        seed_lot_b = sowing_service.register_seed_lot(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
            variety_id=variety.id, code=f"LOT-B-{suffix}", supplier_name=None, supplier_lot_reference=None,
            received_date=None, expiry_date=None,
        )
        batch = crop_batch_service.create_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
        )
        # Reuses `seeding_carrier_type_id` (resolved above) rather than a
        # second, redundant `carrier_types` lookup.
        carrier_a_id = uuid.uuid4()
        carrier_b_id = uuid.uuid4()
        for cid, code in ((carrier_a_id, f"ST-A-{suffix}"), (carrier_b_id, f"ST-B-{suffix}")):
            session.execute(
                text(
                    "INSERT INTO carriers (id, tenant_id, farm_id, carrier_type_id, code, status, issued_date, "
                    "retired_date) VALUES (:id, :tid, :fid, :ctid, :code, 'active', NULL, NULL)"
                ),
                {"id": cid, "tid": tenant.id, "fid": farm.id, "ctid": seeding_carrier_type_id, "code": code},
            )
        # Legal under the pre-NURSERY-OPS-001.1 trigger: two lines of one
        # event, two different Seed Lots of the same crop/variety. Built
        # via raw SQL, NOT `sowing_service.sow_batch` -- the CURRENT
        # (head-version) service code already rejects this itself
        # (`MixedSeedLotInSowingCommandError`) before writing anything, so
        # it cannot be used to construct "data that already existed before
        # this migration" at this deliberately-downgraded schema level
        # (mirrors this same principle already established for
        # test_migrations.py / test_recall_downgrade_guard.py).
        active_run_id = session.execute(
            text("SELECT id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"),
            {"bid": batch.id},
        ).scalar_one()
        event_id = uuid.uuid4()
        sow_time = _now()
        session.execute(
            text(
                "INSERT INTO sowing_events "
                "(id, tenant_id, farm_id, batch_id, active_batch_stage_run_id, effective_time, actor_user_id, "
                "client_command_id, request_fingerprint, note) VALUES "
                "(:id, :tid, :fid, :bid, :run_id, :eff, :uid, :cmd, :fp, NULL)"
            ),
            {
                "id": event_id, "tid": tenant.id, "fid": farm.id, "bid": batch.id, "run_id": active_run_id,
                "eff": sow_time, "uid": user.id, "cmd": uuid.uuid4(), "fp": "pre-nursery-ops-001-1-mixed-lot",
            },
        )
        for carrier_id, seed_lot, sown in ((carrier_a_id, seed_lot_a, 50), (carrier_b_id, seed_lot_b, 50)):
            assignment_id = uuid.uuid4()
            session.execute(
                text(
                    "INSERT INTO batch_carrier_assignments "
                    "(id, tenant_id, farm_id, batch_id, carrier_id, batch_stage_run_id, assigned_effective_time, "
                    "released_effective_time, opening_sowing_event_id, actor_user_id) VALUES "
                    "(:id, :tid, :fid, :bid, :cid, :run_id, :eff, NULL, :eid, :uid)"
                ),
                {
                    "id": assignment_id, "tid": tenant.id, "fid": farm.id, "bid": batch.id, "cid": carrier_id,
                    "run_id": active_run_id, "eff": sow_time, "eid": event_id, "uid": user.id,
                },
            )
            session.execute(
                text(
                    "INSERT INTO sowing_event_lines "
                    "(id, tenant_id, farm_id, sowing_event_id, batch_carrier_assignment_id, carrier_id, seed_lot_id, "
                    "sown_site_count, seed_count, line_note) VALUES "
                    "(:id, :tid, :fid, :eid, :aid, :cid, :lid, :site, :seed, NULL)"
                ),
                {
                    "id": uuid.uuid4(), "tid": tenant.id, "fid": farm.id, "eid": event_id, "aid": assignment_id,
                    "cid": carrier_id, "lid": seed_lot.id, "site": sown, "seed": sown,
                },
            )
        session.commit()

        with pytest.raises(RuntimeError, match="already have lines referencing more than one Seed Lot"):
            command.upgrade(_cfg(), _resolve_head_revision(_cfg()))
    finally:
        session.close()
        conn.close()
        # Delete the offending mixed-Seed-Lot data (still at the
        # downgraded schema level here, which `_cleanup_scenario`'s
        # column-agnostic DELETEs tolerate fine) BEFORE
        # `alembic_head_restore`'s own teardown unconditionally re-upgrades
        # to head -- otherwise that upgrade would hit this exact guard
        # again and fail.
        if tenant_id is not None:
            _cleanup_scenario(test_engine, tenant_id)
