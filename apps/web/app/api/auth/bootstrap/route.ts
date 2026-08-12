import { NextRequest, NextResponse } from "next/server";

import type { AuthBootstrap } from "@/lib/auth/types";
import { resolveAuthMode } from "@/lib/server/auth-mode";
import { fetchAuthMe } from "@/lib/server/fetch-auth-me";
import { applyTenantCookieAction, readSelectedTenantId } from "@/lib/server/tenant-selection";
import { reconcileSelectedTenant } from "@/lib/server/tenant-reconciliation";
import { resolveIdentityForAuthMe } from "@/lib/server/upstream-identity";

const EMPTY_BOOTSTRAP: Omit<AuthBootstrap, "status"> = { user: null, memberships: [], selectedTenantId: null };

/**
 * The ONE central bootstrap endpoint (AUTH-001B2). Calls FastAPI's
 * GET /auth/me exactly once per invocation, reconciles the result against
 * whatever tenant is currently selected (see tenant-reconciliation.ts),
 * and returns a single CMP-owned `AuthBootstrap` shape -- callers never
 * see Auth0's session/user shape or the raw generated `AuthMeRead`.
 *
 * Always responds with a JSON body containing `status`; the HTTP status
 * code mirrors that same state (200 authenticated, 401 unauthenticated,
 * 403 not_provisioned, 502 error) for consistency with the rest of this
 * codebase's status-driven error handling, while still giving the client
 * a body it can read uniformly regardless of status.
 */
export async function GET(request: NextRequest) {
  let mode: ReturnType<typeof resolveAuthMode>;
  try {
    mode = resolveAuthMode();
  } catch (error) {
    return NextResponse.json(
      { status: "error", ...EMPTY_BOOTSTRAP, detail: (error as Error).message },
      { status: 500 },
    );
  }

  const identity = await resolveIdentityForAuthMe(mode);
  if (!identity.ok) {
    const status: AuthBootstrap["status"] = identity.error.status === 401 ? "unauthenticated" : "error";
    return NextResponse.json({ status, ...EMPTY_BOOTSTRAP }, { status: identity.error.status });
  }

  const authMe = await fetchAuthMe(identity.headers);

  if (authMe.kind === "unauthenticated") {
    return NextResponse.json({ status: "unauthenticated", ...EMPTY_BOOTSTRAP }, { status: 401 });
  }
  if (authMe.kind === "not_provisioned") {
    return NextResponse.json({ status: "not_provisioned", ...EMPTY_BOOTSTRAP }, { status: 403 });
  }
  if (authMe.kind === "error") {
    return NextResponse.json({ status: "error", ...EMPTY_BOOTSTRAP }, { status: 502 });
  }

  const existingCookieTenantId = readSelectedTenantId(request);
  const { selectedTenantId, cookieAction } = reconcileSelectedTenant(authMe.memberships, existingCookieTenantId);

  const body: AuthBootstrap = {
    status: "authenticated",
    user: authMe.user,
    memberships: authMe.memberships,
    selectedTenantId,
  };
  const response = NextResponse.json(body);
  applyTenantCookieAction(response, cookieAction, mode);
  return response;
}
