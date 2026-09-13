// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

beforeEach(() => {
  vi.stubEnv("NODE_ENV", "development");
  // DEPLOY-001G: real auth mode (the default here -- no bypass flag is
  // stubbed) now trusts APP_BASE_URL rather than request.nextUrl.host for
  // the same-origin check; match it to this suite's request/Origin so the
  // legitimate-same-origin-request tests below still exercise that path.
  vi.stubEnv("APP_BASE_URL", "http://localhost");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

function callLogout(origin?: string | null) {
  const headers: Record<string, string> = {};
  if (origin !== undefined && origin !== null) headers.origin = origin;
  const request = new NextRequest("http://localhost/api/auth/logout", { method: "POST", headers });
  return POST(request);
}

describe("POST /api/auth/logout", () => {
  it("clears the cmp_tenant_id cookie (Max-Age=0)", async () => {
    const response = await callLogout("http://localhost");
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie") ?? "").toMatch(/cmp_tenant_id=/);
    expect(response.headers.get("set-cookie") ?? "").toMatch(/Max-Age=0/i);
  });

  it("clears cmp_tenant_id ONLY -- no other cookie is set or touched", async () => {
    const response = await callLogout("http://localhost");
    const cookies = response.cookies.getAll();
    expect(cookies).toHaveLength(1);
    expect(cookies[0].name).toBe("cmp_tenant_id");
  });

  it("rejects a cross-origin request", async () => {
    const response = await callLogout("https://evil.example");
    expect(response.status).toBe(403);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("allows a request with no Origin header", async () => {
    const response = await callLogout(null);
    expect(response.status).toBe(200);
  });

  it("never touches any Auth0-owned cookie name", async () => {
    const response = await callLogout("http://localhost");
    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).not.toMatch(/__session/i);
    expect(setCookie).not.toMatch(/appSession/i);
  });
});

describe("POST /api/auth/logout -- postLogoutRedirectUri (LIVE-ACCEPTANCE-HOTFIX-001)", () => {
  it("is an absolute URL, built from the configured APP_BASE_URL, with /login preserved", async () => {
    vi.stubEnv("APP_BASE_URL", "https://growcmp-web.onrender.com");
    const request = new NextRequest("http://0.0.0.0:10000/api/auth/logout", {
      method: "POST",
      headers: { origin: "https://growcmp-web.onrender.com" },
    });

    const response = await POST(request);
    const body = (await response.json()) as { postLogoutRedirectUri: string };

    // 1. absolute
    expect(() => new URL(body.postLogoutRedirectUri)).not.toThrow();
    // 2. /login preserved
    expect(new URL(body.postLogoutRedirectUri).pathname).toBe("/login");
    // 3. resolves to exactly the production result the ticket requires
    expect(body.postLogoutRedirectUri).toBe("https://growcmp-web.onrender.com/login");
  });

  it("uses APP_BASE_URL, not this request's own (internal/bind-address) host or forwarded headers", async () => {
    vi.stubEnv("APP_BASE_URL", "https://growcmp-web.onrender.com");
    const request = new NextRequest("http://0.0.0.0:10000/api/auth/logout", {
      method: "POST",
      headers: {
        origin: "https://growcmp-web.onrender.com",
        // An attacker- or proxy-supplied forwarded host must never leak
        // into the redirect target.
        "x-forwarded-host": "evil.example",
        "x-forwarded-proto": "https",
      },
    });

    const response = await POST(request);
    const body = (await response.json()) as { postLogoutRedirectUri: string };

    expect(body.postLogoutRedirectUri).toBe("https://growcmp-web.onrender.com/login");
    expect(body.postLogoutRedirectUri).not.toContain("evil.example");
    expect(body.postLogoutRedirectUri).not.toContain("0.0.0.0");
  });

  it("local/test environments resolve to their own configured APP_BASE_URL, not the production host", async () => {
    // beforeEach already stubs APP_BASE_URL=http://localhost for this suite.
    const response = await callLogout("http://localhost");
    const body = (await response.json()) as { postLogoutRedirectUri: string };

    expect(body.postLogoutRedirectUri).toBe("http://localhost/login");
  });

  it("no open-redirect: an Origin header for a different (attacker) origin cannot steer postLogoutRedirectUri -- the request is rejected outright", async () => {
    vi.stubEnv("APP_BASE_URL", "https://growcmp-web.onrender.com");
    const response = await callLogout("https://evil.example");

    expect(response.status).toBe(403);
    const body = (await response.json()) as { error?: string; postLogoutRedirectUri?: string };
    expect(body.postLogoutRedirectUri).toBeUndefined();
  });

  it("fails closed (null) rather than fabricating a redirect target when APP_BASE_URL is missing in real auth mode", async () => {
    // Unset the suite's default APP_BASE_URL stub. isSameOriginRequest
    // already rejects a present Origin header in this state, so exercise
    // the no-Origin path to reach postLogoutRedirectUri resolution itself.
    vi.stubEnv("APP_BASE_URL", "");
    const response = await callLogout(null);
    const body = (await response.json()) as { postLogoutRedirectUri: string | null };

    expect(response.status).toBe(200);
    expect(body.postLogoutRedirectUri).toBeNull();
  });
});
