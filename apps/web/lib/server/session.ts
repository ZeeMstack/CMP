/**
 * The CMP-owned server authentication/session boundary (AUTH-001B1).
 *
 * Every other server-side module that needs "get me a token to call
 * FastAPI with" should import from here, never from `@auth0/nextjs-auth0`
 * directly and never from `lib/server/auth0.ts` directly. This is the
 * seam that keeps Auth0-specific shapes (`SessionData`, `User`, raw
 * claims) out of the rest of the frontend -- nothing downstream of this
 * module should ever see an Auth0 `User` object; that is deliberate (see
 * AUTH-001B audit, "Auth0-specific data must not leak into domain").
 *
 * B1 exposes only session/token primitives. The CMP-shaped `/auth/me`
 * bootstrap (fetching FastAPI's own user+memberships contract through
 * this token) is B2's job, not this module's.
 *
 * AUTH-001C.2: this module intentionally exposes only token acquisition,
 * not a standalone "get the session" primitive. `getCmpApiAccessToken()`
 * is the sole, authoritative real-auth check for every CMP operational
 * BFF call -- it resolves the current Auth0-managed session internally
 * (see the SDK evidence below) and fails the same way whether there was
 * no session at all or a session that couldn't yield a usable token, so
 * a separate session precheck would be redundant and could drift out of
 * sync. This does not touch Auth0 SDK session support globally -- the
 * SDK-owned `/auth/profile` route still resolves the session
 * independently for its own purposes; CMP's BFF simply never needs to
 * fetch the Auth0 user/profile itself just to call FastAPI.
 */

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
 * Returns a CMP API access token (never an ID token, never the raw
 * session cookie) for the configured `CMP_API_AUDIENCE`, refreshing it
 * server-side via the SDK's refresh-token flow if the cached one has
 * expired.
 *
 * Zero-argument App Router overload. Every caller of this module is a
 * Route Handler (App Router), so this always uses the SDK's
 * zero-argument overload, which reads the session cookie via
 * `next/headers`'s `cookies()` (implicit request context) rather than an
 * explicit `NextRequest` -- passing a request/response here would
 * silently select the middleware/Pages-Router overload instead, which
 * does not read the App-Router-managed session the same way (see
 * AUTH-001C.1). When called from a Route Handler, the SDK persists a
 * refreshed session cookie itself via `next/headers`'s `cookies()` --
 * there is no response/cookie-carrier object for CMP to propagate; the
 * SDK writes directly to the response Next.js is already building for
 * this request.
 *
 * The SDK's `getAccessToken()` resolves the current Auth0-managed
 * session itself (confirmed by reading the installed
 * `@auth0/nextjs-auth0@4.26.0` source, `server/client.js`
 * `executeGetAccessToken`): it calls its own internal
 * `getSessionFromAuthClient()` and throws `AccessTokenError` (codes
 * `missing_session`, `missing_refresh_token`, `failed_to_refresh_token`,
 * `session_expired`) before ever returning a token if no usable session
 * exists. Every one of those is caught below and wrapped uniformly into
 * `SessionExpiredError` -- callers do not need to call a separate
 * "is there a session" check first solely to decide whether calling this
 * is worthwhile (AUTH-001C.2).
 */
export async function getCmpApiAccessToken(): Promise<string> {
  try {
    const { token } = await getAuth0Client().getAccessToken();
    return token;
  } catch (err) {
    throw new SessionExpiredError(err);
  }
}
