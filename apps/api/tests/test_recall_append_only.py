"""CMP-020 append-only tests: UPDATE/DELETE must be rejected on all five
new recall tables -- recall case identity, its closure, and each of the
three frozen-scope tables."""
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from tests._recall_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    cleanup_recall_scenario,
    close_case,
    committed_connection,
    harvest_all,
    open_case,
    pack_lot,
)


@pytest.mark.integration
def test_recall_case_identity_and_scope_tables_reject_update_and_delete(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()
            batch_id = scaffold["batch"].id

            case = open_case(session, tenant, farm, user, crop_batch_id=batch_id)
            session.commit()
            case_id = case.id
            closure = close_case(session, tenant, farm, user, recall_case_id=case_id)
            session.commit()
            closure_id = closure.id

        with test_engine.connect() as conn:
            with pytest.raises(ProgrammingError):
                with conn.begin():
                    conn.execute(text("UPDATE recall_cases SET code = 'HACKED' WHERE id = :id"), {"id": case_id})
        with test_engine.connect() as conn:
            with pytest.raises(ProgrammingError):
                with conn.begin():
                    conn.execute(text("DELETE FROM recall_cases WHERE id = :id"), {"id": case_id})

        with test_engine.connect() as conn:
            with pytest.raises(ProgrammingError):
                with conn.begin():
                    conn.execute(text("UPDATE recall_case_closures SET close_reason = 'HACKED' WHERE id = :id"), {"id": closure_id})
        with test_engine.connect() as conn:
            with pytest.raises(ProgrammingError):
                with conn.begin():
                    conn.execute(text("DELETE FROM recall_case_closures WHERE id = :id"), {"id": closure_id})

        with test_engine.connect() as conn:
            scope_batch_id = conn.execute(
                text("SELECT id FROM recall_scope_batches WHERE recall_case_id = :cid"), {"cid": case_id}
            ).scalar_one()
            scope_lot_id = conn.execute(
                text("SELECT id FROM recall_scope_produce_lots WHERE recall_case_id = :cid"), {"cid": case_id}
            ).scalar_one()
            scope_fg_id = conn.execute(
                text("SELECT id FROM recall_scope_finished_goods_lots WHERE recall_case_id = :cid"), {"cid": case_id}
            ).scalar_one()

        for table, row_id in (
            ("recall_scope_batches", scope_batch_id),
            ("recall_scope_produce_lots", scope_lot_id),
            ("recall_scope_finished_goods_lots", scope_fg_id),
        ):
            with test_engine.connect() as conn:
                with pytest.raises(ProgrammingError):
                    with conn.begin():
                        conn.execute(text(f"UPDATE {table} SET recorded_time = now() WHERE id = :id"), {"id": row_id})
            with test_engine.connect() as conn:
                with pytest.raises(ProgrammingError):
                    with conn.begin():
                        conn.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)
