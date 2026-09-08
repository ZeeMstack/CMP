"""STORE-INV-003: Issue -- direct Issue, Issue against Reservation, custody
integration with "Not put away"/"Issued to operations", and Quality safety.
Issue is a CUSTODY TRANSFER: it never touches Existence, never reappears as
"Not put away", and never steals quantity a Reservation has already
claimed."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services import (
    inventory_availability_service,
    inventory_existence_ledger_service,
    inventory_issue_service,
    inventory_quality_service,
    inventory_reservation_service,
    inventory_storage_service,
)
from app.services.errors import (
    InactiveStorageBinError,
    InsufficientAvailableToIssueError,
    InsufficientReservationBalanceError,
    InsufficientStorageBinBalanceError,
    InventoryIssueSourceNotUsableError,
    ReservationLineItemMismatchError,
)
from app.services.inventory_issue_service import IssueLineInput
from app.services.inventory_reservation_service import ReservationLineInput
from tests._store_reservation_scenario import build_scenario, receive_and_putaway


def _now():
    return datetime.now(timezone.utc)


@pytest.mark.integration
def test_direct_issue_moves_custody_and_never_reappears_as_not_put_away(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )

    issue = inventory_issue_service.record_issue(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Fertigation prep", effective_time=_now(),
        lines=[
            IssueLineInput(
                inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                source_location_id=bin_id, quantity=Decimal("6"),
            )
        ],
    )
    assert issue.code.startswith("ISS-")

    not_put_away = inventory_storage_service.get_cohort_not_put_away(
        db_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
    )
    assert not_put_away == Decimal("0"), "Issue must never reappear as Not put away"

    bin_balance = inventory_existence_ledger_service.get_cohort_bin_balance(db_session, cohort_id=cohort_id, location_id=bin_id)
    assert bin_balance == Decimal("14")

    existence = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    assert existence == Decimal("20"), "Issue must never change Existence"

    issued_to_ops = inventory_availability_service.get_item_issued_to_operations_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert issued_to_ops == Decimal("6")

    in_store = inventory_availability_service.get_item_in_store_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert in_store == Decimal("14")


@pytest.mark.integration
def test_custody_reconciliation_full_putaway_then_issue(db_session, test_engine) -> None:
    """CTO closure check: Receipt 20 -> Putaway 20 (all of it, into Bin A)
    -> Issue 5. Must read exactly Existence=20, Not put away=0, In Store=15,
    Issued to operations=5, and the four must reconcile:
    Existence = Not put away + In Store + Issued to operations."""
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    inventory_issue_service.record_issue(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Reconciliation check A", effective_time=_now(),
        lines=[
            IssueLineInput(
                inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                source_location_id=bin_id, quantity=Decimal("5"),
            )
        ],
    )

    existence = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    not_put_away = inventory_storage_service.get_cohort_not_put_away(
        db_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
    )
    in_store = inventory_availability_service.get_item_in_store_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    issued_to_ops = inventory_availability_service.get_item_issued_to_operations_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )

    assert existence == Decimal("20")
    assert not_put_away == Decimal("0")
    assert in_store == Decimal("15")
    assert issued_to_ops == Decimal("5")
    assert not_put_away + in_store + issued_to_ops == existence, (
        "Existence must equal Not put away + In Store + Issued to operations"
    )


@pytest.mark.integration
def test_custody_reconciliation_partial_putaway_then_issue(db_session, test_engine) -> None:
    """CTO closure check: Receipt 20 -> Putaway 12 (only part of it, into
    Bin A) -> Issue 5 (from Bin A). Must read exactly Existence=20,
    Not put away=8, In Store=7, Issued to operations=5, reconciling to
    Existence -- and Issue must never move quantity BACK into Not put away
    (the never-putaway 8 stays exactly 8, before and after the Issue)."""
    scenario = build_scenario(test_engine)
    from tests._store_custody_scenario import build_store_bin, receive_cohort

    cohort_id = receive_cohort(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    bin_ = build_store_bin(db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
    inventory_storage_service.record_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
        quantity=Decimal("12"), effective_time=_now(),
    )
    db_session.commit()

    not_put_away_before = inventory_storage_service.get_cohort_not_put_away(
        db_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
    )
    assert not_put_away_before == Decimal("8")

    inventory_issue_service.record_issue(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Reconciliation check B", effective_time=_now(),
        lines=[
            IssueLineInput(
                inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                source_location_id=bin_.id, quantity=Decimal("5"),
            )
        ],
    )

    existence = inventory_existence_ledger_service.get_cohort_balance(db_session, cohort_id=cohort_id)
    not_put_away_after = inventory_storage_service.get_cohort_not_put_away(
        db_session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id
    )
    in_store = inventory_availability_service.get_item_in_store_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    issued_to_ops = inventory_availability_service.get_item_issued_to_operations_quantity(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )

    assert existence == Decimal("20")
    assert not_put_away_after == Decimal("8")
    assert not_put_away_after == not_put_away_before, "Issue must never move quantity back into Not put away"
    assert in_store == Decimal("7")
    assert issued_to_ops == Decimal("5")
    assert not_put_away_after + in_store + issued_to_ops == existence, (
        "Existence must equal Not put away + In Store + Issued to operations"
    )


@pytest.mark.integration
def test_direct_issue_cannot_exceed_available_to_issue_when_reservation_exists(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    inventory_reservation_service.create_reservation(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Committed for WO-2", effective_time=_now(),
        lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("8"))],
    )
    # 20 in store, 8 reserved -> only 12 available to issue directly.
    with pytest.raises(InsufficientAvailableToIssueError):
        inventory_issue_service.record_issue(
            db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), purpose="Too much direct",
            effective_time=_now(),
            lines=[
                IssueLineInput(
                    inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                    source_location_id=bin_id, quantity=Decimal("13"),
                )
            ],
        )


@pytest.mark.integration
def test_issue_against_reservation_matches_worked_example(db_session, test_engine) -> None:
    """docs' own worked example: 20 kg usable in Store, reserve 8 kg
    (available = 12). Issue 5 kg against the reservation: Store custody =
    15, Reservation remaining = 3, Available to issue = 12 (unchanged)."""
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    reservation = inventory_reservation_service.create_reservation(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Worked example", effective_time=_now(),
        lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("8"))],
    )
    line = inventory_reservation_service.list_reservation_lines(
        db_session, tenant_id=scenario["tenant_id"], reservation_id=reservation.id
    )[0]

    available_after_reserve = inventory_availability_service.get_item_available_to_issue(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert available_after_reserve == Decimal("12")

    inventory_issue_service.record_issue(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Issue against reservation", effective_time=_now(),
        reservation_id=reservation.id,
        lines=[
            IssueLineInput(
                inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                source_location_id=bin_id, quantity=Decimal("5"), reservation_line_id=line.id,
            )
        ],
    )

    store_custody = inventory_existence_ledger_service.get_cohort_bin_balance(db_session, cohort_id=cohort_id, location_id=bin_id)
    assert store_custody == Decimal("15")

    remaining = inventory_reservation_service.get_reservation_line_remaining(db_session, reservation_line_id=line.id)
    assert remaining == Decimal("3")

    available_after_issue = inventory_availability_service.get_item_available_to_issue(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert available_after_issue == Decimal("12"), "issuing against a reservation must not change Available to issue"


@pytest.mark.integration
def test_issue_against_reservation_rejects_wrong_item(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    other_item = _build_second_item(db_session, scenario)
    receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=other_item, quantity=Decimal("5"),
    )
    reservation = inventory_reservation_service.create_reservation(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Other item", effective_time=_now(),
        lines=[ReservationLineInput(inventory_item_id=other_item, quantity=Decimal("1"))],
    )
    line = inventory_reservation_service.list_reservation_lines(
        db_session, tenant_id=scenario["tenant_id"], reservation_id=reservation.id
    )[0]

    with pytest.raises(ReservationLineItemMismatchError):
        inventory_issue_service.record_issue(
            db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), purpose="Mismatch",
            effective_time=_now(),
            lines=[
                IssueLineInput(
                    inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                    source_location_id=bin_id, quantity=Decimal("1"), reservation_line_id=line.id,
                )
            ],
        )


@pytest.mark.integration
def test_issue_against_reservation_rejects_exceeding_remaining(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    reservation = inventory_reservation_service.create_reservation(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Small reservation", effective_time=_now(),
        lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("3"))],
    )
    line = inventory_reservation_service.list_reservation_lines(
        db_session, tenant_id=scenario["tenant_id"], reservation_id=reservation.id
    )[0]
    with pytest.raises(InsufficientReservationBalanceError):
        inventory_issue_service.record_issue(
            db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), purpose="Too much against reservation",
            effective_time=_now(),
            lines=[
                IssueLineInput(
                    inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                    source_location_id=bin_id, quantity=Decimal("4"), reservation_line_id=line.id,
                )
            ],
        )


@pytest.mark.integration
def test_issue_rejects_insufficient_bin_balance(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("5"),
    )
    with pytest.raises(InsufficientStorageBinBalanceError):
        inventory_issue_service.record_issue(
            db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), purpose="Overdraw",
            effective_time=_now(),
            lines=[
                IssueLineInput(
                    inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                    source_location_id=bin_id, quantity=Decimal("6"),
                )
            ],
        )


@pytest.mark.integration
def test_issue_rejects_inactive_bin(db_session, test_engine) -> None:
    """A store_bin can only ever be deactivated while it holds ZERO
    custody (an existing STORE-INV-002B invariant) -- so the only way to
    reach "issue from an inactive Bin" is to first empty it (transfer
    everything out), deactivate it, and only then attempt an Issue against
    it. `InactiveStorageBinError` must fire before the (also-true)
    insufficient-balance check."""
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("5"),
    )
    from app.services import inventory_storage_service, location_service
    from tests._store_custody_scenario import build_store_bin

    other_bin = build_store_bin(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"]
    )
    inventory_storage_service.record_transfer(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), cohort_id=cohort_id, source_location_id=bin_id,
        destination_location_id=other_bin.id, quantity=Decimal("5"), effective_time=_now(),
    )
    location_service.deactivate_location(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), location_id=bin_id,
    )
    with pytest.raises(InactiveStorageBinError):
        inventory_issue_service.record_issue(
            db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), purpose="From inactive bin",
            effective_time=_now(),
            lines=[
                IssueLineInput(
                    inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                    source_location_id=bin_id, quantity=Decimal("1"),
                )
            ],
        )


@pytest.mark.integration
def test_issue_rejects_non_usable_source(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("5"),
    )
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="REJECTED", effective_time=_now(), reason="contaminated",
    )
    db_session.commit()
    with pytest.raises(InventoryIssueSourceNotUsableError):
        inventory_issue_service.record_issue(
            db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), purpose="From rejected stock",
            effective_time=_now(),
            lines=[
                IssueLineInput(
                    inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                    source_location_id=bin_id, quantity=Decimal("1"),
                )
            ],
        )


@pytest.mark.integration
def test_issue_rejects_two_lines_overdrawing_the_same_bin_within_one_command(db_session, test_engine) -> None:
    """10 in one Bin. ONE multi-line Issue command with two lines each
    requesting 6 from the SAME cohort/Bin (together 12 > 10) must be
    rejected -- each line's own balance check must account for what an
    EARLIER line in the same command already claimed, not just the
    (unchanged, since nothing is inserted yet) pre-command snapshot."""
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    with pytest.raises(InsufficientStorageBinBalanceError):
        inventory_issue_service.record_issue(
            db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), purpose="Same-source double claim",
            effective_time=_now(),
            lines=[
                IssueLineInput(
                    inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                    source_location_id=bin_id, quantity=Decimal("6"),
                ),
                IssueLineInput(
                    inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                    source_location_id=bin_id, quantity=Decimal("6"),
                ),
            ],
        )
    # No partial effect -- the whole command is one atomic transaction.
    bin_balance = inventory_existence_ledger_service.get_cohort_bin_balance(db_session, cohort_id=cohort_id, location_id=bin_id)
    assert bin_balance == Decimal("10")


@pytest.mark.integration
def test_issue_rejects_two_lines_overdrawing_the_same_reservation_line_within_one_command(db_session, test_engine) -> None:
    """Reservation line has 10 remaining. ONE multi-line Issue command with
    two lines each claiming 6 against the SAME reservation line (together
    12 > 10) must be rejected."""
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    reservation = inventory_reservation_service.create_reservation(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Same-line double claim", effective_time=_now(),
        lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("10"))],
    )
    line = inventory_reservation_service.list_reservation_lines(
        db_session, tenant_id=scenario["tenant_id"], reservation_id=reservation.id
    )[0]
    with pytest.raises(InsufficientReservationBalanceError):
        inventory_issue_service.record_issue(
            db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(), purpose="Double reservation claim",
            effective_time=_now(),
            lines=[
                IssueLineInput(
                    inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                    source_location_id=bin_id, quantity=Decimal("6"), reservation_line_id=line.id,
                ),
                IssueLineInput(
                    inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                    source_location_id=bin_id, quantity=Decimal("6"), reservation_line_id=line.id,
                ),
            ],
        )
    remaining = inventory_reservation_service.get_reservation_line_remaining(db_session, reservation_line_id=line.id)
    assert remaining == Decimal("10")


@pytest.mark.integration
def test_issue_is_idempotent(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    cohort_id, bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    client_command_id = uuid.uuid4()
    kwargs = dict(
        tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=client_command_id, purpose="Idempotent issue", effective_time=_now(),
        lines=[
            IssueLineInput(
                inventory_item_id=scenario["item_id"], inventory_quantity_cohort_id=cohort_id,
                source_location_id=bin_id, quantity=Decimal("4"),
            )
        ],
    )
    first = inventory_issue_service.record_issue(db_session, **kwargs)
    second = inventory_issue_service.record_issue(db_session, **kwargs)
    assert first.id == second.id
    bin_balance = inventory_existence_ledger_service.get_cohort_bin_balance(db_session, cohort_id=cohort_id, location_id=bin_id)
    assert bin_balance == Decimal("6"), "a replayed issue command must not double-debit custody"


def _build_second_item(db_session, scenario) -> uuid.UUID:
    from app.services import inventory_category_service, inventory_item_service
    from tests._store_inv_scenario import uom_id

    category = inventory_category_service.register_inventory_category(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
        code=f"CAT-{uuid.uuid4().hex[:8]}", name="Second Category",
    )
    item = inventory_item_service.register_inventory_item(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
        code=f"ITEM-{uuid.uuid4().hex[:8]}", name="Second Item", category_id=category.id,
        base_uom_id=uom_id(db_session, "kg"), lot_tracking_required=False, expiry_tracking_required=False,
        qc_release_required=False,
    )
    db_session.commit()
    return item.id
