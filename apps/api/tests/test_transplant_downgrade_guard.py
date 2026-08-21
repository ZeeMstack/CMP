"""CMP-011 downgrade-guard proof tests.

Both tests must commit real rows before the guard can be exercised: the
reconciliation constraint triggers reject any half-built, unreconciled
transplant at commit time, so there is no way to trip the migration's
downgrade guard with less than a fully realistic scenario (a published
workflow, a real sowing event, and — for the second test — a fully
reconciled transplant event). That unavoidably emits the same audit
actions (`workflow.published`, `crop_batch.sown`, `crop_batch.transplanted`)
that other test files also produce.

Test isolation here does NOT rely on file or collection order. Each test:
  - uses its own unique tenant (fresh UUID identity per run, so it never
    collides with rows any other test — in this file, this suite, or a
    prior run against the same database — has created or left behind);
  - scopes every assertion to its own tenant/batch/event/stage id, never to
    a bare table-wide count;
  - cleans up every row it committed in a `finally` block, using
    `session_replication_role = replica` to bypass the append-only/no-delete
    triggers that (correctly) protect real production history — mirroring
    the same technique test_transplant_concurrency.py already uses for its
    own committed-connection tests. This is deleting only this test's own
    just-created rows, never production data, and is safe to repeat any
    number of times against the same `cmp_test` database.

Because of that cleanup, running either test does not permanently block
further downgrades on the shared database — the guard is proven at the
moment of the call (via the committed data that exists at that instant),
and the evidence is torn down immediately afterward, exactly like any other
committed-connection test in this suite."""
import uuid
from datetime import datetime, timedelta, timezone
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
# Never hardcode "current head" — later tickets (e.g. CMP-012) add revisions
# on top of this one, and alembic wraps an entire multi-revision
# downgrade/upgrade run in one transaction (migrations/env.py's single
# `context.begin_transaction()` around `context.run_migrations()`), so when
# CMP-011's guard blocks partway through a downgrade that would otherwise
# walk back through later tickets first, the whole attempt — including
# those later tickets' own, otherwise-clean downgrade steps — rolls back
# atomically, leaving the database at whatever the true head is *today*.
# Resolved dynamically via the Alembic script graph so this never goes
# stale again as new tickets land.
_PRE_CMP011_REVISION = "e29b5c1a7d43"


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


def _create_minimal_tenant_farm(session, *, code_suffix: str):
    from app.services import farm_service, membership_service, tenant_service, user_service

    tenant = tenant_service.create_tenant(session, code=f"migr-{code_suffix}", name="Migration Tenant")
    user = user_service.create_user(
        session, oidc_issuer="migr", oidc_subject=code_suffix, email=f"migr-{code_suffix}@example.com",
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


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    """Deletes every row this test committed for its own tenant, bypassing
    the append-only/no-delete triggers exactly as
    test_transplant_concurrency.py's _cleanup_scenario does. Scoped strictly
    to `tenant_id` — never touches another tenant's rows, so it can never
    remove genuine production history. Never relies on connection-close,
    rollback, or Postgres's transactional GUC behavior alone to restore
    session_replication_role — it is always explicitly reset to DEFAULT
    before the connection is released, on both the success and failure
    paths."""
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
        conn.execute(text("DELETE FROM transplant_allocations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_destination_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_events WHERE tenant_id = :tid"), {"tid": tenant_id})
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
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    except Exception:
        # The transaction is now aborted; Postgres rejects any further
        # statement (including SET ... = DEFAULT) until it is rolled back.
        # Roll back first, then explicitly restore DEFAULT as its own
        # statement and commit that restoration on its own — never rely on
        # rollback's GUC-reset behavior alone to undo replica mode.
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
def test_migration_downgrade_blocked_when_transplanting_stage_exists_without_transplant_event(test_engine, alembic_head_restore) -> None:
    from app.services import crop_service, production_system_service, workflow_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, _farm = _create_minimal_tenant_farm(session, code_suffix=f"stg-{suffix}")
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"CROP-{suffix}",
            common_name="Test Crop", scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"VAR-{suffix}",
            name="Test Variety", supplier_reference=None,
        )
        ps = production_system_service.register_production_system(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Test System",
            description=None,
        )
        workflow = workflow_service.register_workflow(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
            production_system_id=ps.id, code=f"WF-{suffix}", name="Test Workflow",
        )
        version = workflow_service.create_draft_version(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
        )
        # Deliberately never published: this test proves that a
        # transplanting-category stage alone — even one that has never been
        # used by a real transplant — is enough to block downgrade.
        stage = workflow_service.add_stage(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            code="TRANSPLANTING", name="Transplanting", display_order=0, stage_category="transplanting",
            expected_duration_minutes=None, permitted_location_type_code=None,
            required_carrier_type_code="cultivation_plate", is_start=True, is_terminal=False,
        )
        stage_id = stage.id
        session.commit()

        with pytest.raises(RuntimeError, match="transplanting-category workflow stages"):
            command.downgrade(_cfg(), _PRE_CMP011_REVISION)

        _assert_at_head(test_engine)
        with test_engine.connect() as verify_conn:
            table_still_present = verify_conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'transplant_events'")
            ).first()
            this_stage_intact = verify_conn.execute(
                text("SELECT count(*) FROM workflow_stages WHERE id = :id AND stage_category = 'transplanting'"),
                {"id": stage_id},
            ).scalar_one()
        assert table_still_present is not None, "a blocked downgrade must leave the CMP-011 schema untouched"
        assert this_stage_intact == 1, "a blocked downgrade must leave this test's own data untouched"
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_migration_downgrade_blocked_when_transplant_history_exists(test_engine, alembic_head_restore) -> None:
    """NURSERY-OPS-004A: modern transplant requires a real, SeedlingEntry-
    anchored Nursery scenario -- built via the shared
    `build_transplant_ready_scenario` helper (sow -> Germination ->
    SeedlingEntry), matching every other 004A test's own setup. Cleaned up
    via the shared `cleanup_traceability_scenario` (covers the Nursery/
    checkpoint tables this scenario touches that this file's own minimal
    `_cleanup_scenario` never needed to know about)."""
    from app.services import transplant_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _create_minimal_tenant_farm(session, code_suffix=f"hist-{suffix}")
        tenant_id = tenant.id
        # CARRIER-CONFIG-001A: this scenario genuinely needs a real
        # seed_tray (nursery_service.sow_new_batch hard-requires it) but
        # this guard is about transplant history, not carrier
        # specifications -- legacy_seed_tray_no_specification models a
        # valid pre-001A seed_tray Carrier (specification_id=NULL) via raw
        # SQL, never creating a carrier_specifications row that would
        # otherwise make e5b8c3a72f04's own, earlier-in-chain guard fire
        # first.
        s = build_transplant_ready_scenario(
            session, tenant, user, farm, suffix=suffix, tray_count=1, legacy_seed_tray_no_specification=True,
        )
        session.commit()

        source_assignment_id = s["source_assignment_ids"][0]
        destination_carrier = s["destination_carriers"][0]
        event = transplant_service.record_transplant(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
            client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
            source_lines=[
                {
                    "source_assignment_id": source_assignment_id, "transplant_damage_count": 0,
                    "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0, "other_loss_note": None,
                    "note": None,
                }
            ],
            destination_lines=[{"destination_carrier_id": destination_carrier.id, "assigned_plant_count": 200, "note": None}],
            allocations=[
                {
                    "source_assignment_id": source_assignment_id, "destination_carrier_id": destination_carrier.id,
                    "allocated_plant_count": 200,
                }
            ],
        )
        session.commit()
        event_id = event.id
        # TRANSPLANT-CORRECTION-001: `event.id` above is an attribute read
        # on an already-committed (and therefore expired) ORM object, which
        # SQLAlchemy services with an implicit reload against `session`'s
        # own connection -- silently reopening a read transaction there that
        # holds an AccessShareLock on `transplant_events` until the next
        # commit (same root cause already documented/fixed for `tenants` in
        # this suite's CARRIER-CONFIG-001 downgrade-guard tests). Harmless
        # against every OLDER migration's downgrade() in this chain, but
        # TRANSPLANT-CORRECTION-001's own downgrade() now runs first (it
        # sits above NURSERY-OPS-004A's in the chain) and its very first
        # step drops a trigger ON `transplant_events` itself -- which
        # requires an AccessExclusiveLock and deadlocks against the stray
        # read lock above until Postgres times it out. An explicit commit
        # here ends that stray read transaction (and its lock) before the
        # downgrade attempt, exactly mirroring that established fix.
        session.commit()

        # NURSERY-OPS-004A's own migration now sits above CMP-011's in the
        # chain -- its own guard (checkpoint history) fires FIRST for any
        # modern transplant, before the downgrade walk ever reaches
        # CMP-011's original "transplant events exist" guard further down.
        # Same shadowing pattern already established for NURSERY-OPS-003B's
        # own guard shadowing an even-older one.
        with pytest.raises(RuntimeError, match="seedling_source_checkpoints"):
            command.downgrade(_cfg(), _PRE_CMP011_REVISION)

        _assert_at_head(test_engine)
        with test_engine.connect() as verify_conn:
            table_still_present = verify_conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'transplant_events'")
            ).first()
            # Scoped to this test's own event: other test files in a
            # full-suite run may have committed their own transplant events
            # via their own dedicated connections, so a bare table-wide
            # count is not a safe assertion here — only that *this* event
            # specifically survived.
            this_event_intact = verify_conn.execute(
                text("SELECT count(*) FROM transplant_events WHERE id = :id"), {"id": event_id}
            ).scalar_one()
        assert table_still_present is not None, "a blocked downgrade must leave the CMP-011 schema untouched"
        assert this_event_intact == 1, "a blocked downgrade must leave CMP-011 data untouched"
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_migration_downgrade_blocked_when_multi_event_source_assignment_exists(test_engine, alembic_head_restore) -> None:
    """NURSERY-OPS-004A section 39: even with zero checkpoints left (so the
    migration's OWN checkpoint-history guard is silenced), the old lifetime-
    once `UNIQUE(source_batch_carrier_assignment_id)` constraint cannot be
    restored once a source assignment has genuinely appeared in more than
    one transplant event -- exactly what a partial/sequential transplant of
    the same Tray produces. Reaching this SPECIFIC guard (rather than the
    checkpoint-history guard, which always fires first and would otherwise
    shadow it -- the same shadowing pattern proven in the test above)
    requires deleting the checkpoint rows directly, bypassing the append-
    only trigger via `session_replication_role`, while deliberately leaving
    the duplicate `transplant_source_lines` rows in place."""
    from app.services import transplant_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _create_minimal_tenant_farm(session, code_suffix=f"multi-{suffix}")
        tenant_id = tenant.id
        # CARRIER-CONFIG-001A: see comment on the other build_transplant_
        # ready_scenario call in this file.
        s = build_transplant_ready_scenario(
            session, tenant, user, farm, suffix=suffix, tray_count=1, normal=100,
            legacy_seed_tray_no_specification=True,
        )
        session.commit()

        source_assignment_id = s["source_assignment_ids"][0]
        destination_carriers = s["destination_carriers"]

        def _source_line(damage=0):
            return [
                {
                    "source_assignment_id": source_assignment_id, "transplant_damage_count": damage,
                    "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0, "other_loss_note": None,
                    "note": None,
                }
            ]

        transplant_service.record_transplant(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
            client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=1), note=None,
            source_lines=_source_line(), destination_lines=[
                {"destination_carrier_id": destination_carriers[0].id, "assigned_plant_count": 40, "note": None}
            ],
            allocations=[
                {
                    "source_assignment_id": source_assignment_id, "destination_carrier_id": destination_carriers[0].id,
                    "allocated_plant_count": 40,
                }
            ],
        )
        session.commit()
        # Second, sequential transplant against the SAME (still-active,
        # remainder=60) source assignment -- fully consumes it, producing a
        # second transplant_source_lines row sharing source_batch_carrier_
        # assignment_id with the first.
        transplant_service.record_transplant(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch_id"],
            client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
            source_lines=_source_line(), destination_lines=[
                {"destination_carrier_id": destination_carriers[1].id, "assigned_plant_count": 60, "note": None}
            ],
            allocations=[
                {
                    "source_assignment_id": source_assignment_id, "destination_carrier_id": destination_carriers[1].id,
                    "allocated_plant_count": 60,
                }
            ],
        )
        session.commit()

        with test_engine.connect() as guard_conn:
            guard_conn.execute(text("SET session_replication_role = replica"))
            guard_conn.execute(
                text("DELETE FROM seedling_source_checkpoints WHERE tenant_id = :tid"), {"tid": tenant.id}
            )
            guard_conn.execute(text("SET session_replication_role = DEFAULT"))
            guard_conn.commit()

        # CARRIER-CONFIG-001: `tenant.id` above is an attribute read on an
        # already-committed (and therefore expired) ORM object, which
        # SQLAlchemy services with an implicit reload against `session`'s
        # own connection -- silently reopening a transaction there that
        # holds an AccessShareLock on `tenants` until the next commit.
        # Harmless against every OLDER migration's downgrade(), but
        # CARRIER-CONFIG-001's own downgrade() now does `DROP TABLE
        # carrier_specifications` as its very first step, and dropping any
        # table with a `tenant_id` FK requires an AccessExclusiveLock on
        # `tenants` itself (to remove that FK's referenced-side enforcement
        # trigger) -- which deadlocks against the lock above until Postgres
        # times it out. An explicit commit here ends that stray read
        # transaction (and its lock) before the downgrade attempt.
        session.commit()

        with pytest.raises(RuntimeError, match="appears in"):
            command.downgrade(_cfg(), _PRE_CMP011_REVISION)

        _assert_at_head(test_engine)
        with test_engine.connect() as verify_conn:
            line_count = verify_conn.execute(
                text(
                    "SELECT count(*) FROM transplant_source_lines "
                    "WHERE source_batch_carrier_assignment_id = :aid"
                ),
                {"aid": source_assignment_id},
            ).scalar_one()
        assert line_count == 2, "a blocked downgrade must leave both source lines intact"
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
