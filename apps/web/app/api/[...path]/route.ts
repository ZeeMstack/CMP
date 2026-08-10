import { NextRequest, NextResponse } from "next/server";

import { devIdentity, resolveAuthMode, testIdentity } from "@/lib/server/auth-mode";
import { requireEnv } from "@/lib/server/env";
import { getAuthenticatedSession, getCmpApiAccessToken, SessionExpiredError } from "@/lib/server/session";

/**
 * Server-side, read-only proxy to the CMP backend (AUTH-001B1).
 *
 * GET ONLY -- deliberately, unchanged from FE-001/FE-002B. No business
 * mutation UX exists yet; widening this to other HTTP verbs is a future
 * ticket's decision, not a side effect of adding authentication.
 *
 * Identity attached to the upstream request depends on `resolveAuthMode()`
 * (see lib/server/auth-mode.ts):
 *  - "dev"/"test": the existing FastAPI dev-auth headers (X-Dev-Tenant-Id /
 *    X-Dev-User-Id), sourced from CMP_DEV_ or CMP_TEST_ variables -- never
 *    from the removed CMP_PILOT_ variables.
 *  - "real": a CMP API access token obtained via the Auth0-backed session,
 *    forwarded as `Authorization: Bearer <token>`. Never an ID token,
 *    never the raw session cookie, never an Auth0 user ID.
 *
 * Tenant selection (X-CMP-Tenant-Id) is intentionally NOT attached to any
 * request in B1 -- that is B2's job. GET /auth/me does not need it (it is
 * deliberately tenant-unscoped on the backend); any tenant-scoped route
 * called through the real-auth path before B2 ships will legitimately
 * receive FastAPI's own 400 "X-CMP-Tenant-Id is required" -- that is
 * correct, intentional, partial-rollout behavior, not a bug to work
 * around here with a guessed or fixed tenant id.
 */
export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;

  let apiBaseUrl: string;
  try {
    apiBaseUrl = requireEnv("CMP_API_BASE_URL");
  } catch (error) {
    return NextResponse.json(
      { error: "proxy_misconfigured", detail: (error as Error).message },
      { status: 500 },
    );
  }

  let mode: ReturnType<typeof resolveAuthMode>;
  try {
    mode = resolveAuthMode();
  } catch (error) {
    // Fail-closed: an ambiguous or unsafe bypass configuration must never
    // silently fall through to any identity mechanism.
    return NextResponse.json(
      { error: "auth_configuration_error", detail: (error as Error).message },
      { status: 500 },
    );
  }

  const upstreamHeaders: Record<string, string> = { Accept: "application/json" };
  // Only ever populated when a token is actually obtained in "real" mode;
  // propagated onto the final response so a refreshed/rotated session
  // cookie reaches the browser (see getCmpApiAccessToken's doc comment).
  const cookieCarrier = new NextResponse();

  if (mode === "dev" || mode === "test") {
    let identity: ReturnType<typeof devIdentity>;
    try {
      identity = mode === "dev" ? devIdentity() : testIdentity();
    } catch (error) {
      // Fail-closed here too: an incomplete bypass identity must never
      // silently fall through to an unauthenticated or partially-headered
      // request.
      return NextResponse.json(
        { error: "auth_configuration_error", detail: (error as Error).message },
        { status: 500 },
      );
    }
    upstreamHeaders["X-Dev-Tenant-Id"] = identity.tenantId;
    upstreamHeaders["X-Dev-User-Id"] = identity.userId;
  } else {
    const session = await getAuthenticatedSession(request);
    if (!session) {
      return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
    }
    let token: string;
    try {
      token = await getCmpApiAccessToken(request, cookieCarrier);
    } catch (error) {
      if (error instanceof SessionExpiredError) {
        return NextResponse.json({ error: "session_expired" }, { status: 401 });
      }
      throw error;
    }
    upstreamHeaders["Authorization"] = `Bearer ${token}`;
  }

  const upstreamUrl = new URL(`/${path.join("/")}`, apiBaseUrl);
  upstreamUrl.search = request.nextUrl.search;

  let upstreamResponse: Response;
  try {
    upstreamResponse = await fetch(upstreamUrl, {
      method: "GET",
      headers: upstreamHeaders,
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "network_error", detail: "Could not reach the backend" }, { status: 502 });
  }

  const body = await upstreamResponse.text();
  const response = new NextResponse(body, {
    status: upstreamResponse.status,
    headers: { "Content-Type": upstreamResponse.headers.get("Content-Type") ?? "application/json" },
  });
  for (const cookie of cookieCarrier.cookies.getAll()) {
    response.cookies.set(cookie);
  }
  return response;
}
