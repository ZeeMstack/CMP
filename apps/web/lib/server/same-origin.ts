import type { NextRequest } from "next/server";

import { resolveAuthMode } from "@/lib/server/auth-mode";

const WEB_URL_SCHEMES = new Set(["http:", "https:"]);

/**
 * Resolves the trusted public application origin from `APP_BASE_URL`
 * (DEPLOY-001G) -- the same value the Auth0 SDK already requires and uses
 * to build callback/redirect URLs (see auth0.ts, auth-mode.ts), so it is
 * necessarily already correct for the deployment or login itself would be
 * broken. Only ever consulted in `mode === "real"` (see below).
 *
 * Returns `null` for anything that must not be trusted: unset, unparseable,
 * or a non-web scheme (e.g. `javascript:`, `file:`, `ftp:`) -- callers must
 * treat `null` as "fail closed", never fall back to a weaker check.
 */
function resolveTrustedOrigin(): string | null {
  const raw = process.env.APP_BASE_URL;
  if (!raw) return null;
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return null;
  }
  if (!WEB_URL_SCHEMES.has(parsed.protocol)) return null;
  return parsed.origin;
}

/**
 * Lightweight, proportionate CSRF defense for state-changing same-origin
 * Route Handlers (AUTH-001B2) -- not a custom CSRF-token framework.
 * SameSite=Lax session/tenant cookies are already the primary protection
 * against cross-site request forgery here (a cross-site POST cannot carry
 * a Lax cookie); this is defense in depth on top of that, checking the
 * browser-supplied `Origin` header against a trusted host.
 *
 * A present-but-mismatched Origin is rejected. A missing Origin is
 * accepted -- some legitimate same-origin/same-site requests omit it,
 * and SameSite already does the heavy lifting for the cross-site case.
 *
 * DEPLOY-001G: `request.nextUrl.host` reflects the Next.js standalone
 * server's own bind address (`HOSTNAME`/`PORT`, e.g. `0.0.0.0:10000`), not
 * the browser-facing public host, whenever the server was started with an
 * explicit hostname/port -- true for every containerized deployment
 * (Render, the Compose/Caddy pilot), regardless of reverse-proxy headers.
 * In real auth mode this is corrected by trusting the explicitly configured
 * `APP_BASE_URL` instead. Dev/test bypass modes never require
 * `APP_BASE_URL` and keep comparing against `request.nextUrl.host`, which
 * is accurate there (`next dev`/`next start` bind to `localhost`, matching
 * the browser's own `Origin`).
 */
export function isSameOriginRequest(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true;

  let originUrl: URL;
  try {
    originUrl = new URL(origin);
  } catch {
    return false;
  }

  let mode: ReturnType<typeof resolveAuthMode>;
  try {
    mode = resolveAuthMode();
  } catch {
    // Ambiguous/unsafe auth configuration -- fail closed rather than
    // falling through to any same-origin comparison.
    return false;
  }

  if (mode === "real") {
    const trustedOrigin = resolveTrustedOrigin();
    if (!trustedOrigin) return false;
    return originUrl.origin === trustedOrigin;
  }

  return originUrl.host === request.nextUrl.host;
}
