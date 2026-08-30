"""PILOT-SETUP-001B2 architecture/security assertions -- mirrors
`tests/test_platform_admin_architecture.py`'s AST-based approach. Guards
that every `/platform/tenants` route is gated by `require_platform_admin`
and nothing else (no `require_tenant_context`, no `require_permission`),
and that the dev-bootstrap mount in `app/main.py` is unaffected by this
router's addition."""

import ast
import inspect
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
PLATFORM_TENANTS_ROUTER = APP_ROOT / "api" / "platform_tenants.py"
MAIN_MODULE = APP_ROOT / "main.py"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _route_decorated_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    functions = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            # Matches router.get(...) / router.post(...) / etc.
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.value.id == "router":
                functions.append(node)
                break
    return functions


# --- 20. every /platform/tenants route is bound to require_platform_admin --


def test_every_platform_tenants_route_has_require_platform_admin_dependency() -> None:
    tree = _parse(PLATFORM_TENANTS_ROUTER)
    route_functions = _route_decorated_functions(tree)
    assert len(route_functions) == 3, "expected exactly 3 routes (list, detail, create) -- update this test if that changes"

    for fn in route_functions:
        found = False
        for arg in fn.args.args + fn.args.kwonlyargs:
            default = _default_for(fn, arg)
            if default is None:
                continue
            if (
                isinstance(default, ast.Call)
                and isinstance(default.func, ast.Name)
                and default.func.id == "Depends"
                and default.args
                and isinstance(default.args[0], ast.Name)
                and default.args[0].id == "require_platform_admin"
            ):
                found = True
        assert found, f"{fn.name} has no Depends(require_platform_admin) parameter"


def _default_for(fn: ast.FunctionDef, arg: ast.arg):
    """Maps a positional-or-keyword/kwonly arg to its AST default node, if
    any -- `ast.arguments` stores defaults as parallel trailing lists, not
    keyed by name, so this reconstructs the pairing."""
    all_args = fn.args.args
    defaults = fn.args.defaults
    offset = len(all_args) - len(defaults)
    for i, a in enumerate(all_args):
        if a is arg and i >= offset:
            return defaults[i - offset]
    kw_defaults = fn.args.kw_defaults
    for a, d in zip(fn.args.kwonlyargs, kw_defaults):
        if a is arg:
            return d
    return None


# --- 21. no /platform/tenants route binds require_tenant_context/permission -


def test_no_platform_tenants_route_binds_tenant_context_or_permission() -> None:
    """AST-based, not a substring search -- mirrors `test_authz_
    architecture.py`'s own established rationale (a plain text search would
    false-positive on this router's own explanatory module docstring, which
    names these concepts in prose specifically to explain their absence)."""
    tree = _parse(PLATFORM_TENANTS_ROUTER)
    imported = _imported_names(tree)
    offending = {
        name
        for name in imported
        if name.endswith("require_tenant_context") or name.endswith("require_permission") or name.endswith("TenantContext")
    }
    assert offending == set(), f"platform_tenants.py imports tenant-scoped auth machinery: {offending}"

    # X-Dev-Tenant-Id/X-CMP-Tenant-Id are legitimately still fine to
    # *mention in prose*; the real invariant is that no FastAPI `Header(...)`
    # parameter default names either one.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Header":
            for kw in node.keywords:
                if kw.arg == "alias" and isinstance(kw.value, ast.Constant):
                    assert kw.value.value not in ("X-Dev-Tenant-Id", "X-CMP-Tenant-Id", "X-Dev-User-Id")


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


# --- 22. no existing tenant router gains a platform-admin bypass -----------


def test_no_tenant_scoped_router_imports_require_platform_admin() -> None:
    """`require_platform_admin` must be imported ONLY by
    `app/api/platform_tenants.py` and `app/core/platform_auth.py` itself --
    never by any other router, which would mean a tenant-scoped route
    accepting platform authority as a substitute for its own permission
    check."""
    offending: list[str] = []
    for path in sorted((APP_ROOT / "api").rglob("*.py")):
        if path == PLATFORM_TENANTS_ROUTER:
            continue
        tree = _parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.core.platform_auth":
                offending.append(str(path.relative_to(APP_ROOT.parent)))
    assert offending == [], f"unexpected require_platform_admin import(s) outside platform_tenants.py: {offending}"


# --- 23. dev-bootstrap mount behavior unchanged -----------------------------


def test_dev_bootstrap_mount_still_conditioned_on_enable_dev_auth() -> None:
    source = MAIN_MODULE.read_text(encoding="utf-8")
    assert "if cfg.enable_dev_auth:" in source
    assert "from app.api.dev_bootstrap import router as dev_bootstrap_router" in source


def test_platform_tenants_router_mounted_unconditionally() -> None:
    """`platform_tenants_router` must be included at module level in
    `create_app`, never inside the `if cfg.enable_dev_auth:` block --
    authorization for these routes happens entirely per-request via
    `require_platform_admin`, never via conditional mounting."""
    tree = _parse(MAIN_MODULE)
    create_app = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "create_app"
    )
    top_level_include_calls: list[str] = []
    conditional_include_calls: list[str] = []

    for node in create_app.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Attribute) and call.func.attr == "include_router":
                if call.args and isinstance(call.args[0], ast.Name):
                    top_level_include_calls.append(call.args[0].id)
        if isinstance(node, ast.If):
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "include_router"
                    and inner.args
                    and isinstance(inner.args[0], ast.Name)
                ):
                    conditional_include_calls.append(inner.args[0].id)

    assert "platform_tenants_router" in top_level_include_calls
    assert "platform_tenants_router" not in conditional_include_calls


def test_require_platform_admin_signature_unchanged_by_b2() -> None:
    """Re-verifies (does not duplicate) the B1 architecture proof that
    `require_platform_admin` composes `require_authenticated_principal`
    only -- guards against a future edit to `platform_tenants.py`
    "helpfully" wiring a tenant dependency into the shared dependency
    itself rather than keeping it off every platform route."""
    from app.core.auth import require_authenticated_principal
    from app.core.platform_auth import require_platform_admin

    sig = inspect.signature(require_platform_admin)
    principal_param = sig.parameters["principal"]
    assert principal_param.default.dependency is require_authenticated_principal
