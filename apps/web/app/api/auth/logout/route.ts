import { NextRequest, NextResponse } from "next/server";

import { resolveAuthMode } from "@/lib/server/auth-mode";
import { isSameOriginRequest, resolveTrustedAppOrigin } from "@/lib/server/same-origin";
import { applyTenantCookieAction } from "@/lib/server/tenant-selection";

/**
 * CMP-owned session housekeeping (AUTH-001B3) -- NOT a business mutation
 * proxy; the generic `/api/[...path]` remains GET-only. Clears only the
 * `cmp_tenant_id` cookie. Never touches any Auth0-owned cookie/session
 * state -- that is exclusively the SDK's `/auth/logout` route's job
 * (see lib/auth/logout.ts, which calls this first and then hands off to
 * it via a full page navigation).
 *
 * Also resolves the absolute post-logout redirect target
 * (LIVE-ACCEPTANCE-HOTFIX-001) and hands it back so the client can pass it
 * to the SDK's `/auth/logout` route as `returnTo`: that route forwards
 * `returnTo` straight into `post_logout_redirect_uri` without resolving a
 * relative value against `appBaseUrl` itself, so building the absolute URL
 * here (from the same trusted-origin source used for the same-origin
 * check, never from this request's own Host/forwarded headers) is what
 * keeps it matching an Auth0 Allowed Logout URL.
 */
export async function POST(request: NextRequest) {
  if (!isSameOriginRequest(request)) {
    return NextResponse.json({ error: "cross_origin_rejected" }, { status: 403 });
  }

  // The Secure flag choice only affects how reliably the browser accepts
  // the clearing Set-Cookie; an auth-mode resolution failure here must
  // not block cleanup, so fall back to the strictest (production) choice.
  let mode: ReturnType<typeof resolveAuthMode>;
  try {
    mode = resolveAuthMode();
  } catch {
    mode = "real";
  }

  const trustedOrigin = resolveTrustedAppOrigin(request, mode);
  const postLogoutRedirectUri = trustedOrigin ? new URL("/login", trustedOrigin).toString() : null;

  const response = NextResponse.json({ ok: true, postLogoutRedirectUri });
  applyTenantCookieAction(response, { kind: "clear" }, mode);
  return response;
}
