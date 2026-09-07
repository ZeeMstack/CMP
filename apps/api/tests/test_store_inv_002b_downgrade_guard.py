"""STORE-INV-002B downgrade-guard proof tests -- mirrors
`test_finished_goods_storage_downgrade_guard.py`'s own approach: a
movement row is independent operational data (custody, unrelated to
existence/quality), so downgrade past `e8baaf4a723e` is blocked while ANY
`inventory_storage_movements` row exists, even one whose net effect on a
bin's balance is zero (a putaway immediately followed by a matching
transfer back out nets to zero, but both rows still exist as independent
history)."""
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

import scripts.reset_test_database
from app.core.settings import settings
from app.services import inventory_storage_service
from tests._store_custody_scenario import build_scenario, build_store_bin, receive_cohort

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_002B_REVISION = "abcdb6f371f9"


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


@pytest.mark.integration
def test_downgrade_blocked_by_storage_movement_history(test_engine, alembic_head_restore) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        bin_ = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()
        inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
            quantity=Decimal("5"), effective_time=_now(),
        )
        session.commit()
    finally:
        session.close()
        conn.close()

    with pytest.raises(RuntimeError, match="inventory_storage_movements row"):
        command.downgrade(_cfg(), _PRE_002B_REVISION)
    _assert_at_head(test_engine)


@pytest.mark.integration
def test_downgrade_blocked_even_when_net_bin_balance_is_zero(test_engine, alembic_head_restore) -> None:
    """A putaway immediately followed by a matching transfer out (to a
    second bin) nets to a zero balance at the first bin, but both rows
    still exist as independent operational history -- the guard counts
    rows, not net balance."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        bin_a = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        bin_b = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()
        inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_a.id,
            quantity=Decimal("5"), effective_time=_now(),
        )
        session.commit()
        inventory_storage_service.record_transfer(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, source_location_id=bin_a.id,
            destination_location_id=bin_b.id, quantity=Decimal("5"), effective_time=_now(),
        )
        session.commit()
    finally:
        session.close()
        conn.close()

    with pytest.raises(RuntimeError, match="inventory_storage_movements row"):
        command.downgrade(_cfg(), _PRE_002B_REVISION)
    _assert_at_head(test_engine)


@pytest.mark.integration
def test_clean_downgrade_with_no_storage_history_reupgrade_restores_head(test_engine, alembic_head_restore) -> None:
    """No custody movement history at all: downgrade must succeed, drop the
    storage table/triggers/function; re-upgrade must restore them and leave
    the table fully functional again. Resets cmp_test to a genuinely
    empty-then-head state first (same hermetic pattern as
    test_store_inv_002a2_command_idempotency_migration.py), so this test
    never depends on execution order relative to any other test that
    commits real movement rows via a separate connection."""
    scripts.reset_test_database.main()
    command.downgrade(_cfg(), _PRE_002B_REVISION)
    with test_engine.connect() as c:
        current = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _PRE_002B_REVISION

        tables = c.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name = 'inventory_storage_movements'"
            )
        ).scalars().all()
        assert tables == [], "downgrade must drop the storage movement table"

        function_exists = c.execute(
            text("SELECT to_regproc('enforce_inventory_storage_movement_insert_integrity') IS NOT NULL")
        ).scalar_one()
        assert function_exists is False, "clean downgrade must drop the trigger function"

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as c:
        current = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _resolve_head_revision(_cfg())
        tables = c.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name = 'inventory_storage_movements'"
            )
        ).scalars().all()
        assert tables == ["inventory_storage_movements"], "re-upgrade must recreate the storage movement table"

    # Re-upgrading must leave the table fully functional again.
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        bin_ = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()
        movement = inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
            quantity=Decimal("5"), effective_time=_now(),
        )
        assert movement.id is not None
    finally:
        session.close()
        conn.close()
