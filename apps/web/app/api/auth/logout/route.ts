import { NextRequest, NextResponse } from "next/server";

import { resolveAuthMode } from "@/lib/server/auth-mode";
import { isSameOriginRequest } from "@/lib/server/same-origin";
import { applyTenantCookieAction } from "@/lib/server/tenant-selection";

/**
 * CMP-owned session housekeeping (AUTH-001B3) -- NOT a business mutation
 * proxy; the generic `/api/[...path]` remains GET-only. Clears only the
 * `cmp_tenant_id` cookie. Never touches any Auth0-owned cookie/session
 * state -- that is exclusively the SDK's `/auth/logout` route's job
 * (see lib/auth/logout.ts, which calls this first and then hands off to
 * it via a full page navigation).
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

  const response = NextResponse.json({ ok: true });
  applyTenantCookieAction(response, { kind: "clear" }, mode);
  return response;
}
