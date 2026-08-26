"""Shared, non-collected scenario builder for POSTHARVEST-OPS-001C
grading tests. Builds on top of `tests/_packing_scenario.py`'s own
committed harvest-lot scenario (reused verbatim, not duplicated) and adds
an active `packing_hall` Location plus an active `GradeDefinitionVersion`
matching the scenario's crop/variety. Not a test file itself (pytest's
default `test_*.py` discovery glob does not match this name)."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import grade_definition_service, location_service
from tests._packing_scenario import build_committed_scenario as _build_harvest_scenario
from tests._packing_scenario import cleanup_scenario as _cleanup_harvest_scenario
from tests._packing_scenario import require_cmp_test


def now():
    return datetime.now(timezone.utc)


def build_committed_scenario(
    test_engine, *, lot_a_weight="10.000", lot_a_count=40, lot_b_weight="5.000", lot_b_count=20,
    carrier_type_code="grow_bag", carrier_count=2,
):
    """Returns everything `_packing_scenario.build_committed_scenario`
    returns, plus `packing_hall_location_id`, `inactive_hall_location_id`,
    `other_location_id` (a non-packing_hall location, e.g. a store),
    `crop_id`, `variety_id`, and `grade_definition_version_id` (an ACTIVE
    version scoped to the scenario's own crop/variety, activated well in
    the past so any reasonable `effective_time` in a test falls inside its
    window)."""
    scenario = _build_harvest_scenario(
        test_engine, lot_a_weight=lot_a_weight, lot_a_count=lot_a_count, lot_b_weight=lot_b_weight,
        lot_b_count=lot_b_count, carrier_type_code=carrier_type_code, carrier_count=carrier_count,
    )

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = scenario["suffix"]
    tenant_id = scenario["tenant_id"]
    farm_id = scenario["farm_id"]
    user_id = scenario["user_id"]

    crop_id, variety_id = session.execute(
        text("SELECT crop_id, variety_id FROM harvested_produce_lots WHERE id = :id"), {"id": scenario["lot_a_id"]}
    ).one()

    hall = location_service.create_location(
        session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, location_type_code="packing_hall",
        code=f"hall-{suffix}", name="Processing Hall", parent_location_id=None, greenhouse_classification=None,
        occupiable=False,
    )
    inactive_hall = location_service.create_location(
        session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, location_type_code="packing_hall",
        code=f"hall-inactive-{suffix}", name="Inactive Hall", parent_location_id=None,
        greenhouse_classification=None, occupiable=False,
    )
    session.execute(text("UPDATE locations SET status = 'inactive' WHERE id = :id"), {"id": inactive_hall.id})
    other_location = location_service.create_location(
        session, tenant_id=tenant_id, farm_id=farm_id, actor_user_id=user_id, location_type_code="store",
        code=f"store-{suffix}", name="Input Store", parent_location_id=None, greenhouse_classification=None,
        occupiable=False,
    )

    grade_definition = grade_definition_service.register_grade_definition(
        session, tenant_id=tenant_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
        code=f"grade-{suffix}", name="Premium", crop_id=crop_id, variety_id=None, description=None,
    )
    grade_version = grade_definition_service.create_draft_version(
        session, tenant_id=tenant_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
        grade_definition_id=grade_definition.id, spec_notes=None,
    )
    grade_definition_service.activate_version(
        session, tenant_id=tenant_id, actor_user_id=user_id, client_command_id=uuid.uuid4(),
        grade_definition_id=grade_definition.id, version_id=grade_version.id,
        effective_time=now() - timedelta(days=30),
    )

    session.commit()
    scenario.update(
        {
            "crop_id": crop_id, "variety_id": variety_id, "packing_hall_location_id": hall.id,
            "inactive_hall_location_id": inactive_hall.id, "other_location_id": other_location.id,
            "grade_definition_id": grade_definition.id, "grade_definition_version_id": grade_version.id,
        }
    )
    session.close()
    conn.close()
    return scenario


def cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    """PRE-COMMIT CORRECTION (POSTHARVEST-OPS-001D verification pass):
    `test_grading_quality_recall.py` opens real `RecallCase`s (via this
    scenario's own tenant) to prove 001C's grading containment gate --
    this cleanup previously never deleted them, leaving orphaned
    `recall_cases`/scope rows referencing an already-deleted tenant behind
    in `cmp_test`, which blocks every full-chain migration downgrade test
    until manually cleaned. Mirrors `tests/_recall_scenario.py::
    cleanup_recall_scenario`'s own FK-safe, children-before-parents
    ordering across all six Recall tables (its own `recall_scope_
    graded_produce_lots` delete is existence-guarded there for the same
    downgrade-guard-compatibility reason kept here)."""
    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM recall_case_closures WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM recall_scope_finished_goods_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        if conn.execute(text("SELECT to_regclass('recall_scope_graded_produce_lots')")).scalar() is not None:
            conn.execute(
                text("DELETE FROM recall_scope_graded_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id}
            )
        conn.execute(text("DELETE FROM recall_scope_produce_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM recall_scope_batches WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM recall_cases WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(
            text("DELETE FROM graded_produce_lot_ledger_entries WHERE tenant_id = :tid"), {"tid": tenant_id}
        )
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
        conn.execute(text("DELETE FROM locations WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    except Exception:
        trans.rollback()
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        raise
    finally:
        conn.close()

    # Delegate the rest (harvest/packing/farm/crop/tenant teardown) to the
    # already-established, more extensive harvest-scenario cleanup.
    _cleanup_harvest_scenario(test_engine, tenant_id)
