// @vitest-environment node
/**
 * Adapter-contract tests: prove our usage of the *real*, installed
 * @auth0/nextjs-auth0 SDK is correct -- real session encryption/
 * decryption via the SDK's own `generateSessionCookie` testing helper,
 * real `Auth0Client` instance, real `getSession`/`getAccessToken` calls.
 * Not a test of Auth0's library itself (its encryption/OIDC correctness
 * is the SDK's own responsibility) -- only that CMP's wrapper drives it
 * the way we assume. No network call, no live Auth0 tenant.
 *
 * AUTH-001C.1: CMP's own wrapper (`lib/server/session.ts`) calls the SDK's
 * zero-argument App Router overloads (`getSession()`, `getAccessToken()`),
 * never the `(request, response)` overloads below. Those overloads are
 * still exercised directly against the real SDK in this file -- not
 * because CMP uses them, but because they are the only practical way to
 * prove the shared session-cookie encrypt/decrypt machinery is wired
 * correctly without a live Next.js request-rendering pipeline: the
 * zero-arg overload reads via `next/headers`'s `cookies()`, which only
 * resolves inside a real Next.js request/work-unit async-storage
 * context (a Route Handler actually invoked by the Next.js server), and
 * throws outside of one -- see the "App Router (zero-argument) contract"
 * suite below, which proves exactly that delegation and its boundary.
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
  it("getSession(request) decrypts a real SDK-generated session cookie -- test-practicality only, CMP's own wrapper never calls this overload (see session.ts)", async () => {
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

describe("App Router (zero-argument) contract -- what session.ts actually calls", () => {
  it("getSession() with zero arguments delegates to next/headers (headers()/cookies()), not to any request object CMP could pass", async () => {
    const client = buildTestClient();

    // Outside a real Next.js request/work-unit async-storage context
    // (i.e. this Vitest process, which is not a running Next.js server),
    // `next/headers`'s `headers()`/`cookies()` throw E251 "called outside
    // a request scope" (confirmed by reading the installed SDK's
    // `resolveRequestContext`/`getSession`: the zero-arg path calls
    // `next/headers`'s `headers()` first, then `cookies()`). A plain
    // Vitest environment cannot fabricate that async-storage context, so
    // this is the strongest practical proof available without a live
    // Next.js server: it demonstrates the zero-arg overload genuinely
    // takes the `next/headers` code path (distinct from the
    // `getSession(request)` overload proven above, which does not
    // depend on that context at all) -- exactly the App Router contract
    // AUTH-001C.1's fix relies on. If the SDK ever silently fell back to
    // some other mechanism for the zero-arg form, this assertion would
    // fail (no throw, or a different error).
    await expect(client.getSession()).rejects.toThrow(/called outside a request scope/);
  });

  it("getAccessToken() with zero arguments also delegates to next/headers for both read and (would-be) refresh-persist", async () => {
    const client = buildTestClient();

    await expect(client.getAccessToken()).rejects.toThrow(/called outside a request scope/);
  });
});
