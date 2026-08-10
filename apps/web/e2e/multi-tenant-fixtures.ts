/** Minimal, deterministic two-tenant fixture set (AUTH-001B2). Separate
 * from fixtures.ts (which models one tenant's rich batch data) -- this
 * one exists purely to prove tenant-switch cache isolation, so it stays
 * intentionally small: one farm per tenant, no batches. No real Auth0,
 * no live FastAPI, no dev database is ever touched. */
import type { AuthBootstrap } from "@/lib/auth/types";
import type { FarmRead } from "@/lib/api/client";

export const tenantAlpha = { id: "aaaaaaaa-0000-0000-0000-000000000001", code: "ALPHA", name: "Alpha Tenant" };
export const tenantBeta = { id: "bbbbbbbb-0000-0000-0000-000000000002", code: "BETA", name: "Beta Tenant" };

export const alphaFarm: FarmRead = {
  id: "aaaaaaaa-1111-1111-1111-111111111111",
  tenant_id: tenantAlpha.id,
  code: "ALPHA-01",
  name: "Alpha Farm",
  country_code: "AE",
  city_region: "Dubai",
  timezone: "Asia/Dubai",
  status: "active",
};

export const betaFarm: FarmRead = {
  id: "bbbbbbbb-2222-2222-2222-222222222222",
  tenant_id: tenantBeta.id,
  code: "BETA-01",
  name: "Beta Farm",
  country_code: "AE",
  city_region: "Dubai",
  timezone: "Asia/Dubai",
  status: "active",
};

export function bootstrapWithSelection(selectedTenantId: string | null): AuthBootstrap {
  return {
    status: "authenticated",
    user: { id: "user-multi-tenant", email: "person@example.com", displayName: "Person" },
    memberships: [
      { tenantId: tenantAlpha.id, tenantCode: tenantAlpha.code, tenantName: tenantAlpha.name, roleCode: "tenant_admin" },
      { tenantId: tenantBeta.id, tenantCode: tenantBeta.code, tenantName: tenantBeta.name, roleCode: "read_only" },
    ],
    selectedTenantId,
  };
}
