"""Real two-connection concurrency tests for CMP-012 split/merge, mirroring
test_transplant_concurrency.py / test_sowing_concurrency.py: committed setup
data via a dedicated connection so two independent sessions can genuinely
race, with cleanup bypassing append-only/no-delete triggers via
`session_replication_role = replica`, scoped to this test only, hardened
with the `cmp_test` guard and explicit `DEFAULT` restore."""
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    batch_derivation_service,
    carrier_service,
    crop_batch_service,
    crop_service,
    farm_service,
    membership_service,
    production_system_service,
    sowing_service,
    tenant_service,
    user_service,
    workflow_service,
)
from app.services.errors import BatchDerivationValidationError, CropBatchClosedError


def _now():
    return datetime.now(timezone.utc)


def _build_committed_scenario(test_engine, *, source_batch_count=1, carriers_per_batch=2):
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"deriv-race-{suffix}", name="Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="deriv-race", oidc_subject=suffix, email=f"deriv-race-{suffix}@example.com",
        display_name="Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    crop = crop_service.register_crop(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"crop-{suffix}", common_name="Iceberg",
        scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"var-{suffix}",
        name="Variety", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"ps-{suffix}", name="System", description=None,
    )
    workflow = workflow_service.register_workflow(
        session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"wf-{suffix}", name="Workflow",
    )
    version = workflow_service.create_draft_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=complete.id, code="ADV", name="Advance",
    )
    workflow_service.publish_version(
        session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    seed_lot = sowing_service.register_seed_lot(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"lot-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )

    batches = []
    all_assignment_ids = []
    for b in range(source_batch_count):
        batch = crop_batch_service.create_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
            code=f"batch-{suffix}-{b}", workflow_id=workflow.id, effective_time=_now(),
        )
        carriers = [
            carrier_service.register_carrier(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                carrier_type_code="seed_tray", code=f"tray-{suffix}-{b}-{n}", issued_date=None,
            )
            for n in range(carriers_per_batch)
        ]
        sowing_service.sow_batch(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
            client_command_id=uuid.uuid4(), effective_time=_now(), note=None,
            lines=[
                {"carrier_id": c.id, "seed_lot_id": seed_lot.id, "sown_site_count": 50, "seed_count": 50, "line_note": None}
                for c in carriers
            ],
        )
        assignments = sowing_service.list_batch_carriers(session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch.id)
        assignment_by_carrier = {a.carrier.code: a.id for a in assignments}
        aids = [assignment_by_carrier[c.code] for c in carriers]
        batches.append(batch)
        all_assignment_ids.append(aids)

    result = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_ids": [b.id for b in batches],
        "assignment_ids": all_assignment_ids, "suffix": suffix,
    }
    session.close()
    conn.close()
    return result


def _cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup (session_replication_role) against "
            f"database {current_db!r}; this cleanup is only permitted against 'cmp_test'"
        )

    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text("DELETE FROM batch_assignment_transfers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_derivation_outputs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_derivation_sources WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_derivation_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_event_lines WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_carrier_assignments WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM sowing_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM seed_lots WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM carriers WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_runs WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM batch_stage_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crop_batches WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_transitions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_stages WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflow_versions WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM workflows WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM production_systems WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM varieties WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM crops WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM audit_events WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM farms WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenant_memberships WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
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


@pytest.mark.integration
def test_concurrent_split_of_same_batch_leaves_one_winner(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, source_batch_count=1, carriers_per_batch=4)
    batch_id = scenario["batch_ids"][0]
    aids = scenario["assignment_ids"][0]
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()

    def worker(name: str, code_prefix: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = batch_derivation_service.split_batch(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], batch_id=batch_id, client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None,
                outputs=[
                    {"output_batch_code": f"{code_prefix}-A", "source_assignment_ids": aids[:2]},
                    {"output_batch_code": f"{code_prefix}-B", "source_assignment_ids": aids[2:]},
                ],
            )
            results[name] = ("ok", event.id)
        except CropBatchClosedError as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a", f"OUT-A-{scenario['suffix']}"))
    t_b = threading.Thread(target=worker, args=("b", f"OUT-B-{scenario['suffix']}"))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])


@pytest.mark.integration
def test_concurrent_overlapping_merges_leave_one_winner(test_engine) -> None:
    scenario = _build_committed_scenario(test_engine, source_batch_count=3, carriers_per_batch=1)
    batch_ids = scenario["batch_ids"]
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}
    effective_time = _now()

    def worker(name: str, source_ids: list[uuid.UUID], code: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = batch_derivation_service.merge_batches(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], source_batch_ids=source_ids, client_command_id=uuid.uuid4(),
                effective_time=effective_time, note=None, output_batch_code=code,
            )
            results[name] = ("ok", event.id)
        except (CropBatchClosedError, BatchDerivationValidationError) as exc:
            results[name] = ("conflict", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    # Overlapping: [0, 1] vs [1, 2] — batch 1 is contested.
    t_a = threading.Thread(target=worker, args=("a", [batch_ids[0], batch_ids[1]], f"MERGE-A-{scenario['suffix']}"))
    t_b = threading.Thread(target=worker, args=("b", [batch_ids[1], batch_ids[2]], f"MERGE-B-{scenario['suffix']}"))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    try:
        assert not t_a.is_alive() and not t_b.is_alive()
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results
        assert outcomes.count("conflict") == 1, results
    finally:
        _cleanup_scenario(test_engine, scenario["tenant_id"])
