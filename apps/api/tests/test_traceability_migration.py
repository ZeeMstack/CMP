"""CMP-019 migration proof: an indexes-only migration (no tables, no
columns, no triggers, no data rewritten). Confirms the exact three
indexes are added on upgrade, removed cleanly on downgrade (and nothing
else), and restored on re-upgrade.

POSTHARVEST-OPS-001E update: this test used to prove "existing operational
data byte-identical across the whole cycle" using a pre-existing
FinishedGoodsLot built before the downgrade. That premise is now
categorically false -- 001E's own downgrade guard (see migration
d8f4a1c92b57) unconditionally blocks any downgrade while packing_events/
packing_input_lines/graded-produce-lot-input packing history exists, and
every FinishedGoodsLot is packing history by definition. The pre-downgrade
scenario below is therefore built with `grade_and_pack_spec=False` (no
packing, no grading -- avoiding 001C's own equally unconditional guard on
any grading history too), so the downgrade/re-upgrade cycle here proves
only the index add/remove/restore mechanics. The "restored indexes work"
claim is instead proven with a FRESH pack performed after re-upgrading to
head, in its own independent scenario/tenant."""
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from tests._dispatch_scenario import pack_one
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, require_cmp_test

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_CMP019_REVISION = "dd8b86a52acf"
_EXPECTED_INDEXES = [
    # POSTHARVEST-OPS-001E renamed this index to
    # ix_packing_input_lines_tenant_farm_graded_produce_lot (the column it
    # covers, packing_input_lines.harvested_produce_lot_id, was itself
    # replaced by graded_produce_lot_id -- see migration d8f4a1c92b57).
    "ix_packing_input_lines_tenant_farm_graded_produce_lot",
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


def _indexes_present(test_engine) -> set:
    with test_engine.connect() as c:
        return set(
            c.execute(
                text("SELECT indexname FROM pg_indexes WHERE indexname = ANY(:names)"), {"names": _EXPECTED_INDEXES}
            ).scalars()
        )


@pytest.mark.integration
def test_migration_creates_exactly_three_indexes_downgrade_removes_them_reupgrade_restores(test_engine, alembic_head_restore) -> None:
    require_cmp_test(test_engine)
    # CARRIER-CONFIG-001A: grow_bag keeps this scenario free of a
    # carrier_specifications row, which would otherwise unconditionally
    # block via e5b8c3a72f04's own, earlier-in-chain guard before this
    # downgrade ever reaches CMP-019's own (index-only) step.
    # grade_and_pack_spec=False: no grading/packing history at all, so
    # neither 001C's nor 001E's own unconditional downgrade guards fire
    # before this test's target revision is ever reached.
    scenario = build_committed_scenario(
        test_engine, lot_a_count=None, carrier_type_code="grow_bag", grade_and_pack_spec=False
    )
    tenant_ids_to_clean = [scenario["tenant_id"]]

    try:
        assert _indexes_present(test_engine) == set(_EXPECTED_INDEXES), "all three indexes must exist at head"

        command.downgrade(_cfg(), _PRE_CMP019_REVISION)
        with test_engine.connect() as c:
            current = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == _PRE_CMP019_REVISION

        assert _indexes_present(test_engine) == set(), "downgrade must remove all three CMP-019 indexes"

        with test_engine.connect() as c:
            # No table, trigger, or function from any prior ticket may be affected.
            storage_table_exists = c.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'finished_goods_storage_movements'")
            ).first()
            assert storage_table_exists is not None, "downgrade must not touch CMP-018's own table"

        command.upgrade(_cfg(), "head")
        with test_engine.connect() as c:
            current = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == _resolve_head_revision(_cfg())

        assert _indexes_present(test_engine) == set(_EXPECTED_INDEXES), "re-upgrade must recreate all three indexes"

        # Behavioral proof the restored indexes actually work: a fresh pack,
        # performed after re-upgrading, in its own independent scenario.
        fresh_scenario = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
        tenant_ids_to_clean.append(fresh_scenario["tenant_id"])
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            fg_lot_id, _ = pack_one(fresh_scenario, session, package_count=3, packed_output_weight_kg=Decimal("2.000"))
            session.commit()
        finally:
            session.close()
            conn.close()

        with test_engine.connect() as c:
            fg_lot = c.execute(
                text(
                    "SELECT id, tenant_id, farm_id, code, packing_event_id, net_packed_weight_kg, package_count "
                    "FROM finished_goods_lots WHERE id = :id"
                ),
                {"id": fg_lot_id},
            ).mappings().one()
        assert fg_lot["net_packed_weight_kg"] == Decimal("2.000")
        assert fg_lot["package_count"] == 3
    finally:
        for tid in tenant_ids_to_clean:
            cleanup_scenario(test_engine, tid)
