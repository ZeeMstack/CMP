"""STORE-INV-003: Reservation -- create, release (partial/full), idempotent
replay, Available-to-issue derivation, and Quality x Reservation
interaction. Reservation is frozen at Farm + Item -- never touches
Existence, Quality, or physical custody."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services import inventory_availability_service, inventory_quality_service, inventory_reservation_service
from app.services.errors import (
    InsufficientAvailableToIssueError,
    InsufficientReservationBalanceError,
    InventoryReservationCommandReusedWithDifferentPayloadError,
    InventoryReservationReleaseCommandReusedWithDifferentPayloadError,
)
from app.services.inventory_reservation_service import ReservationLineInput
from tests._store_reservation_scenario import build_scenario, receive_and_putaway


def _now():
    return datetime.now(timezone.utc)


@pytest.mark.integration
def test_create_reservation_reduces_available_to_issue(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )

    available_before = inventory_availability_service.get_item_available_to_issue(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert available_before == Decimal("20")

    reservation = inventory_reservation_service.create_reservation(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Seeding WO-1", effective_time=_now(),
        lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("8"))],
    )
    assert reservation.code.startswith("RES-")

    available_after = inventory_availability_service.get_item_available_to_issue(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], inventory_item_id=scenario["item_id"]
    )
    assert available_after == Decimal("12")

    lines = inventory_reservation_service.list_reservation_lines(
        db_session, tenant_id=scenario["tenant_id"], reservation_id=reservation.id
    )
    assert len(lines) == 1
    remaining = inventory_reservation_service.get_reservation_line_remaining(db_session, reservation_line_id=lines[0].id)
    assert remaining == Decimal("8")


@pytest.mark.integration
def test_reservation_cannot_exceed_available_to_issue(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    with pytest.raises(InsufficientAvailableToIssueError):
        inventory_reservation_service.create_reservation(
            db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), purpose="Too much", effective_time=_now(),
            lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("11"))],
        )


@pytest.mark.integration
def test_reservation_create_is_idempotent(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    client_command_id = uuid.uuid4()
    kwargs = dict(
        tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=client_command_id, purpose="Idempotent", effective_time=_now(),
        lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("5"))],
    )
    first = inventory_reservation_service.create_reservation(db_session, **kwargs)
    second = inventory_reservation_service.create_reservation(db_session, **kwargs)
    assert first.id == second.id

    with pytest.raises(InventoryReservationCommandReusedWithDifferentPayloadError):
        inventory_reservation_service.create_reservation(
            db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
            actor_user_id=scenario["user_id"], client_command_id=client_command_id, purpose="Different payload",
            effective_time=_now(), lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("5"))],
        )


@pytest.mark.integration
def test_release_partial_then_full(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    reservation = inventory_reservation_service.create_reservation(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Release test", effective_time=_now(),
        lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("10"))],
    )
    line = inventory_reservation_service.list_reservation_lines(
        db_session, tenant_id=scenario["tenant_id"], reservation_id=reservation.id
    )[0]

    inventory_reservation_service.release_reservation_line(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
        reservation_line_id=line.id, quantity=Decimal("4"), effective_time=_now(), reason="no longer needed",
    )
    remaining = inventory_reservation_service.get_reservation_line_remaining(db_session, reservation_line_id=line.id)
    assert remaining == Decimal("6")

    # full release of the rest
    inventory_reservation_service.release_reservation_line(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
        reservation_line_id=line.id, quantity=Decimal("6"), effective_time=_now(),
    )
    remaining = inventory_reservation_service.get_reservation_line_remaining(db_session, reservation_line_id=line.id)
    assert remaining == Decimal("0")

    with pytest.raises(InsufficientReservationBalanceError):
        inventory_reservation_service.release_reservation_line(
            db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), reservation_line_id=line.id, quantity=Decimal("1"), effective_time=_now(),
        )


@pytest.mark.integration
def test_release_is_idempotent(db_session, test_engine) -> None:
    scenario = build_scenario(test_engine)
    receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("10"),
    )
    reservation = inventory_reservation_service.create_reservation(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Release idempotency", effective_time=_now(),
        lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("10"))],
    )
    line = inventory_reservation_service.list_reservation_lines(
        db_session, tenant_id=scenario["tenant_id"], reservation_id=reservation.id
    )[0]
    client_command_id = uuid.uuid4()
    kwargs = dict(
        tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=client_command_id,
        reservation_line_id=line.id, quantity=Decimal("3"), effective_time=_now(),
    )
    first = inventory_reservation_service.release_reservation_line(db_session, **kwargs)
    second = inventory_reservation_service.release_reservation_line(db_session, **kwargs)
    assert first.id == second.id

    with pytest.raises(InventoryReservationReleaseCommandReusedWithDifferentPayloadError):
        inventory_reservation_service.release_reservation_line(
            db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
            client_command_id=client_command_id, reservation_line_id=line.id, quantity=Decimal("4"),
            effective_time=_now(),
        )


@pytest.mark.integration
def test_reservation_blocked_by_quality_when_stock_later_held(db_session, test_engine) -> None:
    """A reservation is never silently reduced when Quality later removes
    usability -- it becomes "Blocked by quality" instead, and unblocks once
    usable stock is sufficient again (docs "Quality x Reservation")."""
    scenario = build_scenario(test_engine)
    cohort_id, _bin_id = receive_and_putaway(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        item_id=scenario["item_id"], quantity=Decimal("20"),
    )
    reservation = inventory_reservation_service.create_reservation(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
        client_command_id=uuid.uuid4(), purpose="Quality interaction", effective_time=_now(),
        lines=[ReservationLineInput(inventory_item_id=scenario["item_id"], quantity=Decimal("15"))],
    )
    line = inventory_reservation_service.list_reservation_lines(
        db_session, tenant_id=scenario["tenant_id"], reservation_id=reservation.id
    )[0]

    not_blocked = inventory_reservation_service.is_line_blocked_by_quality(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        inventory_item_id=scenario["item_id"], remaining=Decimal("15"),
    )
    assert not_blocked is False

    # Quality places the whole cohort on HOLD -- the Quality action must not
    # be blocked merely because a reservation exists, and the reservation
    # itself must not be silently reduced.
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=_now(), reason="contamination suspected",
    )
    db_session.commit()

    remaining = inventory_reservation_service.get_reservation_line_remaining(db_session, reservation_line_id=line.id)
    assert remaining == Decimal("15"), "quality action must never silently reduce a reservation"

    blocked = inventory_reservation_service.is_line_blocked_by_quality(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        inventory_item_id=scenario["item_id"], remaining=remaining,
    )
    assert blocked is True

    # Quality releases the hold -- usable stock is sufficient again.
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HOLD_RELEASED", effective_time=_now(), reason="cleared by lab",
    )
    db_session.commit()
    unblocked_again = inventory_reservation_service.is_line_blocked_by_quality(
        db_session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"],
        inventory_item_id=scenario["item_id"], remaining=remaining,
    )
    assert unblocked_again is False
