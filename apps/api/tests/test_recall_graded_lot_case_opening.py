"""POSTHARVEST-OPS-001D: recall-case opening tests for `GradedProduceLot`
as a fourth typed source -- direct graded-lot-source scope-freeze
correctness (mandatory sibling isolation, no upstream promotion), upstream
(crop-batch/harvested-produce-lot source) freeze now including EXISTING
`GradedProduceLot` descendants, not-found/cross-tenant/cross-farm
rejection, read-model exposure, idempotency, and continued 001C grading
containment after an upstream freeze."""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services import farm_service, recall_service
from app.services.errors import (
    GradedProduceLotNotFoundError,
    RecallCaseCommandReusedWithDifferentPayloadError,
    RecallContainmentOpenError,
)
from tests._recall_graded_lot_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    build_grading_scaffold,
    cleanup_recall_graded_lot_scenario,
    close_case,
    committed_connection,
    grade_lot_two_outputs,
    harvest_all,
    now,
    open_case,
    pack_lot,
)
from app.services import grading_service


def _crop_id_for_lot(session, produce_lot_id) -> uuid.UUID:
    return session.execute(
        text("SELECT crop_id FROM harvested_produce_lots WHERE id = :id"), {"id": produce_lot_id}
    ).scalar_one()


def _build_graded_pair(session, tenant, user, farm, *, weight_per_line=Decimal("10.000")):
    """Batch -> HPL-1 -> one GradingEvent -> GPL-A, GPL-B. Returns
    (batch_id, produce_lot_id, grading_scaffold, gpl_a_id, gpl_b_id)."""
    scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
    _, produce_lot_id = harvest_all(
        session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"],
        weight_per_line=weight_per_line,
    )
    session.commit()
    crop_id = _crop_id_for_lot(session, produce_lot_id)
    grading_scaffold = build_grading_scaffold(session, tenant, user, farm, crop_id=crop_id)
    session.commit()
    _, gpl_a_id, gpl_b_id = grade_lot_two_outputs(
        session, tenant, user, farm, source_produce_lot_id=produce_lot_id,
        packing_hall_location_id=grading_scaffold["packing_hall_location_id"],
        grade_a_version_id=grading_scaffold["grade_a_version_id"],
        grade_b_version_id=grading_scaffold["grade_b_version_id"],
    )
    session.commit()
    return scaffold["batch"].id, produce_lot_id, grading_scaffold, gpl_a_id, gpl_b_id


@pytest.mark.integration
def test_open_graded_produce_lot_recall_isolates_sibling_and_does_not_promote_upstream(test_engine) -> None:
    """The mandatory sibling-isolation scenario: one GradingEvent produces
    GPL-A and GPL-B; a recall scoped specifically to GPL-A must scope only
    GPL-A, never GPL-B, and must never promote the source HarvestedProduceLot
    or CropBatch into their own scope tables."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            batch_id, produce_lot_id, _, gpl_a_id, gpl_b_id = _build_graded_pair(session, tenant, user, farm)

            case = open_case(session, tenant, farm, user, graded_produce_lot_id=gpl_a_id)
            session.commit()
            case_id = case.id

        detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
        assert detail["graded_produce_lot_id"] == gpl_a_id
        assert detail["crop_batch_id"] is None
        assert detail["harvested_produce_lot_id"] is None
        assert detail["finished_goods_lot_id"] is None
        assert detail["frozen_scope"]["graded_produce_lot_ids"] == [gpl_a_id]
        assert detail["frozen_scope"]["crop_batch_ids"] == []
        assert detail["frozen_scope"]["harvested_produce_lot_ids"] == []
        assert detail["frozen_scope"]["finished_goods_lot_ids"] == []

        with test_engine.connect() as conn:
            gpl_b_scope_rows = conn.execute(
                text("SELECT count(*) FROM recall_scope_graded_produce_lots WHERE graded_produce_lot_id = :id"),
                {"id": gpl_b_id},
            ).scalar_one()
            batch_scope_rows = conn.execute(
                text("SELECT count(*) FROM recall_scope_batches WHERE crop_batch_id = :id"), {"id": batch_id}
            ).scalar_one()
            hpl_scope_rows = conn.execute(
                text("SELECT count(*) FROM recall_scope_produce_lots WHERE harvested_produce_lot_id = :id"),
                {"id": produce_lot_id},
            ).scalar_one()
        assert gpl_b_scope_rows == 0, "sibling GPL-B must never be recalled merely because it shares the GradingEvent"
        assert batch_scope_rows == 0, "CropBatch must never be promoted by a graded-produce-lot-source recall"
        assert hpl_scope_rows == 0, "HarvestedProduceLot must never be promoted by a graded-produce-lot-source recall"

        with committed_connection(test_engine) as session2:
            assert recall_service.has_open_graded_produce_lot_recall(
                session2, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_id=gpl_a_id
            ) is True
            assert recall_service.has_open_graded_produce_lot_recall(
                session2, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_id=gpl_b_id
            ) is False
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_has_open_graded_produce_lot_recall_predicate_lifecycle(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
            case = open_case(session, tenant, farm, user, graded_produce_lot_id=gpl_a_id)
            session.commit()
            case_id = case.id
            assert recall_service.has_open_graded_produce_lot_recall(
                session, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_id=gpl_a_id
            ) is True

            close_case(session, tenant, farm, user, recall_case_id=case_id)
            session.commit()
            assert recall_service.has_open_graded_produce_lot_recall(
                session, tenant_id=tenant_id, farm_id=farm_id, graded_produce_lot_id=gpl_a_id
            ) is False
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_second_independent_case_on_same_graded_lot_allowed(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
            case1 = open_case(session, tenant, farm, user, graded_produce_lot_id=gpl_a_id, suffix="one")
            case2 = open_case(session, tenant, farm, user, graded_produce_lot_id=gpl_a_id, suffix="two")
            session.commit()
            assert case1.id != case2.id
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_unknown_graded_produce_lot_rejected(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            session.commit()
            with pytest.raises(GradedProduceLotNotFoundError):
                recall_service.open_recall_case(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                    client_command_id=uuid.uuid4(), effective_time=now(), code="RC-UNKNOWN-GPL",
                    crop_batch_id=None, harvested_produce_lot_id=None, graded_produce_lot_id=uuid.uuid4(),
                    finished_goods_lot_id=None, reason_code="contamination_suspected", reason_text="unknown lot",
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_cross_tenant_graded_produce_lot_rejected(test_engine) -> None:
    tenant_id = None
    other_tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)

        with committed_connection(test_engine) as session2:
            other_tenant, other_user, other_farm = build_committed_tenant_farm(session2)
            other_tenant_id = other_tenant.id
            session2.commit()
            with pytest.raises(GradedProduceLotNotFoundError):
                recall_service.open_recall_case(
                    session2, tenant_id=other_tenant.id, farm_id=other_farm.id, actor_user_id=other_user.id,
                    client_command_id=uuid.uuid4(), effective_time=now(), code="RC-CROSS-TENANT-GPL",
                    crop_batch_id=None, harvested_produce_lot_id=None, graded_produce_lot_id=gpl_a_id,
                    finished_goods_lot_id=None, reason_code="contamination_suspected", reason_text="cross tenant",
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)
        if other_tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, other_tenant_id)


@pytest.mark.integration
def test_cross_farm_graded_produce_lot_rejected(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)

            other_farm = farm_service.create_farm(
                session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-other-{uuid.uuid4().hex[:8]}",
                name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
            )
            session.commit()

            with pytest.raises(GradedProduceLotNotFoundError):
                recall_service.open_recall_case(
                    session, tenant_id=tenant.id, farm_id=other_farm.id, actor_user_id=user.id,
                    client_command_id=uuid.uuid4(), effective_time=now(), code="RC-CROSS-FARM-GPL",
                    crop_batch_id=None, harvested_produce_lot_id=None, graded_produce_lot_id=gpl_a_id,
                    finished_goods_lot_id=None, reason_code="contamination_suspected", reason_text="cross farm",
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


def _all_graded_lot_ids_for_hpl(session, produce_lot_id) -> list:
    """POSTHARVEST-OPS-001E: `pack_lot` can no longer consume a
    HarvestedProduceLot directly -- packing any of its "remaining" balance
    now transparently grades that remaining weight into its OWN additional
    GradedProduceLot first (see `_traceability_scenario.pack_lot`'s own
    docstring). A recall's frozen scope must include every one of an HPL's
    GPL descendants, not just the two explicitly named by the test's own
    setup -- so the expected set is read back from the database rather
    than hardcoded, staying correct regardless of how many GPLs a given
    scenario helper happens to create."""
    return sorted(
        session.execute(
            text(
                "SELECT gpl.id FROM graded_produce_lots gpl "
                "JOIN grading_events ge ON ge.id = gpl.grading_event_id "
                "WHERE ge.source_harvested_produce_lot_id = :hpl_id"
            ),
            {"hpl_id": produce_lot_id},
        ).scalars().all()
    )


@pytest.mark.integration
def test_batch_source_recall_freezes_existing_graded_lot_descendants(test_engine) -> None:
    """Batch B -> HPL-1 -> grading -> GPL-A, GPL-B; the remaining HPL-1
    balance is packed into an FG lot (which, post-001E, requires grading
    that remaining balance into its own additional GPL first). A recall
    opened on Batch B must freeze the batch, HPL-1, every one of HPL-1's
    GPL descendants, and the FG lot -- existing FinishedGoodsLot freeze
    behavior is unchanged."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            batch_id, produce_lot_id, _, gpl_a_id, gpl_b_id = _build_graded_pair(session, tenant, user, farm)
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()
            expected_gpl_ids = _all_graded_lot_ids_for_hpl(session, produce_lot_id)
            assert {gpl_a_id, gpl_b_id}.issubset(set(expected_gpl_ids))

            case = open_case(session, tenant, farm, user, crop_batch_id=batch_id)
            session.commit()
            case_id = case.id

        detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
        assert detail["frozen_scope"]["crop_batch_ids"] == [batch_id]
        assert detail["frozen_scope"]["harvested_produce_lot_ids"] == [produce_lot_id]
        assert sorted(detail["frozen_scope"]["graded_produce_lot_ids"]) == expected_gpl_ids
        assert detail["frozen_scope"]["finished_goods_lot_ids"] == [fg_lot_id]
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_harvested_produce_lot_source_recall_freezes_existing_graded_lot_descendants_without_promoting_batch(test_engine) -> None:
    """HPL-1 -> grading -> GPL-A, GPL-B; the remaining balance is packed
    into an FG lot (which, post-001E, requires grading that remaining
    balance into its own additional GPL first). A recall opened directly
    on HPL-1 must freeze HPL-1, every one of HPL-1's GPL descendants, and
    the FG lot -- but never promote the CropBatch."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            batch_id, produce_lot_id, _, gpl_a_id, gpl_b_id = _build_graded_pair(session, tenant, user, farm)
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()
            expected_gpl_ids = _all_graded_lot_ids_for_hpl(session, produce_lot_id)
            assert {gpl_a_id, gpl_b_id}.issubset(set(expected_gpl_ids))

            case = open_case(session, tenant, farm, user, harvested_produce_lot_id=produce_lot_id)
            session.commit()
            case_id = case.id

        detail = recall_service.get_recall_case(tenant_id=tenant_id, farm_id=farm_id, recall_case_id=case_id, engine=test_engine)
        assert detail["frozen_scope"]["crop_batch_ids"] == []
        assert detail["frozen_scope"]["harvested_produce_lot_ids"] == [produce_lot_id]
        assert sorted(detail["frozen_scope"]["graded_produce_lot_ids"]) == expected_gpl_ids
        assert detail["frozen_scope"]["finished_goods_lot_ids"] == [fg_lot_id]
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_grading_from_recalled_batch_remains_blocked_after_upstream_freeze(test_engine) -> None:
    """Proves the frozen graded-lot scope never needs dynamic later
    mutation: 001C's existing Grading containment gate (source-batch check)
    continues to reject a NEW GradingEvent against the recalled batch's
    produce lot even after an upstream batch-source recall has already
    frozen its existing graded descendants."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(
                session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"],
                weight_per_line=Decimal("10.000"),
            )
            session.commit()
            batch_id = scaffold["batch"].id
            crop_id = _crop_id_for_lot(session, produce_lot_id)
            grading_scaffold = build_grading_scaffold(session, tenant, user, farm, crop_id=crop_id)
            session.commit()
            grading_service.record_grading(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
                source_harvested_produce_lot_id=produce_lot_id,
                processing_hall_location_id=grading_scaffold["packing_hall_location_id"], effective_time=now(),
                note=None, input_presented_weight_kg=Decimal("3.000"), input_presented_whole_unit_count=None,
                rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
                loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
                sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
                remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=None,
                outputs=[
                    {
                        "grade_definition_version_id": grading_scaffold["grade_a_version_id"], "code": "GPL-FIRST",
                        "output_weight_kg": Decimal("3.000"), "output_whole_unit_count": None,
                    },
                ],
            )
            session.commit()

            open_case(session, tenant, farm, user, crop_batch_id=batch_id)
            session.commit()

            with pytest.raises(RecallContainmentOpenError):
                grading_service.record_grading(
                    session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                    client_command_id=uuid.uuid4(), source_harvested_produce_lot_id=produce_lot_id,
                    processing_hall_location_id=grading_scaffold["packing_hall_location_id"], effective_time=now(),
                    note=None, input_presented_weight_kg=Decimal("2.000"), input_presented_whole_unit_count=None,
                    rejected_weight_kg=Decimal("0"), rejected_whole_unit_count=None,
                    loss_weight_kg=Decimal("0"), loss_whole_unit_count=None,
                    sample_weight_kg=Decimal("0"), sample_whole_unit_count=None,
                    remainder_weight_kg=Decimal("0"), remainder_whole_unit_count=None,
                    outputs=[
                        {
                            "grade_definition_version_id": grading_scaffold["grade_b_version_id"], "code": "GPL-SECOND",
                            "output_weight_kg": Decimal("2.000"), "output_whole_unit_count": None,
                        },
                    ],
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_graded_produce_lot_recall_exact_replay_and_conflicting_payload(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            _, _, _, gpl_a_id, gpl_b_id = _build_graded_pair(session, tenant, user, farm)

            client_command_id = uuid.uuid4()
            eff = now()
            case1 = recall_service.open_recall_case(
                session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id,
                client_command_id=client_command_id, effective_time=eff, code="RC-GPL-REPLAY-01",
                crop_batch_id=None, harvested_produce_lot_id=None, graded_produce_lot_id=gpl_a_id,
                finished_goods_lot_id=None, reason_code="contamination_suspected", reason_text="test",
            )
            case2 = recall_service.open_recall_case(
                session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id,
                client_command_id=client_command_id, effective_time=eff, code="RC-GPL-REPLAY-01",
                crop_batch_id=None, harvested_produce_lot_id=None, graded_produce_lot_id=gpl_a_id,
                finished_goods_lot_id=None, reason_code="contamination_suspected", reason_text="test",
            )
            assert case1.id == case2.id
            session.commit()
            case_id = case1.id

            scope_count = session.execute(
                text("SELECT count(*) FROM recall_scope_graded_produce_lots WHERE recall_case_id = :cid"),
                {"cid": case_id},
            ).scalar_one()
            audit_count = session.execute(
                text(
                    "SELECT count(*) FROM audit_events WHERE action = 'recall_case.opened' AND entity_id = :cid"
                ),
                {"cid": case_id},
            ).scalar_one()
            assert scope_count == 1
            assert audit_count == 1

            with pytest.raises(RecallCaseCommandReusedWithDifferentPayloadError):
                recall_service.open_recall_case(
                    session, tenant_id=tenant.id, farm_id=farm_id, actor_user_id=user.id,
                    client_command_id=client_command_id, effective_time=eff, code="RC-GPL-REPLAY-01",
                    crop_batch_id=None, harvested_produce_lot_id=None, graded_produce_lot_id=gpl_b_id,
                    finished_goods_lot_id=None, reason_code="contamination_suspected", reason_text="test",
                )
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_recall_case_list_and_summary_expose_graded_produce_lot_source(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
            case = open_case(session, tenant, farm, user, graded_produce_lot_id=gpl_a_id)
            session.commit()
            case_id = case.id

            rows = recall_service.list_recall_cases(session, tenant_id=tenant_id, farm_id=farm_id)
        matching = [r for r in rows if r["recall_case_id"] == case_id]
        assert len(matching) == 1
        assert matching[0]["graded_produce_lot_id"] == gpl_a_id
        assert matching[0]["crop_batch_id"] is None
        assert matching[0]["harvested_produce_lot_id"] is None
        assert matching[0]["finished_goods_lot_id"] is None
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)
