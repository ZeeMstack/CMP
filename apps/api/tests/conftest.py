from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import get_db
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
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


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
