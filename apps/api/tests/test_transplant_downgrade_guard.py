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
    from app.services import (
        carrier_service,
        crop_batch_service,
        crop_service,
        production_system_service,
        sowing_service,
        transplant_service,
        workflow_service,
    )

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user, farm = _create_minimal_tenant_farm(session, code_suffix=f"hist-{suffix}")
        tenant_id = tenant.id
        crop = crop_service.register_crop(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"CROP-H-{suffix}",
            common_name="History Crop", scientific_name=None, crop_category="leafy_green",
        )
        variety = crop_service.register_variety(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"VAR-H-{suffix}",
            name="History Variety", supplier_reference=None,
        )
        ps = production_system_service.register_production_system(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-H-{suffix}", name="History System",
            description=None,
        )
        workflow = workflow_service.register_workflow(
            session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
            production_system_id=ps.id, code=f"WF-H-{suffix}", name="History Workflow",
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
        transplanting = workflow_service.add_stage(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            code="TRANSPLANTING", name="Transplanting", display_order=1, stage_category="transplanting",
            expected_duration_minutes=None, permitted_location_type_code=None,
            required_carrier_type_code="cultivation_plate", is_start=False, is_terminal=False,
        )
        complete = workflow_service.add_stage(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            code="COMPLETE", name="Complete", display_order=2, stage_category="completed",
            expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
            is_start=False, is_terminal=True,
        )
        transition = workflow_service.add_transition(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=seeding.id, to_stage_id=transplanting.id, code="ADVANCE-1", name="Advance",
        )
        workflow_service.add_transition(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
            from_stage_id=transplanting.id, to_stage_id=complete.id, code="ADVANCE-2", name="Advance 2",
        )
        workflow_service.publish_version(
            session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
        )
        batch = crop_batch_service.create_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            code=f"BATCH-H-{suffix}", workflow_id=workflow.id, effective_time=_now(),
        )
        seed_lot = sowing_service.register_seed_lot(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
            variety_id=variety.id, code=f"LOT-H-{suffix}", supplier_name=None, supplier_lot_reference=None,
            received_date=None, expiry_date=None,
        )
        source_carrier = carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="seed_tray", code=f"ST-H-{suffix}", issued_date=None,
        )
        sowing_service.sow_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
            lines=[
                {
                    "carrier_id": source_carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": 100,
                    "seed_count": 100, "line_note": None,
                }
            ],
        )
        source_assignment_id = sowing_service.list_batch_carriers(
            session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id
        )[0].id
        crop_batch_service.transition_stage(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), configured_transition_id=transition.id, effective_time=_now(),
            reason=None,
        )
        destination_carrier = carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="cultivation_plate", code=f"CP-H-{suffix}", issued_date=None,
        )
        event = transplant_service.record_transplant(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
            source_lines=[
                {
                    "source_assignment_id": source_assignment_id, "source_plant_count": 100,
                    "discarded_plant_count": 0, "note": None,
                }
            ],
            destination_lines=[{"destination_carrier_id": destination_carrier.id, "assigned_plant_count": 100, "note": None}],
            allocations=[
                {
                    "source_assignment_id": source_assignment_id, "destination_carrier_id": destination_carrier.id,
                    "allocated_plant_count": 100,
                }
            ],
        )
        event_id = event.id

        with pytest.raises(RuntimeError, match="transplant events"):
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
            _cleanup_scenario(test_engine, tenant_id)
