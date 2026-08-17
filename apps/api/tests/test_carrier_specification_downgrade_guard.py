"""CARRIER-CONFIG-001 downgrade-guard proof tests. Each test commits real
rows on a dedicated connection, attempts a downgrade past e5b8c3a72f04, and
confirms the guard blocks it -- then cleans up its own committed rows in a
`finally` block via `session_replication_role = replica`, exactly the
established pattern `test_transplant_downgrade_guard.py` already uses."""
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_CARRIER_CONFIG_REVISION = "c8f1d4a92b6e"


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
    from app.services import tenant_service, user_service, membership_service

    tenant = tenant_service.create_tenant(session, code=f"cfgguard-{code_suffix}", name="Config Guard Tenant")
    user = user_service.create_user(
        session, oidc_issuer="cfgguard", oidc_subject=code_suffix, email=f"cfgguard-{code_suffix}@example.com",
        display_name="Config Guard User",
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
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carrier_specifications WHERE tenant_id = :tid"), {"tid": tenant_id})
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
def test_downgrade_blocked_when_specification_exists(test_engine, alembic_head_restore) -> None:
    from app.services import carrier_specification_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user = _create_minimal_tenant(session, code_suffix=f"spec-{suffix}")
        tenant_id = tenant.id
        spec = carrier_specification_service.register_carrier_specification(
            session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="seed_tray",
            code="GUARD-SPEC", name="Guard Spec", length_mm=100, width_mm=100, height_mm=None,
            biological_position_count=100,
        )
        session.commit()
        spec_id = spec.id

        with pytest.raises(RuntimeError, match="carrier_specifications row"):
            command.downgrade(_cfg(), _PRE_CARRIER_CONFIG_REVISION)

        _assert_at_head(test_engine)
        with test_engine.connect() as verify_conn:
            still_exists = verify_conn.execute(
                text("SELECT count(*) FROM carrier_specifications WHERE id = :id"), {"id": spec_id}
            ).scalar_one()
        assert still_exists == 1
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup(test_engine, tenant_id)


@pytest.mark.integration
def test_downgrade_blocked_when_carrier_references_specification(test_engine, alembic_head_restore) -> None:
    from app.services import carrier_service, carrier_specification_service, farm_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user = _create_minimal_tenant(session, code_suffix=f"ref-{suffix}")
        tenant_id = tenant.id
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Guard Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        spec = carrier_specification_service.register_carrier_specification(
            session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="nursery_cultivation_plate",
            code="GUARD-REF", name="Guard Ref Spec", length_mm=100, width_mm=100, height_mm=None,
            biological_position_count=100,
        )
        carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=spec.id, code="GUARD-CARRIER", issued_date=None,
        )
        session.commit()

        with pytest.raises(RuntimeError, match="carrier_specifications row"):
            command.downgrade(_cfg(), _PRE_CARRIER_CONFIG_REVISION)

        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup(test_engine, tenant_id)


@pytest.mark.integration
def test_downgrade_blocked_when_plate_type_carrier_exists_without_specification(
    test_engine, alembic_head_restore
) -> None:
    """A Plate-type Carrier with `specification_id IS NULL` and NO
    `carrier_specifications` row anywhere still uses a CarrierType this
    downgrade would delete -- must still block. Built directly via SQL,
    bypassing `carrier_service.register_carrier` (which always requires a
    specification for this CarrierType), specifically to isolate the
    migration's THIRD downgrade guard (`plate_type_carrier_count`) from the
    first two (a `carrier_specifications` row existing / a Carrier's
    `specification_id` being non-null) -- neither of those conditions holds
    in this test."""
    from app.services import farm_service

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant, user = _create_minimal_tenant(session, code_suffix=f"plate-{suffix}")
        tenant_id = tenant.id
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Guard Farm 2",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        plate_type_id = session.execute(
            text("SELECT id FROM carrier_types WHERE code = 'production_cultivation_plate'")
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO carriers (id, tenant_id, farm_id, carrier_type_id, code, status, "
                "specification_id) VALUES (:id, :tid, :fid, :ctid, :code, 'active', NULL)"
            ),
            {
                "id": uuid.uuid4(), "tid": tenant.id, "fid": farm.id, "ctid": plate_type_id,
                "code": "GUARD-PCP-CARRIER",
            },
        )
        session.commit()

        with pytest.raises(RuntimeError, match="use nursery_cultivation_plate/production_cultivation_plate"):
            command.downgrade(_cfg(), _PRE_CARRIER_CONFIG_REVISION)

        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup(test_engine, tenant_id)


@pytest.mark.integration
def test_downgrade_clean_when_no_specification_data_exists(test_engine, alembic_head_restore) -> None:
    command.downgrade(_cfg(), _PRE_CARRIER_CONFIG_REVISION)
    with test_engine.connect() as verify_conn:
        current = verify_conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert current == _PRE_CARRIER_CONFIG_REVISION
    command.upgrade(_cfg(), "head")
    _assert_at_head(test_engine)
