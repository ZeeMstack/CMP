/**
 * The `cmp_tenant_id` cookie: CMP-owned, server-only read/write (AUTH-001B2).
 *
 * This cookie is UX state, not authorization truth -- FastAPI independently
 * re-validates active membership on every tenant-scoped request
 * (`require_tenant_context`, AUTH-001A). A user (or a malicious browser)
 * changing this value can never grant access to a tenant they are not a
 * member of; it can only ever change *which* tenant the BFF asks FastAPI
 * about. That is also exactly why no signature/encryption is applied here
 * -- there is nothing to protect against tampering, because tampering
 * cannot escalate access. HttpOnly is still set so ordinary page
 * JavaScript never reads or writes it directly; only server Route
 * Handlers do.
 */

import type { NextRequest, NextResponse } from "next/server";

import type { AuthMode } from "@/lib/server/auth-mode";
import type { TenantCookieAction } from "@/lib/server/tenant-reconciliation";

export const TENANT_COOKIE_NAME = "cmp_tenant_id";

export function readSelectedTenantId(request: NextRequest): string | null {
  return request.cookies.get(TENANT_COOKIE_NAME)?.value ?? null;
}

/**
 * `Secure` is required whenever real Auth0-backed authentication is
 * actually running in a production-shaped runtime -- the one case where
 * this cookie travels over a real, deployed origin. Dev mode and the
 * Playwright test-only mode both run over local HTTP (`next start` on
 * 127.0.0.1 with no TLS in front of it for the test harness), so `Secure`
 * there would make the browser silently refuse to store the cookie at
 * all -- not a security improvement, just a broken feature. This must
 * never be loosened for "real" mode under NODE_ENV=production.
 */
export function tenantCookieSecureFlag(mode: AuthMode): boolean {
  if (mode === "real") {
    return process.env.NODE_ENV === "production";
  }
  return false;
}

/** Applies a `TenantCookieAction` to a `NextResponse`. Deliberately no
 * `maxAge`/`expires` -- a plain session cookie is sufficient (matches the
 * lifetime of "what was I last looking at," not an authorization grant
 * that would need a bounded lifetime of its own). Deliberately no
 * `domain` -- host-only, never shared across subdomains. */
export function applyTenantCookieAction(response: NextResponse, action: TenantCookieAction, mode: AuthMode): void {
  if (action.kind === "set") {
    response.cookies.set(TENANT_COOKIE_NAME, action.tenantId, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      secure: tenantCookieSecureFlag(mode),
    });
    return;
  }
  if (action.kind === "clear") {
    response.cookies.set(TENANT_COOKIE_NAME, "", {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      secure: tenantCookieSecureFlag(mode),
      maxAge: 0,
    });
    return;
  }
  // "none" -- no-op, intentionally left untouched.
}
