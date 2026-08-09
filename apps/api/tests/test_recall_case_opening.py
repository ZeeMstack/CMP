"""CMP-020 recall case opening tests: scope-freeze correctness for all
three typed source kinds (crop-batch descendant closure including split
and multi-generation split+merge; harvested-produce-lot with no batch
promotion; finished-goods-lot with no upstream co-input promotion),
idempotency (exact replay, payload-conflict), case-code uniqueness, and
effective-time validation."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.crop_batch import CropBatch
from app.services import batch_derivation_service, recall_service
from app.services.errors import (
    CropBatchNotFoundError,
    DuplicateRecallCaseCodeError,
    InvalidRecallCaseEffectiveTimeError,
    RecallCaseCommandReusedWithDifferentPayloadError,
    RecallScopeStabilizationError,
)
from tests._packing_scenario import require_cmp_test
from tests._recall_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    build_workflow_scaffold,
    cleanup_recall_scenario,
    committed_connection,
    dispatch,
    harvest_all,
    now,
    open_case,
    pack_lot,
    pack_multi,
    sow_new_batch,
)


@pytest.mark.integration
def test_open_crop_batch_recall_freezes_batch_produce_and_fg_scope(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id)
            session.commit()
            batch_id = scaffold["batch"].id

            case = open_case(session, tenant, farm, user, crop_batch_id=batch_id)
            session.commit()
            case_id = case.id

        detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
        assert detail["frozen_scope"]["crop_batch_ids"] == [batch_id]
        assert detail["frozen_scope"]["harvested_produce_lot_ids"] == [produce_lot_id]
        assert detail["frozen_scope"]["finished_goods_lot_ids"] == [fg_lot_id]
        assert detail["is_open"] is True
        assert detail["closure"] is None
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_open_batch_recall_includes_split_descendants(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2)
            suffix = uuid.uuid4().hex[:6]
            split_event = batch_derivation_service.split_batch(
                session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id, batch_id=scaffold["batch"].id,
                client_command_id=uuid.uuid4(), effective_time=now(), note=None,
                outputs=[
                    {"output_batch_code": f"OUT-B-{suffix}", "source_assignment_ids": scaffold["assignment_ids"][:1]},
                    {"output_batch_code": f"OUT-C-{suffix}", "source_assignment_ids": scaffold["assignment_ids"][1:]},
                ],
            )
            session.commit()
            batch_b = session.execute(
                select(CropBatch).where(CropBatch.created_by_batch_derivation_event_id == split_event.id, CropBatch.code == f"OUT-B-{suffix}")
            ).scalar_one()
            batch_b_id = batch_b.id
            assignments_b = session.execute(
                __import__("sqlalchemy").text(
                    "SELECT id FROM batch_carrier_assignments WHERE batch_id = :bid AND released_effective_time IS NULL"
                ), {"bid": batch_b_id},
            ).scalars().all()
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=batch_b_id, assignment_ids=assignments_b)
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id)
            session.commit()
            root_batch_id = scaffold["batch"].id
            batch_c_id = session.execute(
                select(CropBatch.id).where(CropBatch.created_by_batch_derivation_event_id == split_event.id, CropBatch.code == f"OUT-C-{suffix}")
            ).scalar_one()

            case = open_case(session, tenant, farm, user, crop_batch_id=root_batch_id)
            session.commit()
            case_id = case.id

        detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
        assert set(detail["frozen_scope"]["crop_batch_ids"]) == {root_batch_id, batch_b_id, batch_c_id}
        assert detail["frozen_scope"]["harvested_produce_lot_ids"] == [produce_lot_id]
        assert detail["frozen_scope"]["finished_goods_lot_ids"] == [fg_lot_id]
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_open_batch_recall_multi_generation_split_then_merge(test_engine) -> None:
    """A -> split -> B, C. B, C -> merge -> D. Harvest+pack from D. A
    recall opened on A must include A, B, C, D in batch scope."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2)
            suffix = uuid.uuid4().hex[:6]
            split_event = batch_derivation_service.split_batch(
                session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id, batch_id=scaffold["batch"].id,
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
                session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id,
                source_batch_ids=[batch_b.id, batch_c.id], client_command_id=uuid.uuid4(), effective_time=now(),
                note=None, output_batch_code=f"MERGED-{suffix}",
            )
            session.commit()
            batch_d = session.execute(
                select(CropBatch).where(CropBatch.created_by_batch_derivation_event_id == merge_event.id)
            ).scalar_one()
            assignments_d = session.execute(
                __import__("sqlalchemy").text(
                    "SELECT id FROM batch_carrier_assignments WHERE batch_id = :bid AND released_effective_time IS NULL"
                ), {"bid": batch_d.id},
            ).scalars().all()
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=batch_d.id, assignment_ids=assignments_d)
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id)
            session.commit()
            root_batch_id, batch_b_id, batch_c_id, batch_d_id = scaffold["batch"].id, batch_b.id, batch_c.id, batch_d.id

            case = open_case(session, tenant, farm, user, crop_batch_id=root_batch_id)
            session.commit()
            case_id = case.id

        detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
        assert set(detail["frozen_scope"]["crop_batch_ids"]) == {root_batch_id, batch_b_id, batch_c_id, batch_d_id}
        assert detail["frozen_scope"]["finished_goods_lot_ids"] == [fg_lot_id]
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_batch_scope_stabilization_limit_exceeded_raises_and_persists_nothing(test_engine, monkeypatch) -> None:
    """`_MAX_SCOPE_STABILIZATION_ROUNDS` is a defensive corruption/
    pathological-race guard only, never a business limit -- the production
    value (500) is never changed here, only monkeypatched down to 0 for
    this test. A genuine one-generation split (batch A -> split -> B, C)
    is enough: with the bound at 0, the very first stabilization round
    (which every non-trivial descendant closure requires at least one of)
    immediately exceeds it, proving the guard fires -- and that no partial
    case or scope row is ever persisted when it does."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=2)
            session.commit()
            batch_id = scaffold["batch"].id
            suffix = uuid.uuid4().hex[:6]
            batch_derivation_service.split_batch(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch_id,
                client_command_id=uuid.uuid4(), effective_time=now(), note=None,
                outputs=[
                    {"output_batch_code": f"STAB-A-{suffix}", "source_assignment_ids": scaffold["assignment_ids"][:1]},
                    {"output_batch_code": f"STAB-B-{suffix}", "source_assignment_ids": scaffold["assignment_ids"][1:]},
                ],
            )
            session.commit()

            monkeypatch.setattr(recall_service, "_MAX_SCOPE_STABILIZATION_ROUNDS", 0)
            with pytest.raises(RecallScopeStabilizationError, match="did not stabilize"):
                recall_service.open_recall_case(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                    client_command_id=uuid.uuid4(), effective_time=now(), code=f"RC-STAB-{suffix}",
                    crop_batch_id=batch_id, harvested_produce_lot_id=None, finished_goods_lot_id=None,
                    reason_code="contamination_suspected", reason_text="stabilization bound test",
                )
            session.rollback()

        # No partial case or scope row was ever persisted.
        from sqlalchemy import text as _text
        with test_engine.connect() as conn:
            case_count = conn.execute(
                _text("SELECT count(*) FROM recall_cases WHERE tenant_id = :tid"), {"tid": tenant_id}
            ).scalar_one()
            scope_count = conn.execute(
                _text("SELECT count(*) FROM recall_scope_batches WHERE tenant_id = :tid"), {"tid": tenant_id}
            ).scalar_one()
        assert case_count == 0
        assert scope_count == 0
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_open_produce_lot_recall_scope_excludes_batch(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id)
            session.commit()

            case = open_case(session, tenant, farm, user, harvested_produce_lot_id=produce_lot_id)
            session.commit()
            case_id = case.id

        detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
        assert detail["frozen_scope"]["crop_batch_ids"] == []
        assert detail["frozen_scope"]["harvested_produce_lot_ids"] == [produce_lot_id]
        assert detail["frozen_scope"]["finished_goods_lot_ids"] == [fg_lot_id]
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_open_finished_goods_lot_recall_scope_excludes_mixed_upstream_co_inputs(test_engine) -> None:
    """An FG lot packed from TWO produce lots (mixed source): recall
    scoped to that FG lot must never promote either upstream produce lot
    or crop batch into scope."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            wf_scaffold = build_workflow_scaffold(session, tenant, user, farm)
            batch_a = sow_new_batch(session, tenant, user, farm, wf_scaffold, carrier_count=1)
            batch_b = sow_new_batch(session, tenant, user, farm, wf_scaffold, carrier_count=1)
            from decimal import Decimal
            _, lot_a = harvest_all(session, tenant, user, farm, batch_id=batch_a["batch"].id, assignment_ids=batch_a["assignment_ids"], weight_per_line=Decimal("3.000"))
            _, lot_b = harvest_all(session, tenant, user, farm, batch_id=batch_b["batch"].id, assignment_ids=batch_b["assignment_ids"], weight_per_line=Decimal("2.000"))
            fg_lot_id, _ = pack_multi(session, tenant, user, farm, produce_lot_ids_and_weights=[(lot_a, Decimal("3.000")), (lot_b, Decimal("2.000"))])
            session.commit()

            case = open_case(session, tenant, farm, user, finished_goods_lot_id=fg_lot_id)
            session.commit()
            case_id = case.id

        detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
        assert detail["frozen_scope"]["crop_batch_ids"] == []
        assert detail["frozen_scope"]["harvested_produce_lot_ids"] == []
        assert detail["frozen_scope"]["finished_goods_lot_ids"] == [fg_lot_id]
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_case_exact_replay_returns_original_no_duplicate_scope(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id)
            session.commit()
            batch_id = scaffold["batch"].id

            client_command_id = uuid.uuid4()
            eff = now()
            case1 = recall_service.open_recall_case(
                session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id, client_command_id=client_command_id,
                effective_time=eff, code="RC-REPLAY-01", crop_batch_id=batch_id, harvested_produce_lot_id=None,
                finished_goods_lot_id=None, reason_code="contamination_suspected", reason_text="test",
            )
            case2 = recall_service.open_recall_case(
                session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id, client_command_id=client_command_id,
                effective_time=eff, code="RC-REPLAY-01", crop_batch_id=batch_id, harvested_produce_lot_id=None,
                finished_goods_lot_id=None, reason_code="contamination_suspected", reason_text="test",
            )
            assert case1.id == case2.id
            session.commit()
            case_id = case1.id

        detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
        assert detail["frozen_scope"]["crop_batch_ids"] == [batch_id]
        assert detail["frozen_scope"]["finished_goods_lot_ids"] == [fg_lot_id]
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_case_command_reused_with_different_payload_conflicts(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            session.commit()
            batch_id = scaffold["batch"].id

            client_command_id = uuid.uuid4()
            recall_service.open_recall_case(
                session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id, client_command_id=client_command_id,
                effective_time=now(), code="RC-CONFLICT-01", crop_batch_id=batch_id, harvested_produce_lot_id=None,
                finished_goods_lot_id=None, reason_code="contamination_suspected", reason_text="original",
            )
            session.commit()
            with pytest.raises(RecallCaseCommandReusedWithDifferentPayloadError):
                recall_service.open_recall_case(
                    session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id, client_command_id=client_command_id,
                    effective_time=now(), code="RC-CONFLICT-01", crop_batch_id=batch_id, harvested_produce_lot_id=None,
                    finished_goods_lot_id=None, reason_code="contamination_suspected", reason_text="CHANGED",
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_case_code_uniqueness_case_insensitive_within_farm(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold_a = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1, suffix="dup-a")
            scaffold_b = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1, suffix="dup-b")
            session.commit()

            recall_service.open_recall_case(
                session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                effective_time=now(), code="RC-DUP-01", crop_batch_id=scaffold_a["batch"].id,
                harvested_produce_lot_id=None, finished_goods_lot_id=None,
                reason_code="contamination_suspected", reason_text="first",
            )
            session.commit()
            with pytest.raises(DuplicateRecallCaseCodeError):
                recall_service.open_recall_case(
                    session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                    effective_time=now(), code="rc-dup-01", crop_batch_id=scaffold_b["batch"].id,
                    harvested_produce_lot_id=None, finished_goods_lot_id=None,
                    reason_code="contamination_suspected", reason_text="second",
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_case_effective_time_cannot_be_future(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            session.commit()
            with pytest.raises(InvalidRecallCaseEffectiveTimeError):
                recall_service.open_recall_case(
                    session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                    effective_time=now() + timedelta(days=1), code="RC-FUTURE-01", crop_batch_id=scaffold["batch"].id,
                    harvested_produce_lot_id=None, finished_goods_lot_id=None,
                    reason_code="contamination_suspected", reason_text="future",
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_case_effective_time_cannot_precede_source_creation(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            session.commit()
            batch = session.get(CropBatch, scaffold["batch"].id)
            too_early = batch.created_effective_time - timedelta(days=1)
            with pytest.raises(InvalidRecallCaseEffectiveTimeError):
                recall_service.open_recall_case(
                    session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                    effective_time=too_early, code="RC-EARLY-01", crop_batch_id=scaffold["batch"].id,
                    harvested_produce_lot_id=None, finished_goods_lot_id=None,
                    reason_code="contamination_suspected", reason_text="too early",
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_case_tenant_farm_isolation(test_engine) -> None:
    tenant_id = None
    other_tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            session.commit()
            batch_id = scaffold["batch"].id
            case = open_case(session, tenant, farm, user, crop_batch_id=batch_id)
            session.commit()
            case_id = case.id

        with committed_connection(test_engine) as session2:
            other_tenant, other_user, other_farm = build_committed_tenant_farm(session2)
            session2.commit()
            other_tenant_id = other_tenant.id
            other_farm_id = other_farm.id
            other_user_id = other_user.id

        from app.services.errors import RecallCaseNotFoundError
        with pytest.raises(RecallCaseNotFoundError):
            recall_service.get_recall_case(tenant_id=other_tenant_id, farm_id=other_farm_id, recall_case_id=case_id, engine=test_engine)

        # A batch from a different tenant cannot be used as a recall source.
        with committed_connection(test_engine) as session3:
            with pytest.raises(CropBatchNotFoundError):
                recall_service.open_recall_case(
                    session3, tenant_id=other_tenant_id, farm_id=other_farm_id, actor_user_id=other_user_id,
                    client_command_id=uuid.uuid4(), effective_time=now(), code="RC-CROSS-01",
                    crop_batch_id=batch_id, harvested_produce_lot_id=None, finished_goods_lot_id=None,
                    reason_code="contamination_suspected", reason_text="cross tenant",
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)
        if other_tenant_id is not None:
            cleanup_recall_scenario(test_engine, other_tenant_id)


@pytest.mark.integration
def test_recall_case_already_dispatched_material_reported_not_recovered(test_engine) -> None:
    """Opening a recall after a full dispatch must report the existing
    dispatch as immutable history via live_state -- never claim the
    product was recovered."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=__import__("decimal").Decimal("5.000"), package_count=5)
            dispatch(session, tenant, user, farm, finished_goods_lot_id=fg_lot_id, weight=__import__("decimal").Decimal("5.000"), count=5)
            session.commit()

            case = open_case(session, tenant, farm, user, finished_goods_lot_id=fg_lot_id)
            session.commit()
            case_id = case.id

        detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
        dispatches = detail["live_state"]["dispatches"]
        assert len(dispatches) == 1
        assert dispatches[0]["finished_goods_lot_id"] == fg_lot_id
        fg_live = detail["live_state"]["finished_goods_lots"][0]
        assert fg_live["available_weight_kg"] == __import__("decimal").Decimal("0.000")
        # No recovery/notification vocabulary anywhere in the response shape.
        assert "recovered" not in str(detail).lower()
        assert "notified" not in str(detail).lower()
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)
