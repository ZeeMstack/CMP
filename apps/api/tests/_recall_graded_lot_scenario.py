"""Shared, non-collected scenario helpers for POSTHARVEST-OPS-001D
graded-produce-lot recall tests. Extends `tests._recall_scenario` (which
itself extends `tests._traceability_scenario`, built on ORM tenant/farm/
user objects, unlike `tests._grading_scenario`'s own raw-id convention)
with a processing/grading scaffold (packing hall + two grade definitions)
and a two-output grading wrapper, so a batch/HPL-source recall's upstream
freeze can be proven against real `GradedProduceLot` descendants. Not a
test file itself (pytest's default `test_*.py` discovery glob does not
match this name)."""
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import grade_definition_service, grading_service, location_service
from tests._recall_scenario import (  # noqa: F401  (re-exported for test files)
    build_batch_with_assignments,
    build_committed_tenant_farm,
    build_workflow_scaffold,
    cleanup_recall_scenario,
    close_case,
    committed_connection,
    create_cold_store_position,
    dispatch,
    harvest_all,
    now,
    open_case,
    pack_lot,
    pack_multi,
    place,
    sow_new_batch,
)


def build_grading_scaffold(db: Session, tenant, user, farm, *, crop_id, suffix=None):
    """An active `packing_hall` Location plus two ACTIVE `GradeDefinition`s
    (Grade A / Grade B) scoped to `crop_id`, activated well in the past so
    any reasonable `effective_time` in a test falls inside their window.
    Two separate grade definitions (not two versions of one) are used so a
    single `GradingEvent` can output both in one command -- `GradedProduceLot`
    enforces `UNIQUE(grading_event_id, grade_definition_version_id)`, so one
    event's two outputs must reference two distinct grade-definition
    versions."""
    suffix = suffix or uuid.uuid4().hex[:8]
    hall = location_service.create_location(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, location_type_code="packing_hall",
        code=f"hall-{suffix}", name="Processing Hall", parent_location_id=None, greenhouse_classification=None,
        occupiable=False,
    )

    def _grade_version(label: str) -> uuid.UUID:
        definition = grade_definition_service.register_grade_definition(
            db, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            code=f"grade-{label}-{suffix}", name=f"Grade {label}", crop_id=crop_id, variety_id=None,
            description=None,
        )
        version = grade_definition_service.create_draft_version(
            db, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            grade_definition_id=definition.id, spec_notes=None,
        )
        grade_definition_service.activate_version(
            db, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            grade_definition_id=definition.id, version_id=version.id, effective_time=now() - timedelta(days=30),
        )
        return version.id

    return {
        "packing_hall_location_id": hall.id,
        "grade_a_version_id": _grade_version("A"),
        "grade_b_version_id": _grade_version("B"),
    }


def grade_lot_two_outputs(
    db: Session, tenant, user, farm, *, source_produce_lot_id, packing_hall_location_id, grade_a_version_id,
    grade_b_version_id, input_presented=Decimal("5.000"), weight_a=Decimal("3.000"), weight_b=Decimal("2.000"),
    suffix=None,
):
    """One `GradingEvent` against `source_produce_lot_id` producing exactly
    two `GradedProduceLot`s (GPL-A, GPL-B) -- the shared fixture every
    001D sibling-isolation and upstream-freeze test needs. Returns
    `(grading_event_id, gpl_a_id, gpl_b_id)`."""
    suffix = suffix or uuid.uuid4().hex[:8]
    code_a, code_b = f"GPL-A-{suffix}", f"GPL-B-{suffix}"
    remainder = input_presented - weight_a - weight_b
    event = grading_service.record_grading(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        source_harvested_produce_lot_id=source_produce_lot_id,
        processing_hall_location_id=packing_hall_location_id, effective_time=now(), note=None,
        input_presented_weight_kg=input_presented, input_presented_whole_unit_count=None,
        rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
        loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
        sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
        remainder_weight_kg=remainder, remainder_whole_unit_count=None,
        outputs=[
            {
                "grade_definition_version_id": grade_a_version_id, "code": code_a,
                "output_weight_kg": weight_a, "output_whole_unit_count": None,
            },
            {
                "grade_definition_version_id": grade_b_version_id, "code": code_b,
                "output_weight_kg": weight_b, "output_whole_unit_count": None,
            },
        ],
    )
    gpl_a_id = db.execute(
        text("SELECT id FROM graded_produce_lots WHERE grading_event_id = :eid AND code = :c"),
        {"eid": event.id, "c": code_a},
    ).scalar_one()
    gpl_b_id = db.execute(
        text("SELECT id FROM graded_produce_lots WHERE grading_event_id = :eid AND code = :c"),
        {"eid": event.id, "c": code_b},
    ).scalar_one()
    return event.id, gpl_a_id, gpl_b_id


def cleanup_recall_graded_lot_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    """Deletes 001C grading rows and the 001D graded-lot recall scope
    (ahead of every table `cleanup_recall_scenario` already knows about),
    then defers to it for everything else."""
    from tests._packing_scenario import require_cmp_test

    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        if conn.execute(text("SELECT to_regclass('recall_scope_graded_produce_lots')")).scalar() is not None:
            conn.execute(
                text("DELETE FROM recall_scope_graded_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id}
            )
        conn.execute(text("DELETE FROM graded_produce_lot_ledger_entries WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM graded_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(
            text(
                "DELETE FROM produce_lot_ledger_entries WHERE tenant_id = :tid AND entry_kind = 'grading_consumption'"
            ),
            {"tid": tenant_id},
        )
        conn.execute(text("DELETE FROM grading_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM grade_definition_versions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM grade_definitions WHERE tenant_id = :tid"), {"tid": tenant_id})
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
    cleanup_recall_scenario(test_engine, tenant_id)
