"""CMP-018 downgrade-guard proof tests.

Storage movement history follows CMP-015/017's own unconditional-block
model: a movement row is independent operational data (nothing else in
the schema can rebuild it), so downgrade past CMP-018 is blocked while
ANY movement row exists -- even one whose net effect on a location's
balance is zero (a place immediately followed by a matching release).
This file also proves a clean downgrade drops the storage table/triggers,
restores the byte-exact CMP-017 (v2) ledger insert-integrity trigger
attachment, removes only the CMP-018-added `uq_locations_tenant_farm_id`
constraint, leaves every packing/dispatch row untouched, and that
re-upgrade restores the v3 trigger attachment and the composite unique
constraint."""
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

from app.core.settings import settings
from app.services import finished_goods_storage_service
from tests._dispatch_scenario import pack_one
from tests._packing_scenario import (
    build_committed_scenario, build_packing_scaffold, cleanup_scenario, grade_entire_lot, require_cmp_test,
)
from tests._storage_scenario import create_cold_store, create_cold_store_position, place_one, release_one

API_ROOT = Path(__file__).resolve().parent.parent
# Specific, historically fixed migration under test -- the target this test
# downgrades to (CMP-017 head) -- is safe to hardcode; "current head" is not.
_PRE_CMP018_REVISION = "63d4d7e184e2"


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


def _build_placed_scenario(test_engine):
    # CARRIER-CONFIG-001A: storage-movement history is unrelated to carrier
    # type -- grow_bag keeps the scenario free of a carrier_specifications
    # row, which would otherwise unconditionally block via e5b8c3a72f04's
    # own, earlier-in-chain guard before this guard is ever reached.
    s = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(s, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
    cold_store = create_cold_store(s, session)
    pos = create_cold_store_position(s, session, cold_store_id=cold_store.id)
    pos_id = pos.id
    session.commit()
    movement = place_one(s, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_id, moved_weight_kg=Decimal("2.000"), moved_package_count=2)
    movement_id = movement.id
    session.commit()
    session.close()
    conn.close()
    s["fg_lot_id"] = fg_lot_id
    s["position_id"] = pos_id
    s["movement_id"] = movement_id
    return s


@pytest.mark.integration
def test_downgrade_blocked_by_storage_movement_history(test_engine, alembic_head_restore) -> None:
    s = _build_placed_scenario(test_engine)
    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP018_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, s["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_even_when_net_placed_balance_is_zero(test_engine, alembic_head_restore) -> None:
    """A place immediately followed by a matching release nets to a zero
    balance at that position, but both rows still exist as independent
    operational history -- the guard counts rows, not net balance, so
    downgrade must still be blocked."""
    # CARRIER-CONFIG-001A: storage-movement history is unrelated to carrier
    # type -- grow_bag keeps the scenario free of a carrier_specifications
    # row, which would otherwise unconditionally block via e5b8c3a72f04's
    # own, earlier-in-chain guard before this guard is ever reached.
    s = build_committed_scenario(test_engine, lot_a_count=None, carrier_type_code="grow_bag")
    conn = test_engine.connect()
    session = Session(bind=conn)
    fg_lot_id, _ = pack_one(s, session, package_count=10, packed_output_weight_kg=Decimal("8.000"))
    cold_store = create_cold_store(s, session)
    pos = create_cold_store_position(s, session, cold_store_id=cold_store.id)
    pos_id = pos.id
    session.commit()
    place_one(s, session, finished_goods_lot_id=fg_lot_id, destination_location_id=pos_id, moved_weight_kg=Decimal("2.000"), moved_package_count=2)
    session.commit()
    release_one(s, session, finished_goods_lot_id=fg_lot_id, source_location_id=pos_id, moved_weight_kg=Decimal("2.000"), moved_package_count=2)
    session.commit()
    session.close()
    conn.close()

    try:
        with test_engine.connect() as c:
            balance = c.execute(
                text(
                    "SELECT COALESCE(SUM(CASE WHEN movement_kind = 'place' THEN moved_weight_kg "
                    "  WHEN movement_kind = 'release' THEN -moved_weight_kg ELSE 0 END), 0) "
                    "FROM finished_goods_storage_movements WHERE finished_goods_lot_id = :lid"
                ),
                {"lid": fg_lot_id},
            ).scalar_one()
        assert balance == Decimal("0.000"), "the place/release pair must net to a zero balance for this to be meaningful"

        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001E"):
            command.downgrade(_cfg(), _PRE_CMP018_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, s["tenant_id"])


@pytest.mark.integration
def test_clean_downgrade_with_no_storage_history_reupgrade_restores_exact_cmp017_state(test_engine, alembic_head_restore) -> None:
    """No storage movement history at all: downgrade must succeed, drop
    the storage table/triggers/function, restore the byte-exact CMP-017
    (v2) ledger trigger attachment, remove only the CMP-018-added
    `uq_locations_tenant_farm_id` constraint, and re-upgrade must
    reattach the v3 trigger and recreate the composite unique constraint.
    Also proves (hardening pass): both the source- and destination-
    location foreign keys on the storage table target
    `uq_locations_tenant_farm_id` specifically (not some other index),
    and every location row -- created before the downgrade, deliberately
    left with no movements referencing it, so the downgrade guard still
    passes cleanly -- survives the full downgrade/re-upgrade cycle byte-
    identical, proving the constraint drop/recreate never touches
    `locations` data, only its own catalog entry.

    POSTHARVEST-OPS-001E: unlike this test's own pre-001E shape, no
    packing/GradedProduceLot history is created before the downgrade --
    any real packing_events row (or, further down the same cascade, any
    real GradingEvent/GradedProduceLot row from build_committed_scenario's
    own default grading step) now unconditionally blocks downgrade past
    001E/001C respectively, both of which sit above CMP-018 in the chain,
    before it could ever reach CMP-018's own state. The "preserve an
    existing packing receipt" proof this test used to make is superseded
    by the stronger guarantee (no packing receipt can ever survive a
    downgrade past 001E) proven in test_dispatch_downgrade_guard.py and
    test_packing_downgrade_guard.py. The "movement table is fully
    functional again" proof below packs a FRESH finished-goods lot AFTER
    re-upgrading to head instead, which needs no packing history to have
    survived the downgrade itself."""
    require_cmp_test(test_engine)
    # CARRIER-CONFIG-001A: this test's downgrade must succeed cleanly --
    # grow_bag keeps the scenario free of a carrier_specifications row.
    # grade_and_pack_spec=False: see the POSTHARVEST-OPS-001E docstring
    # note above.
    scenario = build_committed_scenario(
        test_engine, lot_a_count=None, carrier_type_code="grow_bag", grade_and_pack_spec=False,
    )
    conn = test_engine.connect()
    session = Session(bind=conn)
    cold_store = create_cold_store(scenario, session)
    pos = create_cold_store_position(scenario, session, cold_store_id=cold_store.id)
    cold_store_id, pos_id = cold_store.id, pos.id
    session.commit()

    def _location_rows_snapshot():
        with test_engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT id, tenant_id, farm_id, location_type_id, code, name, parent_location_id, status, "
                    "greenhouse_classification, occupiable, created_at "
                    "FROM locations WHERE id IN (:cs, :pos) ORDER BY id"
                ),
                {"cs": cold_store_id, "pos": pos_id},
            ).mappings().all()
            return [dict(r) for r in rows]

    locations_before = _location_rows_snapshot()
    assert len(locations_before) == 2, "both location rows must exist before downgrade"
    session.close()
    conn.close()

    with test_engine.connect() as c:
        v4_before = c.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                "AND tgfoid = 'enforce_finished_goods_ledger_entry_insert_integrity_v4'::regproc"
            )
        ).scalar_one()
        assert v4_before == 1, "the v4 trigger must be attached at head (CMP-020 sits above CMP-018)"
        locations_unique_before = c.execute(
            text(
                "SELECT count(*) FROM pg_constraint WHERE conname = 'uq_locations_tenant_farm_id' "
                "AND conrelid = 'locations'::regclass"
            )
        ).scalar_one()
        assert locations_unique_before == 1, "constraint must be present at CMP-018 head"

        # Both the source- and destination-location foreign keys must
        # target the (tenant_id, farm_id, id) shape backed by
        # uq_locations_tenant_farm_id -- not merely `locations.id` alone.
        fk_defs = dict(
            c.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'finished_goods_storage_movements'::regclass AND contype = 'f' "
                    "AND conname IN ("
                    "'fk_finished_goods_storage_movements_tenant_farm_src_location', "
                    "'fk_finished_goods_storage_movements_tenant_farm_dest_location')"
                )
            ).all()
        )
        assert len(fk_defs) == 2, "both source and destination composite FKs must exist"
        for name, definition in fk_defs.items():
            assert "REFERENCES locations(tenant_id, farm_id, id)" in definition, (name, definition)

    try:
        command.downgrade(_cfg(), _PRE_CMP018_REVISION)
        with test_engine.connect() as c:
            current = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == _PRE_CMP018_REVISION

            tables = c.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                    "AND table_name = 'finished_goods_storage_movements'"
                )
            ).scalars().all()
            assert tables == [], "downgrade must drop the storage movement table"

            locations_unique_after = c.execute(
                text(
                    "SELECT count(*) FROM pg_constraint WHERE conname = 'uq_locations_tenant_farm_id' "
                    "AND conrelid = 'locations'::regclass"
                )
            ).scalar_one()
            assert locations_unique_after == 0, "downgrade must remove the CMP-018-added composite unique on locations"

            locations_after_downgrade = c.execute(
                text(
                    "SELECT id, tenant_id, farm_id, location_type_id, code, name, parent_location_id, status, "
                    "greenhouse_classification, occupiable, created_at "
                    "FROM locations WHERE id IN (:cs, :pos) ORDER BY id"
                ),
                {"cs": cold_store_id, "pos": pos_id},
            ).mappings().all()
            assert [dict(r) for r in locations_after_downgrade] == locations_before, (
                "downgrade must drop only the constraint catalog entry -- location rows themselves must be untouched"
            )

            v3_after_downgrade = c.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                    "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                    "AND tgfoid = to_regproc('enforce_finished_goods_ledger_entry_insert_integrity_v3')"
                )
            ).scalar_one()
            assert v3_after_downgrade == 0
            v3_function_exists = c.execute(
                text("SELECT to_regproc('enforce_finished_goods_ledger_entry_insert_integrity_v3') IS NOT NULL")
            ).scalar_one()
            assert v3_function_exists is False, "clean downgrade must drop the v3 function entirely"

            v2_after_downgrade = c.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                    "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                    "AND tgfoid = 'enforce_finished_goods_ledger_entry_insert_integrity_v2'::regproc"
                )
            ).scalar_one()
            assert v2_after_downgrade == 1, "clean downgrade must restore the exact CMP-017 v2 trigger attachment"

            movement_functions_exist = c.execute(
                text("SELECT to_regproc('enforce_finished_goods_storage_movement_insert_integrity') IS NOT NULL")
            ).scalar_one()
            assert movement_functions_exist is False, "clean downgrade must drop the storage movement trigger function"

        command.upgrade(_cfg(), "head")
        with test_engine.connect() as c:
            current = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == _resolve_head_revision(_cfg())

            # CMP-020 sits above CMP-018 at "head", so re-upgrading here also
            # reattaches its own v4 trigger (superseding v3's attachment) --
            # see test_recall_downgrade_guard.py for CMP-020's own dedicated
            # downgrade/re-upgrade proof.
            v4_after_reupgrade = c.execute(
                text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'finished_goods_ledger_entries'::regclass "
                    "AND tgname = 'finished_goods_ledger_entries_enforce_insert_integrity' "
                    "AND tgfoid = 'enforce_finished_goods_ledger_entry_insert_integrity_v4'::regproc"
                )
            ).scalar_one()
            assert v4_after_reupgrade == 1, "re-upgrade must reattach the v4 trigger"

            locations_unique_after_reupgrade = c.execute(
                text(
                    "SELECT count(*) FROM pg_constraint WHERE conname = 'uq_locations_tenant_farm_id' "
                    "AND conrelid = 'locations'::regclass"
                )
            ).scalar_one()
            assert locations_unique_after_reupgrade == 1, "re-upgrade must recreate the composite unique on locations"

            locations_after_reupgrade = c.execute(
                text(
                    "SELECT id, tenant_id, farm_id, location_type_id, code, name, parent_location_id, status, "
                    "greenhouse_classification, occupiable, created_at "
                    "FROM locations WHERE id IN (:cs, :pos) ORDER BY id"
                ),
                {"cs": cold_store_id, "pos": pos_id},
            ).mappings().all()
            assert [dict(r) for r in locations_after_reupgrade] == locations_before, (
                "re-upgrade must leave both location rows byte-identical across the full downgrade/re-upgrade cycle"
            )

        # Re-upgrading must also leave the movement table fully functional
        # again -- pack a FRESH finished-goods lot now (needs no packing
        # history to have survived the downgrade itself) and place it.
        # The scenario was built with grade_and_pack_spec=False (see the
        # POSTHARVEST-OPS-001E note above), so it needs its own grading
        # scaffold + GradedProduceLot built here, post-reupgrade, before
        # pack_one can consume it.
        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            from app.models.farm import Farm
            from app.models.tenant import Tenant
            from app.models.user import User

            tenant_obj = verify_session.get(Tenant, scenario["tenant_id"])
            user_obj = verify_session.get(User, scenario["user_id"])
            farm_obj = verify_session.get(Farm, scenario["farm_id"])
            crop_id = verify_session.execute(
                text("SELECT crop_id FROM harvested_produce_lots WHERE id = :lid"), {"lid": scenario["lot_a_id"]}
            ).scalar_one()
            post_scaffold = build_packing_scaffold(
                verify_session, tenant_obj, user_obj, farm_obj, crop_id=crop_id, suffix=f"post-{scenario['suffix']}",
            )
            gpl_id = grade_entire_lot(
                verify_session, tenant_obj, user_obj, farm_obj,
                produce_lot_id=scenario["lot_a_id"], weight=scenario["lot_a_weight"], count=scenario["lot_a_count"],
                scaffold=post_scaffold, suffix=f"post-{scenario['suffix']}",
            )
            scenario["gpl_a_id"] = gpl_id
            scenario["pack_specification_version_id"] = post_scaffold["pack_specification_version_id"]
            fresh_fg_lot_id, _ = pack_one(
                scenario, verify_session, package_count=1, packed_output_weight_kg=Decimal("1.000"),
                code_suffix="-POST",
            )
            cold_store = create_cold_store(scenario, verify_session, code_suffix="-POST")
            pos = create_cold_store_position(scenario, verify_session, cold_store_id=cold_store.id, code_suffix="-POST")
            verify_session.commit()
            movement = finished_goods_storage_service.record_movement(
                verify_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), effective_time=_now(),
                finished_goods_lot_id=fresh_fg_lot_id, movement_kind="place", source_location_id=None,
                destination_location_id=pos.id, moved_weight_kg=Decimal("1.000"), moved_package_count=1, note=None,
            )
            assert movement.id is not None
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])
