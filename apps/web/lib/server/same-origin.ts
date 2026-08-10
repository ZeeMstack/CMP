import type { NextRequest } from "next/server";

/**
 * Lightweight, proportionate CSRF defense for state-changing same-origin
 * Route Handlers (AUTH-001B2) -- not a custom CSRF-token framework.
 * SameSite=Lax session/tenant cookies are already the primary protection
 * against cross-site request forgery here (a cross-site POST cannot carry
 * a Lax cookie); this is defense in depth on top of that, checking the
 * browser-supplied `Origin` header against the request's own host.
 *
 * A present-but-mismatched Origin is rejected. A missing Origin is
 * accepted -- some legitimate same-origin/same-site requests omit it,
 * and SameSite already does the heavy lifting for the cross-site case.
 */
export function isSameOriginRequest(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try {
    return new URL(origin).host === request.nextUrl.host;
  } catch {
    return false;
  }
}
