"use client";

import type { QueryClient } from "@tanstack/react-query";

/**
 * CMP-owned sign-out sequence (AUTH-001B3):
 *  1. Clear the QueryClient -- no stale tenant-scoped (or bootstrap)
 *     data may survive into whatever renders next.
 *  2. Best-effort CMP-owned cleanup (POST /api/auth/logout) -- clears
 *     the cmp_tenant_id cookie only, and returns the absolute post-logout
 *     redirect target resolved server-side from the trusted app origin
 *     (see lib/server/same-origin.ts::resolveTrustedAppOrigin). Never
 *     touches any Auth0-owned cookie or session state directly.
 *  3. Hand off to the SDK-owned /auth/logout route via a full page
 *     navigation (not client-side routing -- this leaves the SPA
 *     entirely, into the SDK's own redirect/provider-logout flow), with
 *     an ABSOLUTE `returnTo`: the SDK's logout handler forwards `returnTo`
 *     straight into the OIDC `post_logout_redirect_uri` without resolving
 *     a relative value against its own configured base URL, so a bare
 *     "/login" reaches Auth0 unresolved and fails its Allowed Logout URLs
 *     check (LIVE-ACCEPTANCE-HOTFIX-001). `window.location.origin` is used
 *     only as a last-resort fallback if step 2's fetch itself fails --
 *     it is this same browser's actual page origin, not an
 *     attacker-controllable header, so it cannot introduce an open
 *     redirect; the literal "/login" path is always appended, never a
 *     caller-supplied path.
 *
 * A failure in step 2 does not block steps 1/3 -- an un-cleared
 * cmp_tenant_id cookie is not an authorization credential (B2 already
 * fresh-validates it against real membership on every use), so it is
 * safe to proceed with the SDK logout regardless.
 */
export async function performSignOut(queryClient: QueryClient): Promise<void> {
  queryClient.clear();
  let postLogoutRedirectUri: string | null = null;
  try {
    const response = await fetch("/api/auth/logout", { method: "POST" });
    const data: unknown = await response.json();
    const candidate = (data as { postLogoutRedirectUri?: unknown } | null)?.postLogoutRedirectUri;
    if (typeof candidate === "string") {
      postLogoutRedirectUri = candidate;
    }
  } catch {
    // Best-effort only -- see doc comment above.
  }
  const returnTo = postLogoutRedirectUri ?? new URL("/login", window.location.origin).toString();
  window.location.assign(`/auth/logout?returnTo=${encodeURIComponent(returnTo)}`);
}
