"""AUTHZ-001A: the centralized permission catalog and role policy
(`app.core.permissions`). Pure Python-level tests -- no DB, no HTTP client,
deterministic. HTTP-level enforcement is covered separately in
tests/test_authz_farm_proof.py; cross-cutting security/architecture
assertions are in tests/test_authz_architecture.py.

CARRIER-CONFIG-001 added `carrier_specification.read`/`carrier_specification.manage`
(deliberately separate from `carrier.read`/`carrier.manage` -- see
app/core/permissions.py) after Matrix A (AUTHZ-002B2, ROLE_PERMISSION_POLICY_PROPOSAL.md
section 12) was pinned below. Every role gets `carrier_specification.read`
matching its existing `carrier.read` grant; only `farm_manager` also gets
`carrier_specification.manage`, matching that role's existing sole ownership
of `carrier.manage`/farm-level equipment setup. See that document's
CARRIER-CONFIG-001 addendum (section 14) for the authorized grant.

BIOLOGICAL-DISPOSITION-AUTHZ-001 added `biological_disposition.correct`
(deliberately separate from `biological_disposition.manage` -- see
app/core/permissions.py), mirroring TRANSPLANT_CORRECT's own identical
split from TRANSPLANT_MANAGE exactly: `production_supervisor` keeps both
(same MANAGE+CORRECT pair as its existing Transplant grant); `farm_manager`/
`head_grower` gain CORRECT only, never MANAGE (same pattern as their
existing TRANSPLANT_CORRECT-without-TRANSPLANT_MANAGE grant); `operator`
keeps MANAGE only, explicitly excluded from CORRECT (same pattern as its
existing TRANSPLANT_MANAGE-without-TRANSPLANT_CORRECT grant). Catalog size
46 -> 47."""

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


# --- Role policy: Imperial Pilot activation (AUTHZ-002B2) -------------------
#
# EXPECTED_ROLE_GRANTS is an INDEPENDENT hand/mechanically-transcribed
# pin of docs/domain/ROLE_PERMISSION_POLICY_PROPOSAL.md's Matrix A
# ("Imperial Pilot", the current-implementable matrix), not a re-import
# of app.core.permissions.ROLE_PERMISSIONS -- comparing the policy
# against itself would be tautological and would never catch an
# accidental production edit. `farm_manager` uses that document's
# explicit MINIMUM tier (25 permissions, no `dispatch.manage`), not the
# optional 26-permission "broader pilot" tier.

EXPECTED_ROLE_GRANTS: dict[str, frozenset[Permission]] = {
    "farm_manager": frozenset({
        Permission.FARM_READ, Permission.FARM_MANAGE,
        Permission.LOCATION_READ, Permission.LOCATION_MANAGE,
        Permission.ASSET_READ, Permission.ASSET_MANAGE,
        Permission.CARRIER_READ, Permission.CARRIER_MANAGE,
        Permission.CARRIER_SPECIFICATION_READ, Permission.CARRIER_SPECIFICATION_MANAGE,
        Permission.CROP_READ,
        Permission.PRODUCTION_SYSTEM_READ,
        Permission.WORKFLOW_READ,
        Permission.CROP_BATCH_READ,
        Permission.BATCH_DERIVATION_READ,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ,
        Permission.TRANSPLANT_READ, Permission.TRANSPLANT_CORRECT,
        Permission.OBSERVATION_READ,
        Permission.BIOLOGICAL_DISPOSITION_CORRECT,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ,
        Permission.PACKING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ, Permission.RECALL_MANAGE,
        Permission.TRACEABILITY_READ,
    }),
    "head_grower": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.CROP_READ, Permission.CROP_MANAGE,
        Permission.PRODUCTION_SYSTEM_READ, Permission.PRODUCTION_SYSTEM_MANAGE,
        Permission.WORKFLOW_READ, Permission.WORKFLOW_MANAGE,
        Permission.CROP_BATCH_READ, Permission.CROP_BATCH_MANAGE,
        Permission.BATCH_DERIVATION_READ, Permission.BATCH_DERIVATION_MANAGE,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ,
        Permission.TRANSPLANT_READ, Permission.TRANSPLANT_CORRECT,
        Permission.OBSERVATION_READ, Permission.OBSERVATION_ENTRY_MANAGE,
        Permission.OBSERVATION_DEFINITION_MANAGE,
        Permission.BIOLOGICAL_DISPOSITION_CORRECT,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ, Permission.HARVEST_MANAGE,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    "production_supervisor": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.MOVEMENT_MANAGE,
        Permission.CROP_READ,
        Permission.PRODUCTION_SYSTEM_READ,
        Permission.WORKFLOW_READ,
        Permission.CROP_BATCH_READ, Permission.CROP_BATCH_MANAGE,
        Permission.BATCH_DERIVATION_READ, Permission.BATCH_DERIVATION_MANAGE,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ, Permission.SOWING_MANAGE,
        Permission.TRANSPLANT_READ, Permission.TRANSPLANT_MANAGE, Permission.TRANSPLANT_CORRECT,
        Permission.OBSERVATION_READ, Permission.OBSERVATION_ENTRY_MANAGE,
        Permission.BIOLOGICAL_DISPOSITION_MANAGE, Permission.BIOLOGICAL_DISPOSITION_CORRECT,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ, Permission.HARVEST_MANAGE,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    "operator": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.MOVEMENT_MANAGE,
        Permission.CROP_BATCH_READ,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ, Permission.SOWING_MANAGE,
        Permission.TRANSPLANT_READ, Permission.TRANSPLANT_MANAGE,
        Permission.OBSERVATION_READ, Permission.OBSERVATION_ENTRY_MANAGE,
        Permission.BIOLOGICAL_DISPOSITION_MANAGE,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ, Permission.HARVEST_MANAGE,
    }),
    "storekeeper": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.SEED_LOT_READ, Permission.SEED_LOT_MANAGE,
    }),
    "qc_officer": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.CROP_READ,
        Permission.CROP_BATCH_READ,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ,
        Permission.TRANSPLANT_READ,
        Permission.OBSERVATION_READ, Permission.OBSERVATION_ENTRY_MANAGE,
        Permission.QUALITY_HOLD_READ, Permission.QUALITY_HOLD_MANAGE,
        Permission.HARVEST_READ,
        Permission.PACKING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    "packing_supervisor": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.CROP_BATCH_READ,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ,
        Permission.PACKING_READ, Permission.PACKING_MANAGE,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    "cold_store_supervisor": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.QUALITY_HOLD_READ,
        Permission.PACKING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ, Permission.FINISHED_GOODS_STORAGE_MANAGE,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    "dispatch_officer": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.QUALITY_HOLD_READ,
        Permission.PACKING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ, Permission.DISPATCH_MANAGE,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    "auditor": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.CROP_READ,
        Permission.PRODUCTION_SYSTEM_READ,
        Permission.WORKFLOW_READ,
        Permission.CROP_BATCH_READ,
        Permission.BATCH_DERIVATION_READ,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ,
        Permission.TRANSPLANT_READ,
        Permission.OBSERVATION_READ,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ,
        Permission.PACKING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
    "read_only": frozenset({
        Permission.FARM_READ,
        Permission.LOCATION_READ,
        Permission.ASSET_READ,
        Permission.CARRIER_READ,
        Permission.CARRIER_SPECIFICATION_READ,
        Permission.CROP_READ,
        Permission.PRODUCTION_SYSTEM_READ,
        Permission.WORKFLOW_READ,
        Permission.CROP_BATCH_READ,
        Permission.BATCH_DERIVATION_READ,
        Permission.SEED_LOT_READ,
        Permission.SOWING_READ,
        Permission.TRANSPLANT_READ,
        Permission.OBSERVATION_READ,
        Permission.QUALITY_HOLD_READ,
        Permission.HARVEST_READ,
        Permission.PACKING_READ,
        Permission.FINISHED_GOODS_STORAGE_READ,
        Permission.DISPATCH_READ,
        Permission.RECALL_READ,
        Permission.TRACEABILITY_READ,
    }),
}

_EXPECTED_COUNTS = {
    "farm_manager": 29, "head_grower": 28, "production_supervisor": 28, "operator": 18,
    "storekeeper": 7, "qc_officer": 20, "packing_supervisor": 13, "cold_store_supervisor": 12,
    "dispatch_officer": 12, "auditor": 21, "read_only": 21,
}


def test_tenant_admin_has_every_currently_defined_permission() -> None:
    assert get_permissions_for_role("tenant_admin") == _ALL_PERMISSIONS
    assert len(_ALL_PERMISSIONS) > 0  # sanity: the catalog is not accidentally empty
    assert len(_ALL_PERMISSIONS) == 47


def test_expected_role_grants_covers_every_non_admin_approved_role() -> None:
    """The pin itself must cover exactly the 11 non-admin approved roles --
    catches a role silently missing from EXPECTED_ROLE_GRANTS before it
    could mask a missing/incorrect exact-set assertion below."""
    assert set(EXPECTED_ROLE_GRANTS.keys()) == APPROVED_ROLE_CODES - {"tenant_admin"}


@pytest.mark.parametrize("role", sorted(EXPECTED_ROLE_GRANTS.keys()))
def test_role_has_exactly_the_approved_imperial_pilot_permission_set(role: str) -> None:
    """AUTHZ-002B2: the Imperial Pilot policy is now active. Asserts the
    EXACT set, not merely a count -- a role gaining or losing any single
    permission fails this test even if the total count happens to still
    match. Counts are asserted separately below as a secondary,
    easier-to-read signal of *what* changed when this fails."""
    actual = get_permissions_for_role(role)
    expected = EXPECTED_ROLE_GRANTS[role]
    assert actual == expected, (
        f"{role}: missing {sorted(p.value for p in expected - actual)}, "
        f"unexpected {sorted(p.value for p in actual - expected)}"
    )


@pytest.mark.parametrize("role", sorted(EXPECTED_ROLE_GRANTS.keys()))
def test_role_permission_count_matches_approved_policy_document(role: str) -> None:
    assert len(get_permissions_for_role(role)) == _EXPECTED_COUNTS[role]


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


def test_role_permissions_keys_exactly_equal_approved_role_codes() -> None:
    """AUTHZ-002B2: stronger than the subset check above -- every one of
    the 12 APPROVED_ROLE_CODES must now have an explicit policy entry
    (no role silently left out of the activation), and no extra,
    unapproved key may appear either."""
    assert set(ROLE_PERMISSIONS.keys()) == APPROVED_ROLE_CODES
    assert len(APPROVED_ROLE_CODES) == 12


def test_auditor_and_read_only_contain_zero_manage_permissions() -> None:
    """AUTHZ-002B2 section 8: both are pure-visibility roles by design --
    neither may hold any mutation authority, regardless of how their read
    sets evolve."""
    for role in ("auditor", "read_only"):
        granted = get_permissions_for_role(role)
        manage_grants = {p for p in granted if p.value.endswith(".manage")}
        assert manage_grants == set(), f"{role} unexpectedly holds manage permission(s): {manage_grants}"


def test_auditor_and_read_only_are_currently_identical_by_design() -> None:
    """Not a fabricated difference -- the policy document is explicit that
    these two roles are technically identical until a future `audit.read`
    permission exists. This test documents that as an intentional,
    verified fact rather than an accidental coincidence."""
    assert get_permissions_for_role("auditor") == get_permissions_for_role("read_only")


# --- Sensitive-permission negative tests (AUTHZ-002B2 section 12) -----------
#
# EXPECTED_ROLE_GRANTS's exact-set tests above already prove these
# implicitly (a missing permission can't be present), but the ticket asks
# for dedicated, explicitly-named negative assertions for the specific
# sensitive permissions it names -- kept as a separate, traceable block.


def test_farm_manager_negative_grants() -> None:
    granted = get_permissions_for_role("farm_manager")
    assert Permission.TENANT_MEMBERS_MANAGE not in granted
    assert Permission.DISPATCH_MANAGE not in granted  # minimum policy: no broader-pilot backup dispatch
    # BIOLOGICAL-DISPOSITION-AUTHZ-001: correction-only, mirrors this
    # role's existing TRANSPLANT_CORRECT-without-TRANSPLANT_MANAGE grant.
    assert Permission.BIOLOGICAL_DISPOSITION_CORRECT in granted
    assert Permission.BIOLOGICAL_DISPOSITION_MANAGE not in granted


def test_head_grower_negative_grants() -> None:
    granted = get_permissions_for_role("head_grower")
    assert Permission.OBSERVATION_DEFINITION_MANAGE in granted
    assert Permission.TENANT_MEMBERS_MANAGE not in granted
    # BIOLOGICAL-DISPOSITION-AUTHZ-001: correction-only, same pattern as farm_manager.
    assert Permission.BIOLOGICAL_DISPOSITION_CORRECT in granted
    assert Permission.BIOLOGICAL_DISPOSITION_MANAGE not in granted


def test_production_supervisor_negative_grants() -> None:
    granted = get_permissions_for_role("production_supervisor")
    assert Permission.OBSERVATION_ENTRY_MANAGE in granted
    assert Permission.OBSERVATION_DEFINITION_MANAGE not in granted
    # BIOLOGICAL-DISPOSITION-AUTHZ-001: both ordinary recording and
    # correction authority, mirroring this role's existing
    # TRANSPLANT_MANAGE + TRANSPLANT_CORRECT pair.
    assert Permission.BIOLOGICAL_DISPOSITION_MANAGE in granted
    assert Permission.BIOLOGICAL_DISPOSITION_CORRECT in granted


def test_operator_negative_grants() -> None:
    granted = get_permissions_for_role("operator")
    assert Permission.OBSERVATION_ENTRY_MANAGE in granted
    assert Permission.OBSERVATION_DEFINITION_MANAGE not in granted
    # BIOLOGICAL-DISPOSITION-AUTHZ-001: routine recording only, mirrors
    # this role's existing TRANSPLANT_MANAGE-without-TRANSPLANT_CORRECT grant.
    assert Permission.BIOLOGICAL_DISPOSITION_MANAGE in granted
    assert Permission.BIOLOGICAL_DISPOSITION_CORRECT not in granted


def test_qc_officer_negative_grants() -> None:
    granted = get_permissions_for_role("qc_officer")
    assert Permission.OBSERVATION_ENTRY_MANAGE in granted
    assert Permission.OBSERVATION_DEFINITION_MANAGE not in granted
    assert Permission.RECALL_MANAGE not in granted


def test_storekeeper_negative_grants() -> None:
    granted = get_permissions_for_role("storekeeper")
    assert Permission.ASSET_MANAGE not in granted
    assert Permission.CARRIER_MANAGE not in granted


def test_packing_supervisor_negative_grants() -> None:
    granted = get_permissions_for_role("packing_supervisor")
    assert Permission.FINISHED_GOODS_STORAGE_MANAGE not in granted
    assert Permission.DISPATCH_MANAGE not in granted


def test_cold_store_supervisor_negative_grants() -> None:
    granted = get_permissions_for_role("cold_store_supervisor")
    assert Permission.PACKING_MANAGE not in granted
    assert Permission.DISPATCH_MANAGE not in granted


def test_dispatch_officer_negative_grants() -> None:
    """Matrix A grants dispatch_officer only dispatch.read/manage,
    finished_goods_storage.read, and packing.read -- no
    finished_goods_storage.manage or packing.manage."""
    granted = get_permissions_for_role("dispatch_officer")
    assert Permission.PACKING_MANAGE not in granted
    assert Permission.FINISHED_GOODS_STORAGE_MANAGE not in granted


def test_tenant_admin_has_all_43() -> None:
    """Name kept as `_all_43` for history/diff-friendliness (matches the
    original AUTHZ-001A test name); the assertion itself checks the current
    catalog size (47 as of BIOLOGICAL-DISPOSITION-AUTHZ-001), not the
    literal number 43."""
    granted = get_permissions_for_role("tenant_admin")
    assert len(granted) == 47
    assert granted == _ALL_PERMISSIONS


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


def test_has_permission_false_for_a_permission_the_role_is_not_granted() -> None:
    """AUTHZ-002B2: `operator` now holds real permissions, so this can no
    longer use FARM_READ as a negative example -- use a permission the
    approved policy specifically withholds from each role instead."""
    assert has_permission(_ctx("operator"), Permission.TENANT_MEMBERS_MANAGE) is False
    assert has_permission(_ctx("operator"), Permission.OBSERVATION_DEFINITION_MANAGE) is False
    assert has_permission(_ctx("read_only"), Permission.FARM_MANAGE) is False


def test_has_permission_false_for_blank_role() -> None:
    """A blank/missing role_code is still the one true "zero permissions"
    case now that every approved role_code has real grants."""
    assert has_permission(_ctx(None), Permission.FARM_READ) is False
