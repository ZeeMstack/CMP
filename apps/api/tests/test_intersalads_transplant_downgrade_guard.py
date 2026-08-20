"""NURSERY-OPS-004B.1 downgrade-guard proof tests for migration
b7e2f4a9c1d6, mirroring `test_carrier_specification_downgrade_guard.py`'s
established pattern exactly: commit real rows on a dedicated connection,
attempt a downgrade past the migration, confirm the guard blocks it, then
clean up via `session_replication_role = replica`."""
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
from app.schemas.farm_setup import GreenhouseSetupCreate, NurserySetupConfig, TableGeneratorConfig

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_MIGRATION_REVISION = "d9a417c5e832"


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

    tenant = tenant_service.create_tenant(session, code=f"istguard-{code_suffix}", name="InterSalads Guard Tenant")
    user = user_service.create_user(
        session, oidc_issuer="istguard", oidc_subject=code_suffix, email=f"istguard-{code_suffix}@example.com",
        display_name="InterSalads Guard User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    return tenant, user


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
        conn.execute(text("DELETE FROM movements WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM occupancies WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carrier_specifications WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM locations WHERE tenant_id = :tid"), {"tid": tenant_id})
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


def _place_plate_on_intersalads_table(session, *, tenant, user, farm):
    from app.services import carrier_service, carrier_specification_service, farm_setup_service, movement_service

    suffix = uuid.uuid4().hex[:8]
    setup = farm_setup_service.create_greenhouse_setup(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code=f"NUR-{suffix}", name="Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(
                intersalads_tables=TableGeneratorConfig(code_prefix=f"IS{suffix[:4]}", start=1, end=1, pad_width=2, capacity=4),
            ),
        ),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=setup.greenhouse_id,
    )
    table_id = structure.nursery_intersalads.tables[0].id
    spec = carrier_specification_service.register_carrier_specification(
        session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="nursery_cultivation_plate",
        code=f"GUARD-{suffix}", name="Guard Plate", length_mm=500, width_mm=300, height_mm=60,
        biological_position_count=200,
    )
    plate = carrier_service.register_carrier(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code=f"GUARD-PLATE-{suffix}", issued_date=None,
    )
    movement_service.execute_movement(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=datetime.now(timezone.utc) - timedelta(minutes=1), occupant_kind="carrier",
        occupant_id=plate.id, destination_kind="location", destination_id=table_id, reason=None,
    )
    return plate, table_id


@pytest.mark.integration
def test_downgrade_blocked_when_plate_occupies_intersalads_table(test_engine, alembic_head_restore) -> None:
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
        _place_plate_on_intersalads_table(session, tenant=tenant, user=user, farm=farm)
        session.commit()

        with pytest.raises(RuntimeError, match="currently occupy an InterSalads Table"):
            command.downgrade(_cfg(), _PRE_MIGRATION_REVISION)

        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup(test_engine, tenant_id)


@pytest.mark.integration
def test_downgrade_clean_when_no_live_occupancy_exists(test_engine, alembic_head_restore) -> None:
    command.downgrade(_cfg(), _PRE_MIGRATION_REVISION)
    with test_engine.connect() as verify_conn:
        current = verify_conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        trigger_gone = verify_conn.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgname = 'transplant_destination_lines_enforce_capacity'"
            )
        ).scalar_one()
        compat_gone = verify_conn.execute(
            text(
                "SELECT count(*) FROM occupancy_compatibility_rules r "
                "JOIN carrier_types ct ON ct.id = r.occupant_carrier_type_id AND ct.code = 'nursery_cultivation_plate' "
                "JOIN location_types lt ON lt.id = r.target_location_type_id AND lt.code = 'intersalads_table'"
            )
        ).scalar_one()
    assert current == _PRE_MIGRATION_REVISION
    assert trigger_gone == 0
    assert compat_gone == 0
    command.upgrade(_cfg(), "head")
    _assert_at_head(test_engine)
