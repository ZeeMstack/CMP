/**
 * The single place that calls FastAPI's GET /auth/me and maps its
 * generated `AuthMeRead` shape into CMP's own `AuthBootstrapUser`/
 * `TenantMembership` types (AUTH-001B2). Shared by the bootstrap route
 * and the tenant-selection route so both always parse the exact same
 * fresh response the exact same way.
 */

import type { AuthBootstrapUser, TenantMembership } from "@/lib/auth/types";
import type { components } from "@/lib/api/schema.gen";
import { requireEnv } from "@/lib/server/env";

type AuthMeRead = components["schemas"]["AuthMeRead"];

export type AuthMeFetchResult =
  | { kind: "success"; user: AuthBootstrapUser; memberships: TenantMembership[] }
  | { kind: "unauthenticated" }
  | { kind: "not_provisioned" }
  | { kind: "error" };

export async function fetchAuthMe(headers: Record<string, string>): Promise<AuthMeFetchResult> {
  let apiBaseUrl: string;
  try {
    apiBaseUrl = requireEnv("CMP_API_BASE_URL");
  } catch {
    return { kind: "error" };
  }

  let upstream: Response;
  try {
    upstream = await fetch(new URL("/auth/me", apiBaseUrl), {
      headers: { ...headers, Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    return { kind: "error" };
  }

  if (upstream.status === 401) return { kind: "unauthenticated" };
  if (upstream.status === 403) return { kind: "not_provisioned" };
  if (upstream.status !== 200) return { kind: "error" };

  let body: AuthMeRead;
  try {
    body = (await upstream.json()) as AuthMeRead;
  } catch {
    return { kind: "error" };
  }

  return {
    kind: "success",
    user: { id: body.user.id, email: body.user.email, displayName: body.user.display_name },
    memberships: body.memberships.map((m) => ({
      tenantId: m.tenant_id,
      tenantCode: m.tenant_code,
      tenantName: m.tenant_name,
      roleCode: m.role_code,
    })),
  };
}
