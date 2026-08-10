// @vitest-environment node
/**
 * Adapter-contract tests: prove our usage of the *real*, installed
 * @auth0/nextjs-auth0 SDK is correct -- real session encryption/
 * decryption via the SDK's own `generateSessionCookie` testing helper,
 * real `Auth0Client` instance, real `getSession`/`getAccessToken` calls.
 * Not a test of Auth0's library itself (its encryption/OIDC correctness
 * is the SDK's own responsibility) -- only that CMP's wrapper drives it
 * the way we assume. No network call, no live Auth0 tenant.
 */
import { Auth0Client } from "@auth0/nextjs-auth0/server";
import { generateSessionCookie } from "@auth0/nextjs-auth0/testing";
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

const TEST_SECRET = "a".repeat(64); // 32-byte hex, matches AUTH0_SECRET's documented format
const TEST_DOMAIN = "cmp-test.us.auth0.com";
const TEST_CLIENT_ID = "test-client-id";
const TEST_CLIENT_SECRET = "test-client-secret";
const TEST_APP_BASE_URL = "https://cmp.example.test";
const TEST_AUDIENCE = "https://cmp-api.example.test";

function buildTestClient() {
  return new Auth0Client({
    domain: TEST_DOMAIN,
    clientId: TEST_CLIENT_ID,
    clientSecret: TEST_CLIENT_SECRET,
    appBaseUrl: TEST_APP_BASE_URL,
    secret: TEST_SECRET,
    authorizationParameters: { audience: TEST_AUDIENCE, scope: "openid profile email offline_access" },
  });
}

async function requestWithSessionCookie(sessionOverrides: Record<string, unknown> = {}) {
  const futureExpiry = Math.floor(Date.now() / 1000) + 3600;
  const cookieValue = await generateSessionCookie(
    {
      user: { sub: "auth0|cmp-test-user" },
      tokenSet: {
        accessToken: "real-sdk-managed-access-token",
        expiresAt: futureExpiry,
        audience: TEST_AUDIENCE,
        scope: "openid profile email offline_access",
      },
      internal: { sid: "test-sid", createdAt: Math.floor(Date.now() / 1000) },
      ...sessionOverrides,
    },
    { secret: TEST_SECRET },
  );
  return new NextRequest(`${TEST_APP_BASE_URL}/`, { headers: { cookie: `__session=${cookieValue}` } });
}

describe("Auth0Client wiring (real SDK, no network)", () => {
  it("getSession(request) decrypts a real SDK-generated session cookie", async () => {
    const client = buildTestClient();
    const request = await requestWithSessionCookie();

    const session = await client.getSession(request);

    expect(session).not.toBeNull();
    expect(session?.user.sub).toBe("auth0|cmp-test-user");
  });

  it("getSession(request) returns null when no session cookie is present", async () => {
    const client = buildTestClient();
    const request = new NextRequest(`${TEST_APP_BASE_URL}/`);

    await expect(client.getSession(request)).resolves.toBeNull();
  });

  it("getAccessToken(request, response) returns the cached token for the configured audience without a network call", async () => {
    const client = buildTestClient();
    const request = await requestWithSessionCookie();
    const response = new (await import("next/server")).NextResponse();

    const result = await client.getAccessToken(request, response);

    expect(result.token).toBe("real-sdk-managed-access-token");
    expect(result.audience).toBe(TEST_AUDIENCE);
  });

  it("a session cookie encrypted with a different secret does not decrypt (tamper/misconfiguration resistance)", async () => {
    const client = buildTestClient();
    const wrongSecretCookie = await generateSessionCookie(
      {
        user: { sub: "auth0|cmp-test-user" },
        tokenSet: { accessToken: "x", expiresAt: Math.floor(Date.now() / 1000) + 3600, audience: TEST_AUDIENCE },
        internal: { sid: "test-sid", createdAt: Math.floor(Date.now() / 1000) },
      },
      { secret: "b".repeat(64) },
    );
    const request = new NextRequest(`${TEST_APP_BASE_URL}/`, {
      headers: { cookie: `__session=${wrongSecretCookie}` },
    });

    await expect(client.getSession(request)).resolves.toBeNull();
  });
});
