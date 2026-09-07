"""STORE-INV-002B: physical custody / putaway -- service-level and API-level
tests for `inventory_storage_service.py`, the `location_service.py`
bin-deactivation guard, the existence/custody safety invariant in
`inventory_existence_ledger_service.py`, and the Quality-split x custody
integration seam in `inventory_quality_service.py`."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services import inventory_existence_ledger_service, inventory_quality_service, inventory_storage_service, location_service
from app.services.errors import (
    ExistenceBelowCustodyError,
    IneligibleStorageBinError,
    InactiveStorageBinError,
    InsufficientNotPutAwayQuantityError,
    InsufficientStorageBinBalanceError,
    InventoryQuantityCohortSplitAllocationExceedsBalanceError,
    InventoryStorageCommandReusedWithDifferentPayloadError,
    LocationHasActiveInventoryCustodyError,
    StorageBinNotFoundError,
    StorageBinsMustDifferError,
)
from tests._store_custody_scenario import build_scenario, build_store_bin, receive_cohort
from tests._store_inv_scenario import build_category, build_item, uom_id


def _now():
    return datetime.now(timezone.utc)


@pytest.mark.integration
def test_putaway_happy_path_reduces_not_put_away(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("100"),
        )
        bin_ = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()

        movement = inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
            quantity=Decimal("40"), effective_time=_now(),
        )
        assert movement.movement_kind == "putaway"
        not_put_away = inventory_storage_service.get_cohort_not_put_away(session, tenant_id=scenario["tenant_id"], cohort_id=cohort_id)
        assert not_put_away == Decimal("60")
        bin_balance = inventory_existence_ledger_service.get_cohort_bin_balance(session, cohort_id=cohort_id, location_id=bin_.id)
        assert bin_balance == Decimal("40")
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_putaway_exceeding_not_put_away_rejected(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        bin_ = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()

        with pytest.raises(InsufficientNotPutAwayQuantityError):
            inventory_storage_service.record_putaway(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
                quantity=Decimal("11"), effective_time=_now(),
            )
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_putaway_into_non_bin_location_rejected(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        store = location_service.create_location(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            location_type_code="store", code=f"STORE-{uuid.uuid4().hex[:8]}", name="Plain Store",
            parent_location_id=None, greenhouse_classification=None, occupiable=None,
        )
        session.commit()

        with pytest.raises(IneligibleStorageBinError):
            inventory_storage_service.record_putaway(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=store.id,
                quantity=Decimal("5"), effective_time=_now(),
            )
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_putaway_into_inactive_bin_rejected(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        bin_ = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()
        location_service.deactivate_location(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), location_id=bin_.id,
        )
        session.commit()

        with pytest.raises(InactiveStorageBinError):
            inventory_storage_service.record_putaway(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
                quantity=Decimal("5"), effective_time=_now(),
            )
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_putaway_unknown_bin_rejected(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        session.commit()

        with pytest.raises(StorageBinNotFoundError):
            inventory_storage_service.record_putaway(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=uuid.uuid4(),
                quantity=Decimal("5"), effective_time=_now(),
            )
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_putaway_idempotent_replay_and_conflict(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("100"),
        )
        bin_ = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()
        client_command_id = uuid.uuid4()
        effective_time = _now()

        first = inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=client_command_id, cohort_id=cohort_id, destination_location_id=bin_.id,
            quantity=Decimal("40"), effective_time=effective_time,
        )
        replay = inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=client_command_id, cohort_id=cohort_id, destination_location_id=bin_.id,
            quantity=Decimal("40"), effective_time=effective_time,
        )
        assert replay.id == first.id

        with pytest.raises(InventoryStorageCommandReusedWithDifferentPayloadError):
            inventory_storage_service.record_putaway(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=client_command_id, cohort_id=cohort_id, destination_location_id=bin_.id,
                quantity=Decimal("41"), effective_time=effective_time,
            )
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_transfer_happy_path_moves_between_bins(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("100"),
        )
        bin_a = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        bin_b = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()
        inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_a.id,
            quantity=Decimal("50"), effective_time=_now(),
        )
        session.commit()

        inventory_storage_service.record_transfer(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, source_location_id=bin_a.id,
            destination_location_id=bin_b.id, quantity=Decimal("20"), effective_time=_now(),
        )
        assert inventory_existence_ledger_service.get_cohort_bin_balance(session, cohort_id=cohort_id, location_id=bin_a.id) == Decimal("30")
        assert inventory_existence_ledger_service.get_cohort_bin_balance(session, cohort_id=cohort_id, location_id=bin_b.id) == Decimal("20")
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_transfer_same_bin_rejected(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        bin_ = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()

        with pytest.raises(StorageBinsMustDifferError):
            inventory_storage_service.record_transfer(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), cohort_id=cohort_id, source_location_id=bin_.id,
                destination_location_id=bin_.id, quantity=Decimal("5"), effective_time=_now(),
            )
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_transfer_exceeding_source_bin_balance_rejected(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        bin_a = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        bin_b = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()
        inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_a.id,
            quantity=Decimal("5"), effective_time=_now(),
        )
        session.commit()

        with pytest.raises(InsufficientStorageBinBalanceError):
            inventory_storage_service.record_transfer(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), cohort_id=cohort_id, source_location_id=bin_a.id,
                destination_location_id=bin_b.id, quantity=Decimal("6"), effective_time=_now(),
            )
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_existence_adjustment_below_custody_rejected(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("100"),
        )
        bin_ = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()
        inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
            quantity=Decimal("90"), effective_time=_now(),
        )
        session.commit()

        with pytest.raises(ExistenceBelowCustodyError):
            inventory_existence_ledger_service.record_adjustment(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), cohort_id=cohort_id, quantity_delta=Decimal("-20"),
                effective_time=_now(), reason="test overdraw below custody",
            )
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_bin_deactivation_blocked_by_nonzero_custody(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        bin_ = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()
        inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
            quantity=Decimal("10"), effective_time=_now(),
        )
        session.commit()

        with pytest.raises(LocationHasActiveInventoryCustodyError):
            location_service.deactivate_location(
                session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
                client_command_id=uuid.uuid4(), location_id=bin_.id,
            )
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_bin_deactivation_allowed_after_custody_fully_transferred_out(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("10"),
        )
        bin_a = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        bin_b = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()
        inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_a.id,
            quantity=Decimal("10"), effective_time=_now(),
        )
        session.commit()
        inventory_storage_service.record_transfer(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, source_location_id=bin_a.id,
            destination_location_id=bin_b.id, quantity=Decimal("10"), effective_time=_now(),
        )
        session.commit()

        deactivated = location_service.deactivate_location(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), location_id=bin_a.id,
        )
        assert deactivated.status == "inactive"
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_quality_partial_split_against_not_put_away_bucket(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("100"),
        )
        session.commit()

        child = inventory_quality_service.apply_quality_disposition_to_partial_quantity(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
            source_cohort_id=cohort_id, quantity=Decimal("30"), disposition="HELD", effective_time=_now(),
            reason="partial hold", custody_location_id=None,
        )
        assert inventory_existence_ledger_service.get_cohort_balance(session, cohort_id=child.id) == Decimal("30")
        assert inventory_storage_service.get_cohort_not_put_away(session, tenant_id=scenario["tenant_id"], cohort_id=child.id) == Decimal("30")
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_quality_partial_split_against_bin_bucket_reassigns_custody(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("100"),
        )
        bin_ = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()
        inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
            quantity=Decimal("60"), effective_time=_now(),
        )
        session.commit()

        child = inventory_quality_service.apply_quality_disposition_to_partial_quantity(
            session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
            source_cohort_id=cohort_id, quantity=Decimal("25"), disposition="HELD", effective_time=_now(),
            reason="partial hold in bin", custody_location_id=bin_.id,
        )
        # Bin's own total is unchanged -- 60 stayed in the bin, only which
        # cohort owns 25 of it changed.
        parent_bin_balance = inventory_existence_ledger_service.get_cohort_bin_balance(session, cohort_id=cohort_id, location_id=bin_.id)
        child_bin_balance = inventory_existence_ledger_service.get_cohort_bin_balance(session, cohort_id=child.id, location_id=bin_.id)
        assert parent_bin_balance == Decimal("35")
        assert child_bin_balance == Decimal("25")
        assert parent_bin_balance + child_bin_balance == Decimal("60")
    finally:
        session.close()
        conn.close()


@pytest.mark.integration
def test_quality_partial_split_against_bin_exceeding_bin_balance_rejected(test_engine) -> None:
    scenario = build_scenario(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        cohort_id = receive_cohort(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            item_id=scenario["item_id"], quantity=Decimal("100"),
        )
        bin_ = build_store_bin(session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"])
        session.commit()
        inventory_storage_service.record_putaway(
            session, tenant_id=scenario["tenant_id"], farm_id=scenario["farm_id"], actor_user_id=scenario["user_id"],
            client_command_id=uuid.uuid4(), cohort_id=cohort_id, destination_location_id=bin_.id,
            quantity=Decimal("20"), effective_time=_now(),
        )
        session.commit()

        # 70 not-put-away exists on the cohort overall, but only 20 sits in
        # this specific bin -- the bucket-aware check must reject against
        # the BIN's own balance, not the cohort's whole existence.
        with pytest.raises(InventoryQuantityCohortSplitAllocationExceedsBalanceError):
            inventory_quality_service.apply_quality_disposition_to_partial_quantity(
                session, tenant_id=scenario["tenant_id"], actor_user_id=scenario["user_id"], client_command_id=uuid.uuid4(),
                source_cohort_id=cohort_id, quantity=Decimal("21"), disposition="HELD", effective_time=_now(),
                reason="exceeds bin balance", custody_location_id=bin_.id,
            )
    finally:
        session.close()
        conn.close()


@pytest.fixture(autouse=True)
def _enable_dev_auth(monkeypatch):
    """Mirrors `test_store_inv_002a2_quality_http.py`'s own sanctioned
    monkeypatch -- this local `.env` runs with `ENABLE_DEV_AUTH=false`."""
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)


def _membership_headers(db_session, *, tenant_id, role_code: str) -> dict[str, str]:
    from app.services import membership_service, user_service

    user = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"custody-{uuid.uuid4().hex}",
        email=f"{uuid.uuid4().hex}@example.com", display_name="Custody HTTP Test User",
    )
    membership_service.add_membership(db_session, tenant_id=tenant_id, user_id=user.id, role_code=role_code, actor_user_id=None)
    return user, {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user.id)}


@pytest.mark.integration
def test_api_putaway_qc_officer_denied_storekeeper_allowed(client, db_session) -> None:
    from app.services import farm_service, tenant_service

    tenant = tenant_service.create_tenant(db_session, code=f"t-custody-{uuid.uuid4().hex[:8]}", name="Custody HTTP Tenant")
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=None, code="custody-farm", name="Custody Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    receiver, _ = _membership_headers(db_session, tenant_id=tenant.id, role_code="storekeeper")
    _qc_user, qc_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="qc_officer")
    _sk_user, sk_headers = _membership_headers(db_session, tenant_id=tenant.id, role_code="storekeeper")

    category = build_category(db_session, tenant, actor_user_id=receiver.id)
    item = build_item(db_session, tenant, category.id, uom_id(db_session, "kg"), actor_user_id=receiver.id)
    cohort_id = receive_cohort(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=receiver.id, item_id=item.id,
        quantity=Decimal("10"),
    )
    bin_ = build_store_bin(db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=receiver.id)
    db_session.commit()

    payload = {
        "client_command_id": str(uuid.uuid4()), "inventory_quantity_cohort_id": str(cohort_id),
        "destination_location_id": str(bin_.id), "quantity": "5", "effective_time": _now().isoformat(),
    }
    denied = client.post(f"/farms/{farm.id}/inventory-putaways", json=payload, headers=qc_headers)
    assert denied.status_code == 403, denied.text

    allowed = client.post(
        f"/farms/{farm.id}/inventory-putaways",
        json={**payload, "client_command_id": str(uuid.uuid4())}, headers=sk_headers,
    )
    assert allowed.status_code == 201, allowed.text
