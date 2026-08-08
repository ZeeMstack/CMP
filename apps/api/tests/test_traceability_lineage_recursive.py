"""CMP-019 recursive crop-batch lineage tests: multi-generation split-then-
merge dedup (same ancestor reached through more than one path, counted
once, edges preserved), and database-level corruption safety (a lineage
cycle -- structurally impossible through normal split/merge commands, but
constructed here via a direct-SQL bypass exactly like every other
"corrupted required edge" test in this codebase -- must fail with a typed
integrity error, never a silently truncated trace)."""
import uuid

import pytest
from sqlalchemy import select, text

from app.models.crop_batch import CropBatch
from app.services import batch_derivation_service, traceability_service
from app.services.errors import TraceabilityIntegrityError
from tests._packing_scenario import require_cmp_test
from tests._traceability_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    cleanup_traceability_scenario,
    committed_connection,
    harvest_all,
    now,
    pack_lot,
)


@pytest.mark.integration
def test_multi_generation_split_then_merge_dedups_ancestor_and_preserves_edges(test_engine) -> None:
    """A -> split -> B, C. B, C -> merge -> D. Backward ancestry of D must
    reach A exactly once (via two independent paths: D->B->A and D->C->A)
    while still returning both derivation edges leading to it."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2)
            suffix = uuid.uuid4().hex[:6]
            split_event = batch_derivation_service.split_batch(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=scaffold["batch"].id,
                client_command_id=uuid.uuid4(), effective_time=now(), note=None,
                outputs=[
                    {"output_batch_code": f"OUT-B-{suffix}", "source_assignment_ids": scaffold["assignment_ids"][:1]},
                    {"output_batch_code": f"OUT-C-{suffix}", "source_assignment_ids": scaffold["assignment_ids"][1:]},
                ],
            )
            session.commit()
            batch_b, batch_c = session.execute(
                select(CropBatch).where(CropBatch.created_by_batch_derivation_event_id == split_event.id).order_by(CropBatch.code)
            ).scalars().all()

            merge_event = batch_derivation_service.merge_batches(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                source_batch_ids=[batch_b.id, batch_c.id], client_command_id=uuid.uuid4(), effective_time=now(),
                note=None, output_batch_code=f"MERGED-{suffix}",
            )
            session.commit()
            batch_d = session.execute(
                select(CropBatch).where(CropBatch.created_by_batch_derivation_event_id == merge_event.id)
            ).scalar_one()

            farm_id = farm.id
            source_batch_id, batch_b_id, batch_c_id, batch_d_id = scaffold["batch"].id, batch_b.id, batch_c.id, batch_d.id

        # Forward impact from A must reach D exactly once as a descendant,
        # and both split edges (A->B, A->C) plus the merge edges (B->D,
        # C->D) must all be present.
        impact = traceability_service.get_crop_batch_impact(
            tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=source_batch_id, engine=test_engine
        )
        batch_ids = [b["batch_id"] for b in impact["lineage"]["batches"]]
        assert batch_ids.count(batch_d_id) == 1, "D must appear exactly once despite two reachable paths"
        assert {batch_c_id, batch_b_id, batch_d_id, source_batch_id} <= set(batch_ids)
        edges = {(e["parent_batch_id"], e["child_batch_id"]) for e in impact["lineage"]["edges"]}
        assert (source_batch_id, batch_b_id) in edges
        assert (source_batch_id, batch_c_id) in edges
        assert (batch_b_id, batch_d_id) in edges
        assert (batch_c_id, batch_d_id) in edges
        assert len(impact["lineage"]["edges"]) == 4
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_lineage_cycle_fails_with_integrity_error(test_engine) -> None:
    """Constructs a structurally-impossible-through-normal-commands cycle
    (batch A's creating event's source is batch B; batch B's creating
    event's source is batch A) via a direct-SQL bypass, exactly like every
    other "corrupted required edge" test in this codebase. Both
    `batch_derivation_sources.source_batch_id` and
    `batch_derivation_outputs.output_batch_id` stay individually unique
    (A is a source once, B is a source once; each is an output once) --
    the cycle exists only across the two events together, which no single
    row's own constraints can catch. The recursive ancestor traversal
    must detect this and raise TraceabilityIntegrityError -- never
    silently stop and return a partial, seemingly-valid trace."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold_a = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1, suffix="cyc-a")
            scaffold_b = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1, suffix="cyc-b")
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold_a["batch"].id, assignment_ids=scaffold_a["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id)
            session.commit()
            farm_id, user_id = farm.id, user.id
            batch_a_id, batch_b_id = scaffold_a["batch"].id, scaffold_b["batch"].id
            workflow_a_id, workflow_version_a_id = scaffold_a["workflow"].id, scaffold_a["version"].id
            run_a_id, stage_a_id = session.execute(
                text("SELECT id, workflow_stage_id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"),
                {"bid": batch_a_id},
            ).one()
            run_b_id = session.execute(
                text("SELECT id FROM batch_stage_runs WHERE batch_id = :bid AND exited_effective_time IS NULL"),
                {"bid": batch_b_id},
            ).scalar_one()

        require_cmp_test(test_engine)
        bypass_conn = test_engine.connect()
        trans = bypass_conn.begin()
        try:
            bypass_conn.execute(text("SET session_replication_role = replica"))
            event_1_id, event_2_id = uuid.uuid4(), uuid.uuid4()
            # Event 1: "A was created by splitting B" (source=B, output=A).
            # Event 2: "B was created by splitting A" (source=A, output=B).
            bypass_conn.execute(
                text(
                    "INSERT INTO batch_derivation_events "
                    "(id, tenant_id, farm_id, derivation_kind, workflow_id, workflow_version_id, "
                    "inherited_workflow_stage_id, effective_time, actor_user_id, client_command_id, "
                    "request_fingerprint, note) "
                    "VALUES (:id, :tid, :fid, 'split', :wfid, :wfvid, :stage, :eff, :uid, :ccid, 'fp', NULL)"
                ),
                {
                    "id": event_1_id, "tid": tenant_id, "fid": farm_id, "wfid": workflow_a_id,
                    "wfvid": workflow_version_a_id, "stage": stage_a_id, "eff": now(), "uid": user_id, "ccid": uuid.uuid4(),
                },
            )
            bypass_conn.execute(
                text(
                    "INSERT INTO batch_derivation_events "
                    "(id, tenant_id, farm_id, derivation_kind, workflow_id, workflow_version_id, "
                    "inherited_workflow_stage_id, effective_time, actor_user_id, client_command_id, "
                    "request_fingerprint, note) "
                    "VALUES (:id, :tid, :fid, 'split', :wfid, :wfvid, :stage, :eff, :uid, :ccid, 'fp', NULL)"
                ),
                {
                    "id": event_2_id, "tid": tenant_id, "fid": farm_id, "wfid": workflow_a_id,
                    "wfvid": workflow_version_a_id, "stage": stage_a_id, "eff": now(), "uid": user_id, "ccid": uuid.uuid4(),
                },
            )
            bypass_conn.execute(
                text(
                    "INSERT INTO batch_derivation_sources "
                    "(id, tenant_id, farm_id, derivation_event_id, source_batch_id, source_batch_stage_run_id, "
                    "recorded_plant_quantity_total, recorded_carrier_assignment_count) "
                    "VALUES (:id, :tid, :fid, :eid, :bid, :run, 20, 1)"
                ),
                {"id": uuid.uuid4(), "tid": tenant_id, "fid": farm_id, "eid": event_1_id, "bid": batch_b_id, "run": run_b_id},
            )
            bypass_conn.execute(
                text(
                    "INSERT INTO batch_derivation_outputs "
                    "(id, tenant_id, farm_id, derivation_event_id, output_batch_id, "
                    "recorded_plant_quantity_total, recorded_carrier_assignment_count) "
                    "VALUES (:id, :tid, :fid, :eid, :bid, 20, 1)"
                ),
                {"id": uuid.uuid4(), "tid": tenant_id, "fid": farm_id, "eid": event_1_id, "bid": batch_a_id},
            )
            bypass_conn.execute(
                text(
                    "INSERT INTO batch_derivation_sources "
                    "(id, tenant_id, farm_id, derivation_event_id, source_batch_id, source_batch_stage_run_id, "
                    "recorded_plant_quantity_total, recorded_carrier_assignment_count) "
                    "VALUES (:id, :tid, :fid, :eid, :bid, :run, 20, 1)"
                ),
                {"id": uuid.uuid4(), "tid": tenant_id, "fid": farm_id, "eid": event_2_id, "bid": batch_a_id, "run": run_a_id},
            )
            bypass_conn.execute(
                text(
                    "INSERT INTO batch_derivation_outputs "
                    "(id, tenant_id, farm_id, derivation_event_id, output_batch_id, "
                    "recorded_plant_quantity_total, recorded_carrier_assignment_count) "
                    "VALUES (:id, :tid, :fid, :eid, :bid, 20, 1)"
                ),
                {"id": uuid.uuid4(), "tid": tenant_id, "fid": farm_id, "eid": event_2_id, "bid": batch_b_id},
            )
            # ck_crop_batches_command_ownership_shape requires
            # client_command_id/request_fingerprint to be NULL exactly
            # when created_by_batch_derivation_event_id is set -- null
            # them out too, matching what a real derivation-created batch
            # looks like (CHECK constraints are enforced unconditionally,
            # unlike triggers, even under session_replication_role=replica).
            bypass_conn.execute(
                text(
                    "UPDATE crop_batches SET created_by_batch_derivation_event_id = :eid, "
                    "client_command_id = NULL, request_fingerprint = NULL WHERE id = :bid"
                ),
                {"eid": event_1_id, "bid": batch_a_id},
            )
            bypass_conn.execute(
                text(
                    "UPDATE crop_batches SET created_by_batch_derivation_event_id = :eid, "
                    "client_command_id = NULL, request_fingerprint = NULL WHERE id = :bid"
                ),
                {"eid": event_2_id, "bid": batch_b_id},
            )
            bypass_conn.execute(text("SET session_replication_role = DEFAULT"))
            trans.commit()
        except Exception:
            trans.rollback()
            bypass_conn.close()
            raise
        bypass_conn.close()

        with pytest.raises(TraceabilityIntegrityError, match="cycle"):
            traceability_service.get_finished_goods_lot_trace(
                tenant_id=tenant_id, farm_id=farm_id, finished_goods_lot_id=fg_lot_id, engine=test_engine
            )
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_lineage_depth_guard_exceeded_fails_with_integrity_error(test_engine, monkeypatch) -> None:
    """Distinct from the cycle test above: a genuine, non-cyclic split
    chain deeper than the traversal's own defensive depth guard must also
    raise TraceabilityIntegrityError rather than silently truncate to a
    partial trace. `_MAX_LINEAGE_DEPTH` is a plain module-level constant
    with no other role, so it is monkeypatched down to a small value here
    -- the production default (500) is never changed -- and a real chain
    of ordinary splits (each with two genuine outputs, never a
    single-output no-op) is built one generation deeper than the patched
    limit."""
    monkeypatch.setattr(traceability_service, "_MAX_LINEAGE_DEPTH", 3)
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=6)
            farm_id = farm.id
            current_batch_id = scaffold["batch"].id
            remaining_assignment_ids = list(scaffold["assignment_ids"])

            # Four sequential splits (patched guard is 3): each peels off
            # one assignment as a throwaway "side" output and keeps
            # deriving the chain through the "main" output, so the main
            # branch alone reaches depth 4 -- one generation past the
            # patched depth-3 guard -- with no revisit of any prior batch
            # (never a cycle).
            for i in range(4):
                suffix = uuid.uuid4().hex[:6]
                side_code, main_code = f"SIDE-{i}-{suffix}", f"MAIN-{i}-{suffix}"
                split_event = batch_derivation_service.split_batch(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                    batch_id=current_batch_id, client_command_id=uuid.uuid4(), effective_time=now(), note=None,
                    outputs=[
                        {"output_batch_code": side_code, "source_assignment_ids": remaining_assignment_ids[:1]},
                        {"output_batch_code": main_code, "source_assignment_ids": remaining_assignment_ids[1:]},
                    ],
                )
                session.commit()
                main_batch_id = session.execute(
                    select(CropBatch.id).where(
                        CropBatch.created_by_batch_derivation_event_id == split_event.id, CropBatch.code == main_code
                    )
                ).scalar_one()
                remaining_assignment_ids = session.execute(
                    text(
                        "SELECT id FROM batch_carrier_assignments WHERE batch_id = :bid "
                        "AND released_effective_time IS NULL ORDER BY id"
                    ),
                    {"bid": main_batch_id},
                ).scalars().all()
                current_batch_id = main_batch_id

            root_batch_id = scaffold["batch"].id

        with pytest.raises(TraceabilityIntegrityError, match="depth guard"):
            traceability_service.get_crop_batch_impact(
                tenant_id=tenant_id, farm_id=farm_id, crop_batch_id=root_batch_id, engine=test_engine
            )
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
