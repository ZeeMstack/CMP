"""Shared, non-collected scenario helpers for CMP-020 recall-containment
tests. Extends `tests._traceability_scenario` (which itself extends
`tests._packing_scenario`) with recall-case open/close convenience
wrappers and a cleanup routine covering the 5 new recall tables. Not a
test file itself (pytest's default `test_*.py` discovery glob does not
match this name)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import recall_service
from tests._packing_scenario import require_cmp_test
from tests._traceability_scenario import (  # noqa: F401  (re-exported for test files)
    build_batch_with_assignments,
    build_committed_tenant_farm,
    build_workflow_scaffold,
    cleanup_traceability_scenario,
    committed_connection,
    create_cold_store_position,
    dispatch,
    harvest_all,
    now,
    pack_lot,
    pack_multi,
    place,
    sow_new_batch,
)


def open_case(
    db: Session,
    tenant,
    farm,
    user,
    *,
    crop_batch_id=None,
    harvested_produce_lot_id=None,
    graded_produce_lot_id=None,
    finished_goods_lot_id=None,
    effective_time=None,
    reason_code="contamination_suspected",
    reason_text="Routine test containment.",
    suffix=None,
):
    suffix = suffix or uuid.uuid4().hex[:8]
    return recall_service.open_recall_case(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        effective_time=effective_time or now(), code=f"RC-{suffix}", crop_batch_id=crop_batch_id,
        harvested_produce_lot_id=harvested_produce_lot_id, graded_produce_lot_id=graded_produce_lot_id,
        finished_goods_lot_id=finished_goods_lot_id,
        reason_code=reason_code, reason_text=reason_text,
    )


def close_case(db: Session, tenant, farm, user, *, recall_case_id, effective_time=None, close_reason="Contained material segregated; investigation complete."):
    return recall_service.close_recall_case(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, recall_case_id=recall_case_id,
        client_command_id=uuid.uuid4(), effective_time=effective_time or now(), close_reason=close_reason,
    )


def cleanup_recall_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    """Deletes CMP-020 recall rows (children before parents, ahead of
    every table `cleanup_traceability_scenario` already knows about --
    all five recall tables reference crop_batches/harvested_produce_lots/
    finished_goods_lots, which that cleanup deletes later), then defers
    to it for everything else."""
    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM recall_case_closures WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM recall_scope_finished_goods_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        # POSTHARVEST-OPS-001D: recall_scope_graded_produce_lots is new --
        # existence-guarded (`to_regclass`) so this same cleanup keeps
        # working for a downgrade-guard test that runs it while cmp_test is
        # deliberately downgraded below the migration that creates it.
        if conn.execute(text("SELECT to_regclass('recall_scope_graded_produce_lots')")).scalar() is not None:
            conn.execute(text("DELETE FROM recall_scope_graded_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM recall_scope_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM recall_scope_batches WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM recall_cases WHERE tenant_id = :tid"), {"tid": tenant_id})
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
    cleanup_traceability_scenario(test_engine, tenant_id)
