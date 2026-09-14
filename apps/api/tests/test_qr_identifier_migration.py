"""PILOT-SCAN-001 focused DB-level tests for `qr_identifiers` (migration
29d6697de6d5): the partial unique index that makes "one active QR per
entity" a real database constraint (not merely a service-layer check), the
immutability trigger, and the no-hard-delete trigger. Mirrors this
codebase's existing per-migration test convention (e.g.
`test_farm_work_item_migration.py`) -- direct SQL/ORM against `db_session`,
never through the service layer, so these prove the SCHEMA itself is
correct independent of `qr_service`'s own behavior."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.qr_identifier import QrIdentifier


def _insert_qr(db_session, *, tenant_id, farm_id, carrier_id, user_id, token=None):
    identifier = QrIdentifier(
        tenant_id=tenant_id, farm_id=farm_id, entity_type="carrier", carrier_id=carrier_id,
        token=token or uuid.uuid4().hex, status="active", created_by_user_id=user_id,
    )
    db_session.add(identifier)
    db_session.flush()
    return identifier


@pytest.fixture
def carrier_scenario(db_session, active_context_with_farm):
    """PILOT-SCAN-001D: builds its Carrier via direct ORM insert, never
    `carrier_service.register_carrier` -- that service now auto-provisions
    a permanent QR identity at creation, which would leave this fixture's
    Carrier already holding an active `QrIdentifier` before any test here
    inserts its own via `_insert_qr`, corrupting every test below's own
    "first identity"/"second identity" precondition. Matches this file's
    own stated philosophy even better than the service call did: these
    tests prove the `qr_identifiers` SCHEMA itself, independent of
    `qr_service`'s (or now `carrier_service`'s) own behavior."""
    from app.models.carrier import Carrier

    tenant, user, headers, farm = active_context_with_farm
    from tests.conftest import ensure_seed_tray_specification

    spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier = Carrier(
        tenant_id=tenant.id, farm_id=farm.id, carrier_type_id=spec.carrier_type_id,
        specification_id=spec.id, code="QR-CARRIER-0001",
    )
    db_session.add(carrier)
    db_session.commit()
    return tenant, user, farm, carrier


@pytest.mark.integration
def test_active_unique_index_rejects_second_active_identity(db_session, carrier_scenario) -> None:
    tenant, user, farm, carrier = carrier_scenario
    _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    db_session.commit()

    with pytest.raises(IntegrityError):
        _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    db_session.rollback()


@pytest.mark.integration
def test_a_revoked_identity_does_not_block_a_new_active_one(db_session, carrier_scenario) -> None:
    tenant, user, farm, carrier = carrier_scenario
    first = _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    first.status = "revoked"
    first.revoked_at = datetime.now(timezone.utc)
    first.revoked_by_user_id = user.id
    db_session.commit()

    second = _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    db_session.commit()
    assert second.id != first.id


@pytest.mark.integration
def test_token_is_globally_unique(db_session, carrier_scenario) -> None:
    tenant, user, farm, carrier = carrier_scenario
    _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id, token="dup-token")
    db_session.commit()

    from app.models.carrier import Carrier

    # PILOT-SCAN-001D: direct ORM insert, not `carrier_service.register_carrier`
    # -- that would auto-provision this Carrier's own active QR and make
    # the assertion below trip the (also-real, but different) "one active
    # QR per Carrier" constraint instead of the GLOBAL token-uniqueness
    # constraint this test specifically exists to prove.
    other_carrier = Carrier(
        tenant_id=tenant.id, farm_id=farm.id, carrier_type_id=carrier.carrier_type_id,
        specification_id=carrier.specification_id, code="QR-CARRIER-0002",
    )
    db_session.add(other_carrier)
    db_session.commit()
    with pytest.raises(IntegrityError):
        _insert_qr(
            db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=other_carrier.id, user_id=user.id,
            token="dup-token",
        )
    db_session.rollback()


@pytest.mark.integration
def test_identity_fields_are_immutable(db_session, carrier_scenario) -> None:
    tenant, user, farm, carrier = carrier_scenario
    identifier = _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    db_session.commit()

    identifier.token = "changed-token"
    with pytest.raises(DBAPIError):
        db_session.flush()
    db_session.rollback()


@pytest.mark.integration
def test_status_may_change_after_insert(db_session, carrier_scenario) -> None:
    tenant, user, farm, carrier = carrier_scenario
    identifier = _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    db_session.commit()

    revoker_id = user.id  # read before mutating, so autoflush never sees a partial revocation shape
    identifier.status = "revoked"
    identifier.revoked_at = datetime.now(timezone.utc)
    identifier.revoked_by_user_id = revoker_id
    db_session.flush()
    db_session.commit()


@pytest.mark.integration
def test_hard_delete_is_rejected(db_session, carrier_scenario) -> None:
    tenant, user, farm, carrier = carrier_scenario
    identifier = _insert_qr(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id, user_id=user.id)
    db_session.commit()

    db_session.delete(identifier)
    with pytest.raises(DBAPIError):
        db_session.flush()
    db_session.rollback()
