import { NextRequest, NextResponse } from "next/server";

import type { AuthBootstrap } from "@/lib/auth/types";
import { resolveAuthMode } from "@/lib/server/auth-mode";
import { fetchAuthMe } from "@/lib/server/fetch-auth-me";
import { propagateCookies } from "@/lib/server/propagate-cookies";
import { isSameOriginRequest } from "@/lib/server/same-origin";
import { applyTenantCookieAction } from "@/lib/server/tenant-selection";
import { resolveIdentityForAuthMe } from "@/lib/server/upstream-identity";
import { isValidUuid } from "@/lib/server/uuid";

/**
 * Explicit tenant selection (AUTH-001B2). NOT a business mutation proxy --
 * the generic `/api/[...path]` remains GET-only; this is a dedicated,
 * narrow, CMP-owned endpoint.
 *
 * The requested `tenant_id` is never trusted from client-cached state: a
 * *fresh* GET /auth/me is fetched here and the requested tenant must
 * appear in that fresh membership list, or the selection is rejected
 * (403) and the cookie is left untouched. This is what makes a stale or
 * fabricated client-side membership claim harmless.
 */
export async function POST(request: NextRequest) {
  if (!isSameOriginRequest(request)) {
    return NextResponse.json({ error: "cross_origin_rejected" }, { status: 403 });
  }

  let mode: ReturnType<typeof resolveAuthMode>;
  try {
    mode = resolveAuthMode();
  } catch (error) {
    return NextResponse.json({ error: "auth_configuration_error", detail: (error as Error).message }, { status: 500 });
  }

  let requestBody: unknown;
  try {
    requestBody = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid_request", detail: "Request body must be JSON" }, { status: 400 });
  }
  const tenantId = (requestBody as { tenant_id?: unknown } | null)?.tenant_id;
  if (tenantId === undefined || tenantId === null || tenantId === "") {
    return NextResponse.json({ error: "invalid_request", detail: "tenant_id is required" }, { status: 400 });
  }
  if (!isValidUuid(tenantId)) {
    return NextResponse.json({ error: "invalid_request", detail: "tenant_id must be a valid UUID" }, { status: 400 });
  }

  const cookieCarrier = new NextResponse();
  const identity = await resolveIdentityForAuthMe(request, cookieCarrier, mode);
  if (!identity.ok) {
    const response = NextResponse.json(identity.error.body, { status: identity.error.status });
    propagateCookies(cookieCarrier, response);
    return response;
  }

  const authMe = await fetchAuthMe(identity.headers);

  if (authMe.kind === "unauthenticated") {
    const response = NextResponse.json({ error: "unauthenticated" }, { status: 401 });
    propagateCookies(cookieCarrier, response);
    return response;
  }
  if (authMe.kind === "not_provisioned") {
    const response = NextResponse.json({ error: "not_provisioned" }, { status: 403 });
    propagateCookies(cookieCarrier, response);
    return response;
  }
  if (authMe.kind === "error") {
    const response = NextResponse.json({ error: "backend_error" }, { status: 502 });
    propagateCookies(cookieCarrier, response);
    return response;
  }

  const match = authMe.memberships.find((m) => m.tenantId === tenantId);
  if (!match) {
    // Generic detail regardless of *why* the tenant is inaccessible
    // (doesn't exist, isn't active, or simply isn't one of this user's
    // current memberships) -- never confirm or deny another tenant's
    // existence to the caller.
    const response = NextResponse.json({ error: "tenant_not_accessible" }, { status: 403 });
    propagateCookies(cookieCarrier, response);
    return response;
  }

  const body: AuthBootstrap = {
    status: "authenticated",
    user: authMe.user,
    memberships: authMe.memberships,
    selectedTenantId: tenantId,
  };
  const response = NextResponse.json(body);
  applyTenantCookieAction(response, { kind: "set", tenantId }, mode);
  propagateCookies(cookieCarrier, response);
  return response;
}
