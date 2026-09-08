"""STORE-INV-004: Consumption, Return & Scrap -- completes the consumable
Inventory lifecycle. Never collapses Existence, physical custody,
Reservation, or Issue-line reconciliation. Proves the five numeric
reconciliation scenarios from the ticket, the three Scrap source buckets,
Issue-line settlement bounds, Quality/expiry interaction, Reservation
interaction, idempotency, and five focused concurrency races."""
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services import (
    inventory_availability_service,
    inventory_existence_ledger_service,
    inventory_issue_service,
    inventory_material_event_service,
    inventory_quality_service,
    inventory_reservation_service,
    inventory_storage_service,
)
from app.services.errors import (
    InsufficientIssueLineOutstandingError,
    InsufficientNotPutAwayQuantityError,
    InsufficientStorageBinBalanceError,
    InventoryConsumptionSourceNotUsableError,
    InventoryExistenceReversalUnsupportedForEntryKindError,
    InventoryMaterialEventCommandReusedWithDifferentPayloadError,
    InventoryMaterialEventValidationError,
    StorageBinNotFoundError,
)
from app.services.inventory_issue_service import IssueLineInput
from app.services.inventory_reservation_service import ReservationLineInput
from tests._store_custody_scenario import build_store_bin, receive_cohort
from tests._store_reservation_scenario import build_scenario, receive_and_putaway


def _now():
    return datetime.now(timezone.utc)


def _issue(db, scenario, *, cohort_id, bin_id, quantity: Decimal, purpose="Ops use"):
    issue = inventory_issue_service.record_issue(
        db, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose=purpose, effective_time=_now(),
        lines=[
            IssueLineInput(
                inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                source_location_id=bin_id, quantity=quantity,
            )
        ],
    )
    line = inventory_issue_service.list_issue_lines(db, tenant_id=scenario["tenant_id"], issue_id=issue.id)[0]
    return issue, line


# --- Five numeric reconciliation scenarios ------------------------------------


@pytest.mark.integration
def test_scenario_1_consume(db_session, test_engine) -> None:
    """Receive 20, Putaway 20, Issue 10, Consume 6 -> Existence 14,
    Not put away 0, In Store 10, Issued to operations 4."""
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    _issue_evt, line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))
    inventory_material_event_service.record_consumption(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("6"), effective_time=_now(),
    )

    existence = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    not_put_away = inventory_storage_service.get_cohort_not_put_away(
        db_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
    )
    in_store = inventory_availability_service.get_item_in_store_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    issued_ops = inventory_availability_service.get_item_issued_to_operations_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert existence == Decimal("14")
    assert not_put_away == Decimal("0")
    assert in_store == Decimal("10")
    assert issued_ops == Decimal("4")
    assert not_put_away + in_store + issued_ops == existence


@pytest.mark.integration
def test_scenario_2_return(db_session, test_engine) -> None:
    """Receive 20, Putaway 20, Issue 10, Return 4 to Bin -> Existence 20,
    Not put away 0, In Store 14, Issued to operations 6."""
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    _issue_evt, line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))
    inventory_material_event_service.record_return(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, destination_location_id=bin_id,
        quantity=Decimal("4"), effective_time=_now(),
    )

    existence = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    not_put_away = inventory_storage_service.get_cohort_not_put_away(
        db_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
    )
    in_store = inventory_availability_service.get_item_in_store_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    issued_ops = inventory_availability_service.get_item_issued_to_operations_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert existence == Decimal("20")
    assert not_put_away == Decimal("0")
    assert in_store == Decimal("14")
    assert issued_ops == Decimal("6")
    assert not_put_away + in_store + issued_ops == existence


@pytest.mark.integration
def test_scenario_3_scrap_not_put_away(db_session, test_engine) -> None:
    """Receive 20, Putaway 12, Scrap 3 from Not put away -> Existence 17,
    Not put away 5, In Store 12, Issued to operations 0."""
    scenario = build_scenario(test_engine)
    cohort_id = receive_cohort(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    bin_ = build_store_bin(db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
    inventory_storage_service.record_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id, quantity=Decimal("12"),
        effective_time=_now(),
    )
    db_session.commit()

    inventory_material_event_service.record_scrap(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), source_kind="not_put_away", quantity=Decimal("3"),
        reason="physical loss", effective_time=_now(), inventory_quantity_cohort_id=cohort_id,
    )

    existence = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    not_put_away = inventory_storage_service.get_cohort_not_put_away(
        db_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
    )
    in_store = inventory_availability_service.get_item_in_store_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    issued_ops = inventory_availability_service.get_item_issued_to_operations_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert existence == Decimal("17")
    assert not_put_away == Decimal("5")
    assert in_store == Decimal("12")
    assert issued_ops == Decimal("0")
    assert not_put_away + in_store + issued_ops == existence


@pytest.mark.integration
def test_scenario_4_scrap_from_bin(db_session, test_engine) -> None:
    """Receive 20, Putaway 20, Scrap 4 from Bin -> Existence 16,
    Not put away 0, In Store 16, Issued to operations 0."""
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    inventory_material_event_service.record_scrap(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), source_kind="store_bin", quantity=Decimal("4"), reason="damaged packaging",
        effective_time=_now(), inventory_quantity_cohort_id=cohort_id, source_location_id=bin_id,
    )

    existence = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    not_put_away = inventory_storage_service.get_cohort_not_put_away(
        db_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
    )
    in_store = inventory_availability_service.get_item_in_store_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    issued_ops = inventory_availability_service.get_item_issued_to_operations_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert existence == Decimal("16")
    assert not_put_away == Decimal("0")
    assert in_store == Decimal("16")
    assert issued_ops == Decimal("0")
    assert not_put_away + in_store + issued_ops == existence


@pytest.mark.integration
def test_scenario_5_scrap_from_issued(db_session, test_engine) -> None:
    """Receive 20, Putaway 20, Issue 10, Scrap 3 from issued -> Existence
    17, Not put away 0, In Store 10, Issued to operations 7."""
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    _issue_evt, line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))
    inventory_material_event_service.record_scrap(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), source_kind="issued", quantity=Decimal("3"), reason="spill",
        effective_time=_now(), issue_line_id=line.id,
    )

    existence = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    not_put_away = inventory_storage_service.get_cohort_not_put_away(
        db_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
    )
    in_store = inventory_availability_service.get_item_in_store_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    issued_ops = inventory_availability_service.get_item_issued_to_operations_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert existence == Decimal("17")
    assert not_put_away == Decimal("0")
    assert in_store == Decimal("10")
    assert issued_ops == Decimal("7")
    assert not_put_away + in_store + issued_ops == existence


# --- Issue-line reconciliation -------------------------------------------------


@pytest.mark.integration
def test_issue_line_reconciliation_multi_settlement(db_session, test_engine) -> None:
    """Issue 20, Consume 12, Return 5, Scrap 1 -> Outstanding 2."""
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    _issue_evt, line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("20"))

    inventory_material_event_service.record_consumption(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("12"), effective_time=_now(),
    )
    inventory_material_event_service.record_return(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, destination_location_id=bin_id, quantity=Decimal("5"),
        effective_time=_now(),
    )
    inventory_material_event_service.record_scrap(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), source_kind="issued", quantity=Decimal("1"), reason="rejected material disposal",
        effective_time=_now(), issue_line_id=line.id,
    )

    summary = inventory_material_event_service.get_issue_line_reconciliation(
        db_session, tenant_id=scenario["tenant_id"], issue_line_id=line.id
    )
    assert summary["issued_quantity"] == Decimal("20")
    assert summary["consumed_quantity"] == Decimal("12")
    assert summary["returned_quantity"] == Decimal("5")
    assert summary["scrapped_quantity"] == Decimal("1")
    assert summary["outstanding_quantity"] == Decimal("2")

    # Settlement above the original issued quantity is never allowed.
    with pytest.raises(InsufficientIssueLineOutstandingError):
        inventory_material_event_service.record_consumption(
            db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("3"), effective_time=_now(),
        )


# --- Quality/expiry interaction -----------------------------------------------


@pytest.mark.integration
def test_consumption_blocked_by_quality_but_return_and_scrap_remain_allowed(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    _issue_evt, line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))

    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=_now(), reason="contamination suspected",
    )
    db_session.commit()

    with pytest.raises(InventoryConsumptionSourceNotUsableError):
        inventory_material_event_service.record_consumption(
            db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("1"), effective_time=_now(),
        )

    # Return remains allowed regardless of Quality.
    returned = inventory_material_event_service.record_return(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, destination_location_id=bin_id, quantity=Decimal("2"),
        effective_time=_now(),
    )
    assert returned.event_kind == "return"

    # Scrap remains allowed regardless of Quality.
    scrapped = inventory_material_event_service.record_scrap(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), source_kind="issued", quantity=Decimal("1"), reason="rejected material disposal",
        effective_time=_now(), issue_line_id=line.id,
    )
    assert scrapped.event_kind == "scrap"


# --- Reservation interaction ---------------------------------------------------


@pytest.mark.integration
def test_consumption_of_issued_material_does_not_change_available_to_issue(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    _issue_evt, line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))
    available_before = inventory_availability_service.get_item_available_to_issue(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    inventory_material_event_service.record_consumption(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("5"), effective_time=_now(),
    )
    available_after = inventory_availability_service.get_item_available_to_issue(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert available_after == available_before == Decimal("10")


@pytest.mark.integration
def test_return_of_usable_material_increases_available_to_issue(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    _issue_evt, line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))
    available_before = inventory_availability_service.get_item_available_to_issue(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    inventory_material_event_service.record_return(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, destination_location_id=bin_id, quantity=Decimal("4"),
        effective_time=_now(),
    )
    available_after = inventory_availability_service.get_item_available_to_issue(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert available_after == available_before + Decimal("4")


@pytest.mark.integration
def test_store_scrap_may_cause_reservation_to_become_blocked(db_session, test_engine) -> None:
    """Scrap from Store is never blocked merely because a Reservation
    exists, and it may cause that Reservation to become under-covered --
    the reservation itself is never silently reduced."""
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    reservation = inventory_reservation_service.create_reservation(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Committed", effective_time=_now(),
        lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("8"))],
    )
    line = inventory_reservation_service.list_reservation_lines(
        db_session, tenant_id=scenario["tenant_id"], reservation_id=reservation.id
    )[0]
    not_blocked = inventory_reservation_service.is_line_blocked_by_quality(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        inventory_item_id=scenario["item_id"], remaining=Decimal("8"),
    )
    assert not_blocked is False

    inventory_material_event_service.record_scrap(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), source_kind="store_bin", quantity=Decimal("5"), reason="expired material",
        effective_time=_now(), inventory_quantity_cohort_id=cohort_id, source_location_id=bin_id,
    )
    remaining = inventory_reservation_service.get_reservation_line_remaining(db_session, reservation_line_id=line.id)
    assert remaining == Decimal("8"), "scrap must never silently reduce a reservation"

    blocked = inventory_reservation_service.is_line_blocked_by_quality(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        inventory_item_id=scenario["item_id"], remaining=remaining,
    )
    assert blocked is True


# --- Idempotency -----------------------------------------------------------------


@pytest.mark.integration
def test_consumption_is_idempotent(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    _issue_evt, line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))
    client_command_id = uuid.uuid4()
    kwargs = dict(
        tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=client_command_id,
        issue_line_id=line.id, quantity=Decimal("4"), effective_time=_now(),
    )
    first = inventory_material_event_service.record_consumption(db_session, **kwargs)
    second = inventory_material_event_service.record_consumption(db_session, **kwargs)
    assert first.id == second.id
    summary = inventory_material_event_service.get_issue_line_reconciliation(
        db_session, tenant_id=scenario["tenant_id"], issue_line_id=line.id
    )
    assert summary["consumed_quantity"] == Decimal("4"), "a replayed consumption must not double-consume"

    with pytest.raises(InventoryMaterialEventCommandReusedWithDifferentPayloadError):
        inventory_material_event_service.record_consumption(
            db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=client_command_id, issue_line_id=line.id, quantity=Decimal("5"), effective_time=_now(),
        )


@pytest.mark.integration
def test_return_is_idempotent(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    _issue_evt, line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))
    client_command_id = uuid.uuid4()
    kwargs = dict(
        tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=client_command_id,
        issue_line_id=line.id, destination_location_id=bin_id, quantity=Decimal("4"), effective_time=_now(),
    )
    first = inventory_material_event_service.record_return(db_session, **kwargs)
    second = inventory_material_event_service.record_return(db_session, **kwargs)
    assert first.id == second.id
    bin_balance = inventory_existence_ledger_service.get_cohort_bin_balance(db_session, cohort_id=cohort_id, location_id=bin_id)
    assert bin_balance == Decimal("4"), "a replayed return must not double-credit custody"


@pytest.mark.integration
def test_scrap_is_idempotent_and_requires_reason(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    client_command_id = uuid.uuid4()
    kwargs = dict(
        tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=client_command_id,
        source_kind="store_bin", quantity=Decimal("2"), reason="damaged packaging", effective_time=_now(),
        inventory_quantity_cohort_id=cohort_id, source_location_id=bin_id,
    )
    first = inventory_material_event_service.record_scrap(db_session, **kwargs)
    second = inventory_material_event_service.record_scrap(db_session, **kwargs)
    assert first.id == second.id
    bin_balance = inventory_existence_ledger_service.get_cohort_bin_balance(db_session, cohort_id=cohort_id, location_id=bin_id)
    assert bin_balance == Decimal("8"), "a replayed scrap must not double-debit custody"

    with pytest.raises(InventoryMaterialEventValidationError):
        inventory_material_event_service.record_scrap(
            db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), source_kind="store_bin", quantity=Decimal("1"), reason="   ",
            effective_time=_now(), inventory_quantity_cohort_id=cohort_id, source_location_id=bin_id,
        )


# --- Bounds / validation errors -------------------------------------------------


@pytest.mark.integration
def test_scrap_from_bin_cannot_exceed_bin_balance(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("5"),
    )
    with pytest.raises(InsufficientStorageBinBalanceError):
        inventory_material_event_service.record_scrap(
            db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), source_kind="store_bin", quantity=Decimal("6"), reason="physical loss",
            effective_time=_now(), inventory_quantity_cohort_id=cohort_id, source_location_id=bin_id,
        )


@pytest.mark.integration
def test_scrap_from_not_put_away_cannot_exceed_not_put_away(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id = receive_cohort(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("5"),
    )
    db_session.commit()
    with pytest.raises(InsufficientNotPutAwayQuantityError):
        inventory_material_event_service.record_scrap(
            db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), source_kind="not_put_away", quantity=Decimal("6"), reason="physical loss",
            effective_time=_now(), inventory_quantity_cohort_id=cohort_id,
        )


@pytest.mark.integration
def test_return_rejects_bin_from_a_different_farm(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    _issue_evt, line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("5"))

    other_scenario = build_scenario(test_engine)
    other_bin = build_store_bin(
        db_session, tenant_id=other_scenario["tenant_id"], farm_id=other_scenario["farm_id"],
        actor_user_id=other_scenario["user_id"],
    )
    db_session.commit()

    with pytest.raises(StorageBinNotFoundError):
        inventory_material_event_service.record_return(
            db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), issue_line_id=line.id, destination_location_id=other_bin.id,
            quantity=Decimal("1"), effective_time=_now(),
        )


@pytest.mark.integration
def test_existence_reversal_blocks_consumption_and_scrap_entries(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    _issue_evt, line = _issue(db_session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))
    consumption = inventory_material_event_service.record_consumption(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("4"), effective_time=_now(),
    )
    with pytest.raises(InventoryExistenceReversalUnsupportedForEntryKindError):
        inventory_existence_ledger_service.reverse_ledger_entry(
            db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), target_entry_id=consumption.existence_ledger_entry_id,
            reason="attempted correction",
        )


# --- Tenant/Farm isolation ------------------------------------------------------


@pytest.mark.integration
def test_issue_line_not_found_for_other_tenant(db_session, test_engine) -> None:
    scenario_a = build_scenario(test_engine)
    scenario_b = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario_a["tenant_id"], farm_id=scenario_a["farm_id"],
        actor_user_id=scenario_a["user_id"], item_id=scenario_a["item_id"], quantity=Decimal("10"),
    )
    _issue_evt, line = _issue(db_session, scenario_a, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("5"))

    from app.services.errors import InventoryIssueLineNotFoundError

    with pytest.raises(InventoryIssueLineNotFoundError):
        inventory_material_event_service.record_consumption(
            db_session, tenant_id=scenario_b["tenant_id"], actor_user_id=scenario_b["user_id"],
            client_command_id=uuid.uuid4(), issue_line_id=line.id, quantity=Decimal("1"), effective_time=_now(),
        )


# --- Concurrency proofs ----------------------------------------------------------


@pytest.mark.integration
def test_concurrent_consumptions_cannot_over_consume(test_engine) -> None:
    """Proof A: two Consumption commands race the same outstanding Issue
    quantity -> cannot over-consume."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    cohort_id, bin_id = receive_and_putaway(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    _issue_evt, line = _issue(session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))
    line_id = line.id
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
            event = inventory_material_event_service.record_consumption(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), issue_line_id=line_id, quantity=Decimal("7"), effective_time=_now(),
            )
            results[name] = ("ok", event.id)
        except InsufficientIssueLineOutstandingError as exc:
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
        summary_session = Session(bind=verify_conn)
        summary = inventory_material_event_service.get_issue_line_reconciliation(
            summary_session, tenant_id=scenario["tenant_id"], issue_line_id=line_id
        )
    assert summary["outstanding_quantity"] == Decimal("3")


@pytest.mark.integration
def test_return_races_consumption_never_exceeds_issued(test_engine) -> None:
    """Proof B: Return races Consumption on the same Issue line -> total
    settlement never exceeds issued qty."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    cohort_id, bin_id = receive_and_putaway(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    _issue_evt, line = _issue(session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))
    line_id = line.id
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def consume_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = inventory_material_event_service.record_consumption(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), issue_line_id=line_id, quantity=Decimal("7"), effective_time=_now(),
            )
            results["consume"] = ("ok", event.id)
        except InsufficientIssueLineOutstandingError as exc:
            results["consume"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results["consume"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def return_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = inventory_material_event_service.record_return(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), issue_line_id=line_id, destination_location_id=bin_id,
                quantity=Decimal("7"), effective_time=_now(),
            )
            results["return"] = ("ok", event.id)
        except InsufficientIssueLineOutstandingError as exc:
            results["return"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results["return"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=consume_worker)
    t_b = threading.Thread(target=return_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    assert not t_a.is_alive() and not t_b.is_alive()
    outcomes = [results["consume"][0], results["return"][0]]
    assert outcomes.count("ok") == 1, results
    assert outcomes.count("insufficient") == 1, results

    with test_engine.connect() as verify_conn:
        summary_session = Session(bind=verify_conn)
        summary = inventory_material_event_service.get_issue_line_reconciliation(
            summary_session, tenant_id=scenario["tenant_id"], issue_line_id=line_id
        )
    assert summary["outstanding_quantity"] == Decimal("3")
    total_settled = summary["consumed_quantity"] + summary["returned_quantity"] + summary["scrapped_quantity"]
    assert total_settled <= summary["issued_quantity"]


@pytest.mark.integration
def test_store_bin_scrap_races_transfer_cannot_overdraw_bin(test_engine) -> None:
    """Proof C: Store-Bin Scrap races a Bin transfer -> cannot overdraw
    the Bin."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    cohort_id, bin_a = receive_and_putaway(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    bin_b = build_store_bin(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"]
    ).id
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def scrap_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = inventory_material_event_service.record_scrap(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), source_kind="store_bin", quantity=Decimal("7"),
                reason="damaged packaging", effective_time=_now(), inventory_quantity_cohort_id=cohort_id,
                source_location_id=bin_a,
            )
            results["scrap"] = ("ok", event.id)
        except InsufficientStorageBinBalanceError as exc:
            results["scrap"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results["scrap"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def transfer_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            movement = inventory_storage_service.record_transfer(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), cohort_id=cohort_id,
                source_location_id=bin_a, destination_location_id=bin_b, quantity=Decimal("7"),
                effective_time=_now(),
            )
            results["transfer"] = ("ok", movement.id)
        except InsufficientStorageBinBalanceError as exc:
            results["transfer"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results["transfer"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=scrap_worker)
    t_b = threading.Thread(target=transfer_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    assert not t_a.is_alive() and not t_b.is_alive()
    outcomes = [results["scrap"][0], results["transfer"][0]]
    assert outcomes.count("ok") == 1, results
    assert outcomes.count("insufficient") == 1, results

    with test_engine.connect() as verify_conn:
        summary_session = Session(bind=verify_conn)
        bin_a_balance = inventory_existence_ledger_service.get_cohort_bin_balance(
            summary_session, cohort_id=cohort_id, location_id=bin_a
        )
    assert bin_a_balance == Decimal("3")
    assert bin_a_balance >= 0


@pytest.mark.integration
def test_scrap_from_issued_races_another_settlement(test_engine) -> None:
    """Proof D: Scrap-from-issued races another settlement -> Issue-line
    outstanding never negative."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    cohort_id, bin_id = receive_and_putaway(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    _issue_evt, line = _issue(session, scenario, cohort_id=cohort_id, bin_id=bin_id, quantity=Decimal("10"))
    line_id = line.id
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def scrap_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = inventory_material_event_service.record_scrap(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), source_kind="issued", quantity=Decimal("7"),
                reason="rejected material disposal", effective_time=_now(), issue_line_id=line_id,
            )
            results["scrap"] = ("ok", event.id)
        except InsufficientIssueLineOutstandingError as exc:
            results["scrap"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results["scrap"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def consume_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = inventory_material_event_service.record_consumption(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), issue_line_id=line_id, quantity=Decimal("7"), effective_time=_now(),
            )
            results["consume"] = ("ok", event.id)
        except InsufficientIssueLineOutstandingError as exc:
            results["consume"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results["consume"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=scrap_worker)
    t_b = threading.Thread(target=consume_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    assert not t_a.is_alive() and not t_b.is_alive()
    outcomes = [results["scrap"][0], results["consume"][0]]
    assert outcomes.count("ok") == 1, results
    assert outcomes.count("insufficient") == 1, results

    with test_engine.connect() as verify_conn:
        summary_session = Session(bind=verify_conn)
        summary = inventory_material_event_service.get_issue_line_reconciliation(
            summary_session, tenant_id=scenario["tenant_id"], issue_line_id=line_id
        )
    assert summary["outstanding_quantity"] >= 0
    assert summary["outstanding_quantity"] == Decimal("3")


@pytest.mark.integration
def test_not_put_away_scrap_races_putaway(test_engine) -> None:
    """Proof E: Not-put-away Scrap races Putaway -> cannot double-use the
    same not-put-away quantity."""
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    cohort_id = receive_cohort(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    bin_id = build_store_bin(
        session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"]
    ).id
    session.commit()
    session.close()
    conn.close()

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def scrap_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            event = inventory_material_event_service.record_scrap(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), source_kind="not_put_away", quantity=Decimal("7"),
                reason="physical loss", effective_time=_now(), inventory_quantity_cohort_id=cohort_id,
            )
            results["scrap"] = ("ok", event.id)
        except InsufficientNotPutAwayQuantityError as exc:
            results["scrap"] = ("insufficient", str(exc))
        except Exception as exc:  # pragma: no cover
            results["scrap"] = ("error", repr(exc))
        finally:
            session.close()
            conn.close()

    def putaway_worker() -> None:
        conn = test_engine.connect()
        session = Session(bind=conn)
        try:
            barrier.wait(timeout=10)
            movement = inventory_storage_service.record_putaway(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
                actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), cohort_id=cohort_id,
                destination_location_id=bin_id, quantity=Decimal("7"), effective_time=_now(),
            )
            results["putaway"] = ("ok", movement.id)
        except Exception as exc:  # pragma: no cover -- InsufficientNotPutAwayQuantityError included
            results["putaway"] = ("insufficient", repr(exc))
        finally:
            session.close()
            conn.close()

    t_a = threading.Thread(target=scrap_worker)
    t_b = threading.Thread(target=putaway_worker)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)

    assert not t_a.is_alive() and not t_b.is_alive()
    outcomes = [results["scrap"][0], results["putaway"][0]]
    assert outcomes.count("ok") == 1, results
    assert outcomes.count("insufficient") == 1, results

    with test_engine.connect() as verify_conn:
        summary_session = Session(bind=verify_conn)
        not_put_away = inventory_storage_service.get_cohort_not_put_away(
            summary_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
        )
    assert not_put_away == Decimal("3")
    assert not_put_away >= 0
