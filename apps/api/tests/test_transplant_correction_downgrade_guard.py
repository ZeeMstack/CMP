"""TRANSPLANT-CORRECTION-001 downgrade-guard proof tests for migration
f4a8c1e93d27, mirroring `test_intersalads_transplant_downgrade_guard.py`'s
established pattern exactly: commit real rows on a dedicated connection,
attempt a downgrade past the migration, confirm the guard blocks it, then
clean up."""
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

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_MIGRATION_REVISION = "b7e2f4a9c1d6"

pytestmark = pytest.mark.integration


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


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup against database {current_db!r}; "
            "this cleanup is only permitted against 'cmp_test'"
        )

    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM seedling_source_checkpoints WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_allocations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_destination_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_source_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_carrier_assignments WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM transplant_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM seedling_entries WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_event_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_runs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crop_batches WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
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


def _create_minimal_tenant(session, *, code_suffix: str):
    from app.services import membership_service, tenant_service, user_service

    tenant = tenant_service.create_tenant(session, code=f"tcguard-{code_suffix}", name="Correction Guard Tenant")
    user = user_service.create_user(
        session, oidc_issuer="tcguard", oidc_subject=code_suffix, email=f"tcguard-{code_suffix}@example.com",
        display_name="Correction Guard User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    return tenant, user


def _create_reversal(session, *, tenant, user, farm):
    from app.services import transplant_correction_service, transplant_service
    from tests._transplant_scenario import build_transplant_ready_scenario, now

    s = build_transplant_ready_scenario(
        session, tenant, user, farm, tray_count=1, normal=200, abnormal=0,
        transplanting_required_type="cultivation_plate",
    )
    aid = s["source_assignment_ids"][0]
    dest = s["destination_carriers"][0]
    target = transplant_service.record_transplant(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=s["entry_time"] + timedelta(hours=2), note=None,
        source_lines=[
            {
                "source_assignment_id": aid, "transplant_damage_count": 0, "qc_rejection_count": 0,
                "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
            }
        ],
        destination_lines=[{"destination_carrier_id": dest.id, "assigned_plant_count": 200, "note": None}],
        allocations=[{"source_assignment_id": aid, "destination_carrier_id": dest.id, "allocated_plant_count": 200}],
    )
    reversal = transplant_correction_service.correct_transplant(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        target_transplant_event_id=target.id, client_command_id=uuid.uuid4(), reason="guard test", replacement=None,
    )
    return reversal


@pytest.mark.integration
def test_downgrade_blocked_when_correction_history_exists(test_engine, alembic_head_restore) -> None:
    from app.services import farm_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user = _create_minimal_tenant(session, code_suffix=f"live-{suffix}")
        tenant_id = tenant.id
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Guard Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        _create_reversal(session, tenant=tenant, user=user, farm=farm)
        session.commit()

        with pytest.raises(RuntimeError, match="TRANSPLANT-CORRECTION-001"):
            command.downgrade(_cfg(), _PRE_MIGRATION_REVISION)

        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup(test_engine, tenant_id)


@pytest.mark.integration
def test_downgrade_clean_when_no_correction_history_exists(test_engine, alembic_head_restore) -> None:
    command.downgrade(_cfg(), _PRE_MIGRATION_REVISION)
    with test_engine.connect() as verify_conn:
        current = verify_conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        event_kind_gone = verify_conn.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'transplant_events' AND column_name = 'event_kind'"
            )
        ).scalar_one()
        reversal_opener_gone = verify_conn.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'batch_carrier_assignments' AND column_name = 'opening_transplant_reversal_event_id'"
            )
        ).scalar_one()
    assert current == _PRE_MIGRATION_REVISION
    assert event_kind_gone == 0
    assert reversal_opener_gone == 0
    command.upgrade(_cfg(), "head")
    _assert_at_head(test_engine)
