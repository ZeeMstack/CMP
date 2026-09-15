"""PILOT-SCAN-001 focused DB-level tests for `qr_identifiers` (migration
29d6697de6d5): the partial unique index that makes "one active QR per
entity" a real database constraint (not merely a service-layer check), the
immutability trigger, and the no-hard-delete trigger. Mirrors this
codebase's existing per-migration test convention (e.g.
`test_farm_work_item_migration.py`) -- direct SQL/ORM against `db_session`,
never through the service layer, so these prove the SCHEMA itself is
correct independent of `qr_service`'s own behavior."""
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.qr_identifier import QrIdentifier

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_QR_REVISION = "3a278fa65f80"


def _insert_qr(db_session, *, tenant_id, farm_id, carrier_id, user_id, token=None):
    identifier = QrIdentifier(
        tenant_id=tenant_id, farm_id=farm_id, entity_type="carrier", carrier_id=carrier_id,
        token=token or uuid.uuid4().hex, status="active", created_by_user_id=user_id,
    )
    db_session.add(identifier)
    db_session.flush()
    return identifier


@pytest.fixture
def carrier_scenario(db_session, active_context_with_farm):
    """PILOT-SCAN-001D: builds its Carrier via direct ORM insert, never
    `carrier_service.register_carrier` -- that service now auto-provisions
    a permanent QR identity at creation, which would leave this fixture's
    Carrier already holding an active `QrIdentifier` before any test here
    inserts its own via `_insert_qr`, corrupting every test below's own
    "first identity"/"second identity" precondition. Matches this file's
    own stated philosophy even better than the service call did: these
    tests prove the `qr_identifiers` SCHEMA itself, independent of
    `qr_service`'s (or now `carrier_service`'s) own behavior."""
    from app.models.carrier import Carrier

    tenant, user, headers, farm = active_context_with_farm
    from tests.conftest import ensure_seed_tray_specification

    spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier = Carrier(
        tenant_id=tenant.id, farm_id=farm.id, carrier_type_id=spec.carrier_type_id,
        specification_id=spec.id, code="QR-CARRIER-0001",
    )
    db_session.add(carrier)
    db_session.commit()
    return tenant, user, farm, carrier


@pytest.mark.integration
def test_active_unique_index_rejects_second_active_identity(db_session, carrier_scenario) -> None:
    tenant, user, farm, carrier = carrier_scenario
    _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    db_session.commit()

    with pytest.raises(IntegrityError):
        _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    db_session.rollback()


@pytest.mark.integration
def test_a_revoked_identity_does_not_block_a_new_active_one(db_session, carrier_scenario) -> None:
    tenant, user, farm, carrier = carrier_scenario
    first = _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    first.status = "revoked"
    first.revoked_at = datetime.now(timezone.utc)
    first.revoked_by_user_id = user.id
    db_session.commit()

    second = _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    db_session.commit()
    assert second.id != first.id


@pytest.mark.integration
def test_token_is_globally_unique(db_session, carrier_scenario) -> None:
    tenant, user, farm, carrier = carrier_scenario
    _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id, token="dup-token")
    db_session.commit()

    from app.models.carrier import Carrier

    # PILOT-SCAN-001D: direct ORM insert, not `carrier_service.register_carrier`
    # -- that would auto-provision this Carrier's own active QR and make
    # the assertion below trip the (also-real, but different) "one active
    # QR per Carrier" constraint instead of the GLOBAL token-uniqueness
    # constraint this test specifically exists to prove.
    other_carrier = Carrier(
        tenant_id=tenant.id, farm_id=farm.id, carrier_type_id=carrier.carrier_type_id,
        specification_id=carrier.specification_id, code="QR-CARRIER-0002",
    )
    db_session.add(other_carrier)
    db_session.commit()
    with pytest.raises(IntegrityError):
        _insert_qr(
            db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=other_carrier.id, user_id=user.id,
            token="dup-token",
        )
    db_session.rollback()


@pytest.mark.integration
def test_identity_fields_are_immutable(db_session, carrier_scenario) -> None:
    tenant, user, farm, carrier = carrier_scenario
    identifier = _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    db_session.commit()

    identifier.token = "changed-token"
    with pytest.raises(DBAPIError):
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_status_may_change_after_insert(db_session, carrier_scenario) -> None:
    tenant, user, farm, carrier = carrier_scenario
    identifier = _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    db_session.commit()

    revoker_id = user.id  # read before mutating, so autoflush never sees a partial revocation shape
    identifier.status = "revoked"
    identifier.revoked_at = datetime.now(timezone.utc)
    identifier.revoked_by_user_id = revoker_id
    db_session.flush()
    db_session.commit()


@pytest.mark.integration
def test_hard_delete_is_rejected(db_session, carrier_scenario) -> None:
    tenant, user, farm, carrier = carrier_scenario
    identifier = _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    db_session.commit()

    db_session.delete(identifier)
    with pytest.raises(DBAPIError):
        db_session.flush()
    db_session.rollback()


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


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    """Scoped strictly to this test's own tenant_id -- never a bare
    table-wide operation -- mirroring every other committed-connection
    downgrade-guard test's own cleanup in this suite. `qr_identifiers` is
    deleted here via the same `session_replication_role = replica` bypass
    of `qr_identifiers_no_delete` these tests already use elsewhere for
    the identical reason: this is `cmp_test`, and only this test's own
    fixture row is being removed, never production label history."""
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
        conn.execute(text("DELETE FROM qr_identifiers WHERE tenant_id = :tid"), {"tid": tenant_id})
        if conn.execute(text("SELECT to_regclass('carrier_specifications')")).scalar() is not None:
            conn.execute(text("DELETE FROM carrier_specifications WHERE tenant_id = :tid"), {"tid": tenant_id})
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


@pytest.mark.integration
def test_downgrade_past_qr_identifiers_is_refused_while_a_real_identity_exists(
    test_engine, alembic_head_restore_real_downgrade,
) -> None:
    """PILOT-SCAN-001D closure (FINAL DOWNGRADE-GUARD TEST CORRECTION):
    proves PILOT-SCAN-001's own `29d6697de6d5` downgrade guard actually
    fires -- the direct proof `alembic_head_restore`'s auto-truncate
    wrapper (added earlier in this same closure) would make structurally
    impossible, since it clears `qr_identifiers` immediately before every
    `command.downgrade()` call. Uses `alembic_head_restore_real_downgrade`
    instead: the sibling fixture with the identical head-restore guarantee
    but no monkeypatching of `command.downgrade` at all.

    1. Starts at head (asserted by the fixture).
    2. Creates a real `qr_identifiers` row through actual production
       behavior -- `carrier_service.register_carrier`, which auto-
       provisions a permanent QR identity at creation (PILOT-SCAN-001D) --
       never a raw `QrIdentifier(...)` insert.
    3. Calls the REAL, unwrapped `alembic.command.downgrade` toward
       `3a278fa65f80` (29d6697de6d5's own immediate parent).
    4. Asserts the guard's own `RuntimeError` ("Cannot downgrade past
       PILOT-SCAN-001's qr_identifiers table") is raised, and that the
       database is left exactly at head (never partially downgraded).
    5. Verifies the qr_identifiers row committed in step 2 still exists,
       untouched.
    6. Explicitly removes it (this test's own privileged, tenant-scoped
       cleanup step -- production has no such operation).
    7. Re-invokes the same downgrade: with zero qr_identifiers rows left,
       it now succeeds, dropping the table; re-upgrades back to head to
       leave cmp_test exactly as `alembic_head_restore_real_downgrade`'s
       own teardown expects (a no-op re-upgrade if this step already
       restored it, never a source of drift)."""
    from app.services import carrier_service, farm_service, membership_service, tenant_service, user_service
    from tests.conftest import ensure_seed_tray_specification

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant = tenant_service.create_tenant(session, code=f"qrguard-{suffix}", name="QR Guard Tenant")
        tenant_id = tenant.id
        user = user_service.create_user(
            session, oidc_issuer="qrguard", oidc_subject=suffix, email=f"qrguard-{suffix}@example.com",
            display_name="QR Guard User",
        )
        membership_service.add_membership(
            session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
        )
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="QR Guard Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        spec = ensure_seed_tray_specification(session, tenant_id=tenant.id, actor_user_id=user.id)
        carrier = carrier_service.register_carrier(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=spec.id, code=f"QRGUARD-{suffix}", issued_date=None,
        )
        session.commit()

        identifier_id = session.execute(
            text("SELECT id FROM qr_identifiers WHERE carrier_id = :cid AND status = 'active'"), {"cid": carrier.id}
        ).scalar_one()
    finally:
        session.close()
        conn.close()

    # Step 3-4: the real downgrade guard, unwrapped, must refuse.
    with pytest.raises(RuntimeError, match="Cannot downgrade past PILOT-SCAN-001's qr_identifiers table"):
        command.downgrade(_cfg(), _PRE_QR_REVISION)
    _assert_at_head(test_engine)

    # Step 5: the row committed above must still be there, untouched.
    with test_engine.connect() as verify_conn:
        still_active = verify_conn.execute(
            text("SELECT status FROM qr_identifiers WHERE id = :id"), {"id": identifier_id}
        ).scalar_one()
    assert still_active == "active", "a refused downgrade must leave this test's own qr_identifiers row untouched"

    # Step 6: explicit test-only cleanup (production has no equivalent).
    _cleanup_scenario(test_engine, tenant_id)

    # Step 7: with zero qr_identifiers rows left, the same downgrade must
    # now genuinely succeed -- proving step 3-4 was a real guard reacting
    # to real data, not a test artifact.
    command.downgrade(_cfg(), _PRE_QR_REVISION)
    with test_engine.connect() as verify_conn:
        current = verify_conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert current == _PRE_QR_REVISION
    command.upgrade(_cfg(), "head")
    _assert_at_head(test_engine)
