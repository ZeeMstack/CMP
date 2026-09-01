// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { isSameOriginRequest } from "@/lib/server/same-origin";

const ENV_KEYS = [
  "NODE_ENV",
  "CMP_DEV_AUTH_BYPASS",
  "CMP_TEST_AUTH_BYPASS",
  "CMP_DEV_TENANT_ID",
  "CMP_DEV_USER_ID",
  "CMP_TEST_TENANT_ID",
  "CMP_TEST_USER_ID",
  "APP_BASE_URL",
] as const;

function clearAuthEnv() {
  for (const key of ENV_KEYS) delete process.env[key];
}

afterEach(() => {
  clearAuthEnv();
  vi.unstubAllEnvs();
});

function requestWithOrigin(url: string, origin?: string) {
  return new NextRequest(url, origin === undefined ? undefined : { headers: { origin } });
}

describe("isSameOriginRequest", () => {
  it("accepts a request with no Origin header (SameSite cookies remain the primary defense)", () => {
    const request = requestWithOrigin("http://localhost:3000/api/tenant/select");
    expect(isSameOriginRequest(request)).toBe(true);
  });

  it("rejects a malformed Origin header", () => {
    const request = requestWithOrigin("http://localhost:3000/api/tenant/select", "not a url");
    expect(isSameOriginRequest(request)).toBe(false);
  });

  describe("real auth mode (no bypass flags set)", () => {
    it("accepts the configured public origin even when request.nextUrl reflects an unrelated internal bind address (Render/reverse-proxy case)", () => {
      vi.stubEnv("APP_BASE_URL", "https://growcmp-web.onrender.com");
      // The request's own URL/host is the internal container bind address
      // (as it would be behind Render's standalone server.js) -- deliberately
      // NOT the public host, to prove the check no longer depends on it.
      const request = requestWithOrigin("http://0.0.0.0:10000/api/platform/tenants", "https://growcmp-web.onrender.com");
      expect(isSameOriginRequest(request)).toBe(true);
    });

    it("rejects a mismatched host (cross-origin attacker)", () => {
      vi.stubEnv("APP_BASE_URL", "https://growcmp-web.onrender.com");
      const request = requestWithOrigin("http://0.0.0.0:10000/api/platform/tenants", "https://evil.example");
      expect(isSameOriginRequest(request)).toBe(false);
    });

    it("rejects a mismatched scheme (same host, http vs https)", () => {
      vi.stubEnv("APP_BASE_URL", "https://growcmp-web.onrender.com");
      const request = requestWithOrigin("http://0.0.0.0:10000/api/platform/tenants", "http://growcmp-web.onrender.com");
      expect(isSameOriginRequest(request)).toBe(false);
    });

    it("rejects a mismatched port", () => {
      vi.stubEnv("APP_BASE_URL", "https://growcmp-web.onrender.com:8443");
      const request = requestWithOrigin("http://0.0.0.0:10000/api/platform/tenants", "https://growcmp-web.onrender.com");
      expect(isSameOriginRequest(request)).toBe(false);
    });

    it("fails closed when APP_BASE_URL is missing", () => {
      const request = requestWithOrigin("http://0.0.0.0:10000/api/platform/tenants", "https://growcmp-web.onrender.com");
      expect(isSameOriginRequest(request)).toBe(false);
    });

    it("fails closed when APP_BASE_URL is malformed", () => {
      vi.stubEnv("APP_BASE_URL", "not a url");
      const request = requestWithOrigin("http://0.0.0.0:10000/api/platform/tenants", "https://growcmp-web.onrender.com");
      expect(isSameOriginRequest(request)).toBe(false);
    });

    it.each(["javascript:alert(1)", "file:///tmp/app", "ftp://example.com"])(
      "fails closed when APP_BASE_URL uses a non-web scheme (%s)",
      (appBaseUrl) => {
        vi.stubEnv("APP_BASE_URL", appBaseUrl);
        const request = requestWithOrigin("http://0.0.0.0:10000/api/platform/tenants", "https://growcmp-web.onrender.com");
        expect(isSameOriginRequest(request)).toBe(false);
      },
    );

    it("accepts a matching localhost origin (real-mode local dev)", () => {
      vi.stubEnv("APP_BASE_URL", "http://localhost:3000");
      const request = requestWithOrigin("http://localhost:3000/api/tenant/select", "http://localhost:3000");
      expect(isSameOriginRequest(request)).toBe(true);
    });
  });

  describe("dev bypass mode", () => {
    it("accepts a matching request.nextUrl.host without requiring APP_BASE_URL", () => {
      vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
      const request = requestWithOrigin("http://localhost:3000/api/tenant/select", "http://localhost:3000");
      expect(isSameOriginRequest(request)).toBe(true);
    });

    it("rejects a mismatched request.nextUrl.host", () => {
      vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
      const request = requestWithOrigin("http://localhost:3000/api/tenant/select", "http://localhost:4000");
      expect(isSameOriginRequest(request)).toBe(false);
    });
  });

  it("fails closed on an ambiguous auth-mode configuration (both bypass flags set)", () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_TEST_AUTH_BYPASS", "playwright-e2e-only");
    const request = requestWithOrigin("http://localhost:3000/api/tenant/select", "http://localhost:3000");
    expect(isSameOriginRequest(request)).toBe(false);
  });
});
