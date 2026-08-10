// @vitest-environment node
import { describe, expect, it } from "vitest";

import { reconcileSelectedTenant } from "@/lib/server/tenant-reconciliation";
import type { TenantMembership } from "@/lib/auth/types";

function membership(tenantId: string, name = tenantId): TenantMembership {
  return { tenantId, tenantCode: tenantId.toUpperCase(), tenantName: name, roleCode: "tenant_admin" };
}

describe("reconcileSelectedTenant", () => {
  it("0 memberships: selects nothing, clears an existing cookie", () => {
    const result = reconcileSelectedTenant([], "stale-tenant");
    expect(result.selectedTenantId).toBeNull();
    expect(result.cookieAction).toEqual({ kind: "clear" });
  });

  it("0 memberships, no existing cookie: selects nothing, does not touch the cookie", () => {
    const result = reconcileSelectedTenant([], null);
    expect(result.selectedTenantId).toBeNull();
    expect(result.cookieAction).toEqual({ kind: "none" });
  });

  it("exactly 1 membership: auto-selects it and sets the cookie, regardless of prior cookie state", () => {
    const only = membership("tenant-a");
    const result = reconcileSelectedTenant([only], null);
    expect(result.selectedTenantId).toBe("tenant-a");
    expect(result.cookieAction).toEqual({ kind: "set", tenantId: "tenant-a" });
  });

  it("exactly 1 membership: still auto-selects even if the existing cookie names a different tenant", () => {
    const only = membership("tenant-a");
    const result = reconcileSelectedTenant([only], "some-other-tenant");
    expect(result.selectedTenantId).toBe("tenant-a");
    expect(result.cookieAction).toEqual({ kind: "set", tenantId: "tenant-a" });
  });

  it(">1 memberships: preserves the cookie's tenant when it matches a current membership", () => {
    const result = reconcileSelectedTenant([membership("tenant-a"), membership("tenant-b")], "tenant-b");
    expect(result.selectedTenantId).toBe("tenant-b");
    expect(result.cookieAction).toEqual({ kind: "none" });
  });

  it(">1 memberships, no cookie: requires explicit selection", () => {
    const result = reconcileSelectedTenant([membership("tenant-a"), membership("tenant-b")], null);
    expect(result.selectedTenantId).toBeNull();
    expect(result.cookieAction).toEqual({ kind: "none" });
  });

  it(">1 memberships, cookie names a tenant no longer in the fresh list (revoked membership): rejects and clears it", () => {
    const result = reconcileSelectedTenant(
      [membership("tenant-a"), membership("tenant-b")],
      "tenant-that-was-revoked",
    );
    expect(result.selectedTenantId).toBeNull();
    expect(result.cookieAction).toEqual({ kind: "clear" });
  });

  it("never trusts a stale cookie without checking it against the fresh membership list (multi-membership case)", () => {
    // A cookie value that merely resembles a real membership id (e.g. a
    // typo, or a tenant id from an earlier session) must not be accepted
    // just because a string is present -- only exact membership in the
    // freshly-fetched list counts.
    const result = reconcileSelectedTenant([membership("tenant-a"), membership("tenant-b")], "tenant-a-typo");
    expect(result.selectedTenantId).toBeNull();
    expect(result.cookieAction).toEqual({ kind: "clear" });
  });
});
