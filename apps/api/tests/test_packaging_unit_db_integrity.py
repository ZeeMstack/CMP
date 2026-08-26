"""POSTHARVEST-OPS-001B pre-commit verification: direct-SQL proofs of the
PackagingUnit lifecycle-transition trigger's exact semantics
(`enforce_packaging_unit_transition`, migration e8d5f3a2b6c1).

The frozen invariant: PackagingUnit stable identity fields (tenant_id,
code, name, created_at, client_command_id, request_fingerprint) are
immutable under every circumstance; the ONLY permitted UPDATE is
status: active -> retired, with every stable field byte-identical and
`retirement_client_command_id`/`retirement_request_fingerprint` populated
together with it (the one pair deliberately excluded from the
immutability check, since they exist precisely to change during this one
transition). All of active->active, retired->active, retired->retired,
a stable-field change alongside a valid status transition, a stable-field
change with no status transition at all, and hard DELETE must be
independently proven rejected -- never a service-only bypass."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services import packaging_unit_service


def _register(db_session, tenant, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), code="CARTON", name="Carton",
    )
    defaults.update(overrides)
    return packaging_unit_service.register_packaging_unit(db_session, **defaults)


def _retire(db_session, tenant, unit, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=None, client_command_id=uuid.uuid4(), packaging_unit_id=unit.id,
    )
    defaults.update(overrides)
    return packaging_unit_service.retire_packaging_unit(db_session, **defaults)


@pytest.mark.integration
def test_direct_sql_active_to_retired_with_no_other_change_succeeds(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)

    with db_session.begin_nested():
        db_session.execute(
            text(
                "UPDATE packaging_units SET status = 'retired', retirement_client_command_id = :cmd, "
                "retirement_request_fingerprint = 'fp' WHERE id = :id"
            ),
            {"cmd": uuid.uuid4(), "id": unit.id},
        )

    db_session.refresh(unit)
    assert unit.status == "retired"
    assert unit.code == "CARTON"
    assert unit.name == "Carton"


@pytest.mark.integration
def test_direct_sql_retirement_with_name_change_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "UPDATE packaging_units SET status = 'retired', name = 'Changed', "
                    "retirement_client_command_id = :cmd, retirement_request_fingerprint = 'fp' WHERE id = :id"
                ),
                {"cmd": uuid.uuid4(), "id": unit.id},
            )

    db_session.refresh(unit)
    assert unit.status == "active"
    assert unit.name == "Carton"


@pytest.mark.integration
def test_direct_sql_retirement_with_code_change_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "UPDATE packaging_units SET status = 'retired', code = 'CHANGED', "
                    "retirement_client_command_id = :cmd, retirement_request_fingerprint = 'fp' WHERE id = :id"
                ),
                {"cmd": uuid.uuid4(), "id": unit.id},
            )

    db_session.refresh(unit)
    assert unit.status == "active"
    assert unit.code == "CARTON"


@pytest.mark.integration
def test_direct_sql_retired_to_active_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)
    _retire(db_session, tenant, unit)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "UPDATE packaging_units SET status = 'active', retirement_client_command_id = NULL, "
                    "retirement_request_fingerprint = NULL WHERE id = :id"
                ),
                {"id": unit.id},
            )

    db_session.refresh(unit)
    assert unit.status == "retired"


@pytest.mark.integration
def test_direct_sql_identity_only_update_with_no_status_change_rejected(db_session, active_context) -> None:
    """A stable-field mutation with status left completely unchanged (still
    'active') -- distinct from the retirement-combined cases above, this
    proves the identity-immutability rule fires independently of any
    lifecycle transition."""
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("UPDATE packaging_units SET name = 'Changed' WHERE id = :id"), {"id": unit.id})

    db_session.refresh(unit)
    assert unit.name == "Carton"
    assert unit.status == "active"


@pytest.mark.integration
def test_direct_sql_active_to_active_noop_update_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("UPDATE packaging_units SET status = 'active' WHERE id = :id"), {"id": unit.id})


@pytest.mark.integration
def test_direct_sql_retired_to_retired_noop_update_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)
    _retire(db_session, tenant, unit)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("UPDATE packaging_units SET status = 'retired' WHERE id = :id"), {"id": unit.id})


@pytest.mark.integration
def test_direct_sql_hard_delete_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM packaging_units WHERE id = :id"), {"id": unit.id})


@pytest.mark.integration
def test_direct_sql_hard_delete_of_retired_unit_rejected(db_session, active_context) -> None:
    tenant, _user, _headers = active_context
    unit = _register(db_session, tenant)
    _retire(db_session, tenant, unit)

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM packaging_units WHERE id = :id"), {"id": unit.id})
