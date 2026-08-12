"""AUTHZ-001B1 architecture/inventory tests (ticket section 7).

Deterministic, structural proof -- built on FastAPI's own live route
introspection (`app.routes[*].dependant`), not a text/string grep -- that
every tenant-scoped business `GET` endpoint is gated by
`require_permission(...)` with a real `Permission` value, and that none of
them silently remain on the plain `require_tenant_context` dependency.
Because this walks the actual mounted route table, it fails the moment a
future `GET` endpoint is added without `require_permission` -- there is no
list of endpoint names to keep in sync by hand.

Companion tests: `test_authz_architecture.py` (AUTHZ-001A's own
Auth0/role_code-comparison/centralization checks, unchanged and still
applicable), `test_authz_read_enforcement_http.py` (representative
HTTP-level behavior for a cross-section of the newly-enforced domains).
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.core.auth import require_tenant_context
from app.core.permissions import Permission, require_permission
from app.main import app

# The explicit, reviewable exemption list (ticket section 7): every GET
# endpoint that is legitimately NOT gated by a CMP Permission, and why.
EXEMPT_PATHS = {
    "/": "Inline service-info endpoint (app.main.root) -- no auth at all, same class as /health and /ready.",
    "/health": "Infrastructure liveness probe -- no auth at all.",
    "/ready": "Infrastructure readiness probe (DB connectivity only) -- no auth at all.",
    "/auth/me": (
        "Tenant-UNscoped by definition -- its whole purpose is letting an "
        "authenticated caller discover which tenants it may select before "
        "any tenant context (and therefore any role_code/Permission) can "
        "exist. Uses require_authenticated_principal, never "
        "require_tenant_context/require_permission."
    ),
}
EXEMPT_PREFIXES = {
    "/dev/bootstrap": (
        "Development-only bootstrap routes, mounted only when "
        "ENABLE_DEV_AUTH=true (itself forbidden outside ENV=development). "
        "Exists specifically to create a tenant's *first* membership "
        "before any membership -- and therefore any permission -- can "
        "exist."
    ),
}


def _all_api_routes() -> list[APIRoute]:
    """Every real `APIRoute` FastAPI has mounted, including ones wrapped
    in this FastAPI version's internal `_IncludedRouter` (created by
    `app.include_router(...)`) -- `app.routes` alone does not flatten
    those. Falls back to any `APIRoute` mounted directly on the app
    (e.g. `app.main`'s inline `@api.get("/")`)."""
    routes: list[APIRoute] = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            routes.append(route)
        elif hasattr(route, "original_router"):
            routes.extend(r for r in route.original_router.routes if isinstance(r, APIRoute))
    return routes


def _is_exempt(path: str) -> bool:
    return path in EXEMPT_PATHS or any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def _tenant_scoped_get_routes() -> list[APIRoute]:
    return [
        route
        for route in _all_api_routes()
        if "GET" in (route.methods or set()) and not _is_exempt(route.path)
    ]


def _is_require_permission_dependency(call: object) -> bool:
    """`require_permission(permission)` returns a freshly-created closure
    (`_dependency`) each call -- identity comparison against
    `require_permission` itself never matches. Identify it by qualname +
    defining module instead."""
    return (
        getattr(call, "__qualname__", "") == "require_permission.<locals>._dependency"
        and getattr(call, "__module__", "") == require_permission.__module__
    )


def _bound_permission(call: object) -> Permission | None:
    """Extracts the `Permission` value closed over by a
    `require_permission(...)`-produced dependency, by inspecting its
    closure cells -- the only argument `require_permission` ever takes."""
    closure = getattr(call, "__closure__", None)
    if not closure:
        return None
    for cell in closure:
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if isinstance(value, Permission):
            return value
    return None


def test_every_tenant_scoped_get_route_is_gated_by_require_permission() -> None:
    """The core AUTHZ-001B1 regression guard: fails immediately if any
    current or future tenant-scoped GET endpoint is missing
    require_permission, or relies solely on require_tenant_context."""
    routes = _tenant_scoped_get_routes()
    assert routes, "route discovery found nothing -- the introspection helper itself is broken"

    missing: list[str] = []
    bare_tenant_context: list[str] = []
    unbound_permission: list[str] = []

    for route in routes:
        top_level_calls = [d.call for d in route.dependant.dependencies]
        permission_calls = [c for c in top_level_calls if _is_require_permission_dependency(c)]

        if not permission_calls:
            missing.append(route.path)
            continue
        if require_tenant_context in top_level_calls:
            # require_permission already depends on require_tenant_context
            # internally (nested, not top-level) -- a route must never
            # ALSO declare it directly, which would be a second, redundant
            # identity resolution outside the centralized dependency.
            bare_tenant_context.append(route.path)
        if _bound_permission(permission_calls[0]) is None:
            unbound_permission.append(route.path)

    assert missing == [], f"tenant-scoped GET route(s) with no require_permission dependency: {missing}"
    assert bare_tenant_context == [], (
        f"route(s) declare require_tenant_context directly ALONGSIDE require_permission: {bare_tenant_context}"
    )
    assert unbound_permission == [], f"route(s) whose require_permission has no resolvable Permission: {unbound_permission}"


def test_every_permission_bound_to_a_get_route_is_a_read_permission() -> None:
    """A GET route gated by e.g. Permission.FARM_MANAGE instead of
    Permission.FARM_READ would pass the "is gated" check above but grant
    the wrong authority -- catch that class of mistake explicitly."""
    offenders: list[tuple[str, Permission]] = []
    for route in _tenant_scoped_get_routes():
        top_level_calls = [d.call for d in route.dependant.dependencies]
        for call in top_level_calls:
            if not _is_require_permission_dependency(call):
                continue
            permission = _bound_permission(call)
            if permission is not None and not permission.value.endswith(".read"):
                offenders.append((route.path, permission))
    assert offenders == [], f"GET route(s) gated by a non-.read permission: {offenders}"


def test_exemption_list_is_exact_not_a_superset() -> None:
    """Guards the exemption list itself from silently growing stale in
    the *permissive* direction: every exempt path/prefix must still
    correspond to a real, currently-mounted route -- otherwise a route
    that used to be legitimately exempt (and was removed or renamed) could
    mask a real gap if a new route later reuses a similar-looking path
    without anyone revisiting this list. `/dev/bootstrap` currently has no
    GET endpoint at all (its three routes are POST-only) -- checked
    against every method, not just GET, since the exemption exists to
    future-proof against a hypothetical GET being added there later, not
    because one exists today."""
    get_paths = {route.path for route in _all_api_routes() if "GET" in (route.methods or set())}
    all_paths = {route.path for route in _all_api_routes()}
    for exempt_path in EXEMPT_PATHS:
        assert exempt_path in get_paths, f"exempt path {exempt_path!r} no longer exists as a real GET route"
    for prefix in EXEMPT_PREFIXES:
        assert any(p.startswith(prefix) for p in all_paths), f"exempt prefix {prefix!r} matches no real mounted route"


def test_read_enforcement_covers_every_domain_read_permission_at_least_once() -> None:
    """Every `Permission` ending in `.read` should be bound to at least
    one real route after AUTHZ-001B1 -- catches a read permission that
    exists in the catalog but was never actually wired to anything."""
    bound: set[Permission] = set()
    for route in _tenant_scoped_get_routes():
        for call in (d.call for d in route.dependant.dependencies):
            if _is_require_permission_dependency(call):
                permission = _bound_permission(call)
                if permission is not None:
                    bound.add(permission)

    all_read_permissions = {p for p in Permission if p.value.endswith(".read")}
    unbound = all_read_permissions - bound
    assert unbound == set(), f".read permission(s) defined but never bound to any GET route: {unbound}"
