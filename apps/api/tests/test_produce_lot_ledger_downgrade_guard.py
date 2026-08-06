"""CMP-014 downgrade-guard proof tests.

Unlike CMP-013's guard (which blocks on the mere existence of any harvest
history), CMP-014's guard only blocks when a ledger row could not be
reconstructed from CMP-013 data — an unknown `entry_kind`, or a receipt
whose fields no longer match its lot/event. Normal harvest operation can
never produce either state (the immediate trigger + deferred reconciliation
already prevent it), so both scenarios here are deliberately constructed
via direct SQL with `session_replication_role = replica`, guarded by the
same `cmp_test` + explicit `DEFAULT` restore discipline used throughout
this test suite, and "current head" is resolved dynamically via
`ScriptDirectory` rather than hardcoded."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
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

API_ROOT = Path(__file__).resolve().parent.parent
# Specific, historically fixed migration under test — the target this test
# downgrades to — is safe to hardcode; "current head" is not.
_PRE_CMP014_REVISION = "c7f14b8e29a3"


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


def _require_cmp_test(test_engine) -> None:
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test setup/cleanup (session_replication_role) against "
            f"database {current_db!r}; this is only permitted against 'cmp_test'"
        )


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    _require_cmp_test(test_engine)
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


def _build_harvest(test_engine, *, suffix: str):
    conn = test_engine.connect()
    session = Session(bind=conn)
    tenant = tenant_service.create_tenant(session, code=f"ledger-guard-{suffix}", name="Ledger Guard Tenant")
    user = user_service.create_user(
        session, oidc_issuer="ledger-guard", oidc_subject=suffix, email=f"ledger-guard-{suffix}@example.com",
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
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=_now(),
    )
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )
    carrier = carrier_service.register_carrier(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, carrier_type_code="seed_tray",
        code=f"TRAY-{suffix}", issued_date=None,
    )
    sowing_service.sow_batch(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
        lines=[{"carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": 20, "seed_count": 20, "line_note": None}],
    )
    assignment = sowing_service.list_batch_carriers(session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)[0]
    crop_batch_service.transition_stage(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), configured_transition_id=t1.id, effective_time=_now(), reason=None,
    )
    event = harvest_service.record_harvest(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=_now(), produce_lot_code=f"GLOT-{suffix}", note=None,
        source_lines=[{"batch_carrier_assignment_id": assignment.id, "harvested_weight_kg": Decimal("1.000"), "whole_unit_count": None, "note": None}],
    )
    lot_id = session.execute(
        text("SELECT id FROM harvested_produce_lots WHERE harvest_event_id = :eid"), {"eid": event.id}
    ).scalar_one()
    tenant_id = tenant.id
    session.close()
    conn.close()
    return {"tenant_id": tenant_id, "lot_id": lot_id}


_CMP014_ENTRY_KIND_DEPENDENT_CHECKS = (
    "ck_produce_lot_ledger_entries_kind_allowed", "ck_produce_lot_ledger_entries_weight_envelope",
    "ck_produce_lot_ledger_entries_count_positive",
)


@pytest.mark.integration
def test_downgrade_blocked_by_unknown_entry_kind(test_engine) -> None:
    """`entry_kind` is protected by a CHECK constraint (plus, since CMP-015,
    two more CHECKs that are kind-conditional), so this branch of CMP-014's
    own downgrade guard is unreachable through any ordinary INSERT/UPDATE
    against the current schema. To exercise it in isolation, this test
    first downgrades cleanly past CMP-015 (no packing history exists, so
    that guard passes and CMP-015's own downgrade() restores the exact
    original CMP-014 constraint bodies — captured dynamically via
    `pg_get_constraintdef` rather than hardcoded, so this test stays
    correct regardless of what CMP-015 restores), *then* corrupts the
    row against that now-CMP-014-shaped schema, then attempts the final
    downgrade step into CMP-013 to prove CMP-014's own guard independently
    catches it — even `session_replication_role = replica` (which bypasses
    triggers) does not bypass CHECK constraints, so the corruption itself
    requires temporarily dropping the CHECKs, restored in a guaranteed
    finally block."""
    suffix = uuid.uuid4().hex[:8]
    scenario = _build_harvest(test_engine, suffix=suffix)
    _require_cmp_test(test_engine)

    # Downgrade exactly one step, landing at CMP-014's own final shape
    # (de82132ef837) — not all the way to _PRE_CMP014_REVISION, which would
    # also run CMP-014's own downgrade() and drop the table entirely.
    command.downgrade(_cfg(), "de82132ef837")

    with test_engine.connect() as capture_conn:
        original_bodies = dict(
            capture_conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'produce_lot_ledger_entries'::regclass AND contype = 'c' "
                    "AND conname = ANY(:names)"
                ),
                {"names": list(_CMP014_ENTRY_KIND_DEPENDENT_CHECKS)},
            ).all()
        )
    assert set(original_bodies) == set(_CMP014_ENTRY_KIND_DEPENDENT_CHECKS)

    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    for name in _CMP014_ENTRY_KIND_DEPENDENT_CHECKS:
        conn.execute(text(f"ALTER TABLE produce_lot_ledger_entries DROP CONSTRAINT {name}"))
    conn.execute(
        text("UPDATE produce_lot_ledger_entries SET entry_kind = 'future_kind' WHERE produce_lot_id = :lid"),
        {"lid": scenario["lot_id"]},
    )
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()

    try:
        # CMP-016A's own env.py pre-migration guard now intercepts this
        # exact scenario before de82132ef837.downgrade() itself ever runs
        # (it fires for any downgrade whose path includes that step,
        # regardless of where the walk starts) — de82132ef837's own
        # "entry kind other than" message is consequently unreachable
        # through this path today, though the check remains as defence in
        # depth. See test_produce_lot_ledger_downgrade_guard_hardening.py
        # for the dedicated, per-state proofs of the new guard.
        with pytest.raises(RuntimeError, match="Cannot downgrade past CMP-014"):
            command.downgrade(_cfg(), "a4d92f7c1e6b")
        with test_engine.connect() as conn2:
            current = conn2.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == "de82132ef837", "a blocked downgrade must leave the database at CMP-014"
    finally:
        # Restore order matters: delete the tenant's bad row *before*
        # re-adding the CHECKs, since Postgres validates all existing rows
        # against a newly added CHECK unless declared NOT VALID.
        _cleanup_scenario(test_engine, scenario["tenant_id"])
        restore_conn = test_engine.connect()
        restore_trans = restore_conn.begin()
        try:
            for name, body in original_bodies.items():
                restore_conn.execute(
                    text(f"ALTER TABLE produce_lot_ledger_entries ADD CONSTRAINT {name} {body}")
                )
        except Exception:
            restore_trans.rollback()
            raise
        else:
            restore_trans.commit()
        finally:
            restore_conn.close()
        command.upgrade(_cfg(), "head")
        _assert_at_head(test_engine)


@pytest.mark.integration
def test_downgrade_blocked_by_malformed_receipt(test_engine) -> None:
    suffix = uuid.uuid4().hex[:8]
    scenario = _build_harvest(test_engine, suffix=suffix)
    _require_cmp_test(test_engine)

    conn = test_engine.connect()
    trans = conn.begin()
    conn.execute(text("SET session_replication_role = replica"))
    conn.execute(
        text("UPDATE produce_lot_ledger_entries SET weight_delta_kg = 999.000 WHERE produce_lot_id = :lid"),
        {"lid": scenario["lot_id"]},
    )
    conn.execute(text("SET session_replication_role = DEFAULT"))
    trans.commit()
    conn.close()

    try:
        # Same interception as test_downgrade_blocked_by_unknown_entry_kind
        # above: CMP-016A's env.py guard now catches this before
        # de82132ef837.downgrade() itself runs.
        with pytest.raises(RuntimeError, match="Cannot downgrade past CMP-014"):
            command.downgrade(_cfg(), _PRE_CMP014_REVISION)
        _assert_at_head(test_engine)
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])
