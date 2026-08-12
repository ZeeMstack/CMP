"""AUTHZ-001A security/architecture assertions (ticket section 9).
Static, AST-based checks over the actual `app/` source tree -- not
substring/text greps, which would false-positive on this ticket's own
explanatory docstrings (e.g. `app.core.permissions`'s module docstring
itself explains, in prose, that Auth0 roles/organizations/email are never
consulted -- a plain text search for those words would incorrectly flag
that very sentence). AST inspection only sees real imports, attribute
accesses, comparisons, and top-level assignments -- never comments or
docstrings -- so these assertions test the code, not the commentary
about the code."""

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
PERMISSIONS_MODULE = APP_ROOT / "core" / "permissions.py"
FARMS_ROUTER = APP_ROOT / "api" / "farms.py"

# Auth0-claim-shaped concepts that must never be consulted for CMP
# authorization decisions -- deliberately excludes "role"/"role_code"
# itself, which IS the legitimate CMP authority source.
_FORBIDDEN_CLAIM_ATTRS = {"email", "roles", "organization", "org_id", "user_metadata", "app_metadata"}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _all_app_python_files() -> list[Path]:
    return sorted(APP_ROOT.rglob("*.py"))


def _authorization_relevant_files() -> list[Path]:
    """`app/api/` (every route handler) and `app/services/` (every
    business operation a route handler delegates to) -- the layer where a
    hand-rolled `role_code` comparison would actually be a policy bypass,
    because these are exactly the modules `require_permission` exists to
    gate. Deliberately excludes:

    - `app/core/` -- `auth.py`/`dev_auth.py` resolve role_code (they
      don't compare it against a business rule) and `permissions.py` is
      the one file *allowed* to turn role_code into a decision, which it
      already does via a dict lookup rather than a comparison anyway.
    - `app/schemas/` and `app/models/` -- e.g.
      `app/schemas/membership.py` validates that an incoming `role_code`
      is one of `APPROVED_ROLE_CODES`. That's data-shape validation (is
      this a well-formed role at all?), not an authorization decision
      (what may this role do?) -- a fundamentally different concern that
      this test must not conflate with a policy bypass, or a legitimate
      future feature (e.g. a membership-management read endpoint
      displaying `role_code` for humans) would fail this test for a
      reason that has nothing to do with authorization."""
    return sorted((APP_ROOT / "api").rglob("*.py")) + sorted((APP_ROOT / "services").rglob("*.py"))


# --- No Auth0 RBAC / Organizations / email-based authorization --------------


def test_permissions_module_imports_nothing_auth0_shaped() -> None:
    tree = _parse(PERMISSIONS_MODULE)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "auth0" not in alias.name.lower()
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "auth0" not in module.lower()


def test_permissions_module_never_reads_an_auth0_shaped_claim() -> None:
    """No attribute access, subscript, or dict key anywhere in
    app.core.permissions touches an Auth0-style claim (email, roles,
    organization, org_id, user_metadata, app_metadata) -- authorization
    is derived exclusively from TenantContext.role_code."""
    tree = _parse(PERMISSIONS_MODULE)
    offending: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_CLAIM_ATTRS:
            offending.append(node.attr)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in _FORBIDDEN_CLAIM_ATTRS:
            # Only flag string constants used as a subscript key
            # (`x["email"]`), not arbitrary prose -- but permissions.py's
            # only string constants are Permission enum values (dotted,
            # never equal to a bare forbidden word) and the detail
            # message, so this additionally guards against a future dict-
            # keyed claim lookup being introduced.
            offending.append(node.value)
    assert offending == [], f"app.core.permissions references Auth0-shaped claim(s): {offending}"


# --- role_code is never compared ad hoc outside the centralized policy ------


def test_no_router_or_service_directly_compares_role_code() -> None:
    """AUTHZ-001A.1 (section 7): scoped to `app/api/` and `app/services/`
    specifically -- the route-handler and business-operation layer
    `require_permission` exists to gate -- not the whole `app/` tree. A
    repo-wide scan would also flag `app/schemas/membership.py`'s
    role_code *format* validation (`v not in APPROVED_ROLE_CODES`), which
    is data-shape validation, not an authorization decision, and would
    make this test fail on a legitimate future non-authorization use of
    role_code (e.g. a membership-listing endpoint that merely displays
    it). See `_authorization_relevant_files`'s docstring for the full
    reasoning. This still catches the real risk: any router or service
    hand-rolling its own `if ctx.role_code == "..."`/`role_code in (...)`
    business-logic branch instead of going through
    `require_permission`/`has_permission`."""
    offending: list[str] = []
    for path in _authorization_relevant_files():
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            names = [n for n in (node.left, *node.comparators) if isinstance(n, ast.Attribute)]
            if any(n.attr == "role_code" for n in names):
                offending.append(f"{path.relative_to(APP_ROOT.parent)}:{node.lineno}")
    assert offending == [], f"direct role_code comparison(s) found in a router/service: {offending}"


def test_farms_router_never_mentions_role_code() -> None:
    """The technical-proof router itself must not inspect role_code at
    all -- it only ever asks for a Permission via require_permission()
    and uses the returned TenantContext's tenant_id/user_id, exactly as
    it did before this ticket."""
    assert "role_code" not in FARMS_ROUTER.read_text(encoding="utf-8")


# --- centralization: exactly one definition each -----------------------------


def _top_level_assign_targets(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_role_permissions_policy_is_defined_in_exactly_one_module() -> None:
    defining_files = [
        path for path in _all_app_python_files() if "ROLE_PERMISSIONS" in _top_level_assign_targets(_parse(path))
    ]
    assert defining_files == [PERMISSIONS_MODULE]


def test_permission_enum_is_defined_in_exactly_one_module() -> None:
    defining_files = []
    for path in _all_app_python_files():
        tree = _parse(path)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "Permission":
                defining_files.append(path)
    assert defining_files == [PERMISSIONS_MODULE]


# --- require_permission composes require_tenant_context, never bypasses it --


def test_require_permission_depends_on_require_tenant_context() -> None:
    """require_permission's returned dependency must itself declare a
    Depends(require_tenant_context) parameter -- proving tenant-membership
    resolution (and its own 401/400/403 semantics) always runs first, and
    that permission checking is strictly additive, never a parallel/
    alternate identity path."""
    import inspect

    from app.core.auth import require_tenant_context
    from app.core.permissions import Permission, require_permission

    dependency = require_permission(Permission.FARM_READ)
    sig = inspect.signature(dependency)
    (param,) = sig.parameters.values()
    assert param.default.dependency is require_tenant_context
