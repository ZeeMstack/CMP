"""HARVEST-OPS-001 BUILD SLICE 1: real two-connection concurrency proofs for
Leafy Harvest recording and correction, mirroring `test_production_
disposition_concurrency.py`'s established pattern exactly: committed setup
data via a dedicated connection, `threading.Barrier(2)`, two worker threads
each with their OWN `test_engine.connect()`/`Session`."""
import threading
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.batch_carrier_assignment import BatchCarrierAssignment
from app.models.carrier import Carrier
from app.models.harvest_source_line import HarvestSourceLine
from app.models.harvest_source_line_correction import HarvestSourceLineCorrection
from app.models.harvested_produce_lot import HarvestedProduceLot
from app.services import harvest_service, leafy_population_service, packing_service, production_disposition_service, transplant_service

pytestmark = pytest.mark.integration


def _build_committed_plate_scenario(test_engine, *, opening_count=5):
    from app.services import farm_service, membership_service, tenant_service, user_service
    from tests.test_leafy_production_transfer import (
        _leafy_setup, _nursery_plate_source_scenario, _production_plates, _record, _simple_allocation,
        _simple_destination, _simple_source,
    )

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"hv-race-{suffix}", name="Harvest Race Tenant")
    user = user_service.create_user(
        session, oidc_issuer="hv-race", oidc_subject=suffix, email=f"hv-race-{suffix}@example.com",
        display_name="Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s, aids = _nursery_plate_source_scenario(session, tenant, user, farm, suffix=suffix, opening_count=opening_count)
    table_ids = _leafy_setup(session, tenant, user, farm, suffix=suffix)
    plates, _spec = _production_plates(session, tenant, user, farm, suffix=suffix, count=1)
    result = _record(
        session, tenant, farm, user, s["batch"],
        [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=opening_count)],
        [_simple_allocation(aids[0], plates[0].id, opening_count)],
        effective_time=s["transfer_ready_time"] + timedelta(hours=1),
    )
    root_id = result.destination_lines[0].destination_batch_carrier_assignment_id
    session.commit()

    out = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "batch_id": s["batch"].id,
        "root_id": root_id, "et": s["transfer_ready_time"] + timedelta(hours=2),
    }
    session.close()
    conn.close()
    return out


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    from tests._traceability_scenario import cleanup_traceability_scenario

    cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_harvests_racing_below_zero(test_engine, attempt) -> None:
    """living = 5. Operator A harvests 4; Operator B simultaneously
    harvests 4. Only one may succeed -- the other must be rejected, never
    both, and the final authoritative population must never go negative."""
    scenario = _build_committed_plate_scenario(test_engine, opening_count=5)
    try:
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def worker(name: str) -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                event = harvest_service.record_leafy_harvest(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                    effective_time=scenario["et"], produce_lot_code=f"HL-{uuid.uuid4().hex[:8]}", note=None,
                    source_lines=[
                        {
                            "batch_carrier_assignment_id": scenario["root_id"], "whole_unit_count": 4,
                            "harvested_weight_kg": Decimal("1.600"), "note": None,
                        }
                    ],
                )
                results[name] = ("ok", event.id)
            except Exception as exc:  # pragma: no cover -- includes expected balance rejection
                results[name] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=worker, args=("a",))
        t_b = threading.Thread(target=worker, args=("b",))
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            living = leafy_population_service.get_current_living_population(
                verify_session, root_batch_carrier_assignment_id=scenario["root_id"]
            )
            assert living == 1
            assert living >= 0
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_corrections_of_same_predecessor_race(test_engine, attempt) -> None:
    """Two concurrent corrections targeting the exact same predecessor (the
    original HarvestSourceLine, never yet corrected) -- must never both
    succeed; exactly one direct successor must ever exist for it, no
    chain branch."""
    scenario = _build_committed_plate_scenario(test_engine, opening_count=180)
    conn0 = test_engine.connect()
    session0 = Session(bind=conn0)
    event = harvest_service.record_leafy_harvest(
        session0, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=scenario["et"],
        produce_lot_code=f"HL-{uuid.uuid4().hex[:8]}", note=None,
        source_lines=[
            {
                "batch_carrier_assignment_id": scenario["root_id"], "whole_unit_count": 5,
                "harvested_weight_kg": Decimal("2.500"), "note": None,
            }
        ],
    )
    line_id = session0.execute(
        select(HarvestSourceLine.id).where(HarvestSourceLine.harvest_event_id == event.id)
    ).scalar_one()
    session0.commit()
    session0.close()
    conn0.close()

    try:
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def worker(name: str, count: int) -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                correction = harvest_service.correct_leafy_harvest(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    harvest_source_line_id=line_id, supersedes_correction_id=None, is_void=False,
                    corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=count,
                    reason_code="miscounted", note=f"race-{name}",
                )
                results[name] = ("ok", correction.id)
            except Exception as exc:  # pragma: no cover -- includes expected conflict rejection
                results[name] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=worker, args=("a", 4))
        t_b = threading.Thread(target=worker, args=("b", 3))
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["a"][0], results["b"][0]]
        assert outcomes.count("ok") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            successors = verify_session.execute(
                select(HarvestSourceLineCorrection.id).where(
                    HarvestSourceLineCorrection.harvest_source_line_id == line_id,
                    HarvestSourceLineCorrection.supersedes_correction_id.is_(None),
                )
            ).scalars().all()
            assert len(successors) == 1, "no chain branch: exactly one root correction must ever exist"
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])


# =====================================================================
# HARVEST-OPS-001 SLICE 1 CTO CORRECTION 1, Finding 3: the remaining four
# genuine threaded races. Both operations lock the SAME shared resource
# (CropBatch, then either the population-root BCA's owning lock chain, the
# HarvestedProduceLot row, or the Carrier row) via `with_for_update()`, so
# whichever thread acquires that lock first proceeds to commit durably
# before the other even re-reads state; the loser's own re-derived,
# post-lock read of the now-committed state is what correctly rejects it.
# Each test below states, in its own docstring, which side wins under
# which interleaving.
# =====================================================================


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_harvest_vs_plant_loss_racing_below_zero(test_engine, attempt) -> None:
    """living = 8. Operator A harvests 5 (Leafy Harvest); Operator B
    simultaneously records a Plant Loss of 5 on the SAME population root.
    Both lock the owning CropBatch first (shared lock-order convention), so
    whichever commits first durably consumes 5 of the 8; the other's own
    chronological-balance re-check (5 + 5 > 8) then correctly rejects it.
    Exactly one of the two may ever succeed; the combined living population
    must never go negative."""
    scenario = _build_committed_plate_scenario(test_engine, opening_count=8)
    try:
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def harvest_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                event = harvest_service.record_leafy_harvest(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                    effective_time=scenario["et"], produce_lot_code=f"HL-{uuid.uuid4().hex[:8]}", note=None,
                    source_lines=[
                        {
                            "batch_carrier_assignment_id": scenario["root_id"], "whole_unit_count": 5,
                            "harvested_weight_kg": Decimal("2.500"), "note": None,
                        }
                    ],
                )
                results["harvest"] = ("ok", event.id)
            except Exception as exc:  # pragma: no cover -- includes expected balance rejection
                results["harvest"] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        def plant_loss_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                command = production_disposition_service.record_disposition(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    batch_carrier_assignment_id=scenario["root_id"], plant_loss_count=5,
                    reason_code="pest_damage", effective_time=scenario["et"], note=None,
                )
                results["plant_loss"] = ("ok", command.id)
            except Exception as exc:  # pragma: no cover -- includes expected balance rejection
                results["plant_loss"] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=harvest_worker)
        t_b = threading.Thread(target=plant_loss_worker)
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["harvest"][0], results["plant_loss"][0]]
        assert outcomes.count("ok") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            living = leafy_population_service.get_current_living_population(
                verify_session, root_batch_carrier_assignment_id=scenario["root_id"]
            )
            assert living == 3
            assert living >= 0
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_harvest_vs_plant_loss_correction_racing_below_zero(test_engine, attempt) -> None:
    """living opens at 10. A Plant Loss of 2 is recorded and committed FIRST
    (living = 8). Operator A then harvests 5 at t0+1h; Operator B
    simultaneously corrects the Plant Loss, replacing 2 with 7 (an
    additional 5 units of reduction) at t0+2h. Both lock the shared
    CropBatch first. Whichever commits first durably claims the last 5
    units of headroom; the other's chronological-balance re-check (which
    walks the FULL timeline, including the other side's now-committed
    event, in effective_time order) then correctly rejects it -- even
    though each side's own effective_time in isolation looks fine, the
    combined timeline does not. Exactly one of the two may ever succeed."""
    scenario = _build_committed_plate_scenario(test_engine, opening_count=10)
    conn0 = test_engine.connect()
    session0 = Session(bind=conn0)
    plant_loss_command = production_disposition_service.record_disposition(
        session0, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), batch_carrier_assignment_id=scenario["root_id"], plant_loss_count=2,
        reason_code="pest_damage", effective_time=scenario["et"], note=None,
    )
    from app.models.production_disposition_event import ProductionDispositionEvent

    target_event_id = session0.execute(
        select(ProductionDispositionEvent.id).where(ProductionDispositionEvent.command_id == plant_loss_command.id)
    ).scalar_one()
    session0.commit()
    session0.close()
    conn0.close()

    try:
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def harvest_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                event = harvest_service.record_leafy_harvest(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(),
                    effective_time=scenario["et"] + timedelta(hours=1), produce_lot_code=f"HL-{uuid.uuid4().hex[:8]}",
                    note=None,
                    source_lines=[
                        {
                            "batch_carrier_assignment_id": scenario["root_id"], "whole_unit_count": 5,
                            "harvested_weight_kg": Decimal("2.500"), "note": None,
                        }
                    ],
                )
                results["harvest"] = ("ok", event.id)
            except Exception as exc:  # pragma: no cover -- includes expected balance rejection
                results["harvest"] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        def correction_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                command = production_disposition_service.correct_disposition(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), target_event_id=target_event_id,
                    corrected={
                        "plant_loss_count": 7, "reason_code": "pest_damage", "note": "race",
                        "effective_time": scenario["et"] + timedelta(hours=2),
                    },
                )
                results["correction"] = ("ok", command.id)
            except Exception as exc:  # pragma: no cover -- includes expected balance rejection
                results["correction"] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=harvest_worker)
        t_b = threading.Thread(target=correction_worker)
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["harvest"][0], results["correction"][0]]
        assert outcomes.count("ok") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            living = leafy_population_service.get_current_living_population(
                verify_session, root_batch_carrier_assignment_id=scenario["root_id"]
            )
            assert living >= 0
            if results["harvest"][0] == "ok":
                assert living == 3  # 10 - 2 (original plant loss, correction rejected) - 5 (harvest)
            else:
                assert living == 3  # 10 - 7 (replacement plant loss, harvest rejected)
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_harvest_correction_vs_packing_consumption_racing_below_zero(test_engine, attempt) -> None:
    """A Leafy Harvest of 10 units / 5.000kg is recorded and committed
    FIRST, opening a HarvestedProduceLot with an available balance of
    10 units / 5.000kg. Operator A then corrects that harvest down to 5
    units / 2.500kg (freeing 2.5kg / 5 units of lot balance back);
    Operator B simultaneously packs 8 units / 4.000kg out of the SAME lot.
    Both lock the lot row first (shared lock-order convention). Neither
    side may independently assume the other's balance: if the correction
    commits first, the lot's available balance drops to 2.5kg / 5 units,
    which cannot cover Packing's 4.000kg / 8-unit request
    (InsufficientProduceLotBalanceError); if Packing commits first, the
    balance drops to 1.000kg / 2 units, which cannot absorb the
    correction's -2.5kg / -5-unit adjustment without going negative
    (HarvestLedgerBalanceError). Exactly one of the two may ever succeed;
    the lot's final balance must never go negative."""
    scenario = _build_committed_plate_scenario(test_engine, opening_count=15)
    conn0 = test_engine.connect()
    session0 = Session(bind=conn0)
    event = harvest_service.record_leafy_harvest(
        session0, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        batch_id=scenario["batch_id"], client_command_id=uuid.uuid4(), effective_time=scenario["et"],
        produce_lot_code=f"HL-{uuid.uuid4().hex[:8]}", note=None,
        source_lines=[
            {
                "batch_carrier_assignment_id": scenario["root_id"], "whole_unit_count": 10,
                "harvested_weight_kg": Decimal("5.000"), "note": None,
            }
        ],
    )
    line_id = session0.execute(
        select(HarvestSourceLine.id).where(HarvestSourceLine.harvest_event_id == event.id)
    ).scalar_one()
    lot_id = session0.execute(
        select(HarvestedProduceLot.id).where(HarvestedProduceLot.harvest_event_id == event.id)
    ).scalar_one()
    session0.commit()
    session0.close()
    conn0.close()

    try:
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def correction_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                correction = harvest_service.correct_leafy_harvest(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    harvest_source_line_id=line_id, supersedes_correction_id=None, is_void=False,
                    corrected_harvested_weight_kg=Decimal("2.500"), corrected_whole_unit_count=5,
                    reason_code="miscounted", note="race",
                )
                results["correction"] = ("ok", correction.id)
            except Exception as exc:  # pragma: no cover -- includes expected balance rejection
                results["correction"] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        def packing_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                packing_event = packing_service.record_packing(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    effective_time=scenario["et"] + timedelta(hours=1), finished_goods_lot_code=f"FG-{uuid.uuid4().hex[:8]}",
                    package_count=1, packed_output_weight_kg=Decimal("4.000"), process_loss_weight_kg=Decimal("0.000"),
                    rejected_weight_kg=Decimal("0.000"), note=None,
                    input_lines=[
                        {
                            "harvested_produce_lot_id": lot_id, "consumed_weight_kg": Decimal("4.000"),
                            "consumed_whole_unit_count": 8, "note": None,
                        }
                    ],
                )
                results["packing"] = ("ok", packing_event.id)
            except Exception as exc:  # pragma: no cover -- includes expected balance rejection
                results["packing"] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=correction_worker)
        t_b = threading.Thread(target=packing_worker)
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["correction"][0], results["packing"][0]]
        assert outcomes.count("ok") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            from sqlalchemy import func

            from app.models.produce_lot_ledger_entry import ProduceLotLedgerEntry

            weight, count = verify_session.execute(
                select(
                    func.coalesce(func.sum(ProduceLotLedgerEntry.weight_delta_kg), 0),
                    func.coalesce(func.sum(ProduceLotLedgerEntry.whole_unit_count_delta), 0),
                ).where(ProduceLotLedgerEntry.produce_lot_id == lot_id)
            ).one()
            assert weight >= 0 and count >= 0
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])


def _build_committed_carrier_reuse_scenario(test_engine):
    """Two independent nursery-plate sources on the SAME tenant/farm, one
    shared production plate Carrier X. Batch 1's source is transplanted onto
    Carrier X and immediately, fully, Leafy-Harvested -- zero-releasing that
    generation's BCA (Carrier X now has no active assignment). Batch 2's
    source is left un-transplanted, ready for the reuse race."""
    from app.services import farm_service, membership_service, tenant_service, user_service
    from tests.test_leafy_production_transfer import _nursery_plate_source_scenario, _production_plates

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]

    tenant = tenant_service.create_tenant(session, code=f"hv-cr-{suffix}", name="Harvest Carrier Reuse Tenant")
    user = user_service.create_user(
        session, oidc_issuer="hv-cr", oidc_subject=suffix, email=f"hv-cr-{suffix}@example.com", display_name="Race User",
    )
    membership_service.add_membership(
        session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
    )
    farm = farm_service.create_farm(
        session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Race Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    plates, _spec = _production_plates(session, tenant, user, farm, suffix=suffix, count=1)
    carrier_id = plates[0].id

    s1, aids1 = _nursery_plate_source_scenario(session, tenant, user, farm, suffix=f"{suffix}a", opening_count=5)
    s2, aids2 = _nursery_plate_source_scenario(session, tenant, user, farm, suffix=f"{suffix}b", opening_count=10)

    opening_event = transplant_service.record_transplant(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s1["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=s1["transfer_ready_time"] + timedelta(hours=1), note=None,
        source_lines=[
            {
                "source_assignment_id": aids1[0], "transplant_damage_count": 0, "qc_rejection_count": 0,
                "sample_count": 0, "other_loss_count": 0, "other_loss_note": None, "note": None,
            }
        ],
        destination_lines=[{"destination_carrier_id": carrier_id, "assigned_plant_count": 5, "note": None}],
        allocations=[{"source_assignment_id": aids1[0], "destination_carrier_id": carrier_id, "allocated_plant_count": 5}],
    )
    root1_id = session.execute(
        select(BatchCarrierAssignment.id).where(BatchCarrierAssignment.opening_transplant_event_id == opening_event.id)
    ).scalar_one()

    harvest_et = s1["transfer_ready_time"] + timedelta(hours=2)
    harvest_event = harvest_service.record_leafy_harvest(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s1["batch_id"],
        client_command_id=uuid.uuid4(), effective_time=harvest_et, produce_lot_code=f"HL-{uuid.uuid4().hex[:8]}", note=None,
        source_lines=[{"batch_carrier_assignment_id": root1_id, "whole_unit_count": 5, "harvested_weight_kg": Decimal("2.500"), "note": None}],
    )
    line_id = session.execute(
        select(HarvestSourceLine.id).where(HarvestSourceLine.harvest_event_id == harvest_event.id)
    ).scalar_one()
    session.commit()

    root1 = session.execute(select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == root1_id)).scalar_one()
    assert root1.released_effective_time is not None, "sanity: Carrier X's generation must be fully released"

    out = {
        "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id,
        "carrier_id": carrier_id, "root1_id": root1_id, "line_id": line_id,
        "batch2_id": s2["batch_id"], "source2_assignment_id": aids2[0],
        "reuse_et": s2["transfer_ready_time"] + timedelta(hours=1),
    }
    session.close()
    conn.close()
    return out


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_harvest_restoration_correction_vs_carrier_reuse(test_engine, attempt) -> None:
    """Carrier X's only generation (root1) was fully Leafy-Harvest-released
    (zero living population). Operator A corrects that harvest down from
    5 to 3 units, which -- since the lineage is currently exhausted --
    attempts to RESTORE a new BCA generation on Carrier X. Simultaneously,
    Operator B performs a completely unrelated, legitimate new Transplant
    reusing the now-free Carrier X as a destination for a different Batch.
    Both lock the SAME Carrier row first (shared lock-order convention).
    If the correction commits first, it creates the restoration and the
    Carrier's `latest_batch_carrier_assignment_id` pointer moves to it;
    the reuse Transplant's own re-derived active-assignment check then
    correctly rejects with DestinationCarrierAlreadyAssignedError. If the
    reuse Transplant commits first, the Carrier's pointer moves to its new
    destination BCA; the correction's own re-derived Carrier-pointer check
    then correctly rejects with HarvestCarrierReusedError. Illegal in
    either order: old biology restored AFTER the Carrier has already been
    claimed by the new Transplant, two simultaneously-active assignments on
    Carrier X, or `root1` ever being reactivated."""
    from app.services.errors import DestinationCarrierAlreadyAssignedError, HarvestCarrierReusedError

    scenario = _build_committed_carrier_reuse_scenario(test_engine)
    try:
        barrier = threading.Barrier(2)
        results: dict[str, object] = {}

        def correction_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                correction = harvest_service.correct_leafy_harvest(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                    harvest_source_line_id=scenario["line_id"], supersedes_correction_id=None, is_void=False,
                    corrected_harvested_weight_kg=Decimal("1.500"), corrected_whole_unit_count=3,
                    reason_code="miscounted", note="race",
                )
                results["correction"] = ("ok", correction.id)
            except HarvestCarrierReusedError as exc:
                results["correction"] = ("reused", repr(exc))
            except Exception as exc:  # pragma: no cover
                results["correction"] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        def reuse_transplant_worker() -> None:
            conn = test_engine.connect()
            session = Session(bind=conn)
            try:
                barrier.wait(timeout=10)
                event = transplant_service.record_transplant(
                    session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                    actor_user_id=scenario["user_id"], batch_id=scenario["batch2_id"], client_command_id=uuid.uuid4(),
                    effective_time=scenario["reuse_et"], note=None,
                    source_lines=[
                        {
                            "source_assignment_id": scenario["source2_assignment_id"], "transplant_damage_count": 0,
                            "qc_rejection_count": 0, "sample_count": 0, "other_loss_count": 0, "other_loss_note": None,
                            "note": None,
                        }
                    ],
                    destination_lines=[{"destination_carrier_id": scenario["carrier_id"], "assigned_plant_count": 3, "note": None}],
                    allocations=[
                        {
                            "source_assignment_id": scenario["source2_assignment_id"],
                            "destination_carrier_id": scenario["carrier_id"], "allocated_plant_count": 3,
                        }
                    ],
                )
                results["reuse"] = ("ok", event.id)
            except DestinationCarrierAlreadyAssignedError as exc:
                results["reuse"] = ("claimed", repr(exc))
            except Exception as exc:  # pragma: no cover
                results["reuse"] = ("error", repr(exc))
            finally:
                session.close()
                conn.close()

        t_a = threading.Thread(target=correction_worker)
        t_b = threading.Thread(target=reuse_transplant_worker)
        t_a.start()
        t_b.start()
        t_a.join(timeout=20)
        t_b.join(timeout=20)

        assert not t_a.is_alive() and not t_b.is_alive(), "no deadlock: both threads must complete"
        outcomes = [results["correction"][0], results["reuse"][0]]
        assert outcomes.count("ok") == 1, results

        verify_conn = test_engine.connect()
        verify_session = Session(bind=verify_conn)
        try:
            pointer = verify_session.execute(
                select(Carrier.latest_batch_carrier_assignment_id).where(Carrier.id == scenario["carrier_id"])
            ).scalar_one()

            active_on_carrier = verify_session.execute(
                select(BatchCarrierAssignment.id).where(
                    BatchCarrierAssignment.carrier_id == scenario["carrier_id"],
                    BatchCarrierAssignment.released_effective_time.is_(None),
                )
            ).scalars().all()
            assert len(active_on_carrier) == 1, "no dual active assignment on Carrier X"

            root1_after = verify_session.execute(
                select(BatchCarrierAssignment).where(BatchCarrierAssignment.id == scenario["root1_id"])
            ).scalar_one()
            assert root1_after.released_effective_time is not None, "root1 must never be reactivated"

            if results["correction"][0] == "ok":
                restored = verify_session.execute(
                    select(BatchCarrierAssignment).where(
                        BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == scenario["root1_id"]
                    )
                ).scalar_one()
                assert pointer == restored.id, "correction won but Carrier pointer disagrees"
                assert results["reuse"][0] in ("claimed", "error"), "reuse Transplant must not have won too"
            else:
                assert results["reuse"][0] == "ok", results
                reused = verify_session.execute(
                    select(BatchCarrierAssignment).where(
                        BatchCarrierAssignment.carrier_id == scenario["carrier_id"],
                        BatchCarrierAssignment.batch_id == scenario["batch2_id"],
                    )
                ).scalar_one()
                assert pointer == reused.id, "reuse Transplant won but Carrier pointer disagrees"
                no_restoration = verify_session.execute(
                    select(BatchCarrierAssignment.id).where(
                        BatchCarrierAssignment.restored_from_batch_carrier_assignment_id == scenario["root1_id"]
                    )
                ).scalars().all()
                assert no_restoration == [], "old biology must never be restored once the Carrier is claimed"
        finally:
            verify_session.close()
            verify_conn.close()
    finally:
        _cleanup(test_engine, scenario["tenant_id"])
