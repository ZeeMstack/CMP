/**
 * Pure tenant-selection reconciliation logic (AUTH-001B2). Shared by
 * `GET /api/auth/bootstrap` (reconcile against a fresh /auth/me on every
 * bootstrap) and `POST /api/tenant/select` (verify an explicit choice
 * against a fresh /auth/me). No I/O here -- deliberately a pure function
 * so its exact semantics (0/1/many membership behavior, stale-cookie
 * handling) can be asserted directly without mocking cookies/fetch.
 *
 * A cached/cookie-supplied tenant id is NEVER trusted on its own -- it is
 * only ever accepted when it appears in the membership list that was just
 * fetched fresh from FastAPI. This is what makes membership revocation
 * (a tenant disappearing from /auth/me) self-healing on the very next
 * bootstrap, rather than requiring the frontend to notice a 403 later.
 */

import type { TenantMembership } from "@/lib/auth/types";

export type TenantCookieAction = { kind: "set"; tenantId: string } | { kind: "clear" } | { kind: "none" };

export interface TenantReconciliation {
  selectedTenantId: string | null;
  cookieAction: TenantCookieAction;
}

export function reconcileSelectedTenant(
  memberships: TenantMembership[],
  existingCookieTenantId: string | null,
): TenantReconciliation {
  if (memberships.length === 0) {
    return {
      selectedTenantId: null,
      cookieAction: existingCookieTenantId ? { kind: "clear" } : { kind: "none" },
    };
  }

  if (memberships.length === 1) {
    const only = memberships[0].tenantId;
    // Idempotent: setting it again when it already matches is harmless
    // and keeps this branch simple (no need to special-case "already
    // correct" -- Set-Cookie with the same value is a no-op for the
    // browser either way).
    return { selectedTenantId: only, cookieAction: { kind: "set", tenantId: only } };
  }

  if (existingCookieTenantId && memberships.some((m) => m.tenantId === existingCookieTenantId)) {
    return { selectedTenantId: existingCookieTenantId, cookieAction: { kind: "none" } };
  }

  // Multiple memberships, and either no cookie or a cookie naming a
  // tenant that is no longer (or never was) one of the fresh, current
  // memberships -- e.g. membership revoked since the cookie was set.
  // Never guess; require an explicit re-selection.
  return {
    selectedTenantId: null,
    cookieAction: existingCookieTenantId ? { kind: "clear" } : { kind: "none" },
  };
}
