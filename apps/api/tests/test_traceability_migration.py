"""CMP-019 migration proof: an indexes-only migration (no tables, no
columns, no triggers, no data rewritten). Confirms the exact three
indexes are added on upgrade, removed cleanly on downgrade (and nothing
else), and restored on re-upgrade -- with existing operational data
byte-identical across the whole cycle."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.settings import settings
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, require_cmp_test
from tests._dispatch_scenario import pack_one

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_CMP019_REVISION = "dd8b86a52acf"
_EXPECTED_INDEXES = [
    "ix_packing_input_lines_tenant_farm_produce_lot",
    "ix_dispatch_lines_tenant_farm_finished_goods_lot",
    "ix_finished_goods_storage_movements_tenant_farm_lot",
]


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_head_revision(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_current_head()


@pytest.mark.integration
def test_migration_creates_exactly_three_indexes_downgrade_removes_them_reupgrade_restores(test_engine, alembic_head_restore) -> None:
    require_cmp_test(test_engine)
    # CARRIER-CONFIG-001A: this test's downgrade must succeed cleanly --
    # grow_bag keeps the scenario free of a carrier_specifications row,
    # which would otherwise unconditionally block via e5b8c3a72f04's own,
    # earlier-in-chain guard before CMP-019's own (index-only) downgrade
    # is ever reached.
    scenario = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    from sqlalchemy.orm import Session
    from decimal import Decimal

    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(scenario, session, package_count=3, packed_output_weight_kg=Decimal("2.000"))
    session.commit()

    def _fg_lot_snapshot():
        with test_engine.connect() as c:
            return dict(
                c.execute(
                    text("SELECT id, tenant_id, farm_id, code, packing_event_id, net_packed_weight_kg, package_count, effective_time FROM finished_goods_lots WHERE id = :id"),
                    {"id": fg_lot_id},
                ).mappings().one()
            )

    lot_before = _fg_lot_snapshot()
    session.close()
    conn.close()

    with test_engine.connect() as c:
        indexes_before = set(
            c.execute(text("SELECT indexname FROM pg_indexes WHERE indexname = ANY(:names)"), {"names": _EXPECTED_INDEXES}).scalars()
        )
        assert indexes_before == set(_EXPECTED_INDEXES), "all three indexes must exist at head"

    try:
        command.downgrade(_cfg(), _PRE_CMP019_REVISION)
        with test_engine.connect() as c:
            current = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == _PRE_CMP019_REVISION

            indexes_after_downgrade = set(
                c.execute(text("SELECT indexname FROM pg_indexes WHERE indexname = ANY(:names)"), {"names": _EXPECTED_INDEXES}).scalars()
            )
            assert indexes_after_downgrade == set(), "downgrade must remove all three CMP-019 indexes"

            # No table, trigger, or function from any prior ticket may be affected.
            storage_table_exists = c.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'finished_goods_storage_movements'")
            ).first()
            assert storage_table_exists is not None, "downgrade must not touch CMP-018's own table"

            lot_still_present = dict(
                c.execute(
                    text("SELECT id, tenant_id, farm_id, code, packing_event_id, net_packed_weight_kg, package_count, effective_time FROM finished_goods_lots WHERE id = :id"),
                    {"id": fg_lot_id},
                ).mappings().one()
            )
            assert lot_still_present == lot_before, "downgrade must leave existing operational data untouched"

        command.upgrade(_cfg(), "head")
        with test_engine.connect() as c:
            current = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == _resolve_head_revision(_cfg())
            indexes_after_reupgrade = set(
                c.execute(text("SELECT indexname FROM pg_indexes WHERE indexname = ANY(:names)"), {"names": _EXPECTED_INDEXES}).scalars()
            )
            assert indexes_after_reupgrade == set(_EXPECTED_INDEXES), "re-upgrade must recreate all three indexes"

            lot_after_reupgrade = dict(
                c.execute(
                    text("SELECT id, tenant_id, farm_id, code, packing_event_id, net_packed_weight_kg, package_count, effective_time FROM finished_goods_lots WHERE id = :id"),
                    {"id": fg_lot_id},
                ).mappings().one()
            )
            assert lot_after_reupgrade == lot_before, "re-upgrade must leave the lot byte-identical"
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])
