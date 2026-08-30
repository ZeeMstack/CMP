import { describe, expect, it } from "vitest";

import { classifyRoute, decideRouteAccess, resolveAuthPhase } from "@/lib/auth/route-access";
import type { AuthBootstrap } from "@/lib/auth/types";

const TENANT_A = "11111111-1111-1111-1111-111111111111";
const TENANT_B = "22222222-2222-2222-2222-222222222222";

function membership(tenantId: string) {
  return { tenantId, tenantCode: tenantId.slice(0, 4), tenantName: `Tenant ${tenantId}`, roleCode: "tenant_admin" };
}

function bootstrap(overrides: Partial<AuthBootstrap>): AuthBootstrap {
  return { status: "authenticated", user: null, memberships: [], selectedTenantId: null, ...overrides };
}

describe("resolveAuthPhase", () => {
  it("A: bootstrap undefined -> loading", () => {
    expect(resolveAuthPhase(undefined, false)).toBe("loading");
  });

  it("A: isLoading true -> loading, regardless of stale data", () => {
    expect(resolveAuthPhase(bootstrap({ status: "authenticated", selectedTenantId: TENANT_A, memberships: [membership(TENANT_A)] }), true)).toBe(
      "loading",
    );
  });

  it("B: authenticated + selected tenant -> ready", () => {
    expect(
      resolveAuthPhase(bootstrap({ memberships: [membership(TENANT_A)], selectedTenantId: TENANT_A }), false),
    ).toBe("ready");
  });

  it("C: authenticated + >1 memberships + no selection -> needs_tenant_selection", () => {
    expect(
      resolveAuthPhase(bootstrap({ memberships: [membership(TENANT_A), membership(TENANT_B)], selectedTenantId: null }), false),
    ).toBe("needs_tenant_selection");
  });

  it("D: authenticated + exactly 1 membership + no selection yet -> loading (never a second selection mechanism)", () => {
    expect(resolveAuthPhase(bootstrap({ memberships: [membership(TENANT_A)], selectedTenantId: null }), false)).toBe(
      "loading",
    );
  });

  it("E: authenticated + zero memberships -> zero_memberships", () => {
    expect(resolveAuthPhase(bootstrap({ memberships: [], selectedTenantId: null }), false)).toBe("zero_memberships");
  });

  it("F: not_provisioned -> not_provisioned", () => {
    expect(resolveAuthPhase(bootstrap({ status: "not_provisioned" }), false)).toBe("not_provisioned");
  });

  it("G: unauthenticated -> unauthenticated", () => {
    expect(resolveAuthPhase(bootstrap({ status: "unauthenticated" }), false)).toBe("unauthenticated");
  });

  it("H: error -> error", () => {
    expect(resolveAuthPhase(bootstrap({ status: "error" }), false)).toBe("error");
  });
});

describe("classifyRoute", () => {
  it("classifies /login, /select-tenant, /access-denied", () => {
    expect(classifyRoute("/login")).toBe("login");
    expect(classifyRoute("/select-tenant")).toBe("select-tenant");
    expect(classifyRoute("/access-denied")).toBe("access-denied");
  });

  it("classifies protected application routes", () => {
    expect(classifyRoute("/")).toBe("protected");
    expect(classifyRoute("/farms")).toBe("protected");
    expect(classifyRoute("/farms/abc")).toBe("protected");
    expect(classifyRoute("/farms/abc/crop-batches/xyz")).toBe("protected");
  });

  it("classifies /admin routes as platform-admin, never protected (PILOT-SETUP-001B3)", () => {
    expect(classifyRoute("/admin/tenants")).toBe("platform-admin");
    expect(classifyRoute("/admin/tenants/new")).toBe("platform-admin");
    expect(classifyRoute("/admin/tenants/abc-123")).toBe("platform-admin");
  });

  it("classifies Auth0 SDK-owned routes", () => {
    expect(classifyRoute("/auth/login")).toBe("sdk-auth");
    expect(classifyRoute("/auth/logout")).toBe("sdk-auth");
    expect(classifyRoute("/auth/callback")).toBe("sdk-auth");
  });

  it("classifies API routes", () => {
    expect(classifyRoute("/api/farms")).toBe("api");
    expect(classifyRoute("/api/auth/bootstrap")).toBe("api");
  });

  it("classifies anything else as unclassified", () => {
    expect(classifyRoute("/some-unknown-route")).toBe("unclassified");
  });
});

describe("decideRouteAccess: protected routes", () => {
  const base = { routeClass: "protected" as const, pathname: "/farms/abc/crop-batches/xyz", search: "?view=quality" };

  it("loading -> loading", () => {
    expect(decideRouteAccess({ ...base, phase: "loading" })).toEqual({ kind: "loading" });
  });

  it("ready -> allow (protected content may render)", () => {
    expect(decideRouteAccess({ ...base, phase: "ready" })).toEqual({ kind: "allow" });
  });

  it("needs_tenant_selection -> redirect to /select-tenant", () => {
    expect(decideRouteAccess({ ...base, phase: "needs_tenant_selection" })).toEqual({
      kind: "redirect",
      to: "/select-tenant",
    });
  });

  it("zero_memberships -> redirect to /access-denied", () => {
    expect(decideRouteAccess({ ...base, phase: "zero_memberships" })).toEqual({
      kind: "redirect",
      to: "/access-denied",
    });
  });

  it("not_provisioned -> redirect to /access-denied", () => {
    expect(decideRouteAccess({ ...base, phase: "not_provisioned" })).toEqual({
      kind: "redirect",
      to: "/access-denied",
    });
  });

  it("unauthenticated -> redirect to /login with the safe current path + query as returnTo", () => {
    const decision = decideRouteAccess({ ...base, phase: "unauthenticated" });
    expect(decision).toEqual({
      kind: "redirect",
      to: `/login?returnTo=${encodeURIComponent("/farms/abc/crop-batches/xyz?view=quality")}`,
    });
  });

  it("error -> error", () => {
    expect(decideRouteAccess({ ...base, phase: "error" })).toEqual({ kind: "error" });
  });
});

describe("decideRouteAccess: /login", () => {
  it("unauthenticated -> allow (show the sign-in button)", () => {
    expect(
      decideRouteAccess({ routeClass: "login", phase: "unauthenticated", pathname: "/login", search: "" }),
    ).toEqual({ kind: "allow" });
  });

  it("ready with a valid returnTo query param -> redirect there", () => {
    const decision = decideRouteAccess({
      routeClass: "login",
      phase: "ready",
      pathname: "/login",
      search: `?returnTo=${encodeURIComponent("/farms/abc")}`,
    });
    expect(decision).toEqual({ kind: "redirect", to: "/farms/abc" });
  });

  it("ready with no returnTo -> redirect to /farms fallback", () => {
    expect(decideRouteAccess({ routeClass: "login", phase: "ready", pathname: "/login", search: "" })).toEqual({
      kind: "redirect",
      to: "/farms",
    });
  });

  it("ready with a malicious returnTo -> redirect to /farms fallback, never the malicious target", () => {
    const decision = decideRouteAccess({
      routeClass: "login",
      phase: "ready",
      pathname: "/login",
      search: `?returnTo=${encodeURIComponent("https://evil.example")}`,
    });
    expect(decision).toEqual({ kind: "redirect", to: "/farms" });
  });

  it("needs_tenant_selection -> redirect to /select-tenant", () => {
    expect(
      decideRouteAccess({ routeClass: "login", phase: "needs_tenant_selection", pathname: "/login", search: "" }),
    ).toEqual({ kind: "redirect", to: "/select-tenant" });
  });

  it("zero_memberships -> redirect to /access-denied", () => {
    expect(
      decideRouteAccess({ routeClass: "login", phase: "zero_memberships", pathname: "/login", search: "" }),
    ).toEqual({ kind: "redirect", to: "/access-denied" });
  });

  it("not_provisioned -> redirect to /access-denied", () => {
    expect(
      decideRouteAccess({ routeClass: "login", phase: "not_provisioned", pathname: "/login", search: "" }),
    ).toEqual({ kind: "redirect", to: "/access-denied" });
  });

  it("error -> error (service state, not /access-denied, not a redirect loop)", () => {
    expect(decideRouteAccess({ routeClass: "login", phase: "error", pathname: "/login", search: "" })).toEqual({
      kind: "error",
    });
  });
});

describe("decideRouteAccess: /select-tenant", () => {
  const base = { routeClass: "select-tenant" as const, pathname: "/select-tenant", search: "" };

  it("needs_tenant_selection -> allow", () => {
    expect(decideRouteAccess({ ...base, phase: "needs_tenant_selection" })).toEqual({ kind: "allow" });
  });

  it("ready -> allow (still permitted to re-select)", () => {
    expect(decideRouteAccess({ ...base, phase: "ready" })).toEqual({ kind: "allow" });
  });

  it("unauthenticated -> redirect to /login", () => {
    const decision = decideRouteAccess({ ...base, phase: "unauthenticated" });
    expect(decision.kind).toBe("redirect");
    expect((decision as { to: string }).to).toMatch(/^\/login\?returnTo=/);
  });

  it("zero_memberships -> redirect to /access-denied", () => {
    expect(decideRouteAccess({ ...base, phase: "zero_memberships" })).toEqual({
      kind: "redirect",
      to: "/access-denied",
    });
  });

  it("not_provisioned -> redirect to /access-denied", () => {
    expect(decideRouteAccess({ ...base, phase: "not_provisioned" })).toEqual({
      kind: "redirect",
      to: "/access-denied",
    });
  });
});

describe("decideRouteAccess: /access-denied", () => {
  const base = { routeClass: "access-denied" as const, pathname: "/access-denied", search: "" };

  it("zero_memberships -> allow", () => {
    expect(decideRouteAccess({ ...base, phase: "zero_memberships" })).toEqual({ kind: "allow" });
  });

  it("not_provisioned -> allow", () => {
    expect(decideRouteAccess({ ...base, phase: "not_provisioned" })).toEqual({ kind: "allow" });
  });

  it("ready (newly provisioned, e.g. after Check again) -> redirect to /farms", () => {
    expect(decideRouteAccess({ ...base, phase: "ready" })).toEqual({ kind: "redirect", to: "/farms" });
  });

  it("needs_tenant_selection (newly provisioned with multiple memberships) -> redirect to /select-tenant", () => {
    expect(decideRouteAccess({ ...base, phase: "needs_tenant_selection" })).toEqual({
      kind: "redirect",
      to: "/select-tenant",
    });
  });

  it("unauthenticated -> redirect to /login", () => {
    const decision = decideRouteAccess({ ...base, phase: "unauthenticated" });
    expect(decision.kind).toBe("redirect");
    expect((decision as { to: string }).to).toMatch(/^\/login\?returnTo=/);
  });
});

describe("decideRouteAccess: platform-admin routes (PILOT-SETUP-001B3)", () => {
  const base = { routeClass: "platform-admin" as const, pathname: "/admin/tenants", search: "" };

  it("loading -> loading", () => {
    expect(decideRouteAccess({ ...base, phase: "loading" })).toEqual({ kind: "loading" });
  });

  it("ready -> allow", () => {
    expect(decideRouteAccess({ ...base, phase: "ready" })).toEqual({ kind: "allow" });
  });

  it("zero_memberships -> allow (a Platform Admin may legitimately have no Tenant membership at all)", () => {
    expect(decideRouteAccess({ ...base, phase: "zero_memberships" })).toEqual({ kind: "allow" });
  });

  it("needs_tenant_selection -> allow (never forced through /select-tenant)", () => {
    expect(decideRouteAccess({ ...base, phase: "needs_tenant_selection" })).toEqual({ kind: "allow" });
  });

  it("not_provisioned -> redirect to /access-denied (no CMP User at all, like protected routes)", () => {
    expect(decideRouteAccess({ ...base, phase: "not_provisioned" })).toEqual({
      kind: "redirect",
      to: "/access-denied",
    });
  });

  it("unauthenticated -> redirect to /login with returnTo", () => {
    const decision = decideRouteAccess({ ...base, phase: "unauthenticated" });
    expect(decision).toEqual({ kind: "redirect", to: `/login?returnTo=${encodeURIComponent("/admin/tenants")}` });
  });

  it("error -> error", () => {
    expect(decideRouteAccess({ ...base, phase: "error" })).toEqual({ kind: "error" });
  });
});

describe("decideRouteAccess: unconditionally-allowed classes", () => {
  it("sdk-auth is always allowed, regardless of phase", () => {
    for (const phase of ["loading", "unauthenticated", "not_provisioned", "zero_memberships", "needs_tenant_selection", "ready", "error"] as const) {
      expect(decideRouteAccess({ routeClass: "sdk-auth", phase, pathname: "/auth/login", search: "" })).toEqual({
        kind: "allow",
      });
    }
  });

  it("api is always allowed (server-side secured, never page-gated)", () => {
    expect(decideRouteAccess({ routeClass: "api", phase: "unauthenticated", pathname: "/api/farms", search: "" })).toEqual({
      kind: "allow",
    });
  });

  it("unclassified is always allowed", () => {
    expect(
      decideRouteAccess({ routeClass: "unclassified", phase: "unauthenticated", pathname: "/whatever", search: "" }),
    ).toEqual({ kind: "allow" });
  });
});
