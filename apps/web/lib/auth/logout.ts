"use client";

import type { QueryClient } from "@tanstack/react-query";

/**
 * CMP-owned sign-out sequence (AUTH-001B3):
 *  1. Clear the QueryClient -- no stale tenant-scoped (or bootstrap)
 *     data may survive into whatever renders next.
 *  2. Best-effort CMP-owned cleanup (POST /api/auth/logout) -- clears
 *     the cmp_tenant_id cookie only. Never touches any Auth0-owned
 *     cookie or session state directly.
 *  3. Hand off to the SDK-owned /auth/logout route via a full page
 *     navigation (not client-side routing -- this leaves the SPA
 *     entirely, into the SDK's own redirect/provider-logout flow),
 *     which owns deleting its own session cookie and returns the user
 *     to /login.
 *
 * A failure in step 2 does not block steps 1/3 -- an un-cleared
 * cmp_tenant_id cookie is not an authorization credential (B2 already
 * fresh-validates it against real membership on every use), so it is
 * safe to proceed with the SDK logout regardless.
 */
export async function performSignOut(queryClient: QueryClient): Promise<void> {
  queryClient.clear();
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch {
    // Best-effort only -- see doc comment above.
  }
  window.location.assign("/auth/logout?returnTo=/login");
}
