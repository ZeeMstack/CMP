"""POSTHARVEST-OPS-001D downgrade-guard proof tests for
`c3f7a29d5e64` (graded_produce_lot recall scope), mirroring
`test_recall_downgrade_guard.py`'s own established proof style: graded-
lot recall history is independent compliance data, so downgrade past
001D is blocked while ANY row exists in `recall_scope_graded_produce_lots`
or any `recall_cases` row has `graded_produce_lot_id IS NOT NULL` --
including a *closed* case. A clean downgrade drops the new table/column/FK
and restores the byte-exact CMP-020 (three-source) typed-source CHECK and
reconciliation function; re-upgrade restores the four-source shape and a
working graded-produce-lot-source recall."""
import pytest
from sqlalchemy import text

from app.services import recall_service
from tests._recall_graded_lot_scenario import (
    build_committed_tenant_farm,
    cleanup_recall_graded_lot_scenario,
    close_case,
    committed_connection,
    open_case,
)
from tests.test_recall_downgrade_guard import _assert_at_head, _cfg
from tests.test_recall_graded_lot_case_opening import _build_graded_pair
from alembic import command

_PRE_001D_REVISION = "f2c8a5d1e793"


@pytest.mark.integration
def test_downgrade_blocked_by_graded_produce_lot_recall_history(test_engine, alembic_head_restore) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
            open_case(session, tenant, farm, user, graded_produce_lot_id=gpl_a_id)
            session.commit()

        with pytest.raises(RuntimeError, match="graded-produce-lot recall scope or typed-source"):
            command.downgrade(_cfg(), _PRE_001D_REVISION)
        _assert_at_head(test_engine)
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_downgrade_blocked_even_after_graded_produce_lot_case_closed(test_engine, alembic_head_restore) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
            case = open_case(session, tenant, farm, user, graded_produce_lot_id=gpl_a_id)
            session.commit()
            close_case(session, tenant, farm, user, recall_case_id=case.id)
            session.commit()

        with pytest.raises(RuntimeError, match="graded-produce-lot recall scope or typed-source"):
            command.downgrade(_cfg(), _PRE_001D_REVISION)
        _assert_at_head(test_engine)
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_clean_downgrade_with_no_graded_lot_history_reupgrade_restores_exact_prior_state(
    test_engine, alembic_head_restore
) -> None:
    with test_engine.connect() as c:
        check_def_before = c.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_recall_cases_typed_source_shape'")
        ).scalar_one()
    assert "graded_produce_lot_id" in check_def_before

    try:
        command.downgrade(_cfg(), _PRE_001D_REVISION)

        with test_engine.connect() as c:
            table_exists = c.execute(text("SELECT to_regclass('recall_scope_graded_produce_lots')")).scalar()
            assert table_exists is None, "recall_scope_graded_produce_lots must be dropped by a clean downgrade"

            column_exists = c.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = 'recall_cases' AND column_name = 'graded_produce_lot_id'"
                )
            ).scalar_one()
            assert column_exists == 0, "recall_cases.graded_produce_lot_id must be dropped by a clean downgrade"

            check_def_after = c.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_recall_cases_typed_source_shape'"
                )
            ).scalar_one()
            assert "graded_produce_lot_id" not in check_def_after, (
                "the exact CMP-020 (three-source) typed-source CHECK must be restored"
            )

        command.upgrade(_cfg(), "head")
        _assert_at_head(test_engine)
        with test_engine.connect() as c:
            table_restored = c.execute(text("SELECT to_regclass('recall_scope_graded_produce_lots')")).scalar()
            assert table_restored is not None

        # Re-upgraded shape genuinely works again: a fresh graded-lot-source
        # recall opens and freezes its exact scope.
        tenant_id2 = None
        try:
            with committed_connection(test_engine) as session:
                tenant, user, farm = build_committed_tenant_farm(session)
                tenant_id2 = tenant.id
                _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
                case = open_case(session, tenant, farm, user, graded_produce_lot_id=gpl_a_id)
                session.commit()
                case_id = case.id
                farm_id = farm.id

            detail = recall_service.get_recall_case(
                tenant_id=tenant_id2, farm_id=farm_id, recall_case_id=case_id, engine=test_engine
            )
            assert detail["frozen_scope"]["graded_produce_lot_ids"] == [gpl_a_id]
        finally:
            if tenant_id2 is not None:
                cleanup_recall_graded_lot_scenario(test_engine, tenant_id2)
    finally:
        command.upgrade(_cfg(), "head")
