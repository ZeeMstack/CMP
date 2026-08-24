"""LEAFY-OPS-001 downgrade-guard proof tests for migration a5c9e21f7b64,
mirroring `test_leafy_production_occupancy_compatibility_downgrade_guard.py`
's established pattern exactly: commit real rows on a dedicated connection,
attempt a downgrade past the migration, confirm the guard blocks it, then
clean up via `session_replication_role = replica`."""
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
_PRE_MIGRATION_REVISION = "1ffda251c3a8"


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


def _create_minimal_tenant(session, *, code_suffix: str):
    from app.services import membership_service, tenant_service, user_service

    tenant = tenant_service.create_tenant(session, code=f"pdguard-{code_suffix}", name="Production Disposition Guard Tenant")
    user = user_service.create_user(
        session, oidc_issuer="pdguard", oidc_subject=code_suffix, email=f"pdguard-{code_suffix}@example.com",
        display_name="Production Disposition Guard User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    return tenant, user


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    from tests._traceability_scenario import cleanup_traceability_scenario

    cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_downgrade_blocked_when_disposition_events_exist(test_engine, alembic_head_restore) -> None:
    from app.services import farm_service, production_disposition_service

    from tests.test_leafy_production_transfer import (
        _leafy_setup, _nursery_plate_source_scenario, _production_plates, _record, _simple_allocation,
        _simple_destination, _simple_source,
    )

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
        s, aids = _nursery_plate_source_scenario(session, tenant, user, farm, opening_count=10)
        table_ids = _leafy_setup(session, tenant, user, farm)
        plates, _spec = _production_plates(session, tenant, user, farm, count=1)
        result = _record(
            session, tenant, farm, user, s["batch"],
            [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=10)],
            [_simple_allocation(aids[0], plates[0].id, 10)],
            effective_time=s["transfer_ready_time"] + timedelta(hours=1),
        )
        root_id = result.destination_lines[0].destination_batch_carrier_assignment_id
        production_disposition_service.record_disposition(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            batch_carrier_assignment_id=root_id, plant_loss_count=2, reason_code="dead",
            effective_time=s["transfer_ready_time"] + timedelta(hours=2), note=None,
        )
        session.commit()

        with pytest.raises(RuntimeError, match="production_disposition_events"):
            command.downgrade(_cfg(), _PRE_MIGRATION_REVISION)

        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup(test_engine, tenant_id)


@pytest.mark.integration
def test_downgrade_clean_when_no_disposition_history_exists(test_engine, alembic_head_restore) -> None:
    command.downgrade(_cfg(), _PRE_MIGRATION_REVISION)
    with test_engine.connect() as verify_conn:
        current = verify_conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        table_exists = verify_conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'production_disposition_events')"
            )
        ).scalar_one()
        column_exists = verify_conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'batch_carrier_assignments' "
                "AND column_name = 'population_root_batch_carrier_assignment_id')"
            )
        ).scalar_one()
    assert current == _PRE_MIGRATION_REVISION
    assert table_exists is False
    assert column_exists is False

    command.upgrade(_cfg(), "head")
    _assert_at_head(test_engine)
    with test_engine.connect() as verify_conn2:
        table_restored = verify_conn2.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'production_disposition_events')"
            )
        ).scalar_one()
        reasons_restored = verify_conn2.execute(
            text("SELECT count(*) FROM production_disposition_reasons")
        ).scalar_one()
    assert table_restored is True
    assert reasons_restored == 6
