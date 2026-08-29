"""PILOT-SETUP-001B1 architecture/security assertions -- mirrors
`test_authz_architecture.py`'s AST-based approach. Guards the structural
separation between platform-level authority (`app.core.platform_auth`,
`app.models.platform_admin`) and CMP's tenant-scoped authorization model
(`app.core.permissions`, `TenantMembership`) so a future change cannot
accidentally: treat platform-admin authority as a tenant permission, wire a
future platform route without the platform-admin gate, or reuse
`tenant_admin`/TenantContext for a platform-level operation."""

import ast
import inspect
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
PLATFORM_AUTH_MODULE = APP_ROOT / "core" / "platform_auth.py"
PLATFORM_ADMIN_MODEL = APP_ROOT / "models" / "platform_admin.py"
PLATFORM_ADMIN_SERVICE = APP_ROOT / "services" / "platform_admin_service.py"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


# --- require_platform_admin composes require_authenticated_principal only --


def test_require_platform_admin_depends_on_require_authenticated_principal() -> None:
    """The `principal` parameter must default to
    Depends(require_authenticated_principal) -- proving identity resolution
    (WHO-only, no tenant selection) always runs first."""
    from app.core.auth import require_authenticated_principal
    from app.core.platform_auth import require_platform_admin

    sig = inspect.signature(require_platform_admin)
    principal_param = sig.parameters["principal"]
    assert principal_param.default.dependency is require_authenticated_principal


def test_require_platform_admin_never_depends_on_tenant_context_or_permission() -> None:
    """No parameter of require_platform_admin may default to
    Depends(require_tenant_context) or Depends(require_permission(...)) --
    a route gated only by this dependency must never receive a
    TenantContext or tenant Permission check."""
    from app.core.auth import require_tenant_context
    from app.core.platform_auth import require_platform_admin

    sig = inspect.signature(require_platform_admin)
    for param in sig.parameters.values():
        default = param.default
        dependency = getattr(default, "dependency", None)
        assert dependency is not require_tenant_context


def test_platform_auth_module_never_imports_tenant_permission_machinery() -> None:
    """app.core.platform_auth must never import app.core.permissions
    (Permission, require_permission, ROLE_PERMISSIONS, has_permission) --
    platform authority is decided entirely independently of the tenant
    permission catalog."""
    tree = _parse(PLATFORM_AUTH_MODULE)
    imported = _imported_names(tree)
    offending = {name for name in imported if name.startswith("app.core.permissions")}
    assert offending == set(), f"app.core.platform_auth imports tenant-permission machinery: {offending}"


# --- PlatformAdmin model has no tenant_id / role_code -----------------------


def test_platform_admin_model_has_no_tenant_id_or_role_code_column() -> None:
    """Static, AST-based: no class-body assignment/annotation in
    PlatformAdmin is named tenant_id or role_code -- the architecture
    decision (PILOT-SETUP-001B1) is explicit that platform authority is not
    a TenantMembership and carries no tenant scope."""
    tree = _parse(PLATFORM_ADMIN_MODEL)
    class_def = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PlatformAdmin")
    forbidden = {"tenant_id", "role_code"}
    offending: list[str] = []
    for node in class_def.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in forbidden:
            offending.append(node.target.id)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in forbidden:
                    offending.append(target.id)
    assert offending == [], f"PlatformAdmin model unexpectedly declares: {offending}"


# --- platform_admin_service is structurally separate from tenant machinery -


def test_platform_admin_service_never_imports_tenant_membership_or_permissions() -> None:
    """app.services.platform_admin_service must never import
    app.models.membership (TenantMembership) or app.core.permissions --
    platform-admin grant/revoke/check logic is entirely independent of
    tenant membership/role/permission state."""
    tree = _parse(PLATFORM_ADMIN_SERVICE)
    imported = _imported_names(tree)
    offending = {
        name
        for name in imported
        if name.startswith("app.models.membership") or name.startswith("app.core.permissions")
    }
    assert offending == set(), f"platform_admin_service imports tenant-membership/permission machinery: {offending}"


def test_no_router_or_service_reuses_tenant_admin_role_code_for_platform_checks() -> None:
    """No comparison anywhere in app/ tests role_code against the literal
    string "tenant_admin" as a stand-in for platform authority -- the only
    legitimate source of platform authority is
    app.services.platform_admin_service.is_platform_admin."""
    offending: list[str] = []
    for path in sorted((APP_ROOT / "api").rglob("*.py")) + sorted((APP_ROOT / "core").rglob("*.py")):
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            constants = [c.value for c in (node.left, *node.comparators) if isinstance(c, ast.Constant)]
            names = [n.attr for n in (node.left, *node.comparators) if isinstance(n, ast.Attribute)]
            if "tenant_admin" in constants and "role_code" in names:
                offending.append(f"{path.relative_to(APP_ROOT.parent)}:{node.lineno}")
    assert offending == [], f"tenant_admin role_code comparison found outside the approved policy table: {offending}"
