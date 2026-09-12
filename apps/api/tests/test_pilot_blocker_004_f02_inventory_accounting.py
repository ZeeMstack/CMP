"""PILOT-BLOCKER-004 F02: focused PostgreSQL-backed integrity proofs for the
cohort accounting reconciliation fix.

Canonical identity (frozen, `app/services/inventory_cohort_accounting_
service.py`): `existence = not_put_away + in_bins + outstanding_issued`.
Reservations/Quality/expiry never reduce existence -- only Consumption and
Scrap do. Before this fix, several WRITE validators (`record_putaway`,
`record_scrap`'s `not_put_away` source, the two Quality partial-bucket
validators, the generic Adjustment/Reversal existence floor) and the
`enforce_inventory_storage_movement_insert_integrity_v3` DB trigger computed
not-put-away/floor as `existence - custody_total` alone, omitting the
issued-settlement term (`D`) -- correct only until the first Consumption/
Scrap against Issued material, after which it under-counts (over-restricts)
relative to the already-correct READ model
(`inventory_storage_service.get_cohort_not_put_away`).

Proves: the confirmed reproduction sequence, four scrap-source
reconciliations, the negative-adjustment/reversal floor, a Quality partial
split from Not-put-away after consumption, the DB trigger itself
(independent of the service-layer check), idempotent replay, and one
focused concurrency race."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models.inventory_storage_movement import InventoryStorageMovement
from app.services import (
    inventory_availability_service,
    inventory_cohort_accounting_service,
    inventory_existence_ledger_service,
    inventory_material_event_service,
    inventory_quality_service,
    inventory_storage_service,
)
from app.services.errors import (
    ExistenceBelowCustodyError,
    InsufficientNotPutAwayQuantityError,
    InventoryStorageCommandReusedWithDifferentPayloadError,
)
from tests._store_custody_scenario import build_store_bin, receive_cohort
from tests._store_reservation_scenario import build_scenario, receive_and_putaway


def _now():
    return datetime.now(timezone.utc)


def _issue(db, scenario, *, cohort_id, bin_id, quantity: Decimal):
    from app.services import inventory_issue_service
    from app.services.inventory_issue_service import IssueLineInput

    issue = inventory_issue_service.record_issue(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Ops use", effective_time=_now(),
        lines=[
            IssueLineInput(
                inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                source_location_id=bin_id, quantity=quantity,
            )
        ],
    )
    line = inventory_issue_service.list_issue_lines(db, tenant_id=scenario["tenant_id"], issue_id=issue.id)[0]
    return line


def _snapshot(db, cohort_id):
    return inventory_cohort_accounting_service.get_cohort_accounting_snapshot(db, cohort_id=cohort_id)


# --- 1. Confirmed reproduction --------------------------------------------------


@pytest.mark.integration
def test_confirmed_reproduction_putaway_after_consume(db_session, test_engine) -> None:
    """Receive 100, Putaway 60, Issue 30, Consume 30 -> E=70, B=30, O=0,
    N=40 (the ticket's exact confirmed reproduction). Read model, snapshot
    helper, and a subsequent Putaway of 20 (service + DB trigger) must all
    agree that N=40, not the buggy 10 (=E-C)."""
    scenario = build_scenario(test_engine)
    cohort_id = receive_cohort(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("100"),
    )
    bin_ = build_store_bin(db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
    inventory_storage_service.record_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
        quantity=Decimal("60"), effective_time=_now(),
    )
    db_session.commit()
    line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_.id, quantity=Decimal("30"))
    inventory_material_event_service.record_consumption(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("30"), effective_time=_now(),
    )

    existence = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    not_put_away = inventory_storage_service.get_cohort_not_put_away(
        db_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
    )
    in_bins = inventory_availability_service.get_item_in_store_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    outstanding = inventory_availability_service.get_item_issued_to_operations_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    snap = _snapshot(db_session, cohort_id)

    assert existence == Decimal("70")
    assert not_put_away == Decimal("40"), "BEFORE fix this was wrongly 10 (=E-C, missing +D)"
    assert in_bins == Decimal("30")
    assert outstanding == Decimal("0")
    assert not_put_away + in_bins + outstanding == existence
    assert snap.not_put_away == not_put_away
    assert snap.in_bins == in_bins
    assert snap.outstanding_issued == outstanding

    # Service validation + DB trigger must both agree N=40: a Putaway of 20
    # (which exceeds the old buggy ceiling of 10) must succeed.
    inventory_storage_service.record_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
        quantity=Decimal("20"), effective_time=_now(),
    )
    not_put_away_after = inventory_storage_service.get_cohort_not_put_away(
        db_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
    )
    assert not_put_away_after == Decimal("20")


# --- 2. Partial return + consumption ---------------------------------------------


@pytest.mark.integration
def test_partial_return_and_consumption_preserve_outstanding_and_not_put_away(db_session, test_engine) -> None:
    """Receive 50, Putaway 30, Issue 20, Return 5, Consume 10 -> Outstanding
    issued (O) and Not put away (N) must both stay correct and reconcile."""
    scenario = build_scenario(test_engine)
    cohort_id = receive_cohort(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("50"),
    )
    bin_ = build_store_bin(db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
    inventory_storage_service.record_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
        quantity=Decimal("30"), effective_time=_now(),
    )
    db_session.commit()
    line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_.id, quantity=Decimal("20"))
    inventory_material_event_service.record_return(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, destination_location_id=bin_.id,
        quantity=Decimal("5"), effective_time=_now(),
    )
    inventory_material_event_service.record_consumption(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("10"), effective_time=_now(),
    )

    snap = _snapshot(db_session, cohort_id)
    assert snap.existence == Decimal("40")
    assert snap.not_put_away == Decimal("20")
    assert snap.in_bins == Decimal("15")
    assert snap.outstanding_issued == Decimal("5")
    assert snap.not_put_away + snap.in_bins + snap.outstanding_issued == snap.existence

    # The remaining 20 not-put-away (unaffected by Issue/Return/Consume)
    # must still be fully put-away-able.
    inventory_storage_service.record_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
        quantity=Decimal("20"), effective_time=_now(),
    )
    assert _snapshot(db_session, cohort_id).not_put_away == Decimal("0")


# --- 3-5. Scrap source reconciliations --------------------------------------------


@pytest.mark.integration
def test_issued_scrap_reduces_existence_and_outstanding_equally(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))
    before = _snapshot(db_session, cohort_id)
    inventory_material_event_service.record_scrap(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), source_kind="issued", quantity=Decimal("4"), reason="spill",
        effective_time=_now(), issue_line_id=line.id,
    )
    after = _snapshot(db_session, cohort_id)
    assert before.existence - after.existence == Decimal("4")
    assert before.outstanding_issued - after.outstanding_issued == Decimal("4")
    assert after.in_bins == before.in_bins
    assert after.not_put_away == before.not_put_away
    assert after.not_put_away + after.in_bins + after.outstanding_issued == after.existence


@pytest.mark.integration
def test_bin_scrap_reduces_existence_and_in_bins_equally(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    before = _snapshot(db_session, cohort_id)
    inventory_material_event_service.record_scrap(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), source_kind="store_bin", quantity=Decimal("4"), reason="damaged",
        effective_time=_now(), inventory_quantity_cohort_id=cohort_id, source_location_id=bin_id,
    )
    after = _snapshot(db_session, cohort_id)
    assert before.existence - after.existence == Decimal("4")
    assert before.in_bins - after.in_bins == Decimal("4")
    assert after.outstanding_issued == before.outstanding_issued
    assert after.not_put_away == before.not_put_away
    assert after.not_put_away + after.in_bins + after.outstanding_issued == after.existence


@pytest.mark.integration
def test_not_put_away_scrap_reduces_existence_and_not_put_away_equally(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id = receive_cohort(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    db_session.commit()
    before = _snapshot(db_session, cohort_id)
    inventory_material_event_service.record_scrap(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), source_kind="not_put_away", quantity=Decimal("3"), reason="physical loss",
        effective_time=_now(), inventory_quantity_cohort_id=cohort_id,
    )
    after = _snapshot(db_session, cohort_id)
    assert before.existence - after.existence == Decimal("3")
    assert before.not_put_away - after.not_put_away == Decimal("3")
    assert after.in_bins == before.in_bins
    assert after.outstanding_issued == before.outstanding_issued
    assert after.not_put_away + after.in_bins + after.outstanding_issued == after.existence


# --- 6. Negative adjustment / reversal floor --------------------------------------


@pytest.mark.integration
def test_negative_adjustment_and_reversal_floor(db_session, test_engine) -> None:
    """After Receive 100/Putaway 60/Issue 30/Consume 30: E=70,
    floor = in_bins + outstanding_issued = 30 (NOT the stale
    total_custody = 60). A reduction down to exactly 30 is allowed; below it
    is rejected. A Reversal landing on 45 (between the old buggy floor 60
    and the correct floor 30) proves the SAME fix applies to
    `reverse_ledger_entry`, not just `record_adjustment`."""
    scenario = build_scenario(test_engine)
    cohort_id = receive_cohort(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("100"),
    )
    bin_ = build_store_bin(db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
    inventory_storage_service.record_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
        quantity=Decimal("60"), effective_time=_now(),
    )
    db_session.commit()
    line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_.id, quantity=Decimal("30"))
    inventory_material_event_service.record_consumption(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("30"), effective_time=_now(),
    )
    snap = _snapshot(db_session, cohort_id)
    assert snap.existence == Decimal("70")
    assert snap.existence_floor == Decimal("30"), "B+O, not the stale custody_total (60)"

    # Reversal proof: bump E by +10 (E=80), then reverse that bump back to
    # 70 -- always legal (70 >= 30). Now bump again by +10 (E=80) then
    # reverse to land at 45 via a DIFFERENT construction: first reduce to
    # 45 directly with an adjustment (legal: 45 >= 30, but 45 < the OLD
    # buggy floor of 60 -- this already exercises record_adjustment's own
    # fix), then bump +10 to 55 and reverse that bump back down to 45 via
    # reverse_ledger_entry -- 45 is between the two floors, so this
    # reversal is the discriminating proof for reverse_ledger_entry.
    inventory_existence_ledger_service.record_adjustment(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, quantity_delta=Decimal("-25"),
        effective_time=_now(), reason="stock count correction",
    )
    assert _snapshot(db_session, cohort_id).existence == Decimal("45")

    bump = inventory_existence_ledger_service.record_adjustment(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, quantity_delta=Decimal("10"),
        effective_time=_now(), reason="temporary correction",
    )
    assert _snapshot(db_session, cohort_id).existence == Decimal("55")

    inventory_existence_ledger_service.reverse_ledger_entry(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), target_entry_id=bump.id, reason="undo temporary correction",
    )
    assert _snapshot(db_session, cohort_id).existence == Decimal("45"), (
        "BEFORE fix this reversal would have been wrongly rejected "
        "(45 < stale floor 60)"
    )

    # Now at E=45, floor is still 30: reducing by exactly 15 (to 30) is
    # legal; reducing by one more unit (to 29) must be rejected.
    inventory_existence_ledger_service.record_adjustment(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, quantity_delta=Decimal("-15"),
        effective_time=_now(), reason="reduce to the floor",
    )
    assert _snapshot(db_session, cohort_id).existence == Decimal("30")

    with pytest.raises(ExistenceBelowCustodyError):
        inventory_existence_ledger_service.record_adjustment(
            db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, quantity_delta=Decimal("-1"),
            effective_time=_now(), reason="one below the floor",
        )


# --- 7. Quality partial split from Not-put-away after consumption ----------------


@pytest.mark.integration
def test_quality_partial_split_from_not_put_away_after_consumption(db_session, test_engine) -> None:
    """After Receive 100/Putaway 60/Issue 30/Consume 30, Not-put-away is 40
    (not the buggy 10). Splitting 25 kg of it via the partial-Quality
    "Not put away" bucket must succeed, and combined parent+child totals
    must stay conserved."""
    scenario = build_scenario(test_engine)
    cohort_id = receive_cohort(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("100"),
    )
    bin_ = build_store_bin(db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
    inventory_storage_service.record_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
        quantity=Decimal("60"), effective_time=_now(),
    )
    db_session.commit()
    line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_.id, quantity=Decimal("30"))
    inventory_material_event_service.record_consumption(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("30"), effective_time=_now(),
    )
    parent_before = _snapshot(db_session, cohort_id)
    assert parent_before.not_put_away == Decimal("40")

    child = inventory_quality_service.apply_quality_disposition_to_partial_quantity(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), source_cohort_id=cohort_id, quantity=Decimal("25"),
        disposition="HELD", effective_time=_now(), reason="quarantine investigation",
        custody_location_id=None,
    )

    parent_after = _snapshot(db_session, cohort_id)
    child_snap = _snapshot(db_session, child.id)
    assert parent_after.existence == Decimal("45")
    assert parent_after.not_put_away == Decimal("15")
    assert child_snap.existence == Decimal("25")
    assert child_snap.not_put_away == Decimal("25")
    # Combined totals conserved across parent + child.
    assert parent_after.existence + child_snap.existence == parent_before.existence
    assert parent_after.not_put_away + child_snap.not_put_away == parent_before.not_put_away
    assert parent_after.in_bins + child_snap.in_bins == parent_before.in_bins
    assert parent_after.outstanding_issued + child_snap.outstanding_issued == parent_before.outstanding_issued


# --- DB trigger, independent of the service-layer check --------------------------


@pytest.mark.integration
def test_db_trigger_putaway_uses_issued_settlement_floor(db_session, test_engine) -> None:
    """Bypasses `inventory_storage_service.record_putaway`'s own Python
    check entirely -- a raw INSERT into `inventory_storage_movements`,
    relying ONLY on `enforce_inventory_storage_movement_insert_integrity_v4`
    to accept a quantity that the OLD `_v3` trigger's formula
    (existence - custody, without settled-from-issued) would have rejected.
    After Receive 100/Putaway 60/Issue 30/Consume 30: existence=70,
    custody=60 (v3's ceiling: 10), true not-put-away=40. A raw putaway of 15
    exceeds 10 but not 40 -- accepted only by the fixed trigger."""
    scenario = build_scenario(test_engine)
    cohort_id = receive_cohort(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("100"),
    )
    bin_ = build_store_bin(db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
    inventory_storage_service.record_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
        quantity=Decimal("60"), effective_time=_now(),
    )
    db_session.commit()
    line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_.id, quantity=Decimal("30"))
    inventory_material_event_service.record_consumption(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("30"), effective_time=_now(),
    )
    db_session.commit()

    raw_movement = InventoryStorageMovement(
        id=uuid.uuid4(), tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        inventory_quantity_cohort_id=cohort_id, movement_kind="putaway", source_location_id=None,
        destination_location_id=bin_.id, moved_quantity_base=Decimal("15"), effective_time=_now(),
        actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), request_fingerprint="test-raw-insert",
    )
    db_session.add(raw_movement)
    db_session.flush()  # must NOT raise -- proves the v4 trigger, not just the service layer
    db_session.commit()

    assert _snapshot(db_session, cohort_id).not_put_away == Decimal("25")


@pytest.mark.integration
def test_db_trigger_still_rejects_putaway_beyond_true_not_put_away(db_session, test_engine) -> None:
    """Symmetry check: the fixed trigger is not simply permissive -- a raw
    putaway that exceeds the TRUE not-put-away (40) is still rejected."""
    scenario = build_scenario(test_engine)
    cohort_id = receive_cohort(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("100"),
    )
    bin_ = build_store_bin(db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
    inventory_storage_service.record_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
        quantity=Decimal("60"), effective_time=_now(),
    )
    db_session.commit()
    line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_.id, quantity=Decimal("30"))
    inventory_material_event_service.record_consumption(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("30"), effective_time=_now(),
    )
    db_session.commit()

    with pytest.raises(DBAPIError):
        db_session.execute(
            text(
                "INSERT INTO inventory_storage_movements "
                "(id, tenant_id, farm_id, inventory_quantity_cohort_id, movement_kind, source_location_id, "
                " destination_location_id, moved_quantity_base, effective_time, actor_user_id, "
                " client_command_id, request_fingerprint) "
                "VALUES (:id, :tenant_id, :farm_id, :cohort_id, 'putaway', NULL, "
                " :bin_id, :qty, :effective_time, :actor_id, :client_command_id, :fingerprint)"
            ),
            {
                "id": str(uuid.uuid4()), "tenant_id": str(scenario["tenant_id"]), "farm_id": str(scenario["farm_id"]),
                "cohort_id": str(cohort_id), "bin_id": str(bin_.id), "qty": Decimal("41"),
                "effective_time": _now(), "actor_id": str(scenario["user_id"]),
                "client_command_id": str(uuid.uuid4()), "fingerprint": "test-raw-insert-over",
            },
        )
        db_session.flush()
    db_session.rollback()


# --- Idempotent replay -------------------------------------------------------------


@pytest.mark.integration
def test_putaway_replay_does_not_double_apply(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id = receive_cohort(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("100"),
    )
    bin_ = build_store_bin(db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
    inventory_storage_service.record_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
        quantity=Decimal("60"), effective_time=_now(),
    )
    db_session.commit()
    line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_.id, quantity=Decimal("30"))
    inventory_material_event_service.record_consumption(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("30"), effective_time=_now(),
    )
    db_session.commit()

    client_command_id = uuid.uuid4()
    effective_time = _now()
    kwargs = dict(
        tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=client_command_id, cohort_id=cohort_id, destination_location_id=bin_.id,
        quantity=Decimal("20"), effective_time=effective_time,
    )
    first = inventory_storage_service.record_putaway(db_session, **kwargs)
    second = inventory_storage_service.record_putaway(db_session, **kwargs)
    assert first.id == second.id
    assert _snapshot(db_session, cohort_id).not_put_away == Decimal("20"), "a replayed putaway must not double-apply"

    with pytest.raises(InventoryStorageCommandReusedWithDifferentPayloadError):
        inventory_storage_service.record_putaway(
            db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=client_command_id, cohort_id=cohort_id,
            destination_location_id=bin_.id, quantity=Decimal("21"), effective_time=effective_time,
        )


@pytest.mark.integration
def test_adjustment_replay_does_not_double_apply(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id = receive_cohort(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("50"),
    )
    db_session.commit()

    client_command_id = uuid.uuid4()
    effective_time = _now()
    kwargs = dict(
        tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=client_command_id,
        cohort_id=cohort_id, quantity_delta=Decimal("-10"), effective_time=effective_time, reason="count correction",
    )
    first = inventory_existence_ledger_service.record_adjustment(db_session, **kwargs)
    second = inventory_existence_ledger_service.record_adjustment(db_session, **kwargs)
    assert first.id == second.id
    assert _snapshot(db_session, cohort_id).existence == Decimal("40"), "a replayed adjustment must not double-apply"


# --- Concurrency -------------------------------------------------------------------


@pytest.mark.integration
def test_concurrent_putaways_cannot_exceed_true_not_put_away(test_engine) -> None:
    """Two Putaway commands race the SAME not-put-away budget (40, after
    Receive 100/Putaway 60/Issue 30/Consume 30) -- proves the cohort-level
    lock still serializes correctly under the corrected formula: exactly one
    of two 30-kg putaways succeeds (60 > 40), the other is rejected, and the
    final not-put-away is never negative."""
    import threading

    from sqlalchemy.orm import Session

    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    cohort_id = receive_cohort(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("100"),
    )
    bin_ = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
    bin_id = bin_.id
    inventory_storage_service.record_putaway(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_id,
        quantity=Decimal("60"), effective_time=_now(),
    )
    line = _issue(session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("30"))
    inventory_material_event_service.record_consumption(
        session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("30"), effective_time=_now(),
    )
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def worker(name: str) -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            movement = inventory_storage_service.record_putaway(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), cohort_id=cohort_id,
                destination_location_id=bin_id, quantity=Decimal("30"), effective_time=_now(),
            )
            results[name] = ("ok", movement.id)
        except InsufficientNotPutAwayQuantityError as exc:
            results[name] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results[name] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=worker, args=("a",))
    t_b = threading.Thread(target=worker, args=("b",))
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    assert not t_a.is_alive() and not t_b.is_alive()
    outcomes = [results["a"][0], results["b"][0]]
    assert outcomes.count("ok") == 1, results
    assert outcomes.count("insufficient") == 1, results

    with test_engine.connect() as verify_conn:
        verify_session = Session(bind=verify_conn)
        not_put_away = inventory_storage_service.get_cohort_not_put_away(
            verify_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
        )
    assert not_put_away == Decimal("10")
    assert not_put_away >= 0
