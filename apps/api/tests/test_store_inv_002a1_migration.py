"""STORE-INV-002A.1: migration downgrade-guard proof for
`f1a4c8e7b2d5_goods_receipt_lot_quantity_foundation.py` -- mirrors the
existing `test_migrations.py`/`_cfg()`/`alembic_head_restore` pattern
exactly. The clean upgrade/downgrade/upgrade round-trip on an EMPTY
database is already covered by `test_migrations.py::
test_migration_downgrade_then_upgrade_on_test_database` (downgrades all the
way to "base" and back) -- this file adds the one case that isn't: the
guard actually refusing to downgrade once real operational data exists.

STORE-INV-002A.2/002B note: `abcdb6f371f9` (inventory quality command
idempotency) and, on top of it, `e8baaf4a723e` (inventory storage custody)
now sit above `f1a4c8e7b2d5` as the current head. `f1a4c8e7b2d5` itself is
never edited, so its own downgrade guard is unchanged -- but every
`command.downgrade(...)` call below targets the explicit revision id
`10430de8731e` (this migration's own `down_revision`) rather than a
relative "-N" step count, so it stays correct regardless of how many more
migrations get stacked on top in the future. Those higher migrations' own
guards are independently covered by `test_store_inv_002a2_command_
idempotency_migration.py` and `test_store_inv_002b_downgrade_guard.py`.

Isolation note (CTO integrity review, pre-commit cleanup pass):
`test_downgrade_clean_when_empty` asserts a whole-table row count of
exactly zero across every STORE-INV-002A.1 table -- that is what the
downgrade guard itself checks (deliberately table-wide, never
tenant-scoped, since a real downgrade must never destroy any tenant's
data), so unlike an ordinary service test this one cannot be made
order-independent merely by scoping its assertion to its own tenant_id.
The two data-creating guard tests below (and `test_store_inv_002a1_
concurrency.py`'s own committed-connection tests) commit real rows into
these exact append-only tables through separate connections specifically
so `command.downgrade`'s own connection can see them -- rows that cannot
be cleaned up afterward via DELETE (the same append-only/no-hard-delete
triggers under test forbid it). Rather than depending on pytest's
declaration order to run before that residue exists, this test now resets
`cmp_test` to a genuinely empty-then-head state itself, via the same
approved, identity-verified `scripts/reset_test_database.py` tooling
CLAUDE.md requires for all migration/test-database work -- imported and
called directly (never a bare CLI invocation), making the test hermetic
regardless of what ran before it, in this file or any other."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

import scripts.reset_test_database
from app.core.settings import settings
from app.services import goods_receipt_service
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_item, uom_id
from tests._traceability_scenario import build_committed_tenant_farm

API_ROOT = Path(__file__).resolve().parent.parent


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


@pytest.mark.integration
def test_downgrade_clean_when_empty(test_engine, alembic_head_restore) -> None:
    """Order-independent: resets cmp_test to a genuinely empty-then-head
    state itself (see module docstring) before asserting the downgrade
    guard's whole-table row counts, so it no longer depends on running
    before any other test -- in this file or any other -- that commits real
    rows into these tables via a separate connection."""
    scripts.reset_test_database.main()
    command.downgrade(_cfg(), "10430de8731e")
    with test_engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name IN ('goods_receipts', 'goods_receipt_lines', 'inventory_lots', "
                "'inventory_quantity_cohorts', 'inventory_existence_ledger_entries', "
                "'quality_disposition_events', 'inventory_item_packaging', 'inventory_item_seed_profiles')"
            )
        ).scalar_one()
    assert tables == 0
    command.upgrade(_cfg(), "head")


@pytest.mark.integration
def test_downgrade_blocked_once_goods_receipt_exists(test_engine, alembic_head_restore) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        tenant, user, farm = build_committed_tenant_farm(session)
        category = build_category(session, tenant, actor_user_id=user.id)
        item = build_item(session, tenant, category.id, uom_id(session, "kg"), actor_user_id=user.id)
        goods_receipt_service.record_goods_receipt(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
            external_document_id=None, notes=None,
            lines=[GoodsReceiptLineInput(inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(session, "kg"))],
        )
    finally:
        session.close()
        conn.close()

    with pytest.raises(RuntimeError, match="STORE-INV-002A.1"):
        command.downgrade(_cfg(), "10430de8731e")


@pytest.mark.integration
def test_downgrade_blocked_once_inventory_lot_exists(test_engine, alembic_head_restore) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        tenant, user, farm = build_committed_tenant_farm(session)
        category = build_category(session, tenant, actor_user_id=user.id)
        item = build_item(
            session, tenant, category.id, uom_id(session, "kg"), actor_user_id=user.id, lot_tracking_required=True,
        )
        goods_receipt_service.record_goods_receipt(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None,
            external_document_id=None, notes=None,
            lines=[
                GoodsReceiptLineInput(
                    inventory_item_id=item.id, entered_quantity=Decimal("10"), entered_uom_id=uom_id(session, "kg"),
                    manufacturer_name="Yara", manufacturer_lot_reference="CN001",
                )
            ],
        )
    finally:
        session.close()
        conn.close()

    with pytest.raises(RuntimeError, match="STORE-INV-002A.1"):
        command.downgrade(_cfg(), "10430de8731e")
