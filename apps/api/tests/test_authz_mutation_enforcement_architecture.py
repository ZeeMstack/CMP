"""AUTHZ-001B2 architecture/inventory tests (ticket section 9). Mirrors
`test_authz_read_enforcement_architecture.py`'s structural approach for
every tenant-scoped mutation/action route (`POST`/`PUT`/`PATCH`/`DELETE`)
instead of `GET`.

Deterministic, structural proof -- built on FastAPI's own live route
introspection (`app.routes[*].dependant`), not a text/string grep -- that
every tenant-scoped business mutation/action endpoint is gated by
`require_permission(...)` with a real `.manage` `Permission`, and that
none of them silently remain on the plain `require_tenant_context`
dependency. Because this walks the actual mounted route table, it fails
the moment a future mutation endpoint (of any HTTP method) is added
without `require_permission` -- there is no list of endpoint names to
keep in sync by hand.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.core.auth import require_tenant_context
from app.core.permissions import Permission, require_permission
from app.main import app

_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# The explicit, reviewable exemption list (ticket section 2): every
# mutation endpoint that is legitimately NOT gated by a CMP Permission,
# and why.
EXEMPT_PATHS = {
    "/dev/bootstrap/tenants": "Development-only bootstrap: creates a tenant before any membership can exist.",
    "/dev/bootstrap/users": "Development-only bootstrap: creates a CMP user identity record, prior to any tenant membership.",
    "/dev/bootstrap/memberships": (
        "Development-only bootstrap: creates a tenant's *first* membership -- by definition, before any "
        "membership (and therefore any permission) can exist for that tenant. Requires no active membership; "
        "that is the whole point of a bootstrap route."
    ),
}
EXEMPT_PREFIXES: dict[str, str] = {}


def _all_api_routes() -> list[APIRoute]:
    """Every real `APIRoute` FastAPI has mounted, including ones wrapped
    in this FastAPI version's internal `_IncludedRouter` (created by
    `app.include_router(...)`) -- `app.routes` alone does not flatten
    those."""
    routes: list[APIRoute] = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            routes.append(route)
        elif hasattr(route, "original_router"):
            routes.extend(r for r in route.original_router.routes if isinstance(r, APIRoute))
    return routes


def _is_exempt(path: str) -> bool:
    return path in EXEMPT_PATHS or any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES)


def _tenant_scoped_mutation_routes() -> list[APIRoute]:
    return [
        route
        for route in _all_api_routes()
        if (route.methods or set()) & _MUTATION_METHODS and not _is_exempt(route.path)
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


def test_no_mutation_method_other_than_post_exists_anywhere() -> None:
    """Structural confirmation, not an assumption: CMP's API is
    append-only/event-oriented and has never used PUT/PATCH/DELETE.
    Verified against the live mounted route table so this ticket's own
    "VERIFY, do not assume" instruction is actually checked, not just
    asserted in a docstring."""
    all_methods: set[str] = set()
    for route in _all_api_routes():
        all_methods |= route.methods or set()
    assert all_methods <= {"GET", "POST"}, f"unexpected HTTP method(s) mounted: {all_methods - {'GET', 'POST'}}"


def test_every_tenant_scoped_mutation_route_is_gated_by_require_permission() -> None:
    """The core AUTHZ-001B2 regression guard: fails immediately if any
    current or future tenant-scoped mutation/action endpoint (of any
    method in _MUTATION_METHODS) is missing require_permission, or relies
    solely on require_tenant_context."""
    routes = _tenant_scoped_mutation_routes()
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

    assert missing == [], f"tenant-scoped mutation route(s) with no require_permission dependency: {missing}"
    assert bare_tenant_context == [], (
        f"route(s) declare require_tenant_context directly ALONGSIDE require_permission: {bare_tenant_context}"
    )
    assert unbound_permission == [], f"route(s) whose require_permission has no resolvable Permission: {unbound_permission}"


def test_every_permission_bound_to_a_mutation_route_is_a_manage_permission() -> None:
    """A mutation route gated by e.g. Permission.FARM_READ instead of
    Permission.FARM_MANAGE would pass the "is gated" check above but
    grant the wrong (too weak) authority -- catch that class of mistake
    explicitly."""
    offenders: list[tuple[str, Permission]] = []
    for route in _tenant_scoped_mutation_routes():
        top_level_calls = [d.call for d in route.dependant.dependencies]
        for call in top_level_calls:
            if not _is_require_permission_dependency(call):
                continue
            permission = _bound_permission(call)
            if permission is not None and not permission.value.endswith(".manage"):
                offenders.append((route.path, permission))
    assert offenders == [], f"mutation route(s) gated by a non-.manage permission: {offenders}"


def test_exemption_list_is_exact_not_a_superset() -> None:
    """Guards the exemption list itself from silently growing stale in
    the *permissive* direction: every exempt path must still correspond
    to a real, currently-mounted mutation route."""
    all_paths = {route.path for route in _all_api_routes()}
    mutation_paths = {route.path for route in _all_api_routes() if (route.methods or set()) & _MUTATION_METHODS}
    for exempt_path in EXEMPT_PATHS:
        assert exempt_path in mutation_paths, f"exempt path {exempt_path!r} no longer exists as a real mutation route"
    for prefix in EXEMPT_PREFIXES:
        assert any(p.startswith(prefix) for p in all_paths), f"exempt prefix {prefix!r} matches no real mounted route"


def test_mutation_enforcement_covers_every_manage_permission_at_least_once() -> None:
    """Every `Permission` ending in `.manage` should be bound to at least
    one real mutation route after AUTHZ-001B2 -- catches a manage
    permission that exists in the catalog but was never actually wired to
    anything. If one legitimately has no route yet, this test's failure
    IS the report the ticket asks for (section 9's final instruction) --
    not something to silently work around by inventing a route."""
    bound: set[Permission] = set()
    for route in _tenant_scoped_mutation_routes():
        for call in (d.call for d in route.dependant.dependencies):
            if _is_require_permission_dependency(call):
                permission = _bound_permission(call)
                if permission is not None:
                    bound.add(permission)

    all_manage_permissions = {p for p in Permission if p.value.endswith(".manage")}
    unbound = all_manage_permissions - bound
    assert unbound == set(), f".manage permission(s) defined but never bound to any mutation route: {unbound}"


def test_post_farms_is_naturally_included_and_unchanged() -> None:
    """POST /farms was AUTHZ-001A's own technical proof, already
    FARM_MANAGE-gated before this ticket -- confirms it is simply one of
    the now-uniformly-enforced mutation routes, not a special case."""
    routes = {r.path: r for r in _tenant_scoped_mutation_routes()}
    assert "/farms" in routes
    top_level_calls = [d.call for d in routes["/farms"].dependant.dependencies]
    permission_calls = [c for c in top_level_calls if _is_require_permission_dependency(c)]
    assert len(permission_calls) == 1
    assert _bound_permission(permission_calls[0]) == Permission.FARM_MANAGE
