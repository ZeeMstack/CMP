/**
 * The one place `Auth0Client` gets constructed. Deliberately lazy (not a
 * module-scope singleton constructed at import time): `resolveAuthMode()`
 * (see auth-mode.ts) may resolve to "dev" or "test" bypass, in which case
 * no code path ever calls `getAuth0Client()` and no Auth0 configuration
 * needs to exist at all -- this is what lets `next build` and dev/test
 * runtimes work without a real Auth0 tenant configured (AUTH-001C).
 *
 * `domain` / `clientId` / `clientSecret` / `appBaseUrl` / `secret` are
 * intentionally left unset here: the SDK reads them itself from
 * AUTH0_DOMAIN / AUTH0_CLIENT_ID / AUTH0_CLIENT_SECRET / APP_BASE_URL /
 * AUTH0_SECRET when omitted -- no reason to duplicate that env-reading
 * logic ourselves. `CMP_API_AUDIENCE` is CMP-specific naming (mirrors
 * FastAPI's own OIDC_AUDIENCE), so we do pass that one explicitly.
 *
 * `offline_access` is included because the BFF must be able to silently
 * refresh an expired CMP API access token server-side without forcing a
 * new interactive login -- the SDK's `getAccessToken()` only does this
 * when a refresh token is present, which requires requesting this scope
 * at login. `openid profile email` is the baseline identity scope set;
 * nothing CMP-role-related is ever requested here -- CMP resolves roles
 * itself via (oidc_issuer, oidc_subject) against tenant_memberships, not
 * from any Auth0 claim (see AUTH-001A).
 */

import { Auth0Client } from "@auth0/nextjs-auth0/server";

import { requireEnv } from "@/lib/server/env";

let client: Auth0Client | null = null;

export function getAuth0Client(): Auth0Client {
  if (!client) {
    client = new Auth0Client({
      authorizationParameters: {
        audience: requireEnv("CMP_API_AUDIENCE"),
        scope: "openid profile email offline_access",
      },
    });
  }
  return client;
}

/** Test-only hook: lets tests inject a client built with a known `secret`
 * (so `@auth0/nextjs-auth0/testing`'s `generateSessionCookie` can produce
 * a cookie this client will actually decrypt) without touching the
 * production singleton's lazy-construction contract. */
export function setAuth0ClientForTesting(testClient: Auth0Client | null): void {
  client = testClient;
}
