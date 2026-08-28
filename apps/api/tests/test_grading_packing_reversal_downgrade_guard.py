"""POSTHARVEST-OPS-001H downgrade-guard proof tests.

Grading/Packing reversal history (`grading_reversal_events`/
`packing_reversal_events`) is independent commercial/audit-correction
history, never a projection of any older table -- downgrading past this
ticket while any exists would silently discard it, violating this
codebase's immutable-history mandate. Mirrors CMP-015's/POSTHARVEST-OPS-
001E's own "block on the mere existence of history" downgrade-guard idiom
exactly (see `test_packing_downgrade_guard.py`).

Also proves, via `information_schema` introspection (never merely "it
round-tripped without error"), that `packing_input_lines`' new
`uq_packing_input_lines_tenant_farm_id` constraint -- added by this ticket
so `packing_reversal_inputs` can use a real composite FK, mirroring
CMP-018's own `uq_locations_tenant_farm_id` precedent -- is present after
upgrade, absent after downgrade, and exactly restored after re-upgrade.
"""
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
from app.services import grading_service, packing_service
from tests._packing_scenario import build_committed_scenario, cleanup_scenario, require_cmp_test

API_ROOT = Path(__file__).resolve().parent.parent
_PRE_001H_REVISION = "d8f4a1c92b57"


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


def _session(test_engine):
    conn = test_engine.connect()
    return Session(bind=conn), conn


@pytest.mark.integration
def test_downgrade_blocked_when_grading_reversal_history_exists(test_engine, alembic_head_restore) -> None:
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        grading_event_id = session.execute(
            text("SELECT grading_event_id FROM graded_produce_lots WHERE id = :id"), {"id": scenario["gpl_a_id"]}
        ).scalar_one()
        grading_service.reverse_grading_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), grading_event_id=grading_event_id,
            effective_time=_now(), reason_code="OPERATOR_ERROR", note=None,
        )
    finally:
        session.close()
        conn.close()
    require_cmp_test(test_engine)

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001H"):
            command.downgrade(_cfg(), _PRE_001H_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_downgrade_blocked_when_packing_reversal_history_exists(test_engine, alembic_head_restore) -> None:
    scenario = build_committed_scenario(test_engine)
    session, conn = _session(test_engine)
    try:
        event = packing_service.record_packing(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
            pack_specification_version_id=scenario["pack_specification_version_id"], effective_time=_now(),
            finished_goods_lot_code=f"FG-{scenario['suffix']}", package_count=1,
            packed_output_weight_kg=scenario["lot_a_weight"], process_loss_weight_kg=Decimal("0"),
            rejected_weight_kg=Decimal("0"), note=None,
            input_lines=[
                {
                    "graded_produce_lot_id": scenario["gpl_a_id"], "consumed_weight_kg": scenario["lot_a_weight"],
                    "consumed_whole_unit_count": scenario["lot_a_count"], "note": None,
                }
            ],
        )
        packing_service.reverse_packing_event(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), packing_event_id=event.id,
            effective_time=_now(), reason_code="OPERATOR_ERROR", note=None,
        )
    finally:
        session.close()
        conn.close()
    require_cmp_test(test_engine)

    try:
        with pytest.raises(RuntimeError, match="Cannot downgrade past POSTHARVEST-OPS-001H"):
            command.downgrade(_cfg(), _PRE_001H_REVISION)
        _assert_at_head(test_engine)
    finally:
        cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_clean_downgrade_and_reupgrade_restores_packing_input_lines_constraint(
    test_engine, alembic_head_restore
) -> None:
    """Proven via `information_schema` introspection, not merely "no
    exception was raised" -- the whole point of this ticket's own
    `uq_packing_input_lines_tenant_farm_id` addition (needed so
    `packing_reversal_inputs` can use a real composite FK, mirroring
    CMP-018's own `uq_locations_tenant_farm_id` precedent)."""

    def _constraint_columns(conn) -> list[str] | None:
        rows = conn.execute(
            text(
                "SELECT kcu.column_name FROM information_schema.key_column_usage kcu "
                "JOIN information_schema.table_constraints tc "
                "  ON tc.constraint_name = kcu.constraint_name AND tc.table_name = kcu.table_name "
                "WHERE kcu.table_name = 'packing_input_lines' "
                "  AND kcu.constraint_name = 'uq_packing_input_lines_tenant_farm_id' "
                "ORDER BY kcu.ordinal_position"
            )
        ).all()
        return [r[0] for r in rows] or None

    with test_engine.connect() as conn:
        assert _constraint_columns(conn) == ["tenant_id", "farm_id", "id"]

    command.downgrade(_cfg(), _PRE_001H_REVISION)
    with test_engine.connect() as conn:
        assert _constraint_columns(conn) is None, "constraint must be absent once downgraded past 001H"

    command.upgrade(_cfg(), "head")
    with test_engine.connect() as conn:
        assert _constraint_columns(conn) == ["tenant_id", "farm_id", "id"], (
            "constraint must be restored, with the exact same column order, after re-upgrading to head"
        )
