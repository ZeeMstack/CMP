import type { NextResponse } from "next/server";

/** Copies every cookie set on `from` (e.g. a session cookie refreshed
 * mid-request by getCmpApiAccessToken) onto the real outgoing response.
 * Shared by every route that threads a `cookieCarrier` through
 * resolveIdentityForAuthMe/resolveIdentityForTenantScopedCall. */
export function propagateCookies(from: NextResponse, to: NextResponse): void {
  for (const cookie of from.cookies.getAll()) {
    to.cookies.set(cookie);
  }
}
