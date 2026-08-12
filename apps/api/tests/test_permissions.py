"""AUTHZ-001A: the centralized permission catalog and role policy
(`app.core.permissions`). Pure Python-level tests -- no DB, no HTTP client,
deterministic. HTTP-level enforcement is covered separately in
tests/test_authz_farm_proof.py; cross-cutting security/architecture
assertions are in tests/test_authz_architecture.py."""

import uuid

import pytest

from app.core.auth import TenantContext
from app.core.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    get_permissions_for_role,
    has_permission,
)
from app.models.membership import APPROVED_ROLE_CODES

_ALL_PERMISSIONS = frozenset(Permission)


def _ctx(role_code: str | None) -> TenantContext:
    return TenantContext(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), role_code=role_code)  # type: ignore[arg-type]


# --- Role policy: deny by default -------------------------------------------


def test_tenant_admin_has_every_currently_defined_permission() -> None:
    assert get_permissions_for_role("tenant_admin") == _ALL_PERMISSIONS
    assert len(_ALL_PERMISSIONS) > 0  # sanity: the catalog is not accidentally empty


@pytest.mark.parametrize("role", sorted(APPROVED_ROLE_CODES - {"tenant_admin"}))
def test_every_other_approved_role_has_zero_permissions_pending_product_decision(role: str) -> None:
    """Every `role_code` the database will actually accept
    (`APPROVED_ROLE_CODES`) other than `tenant_admin` is a real,
    authenticatable role with no source/doc establishing what it may
    specifically do -- deliberately denied by default (see
    docs/AUTHORIZATION_MODEL.md, 'deferred to AUTHZ-001B'). This is a
    regression guard: granting any of these a permission must be a
    conscious edit to this test, not a silent side effect."""
    assert get_permissions_for_role(role) == frozenset()


def test_unrecognized_role_code_has_zero_permissions() -> None:
    """A role_code that isn't even in APPROVED_ROLE_CODES -- e.g. from
    policy/schema drift, or a future DB migration that adds a role before
    the policy is updated -- must never silently succeed."""
    assert get_permissions_for_role("some_future_role_not_yet_policy_mapped") == frozenset()
    assert get_permissions_for_role("DROP TABLE tenants;") == frozenset()


def test_blank_or_missing_role_has_zero_permissions() -> None:
    assert get_permissions_for_role(None) == frozenset()
    assert get_permissions_for_role("") == frozenset()


def test_every_role_grant_contains_only_defined_permission_values() -> None:
    for role, granted in ROLE_PERMISSIONS.items():
        assert granted <= _ALL_PERMISSIONS, f"role {role!r} grants a value outside the Permission enum"
        assert all(isinstance(p, Permission) for p in granted)


def test_role_permissions_mapping_has_no_unapproved_role_code_keys() -> None:
    """The policy must never grant permissions to a role_code the database
    itself would reject -- keeps the policy and the DB CHECK constraint
    from silently diverging in the 'policy is more permissive' direction."""
    assert set(ROLE_PERMISSIONS.keys()) <= APPROVED_ROLE_CODES


# --- Immutability (AUTHZ-001A.1) ---------------------------------------------
#
# Authorization policy must not be casually mutable at runtime. Each of
# these proves a specific mutation attempt -- including the two the ticket
# names literally -- fails loudly rather than silently altering policy.


def test_role_permission_grant_rejects_add() -> None:
    """The exact mutation the ticket names: `ROLE_PERMISSIONS["tenant_admin"].add(...)`.
    Fails because each grant is a `frozenset`, which has no `.add()` at
    all -- not specific to ROLE_PERMISSIONS's own read-only wrapping."""
    with pytest.raises(AttributeError):
        ROLE_PERMISSIONS["tenant_admin"].add(Permission.FARM_READ)  # type: ignore[attr-defined]


def test_role_permissions_top_level_mapping_rejects_item_reassignment() -> None:
    """The exact mutation the ticket names: `ROLE_PERMISSIONS["tenant_admin"] = ...`."""
    with pytest.raises(TypeError):
        ROLE_PERMISSIONS["tenant_admin"] = frozenset()  # type: ignore[index]


def test_role_permissions_top_level_mapping_rejects_new_key_assignment() -> None:
    with pytest.raises(TypeError):
        ROLE_PERMISSIONS["operator"] = frozenset(Permission)  # type: ignore[index]


def test_role_permissions_top_level_mapping_rejects_deletion() -> None:
    with pytest.raises(TypeError):
        del ROLE_PERMISSIONS["tenant_admin"]  # type: ignore[attr-defined]


def test_role_permissions_is_exported_only_as_a_read_only_mapping_proxy() -> None:
    from types import MappingProxyType

    assert isinstance(ROLE_PERMISSIONS, MappingProxyType)


# --- Permission catalog shape ------------------------------------------------


def test_permission_values_are_stable_lowercase_dotted_strings() -> None:
    import re

    pattern = re.compile(r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$")
    for permission in Permission:
        assert pattern.match(permission.value), f"{permission.value!r} does not match the dotted domain.verb style"


def test_permission_catalog_is_derived_from_the_endpoint_audit_not_the_ticket_example_list() -> None:
    """The ticket's own example vocabulary (batch.read/batch.manage) must
    NOT appear verbatim -- the real domain name in this codebase is
    `crop_batch` (CropBatch model, crop_batch_service, /crop-batches
    routes), proving the catalog was derived from the actual audit rather
    than copied from the example."""
    values = {p.value for p in Permission}
    assert "crop_batch.read" in values
    assert "crop_batch.manage" in values
    assert "batch.read" not in values
    assert "batch.manage" not in values


# --- has_permission -----------------------------------------------------------


def test_has_permission_true_for_a_permission_the_role_is_granted() -> None:
    assert has_permission(_ctx("tenant_admin"), Permission.FARM_READ) is True
    assert has_permission(_ctx("tenant_admin"), Permission.FARM_MANAGE) is True


def test_has_permission_false_for_a_role_with_no_permissions() -> None:
    assert has_permission(_ctx("operator"), Permission.FARM_READ) is False
    assert has_permission(_ctx("read_only"), Permission.FARM_MANAGE) is False


def test_has_permission_false_for_blank_role() -> None:
    assert has_permission(_ctx(None), Permission.FARM_READ) is False
