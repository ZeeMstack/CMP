/**
 * The CMP-owned server authentication/session boundary (AUTH-001B1).
 *
 * Every other server-side module that needs "is there a session" or "get
 * me a token to call FastAPI with" should import from here, never from
 * `@auth0/nextjs-auth0` directly and never from `lib/server/auth0.ts`
 * directly. This is the seam that keeps Auth0-specific shapes
 * (`SessionData`, `User`, raw claims) out of the rest of the frontend --
 * nothing downstream of this module should ever see an Auth0 `User`
 * object; that is deliberate (see AUTH-001B audit, "Auth0-specific data
 * must not leak into domain").
 *
 * B1 exposes only session/token primitives. The CMP-shaped `/auth/me`
 * bootstrap (fetching FastAPI's own user+memberships contract through
 * this token) is B2's job, not this module's.
 */

import type { NextRequest, NextResponse } from "next/server";

import { getAuth0Client } from "@/lib/server/auth0";

/** Thrown whenever a CMP API access token cannot be obtained in real-auth
 * mode -- no session, an unrefreshable/revoked session, or any other SDK
 * failure. Callers must map this to a generic 401, never surface the
 * underlying SDK/provider error message to a client (mirrors the
 * backend's own `TokenVerificationError` -> generic-401 pattern). */
export class SessionExpiredError extends Error {
  constructor(cause: unknown) {
    super("CMP API access token could not be obtained");
    this.name = "SessionExpiredError";
    this.cause = cause;
  }
}

/**
 * Returns the current Auth0-managed session, or `null` if the caller is
 * not authenticated. Real-auth mode only -- callers in dev/test bypass
 * mode must not call this (see `lib/server/upstream-auth.ts`).
 */
export async function getAuthenticatedSession(request: NextRequest) {
  return getAuth0Client().getSession(request);
}

/**
 * Returns a CMP API access token (never an ID token, never the raw
 * session cookie) for the configured `CMP_API_AUDIENCE`, refreshing it
 * server-side via the SDK's refresh-token flow if the cached one has
 * expired. `cookieCarrier` is a `NextResponse` the caller must propagate
 * any Set-Cookie headers from onto its real outgoing response --
 * refreshing a token can rotate the session cookie, and that rotation
 * has to reach the browser or the next request will refresh again
 * needlessly (or, if the refresh token itself was single-use/rotating,
 * fail outright).
 */
export async function getCmpApiAccessToken(request: NextRequest, cookieCarrier: NextResponse): Promise<string> {
  try {
    const { token } = await getAuth0Client().getAccessToken(request, cookieCarrier);
    return token;
  } catch (err) {
    throw new SessionExpiredError(err);
  }
}
