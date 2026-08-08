from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import get_db, get_engine
from app.core.settings import settings
from app.main import app

API_ROOT = Path(__file__).resolve().parent.parent


def _require_test_database_url() -> str:
    # Deliberately no try/except and no skip: if this isn't set, or Postgres
    # is unreachable, tests must fail loudly, not silently pass/skip.
    assert settings.test_database_url, "TEST_DATABASE_URL must be set for integration tests"
    assert settings.test_database_url != settings.database_url, (
        "TEST_DATABASE_URL must not be the same as the development DATABASE_URL"
    )
    return settings.test_database_url


@pytest.fixture(scope="session")
def test_engine():
    url = _require_test_database_url()
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
    )
    # Fails loudly (not skips) if PostgreSQL/cmp_test is unreachable.
    with engine.connect():
        pass
    yield engine
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def apply_test_migrations(test_engine):
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", _require_test_database_url())
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def db_session(test_engine, apply_test_migrations):
    connection = test_engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


@pytest.fixture
def client(db_session, test_engine):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    # CMP-019's traceability service deliberately does not use the
    # request-scoped `db_session` (it owns its own dedicated,
    # REPEATABLE-READ connection via `get_engine`) -- point that dependency
    # at `test_engine` too, so an HTTP test's own committed-connection
    # scenario data is visible to it. Harmless for every other route,
    # which never depends on `get_engine`.
    app.dependency_overrides[get_engine] = lambda: test_engine
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_engine, None)


@pytest.fixture
def active_context(db_session):
    """Creates a tenant, a user, and an active membership linking them —
    the minimum required for a tenant-scoped request to pass
    `require_dev_tenant_context`. Returns (tenant, user, headers)."""
    from app.services import membership_service, tenant_service, user_service

    tenant = tenant_service.create_tenant(db_session, code="ctx-tenant", name="Context Tenant")
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject="ctx-user",
        email="ctx@example.com",
        display_name="Context User",
    )
    membership_service.add_membership(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        role_code="tenant_admin",
        actor_user_id=None,
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    return tenant, user, headers


@pytest.fixture
def active_context_with_farm(active_context, db_session):
    """Extends `active_context` with an active farm — the minimum required
    for any location-engine request. Returns (tenant, user, headers, farm)."""
    from app.services import farm_service

    tenant, user, headers = active_context
    farm = farm_service.create_farm(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=user.id,
        code="ctx-farm",
        name="Context Farm",
        country_code="AE",
        city_region=None,
        timezone="Asia/Dubai",
    )
    return tenant, user, headers, farm


@pytest.fixture
def placed_trolley_and_tray(active_context_with_farm, db_session):
    """Builds the CMP-006 core scenario: nursery greenhouse -> area ->
    germination chamber -> 20 chamber positions; a germination trolley with
    8 shelves x 5 slots; a seed tray. The trolley is placed at chamber
    position P12; the tray is placed at shelf 3 / slot 4. Returns a dict of
    the ids/objects used across occupancy and movement tests."""
    import uuid
    from datetime import datetime, timezone

    from app.services import asset_service, carrier_service, location_service, movement_service

    tenant, user, headers, farm = active_context_with_farm
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code="nursery-gh", name="Nursery Greenhouse",
        parent_location_id=None, greenhouse_classification="nursery", occupiable=None,
    )
    area = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="area", code="germ-area", name="Germination Area",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=None,
    )
    chamber = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="germination_chamber", code="GC-01", name="Germination Chamber GC-01",
        parent_location_id=area.id, greenhouse_classification=None, occupiable=None,
    )
    positions = location_service.bulk_generate_children(
        db_session, tenant_id=tenant.id, farm_id=farm.id, parent_id=chamber.id, actor_user_id=user.id,
        location_type_code="chamber_position", code_prefix="P", start=1, end=20, pad_width=2, name_template=None,
    )
    position_by_code = {p.code: p for p in positions}

    trolley = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code="GT-0001", name="Trolley 1", commissioned_date=None,
    )
    shelf_slots = asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=8, slots_per_shelf=5, shelf_prefix="SH-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    shelf_03 = next(p for p in shelf_slots if p.position_kind == "shelf" and p.code == "SH-03")
    slot_03_04 = next(
        p for p in shelf_slots
        if p.position_kind == "slot" and p.parent_position_id == shelf_03.id and p.code == "SL-04"
    )

    tray = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="seed_tray", code="ST-0001", issued_date=None,
    )

    now = datetime.now(timezone.utc)
    trolley_movement = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=now,
        occupant_kind="asset", occupant_id=trolley.id,
        destination_kind="location", destination_id=position_by_code["P12"].id, reason=None,
    )
    tray_movement = movement_service.execute_movement(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        client_command_id=uuid.uuid4(), effective_time=now,
        occupant_kind="carrier", occupant_id=tray.id,
        destination_kind="asset_position", destination_id=slot_03_04.id, reason=None,
    )

    return {
        "tenant": tenant, "user": user, "headers": headers, "farm": farm,
        "greenhouse": greenhouse, "area": area, "chamber": chamber, "positions": position_by_code,
        "trolley": trolley, "shelf_03": shelf_03, "slot_03_04": slot_03_04, "tray": tray,
        "trolley_movement": trolley_movement, "tray_movement": tray_movement,
    }
