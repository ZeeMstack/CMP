"use client";

import type { AuthBootstrap } from "@/lib/auth/types";

const ERROR_BOOTSTRAP: AuthBootstrap = { status: "error", user: null, memberships: [], selectedTenantId: null };

/** Always resolves with an `AuthBootstrap` -- never throws, and never
 * requires callers to distinguish "the fetch failed" from "the backend
 * said unauthenticated" (both are ordinary, expected UI states, not
 * exceptions). A response body missing the expected shape (a genuinely
 * broken/unreachable backend) becomes `status: "error"`. */
export async function fetchAuthBootstrap(signal?: AbortSignal): Promise<AuthBootstrap> {
  try {
    const response = await fetch("/api/auth/bootstrap", { signal, cache: "no-store" });
    const body = await response.json().catch(() => null);
    if (body && typeof body.status === "string") {
      return body as AuthBootstrap;
    }
    return ERROR_BOOTSTRAP;
  } catch {
    return ERROR_BOOTSTRAP;
  }
}

export type SelectTenantResult = { ok: true; bootstrap: AuthBootstrap } | { ok: false; status: number };

export async function selectTenant(tenantId: string, signal?: AbortSignal): Promise<SelectTenantResult> {
  const response = await fetch("/api/tenant/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tenant_id: tenantId }),
    signal,
  });
  if (!response.ok) {
    return { ok: false, status: response.status };
  }
  const bootstrap = (await response.json()) as AuthBootstrap;
  return { ok: true, bootstrap };
}
