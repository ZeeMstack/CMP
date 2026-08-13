"""CMP-012 downgrade-guard proof test.

A committed split trips every one of the downgrade guard's OR-conditions at
once (a batch_derivation_events row, a derivation-created batch, a
superseded batch, a derivation_entry transition, and derivation-opened/
released assignments), so one dedicated-connection scenario is enough to
prove the guard blocks correctly.

Test isolation does NOT rely on file or collection order. This test uses its
own unique tenant, scopes every assertion to its own ids, and cleans up
every row it committed in a `finally` block using `session_replication_role
= replica` — guarded by an explicit `current_database() == 'cmp_test'`
check, with `DEFAULT` always explicitly restored before the connection is
released, never relying on rollback's GUC-reset behavior alone (mirroring
test_transplant_downgrade_guard.py's hardened pattern)."""
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
# "Current head" is resolved dynamically (see _resolve_head_revision) rather
# than hardcoded, so this test never goes stale when a later ticket adds a
# revision on top of CMP-012. _PRE_CMP012_REVISION names the specific,
# historically fixed migration under test and is safe to hardcode.
_PRE_CMP012_REVISION = "f3a8c2e1b975"


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
        conn.execute(text("DELETE FROM batch_assignment_transfers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_derivation_outputs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_derivation_sources WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_derivation_events WHERE tenant_id = :tid"), {"tid": tenant_id})
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


@pytest.mark.integration
def test_migration_downgrade_blocked_when_split_history_exists(test_engine, alembic_head_restore) -> None:
    from app.services import (
        carrier_service,
        crop_service,
        farm_service,
        membership_service,
        production_system_service,
        sowing_service,
        tenant_service,
        user_service,
        workflow_service,
    )
    from app.services import batch_derivation_service, crop_batch_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant = tenant_service.create_tenant(session, code=f"deriv-guard-{suffix}", name="Derivation Guard Tenant")
        tenant_id = tenant.id
        user = user_service.create_user(
            session, oidc_issuer="deriv-guard", oidc_subject=suffix, email=f"deriv-guard-{suffix}@example.com",
            display_name="Guard User",
        )
        membership_service.add_membership(
            session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
        )
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
        batch = crop_batch_service.create_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
        )
        seed_lot = sowing_service.register_seed_lot(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
            variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
            received_date=None, expiry_date=None,
        )
        carriers = [
            carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code="seed_tray", code=f"TRAY-{suffix}-{n}", issued_date=None,
            )
            for n in range(2)
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
        aids = [assignment_by_carrier[c.code] for c in carriers]

        event = batch_derivation_service.split_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
            outputs=[
                {"output_batch_code": f"OUT-A-{suffix}", "source_assignment_ids": [aids[0]]},
                {"output_batch_code": f"OUT-B-{suffix}", "source_assignment_ids": [aids[1]]},
            ],
        )
        event_id = event.id

        with pytest.raises(RuntimeError, match="Cannot downgrade past CMP-012"):
            command.downgrade(_cfg(), _PRE_CMP012_REVISION)

        _assert_at_head(test_engine)
        with test_engine.connect() as verify_conn:
            table_still_present = verify_conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'batch_derivation_events'")
            ).first()
            event_still_present = verify_conn.execute(
                text("SELECT count(*) FROM batch_derivation_events WHERE id = :id"), {"id": event_id}
            ).scalar_one()
        assert table_still_present is not None, "a blocked downgrade must leave the CMP-012 schema untouched"
        assert event_still_present == 1, "a blocked downgrade must leave this test's own data untouched"
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup_scenario(test_engine, tenant_id)
