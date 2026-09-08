"""STORE-INV-003 downgrade-guard proofs -- mirrors
`test_store_inv_002b_downgrade_guard.py`'s own approach. Reservation/Issue
history is independent operational data; downgrade past `a9c3e71fd2b4` is
blocked while ANY row exists in a table this migration creates (ordinary
putaway/transfer rows in `inventory_storage_movements` never block this
specific downgrade -- that is STORE-INV-002B's own guard; an 'issue'-kind
movement is always accompanied by its own never-deleted `inventory_issues`
header row, so checking that header table alone already proves zero 'issue'
movements exist too)."""
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
from app.services import inventory_issue_service, inventory_reservation_service
from app.services.inventory_issue_service import IssueLineInput
from app.services.inventory_reservation_service import ReservationLineInput
from tests._store_reservation_scenario import build_scenario, receive_and_putaway

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_003_REVISION = "e8baaf4a723e"


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
def test_downgrade_blocked_by_reservation_history(test_engine, alembic_head_restore) -> None:
    # Resets to a genuinely empty-then-head state first -- the guard counts
    # rows across the WHOLE table (by design), so this test's own assertion
    # about exactly which table blocks the downgrade must not depend on
    # execution order relative to any other test that committed real rows
    # via a separate connection (same hermetic pattern as the
    # "clean downgrade" test below and STORE-INV-002B's own equivalent).
    scripts.reset_test_database.main()
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        receive_and_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        inventory_reservation_service.create_reservation(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), purpose="Downgrade guard", effective_time=_now(),
            lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("5"))],
        )
    finally:
        session.close()
        conn.close()

    with pytest.raises(RuntimeError, match="inventory_reservations row"):
        command.downgrade(_cfg(), _PRE_003_REVISION)
    _assert_at_head(test_engine)


@pytest.mark.integration
def test_downgrade_blocked_by_issue_movement_history(test_engine, alembic_head_restore) -> None:
    # See the reset rationale on the reservation-history test above.
    scripts.reset_test_database.main()
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id, bin_id = receive_and_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        inventory_issue_service.record_issue(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), purpose="Downgrade guard issue", effective_time=_now(),
            lines=[
                IssueLineInput(
                    inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                    source_location_id=bin_id, quantity=Decimal("3"),
                )
            ],
        )
    finally:
        session.close()
        conn.close()

    with pytest.raises(RuntimeError, match="inventory_issues row"):
        command.downgrade(_cfg(), _PRE_003_REVISION)
    _assert_at_head(test_engine)


@pytest.mark.integration
def test_clean_downgrade_with_no_003_history_reupgrade_restores_head(test_engine, alembic_head_restore) -> None:
    """No Reservation/Issue history at all: downgrade must succeed, drop
    the new tables/triggers/functions and repoint the storage-movement
    trigger back to v1; re-upgrade must restore everything and leave it
    fully functional again. Resets cmp_test to a genuinely empty-then-head
    state first, same hermetic pattern as the STORE-INV-002B equivalent."""
    scripts.reset_test_database.main()
    command.downgrade(_cfg(), _PRE_003_REVISION)
    with test_engine.connect() as c:
        current = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _PRE_003_REVISION

        for table in ("inventory_reservations", "inventory_reservation_lines", "inventory_reservation_line_entries", "inventory_issues"):
            tables = c.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = :t"),
                {"t": table},
            ).scalars().all()
            assert tables == [], f"downgrade must drop {table}"

        function_exists = c.execute(
            text("SELECT to_regproc('enforce_inventory_storage_movement_insert_integrity_v2') IS NOT NULL")
        ).scalar_one()
        assert function_exists is False, "clean downgrade must drop the v2 trigger function"

        v1_function_exists = c.execute(
            text("SELECT to_regproc('enforce_inventory_storage_movement_insert_integrity') IS NOT NULL")
        ).scalar_one()
        assert v1_function_exists is True, "downgrade must leave the v1 function untouched"

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as c:
        current = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == _resolve_head_revision(_cfg())
        tables = c.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name = 'inventory_reservations'"
            )
        ).scalars().all()
        assert tables == ["inventory_reservations"], "re-upgrade must recreate the reservation table"

    # Re-upgrading must leave everything fully functional again.
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id, bin_id = receive_and_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        issue = inventory_issue_service.record_issue(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), purpose="Post-reupgrade smoke", effective_time=_now(),
            lines=[
                IssueLineInput(
                    inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                    source_location_id=bin_id, quantity=Decimal("2"),
                )
            ],
        )
        assert issue.id is not None
    finally:
        session.close()
        conn.close()
