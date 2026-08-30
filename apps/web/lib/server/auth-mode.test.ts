// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { checkAuthStartupInvariant, devIdentity, resolveAuthMode, testIdentity } from "@/lib/server/auth-mode";

const ENV_KEYS = [
  "NODE_ENV",
  "CMP_DEV_AUTH_BYPASS",
  "CMP_TEST_AUTH_BYPASS",
  "CMP_DEV_TENANT_ID",
  "CMP_DEV_USER_ID",
  "CMP_TEST_TENANT_ID",
  "CMP_TEST_USER_ID",
  "AUTH0_DOMAIN",
  "AUTH0_CLIENT_ID",
  "AUTH0_CLIENT_SECRET",
  "AUTH0_SECRET",
  "APP_BASE_URL",
  "CMP_API_AUDIENCE",
] as const;

function clearAuthEnv() {
  for (const key of ENV_KEYS) delete process.env[key];
}

afterEach(() => {
  clearAuthEnv();
  vi.unstubAllEnvs();
});

describe("resolveAuthMode", () => {
  it("resolves to real when no bypass flag is set", () => {
    vi.stubEnv("NODE_ENV", "development");
    expect(resolveAuthMode()).toBe("real");
  });

  it("resolves to dev when CMP_DEV_AUTH_BYPASS=true outside production", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    expect(resolveAuthMode()).toBe("dev");
  });

  it("fails closed: throws when CMP_DEV_AUTH_BYPASS=true under NODE_ENV=production", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    expect(() => resolveAuthMode()).toThrow(/production/i);
  });

  it("does not activate dev bypass for a non-exact truthy value", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "1");
    expect(resolveAuthMode()).toBe("real");
  });

  it("resolves to test when CMP_TEST_AUTH_BYPASS matches the exact sentinel", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("CMP_TEST_AUTH_BYPASS", "playwright-e2e-only");
    expect(resolveAuthMode()).toBe("test");
  });

  it("test bypass still activates under production NODE_ENV (Playwright's next start)", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("CMP_TEST_AUTH_BYPASS", "playwright-e2e-only");
    expect(() => resolveAuthMode()).not.toThrow();
    expect(resolveAuthMode()).toBe("test");
  });

  it("does not activate test bypass for a merely truthy, non-exact value", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("CMP_TEST_AUTH_BYPASS", "true");
    expect(resolveAuthMode()).toBe("real");
  });

  it("fails closed when both dev and test bypass are active simultaneously", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_TEST_AUTH_BYPASS", "playwright-e2e-only");
    expect(() => resolveAuthMode()).toThrow(/ambiguous/i);
  });
});

describe("devIdentity / testIdentity", () => {
  it("devIdentity reads CMP_DEV_TENANT_ID / CMP_DEV_USER_ID", () => {
    vi.stubEnv("CMP_DEV_TENANT_ID", "tenant-dev-1");
    vi.stubEnv("CMP_DEV_USER_ID", "user-dev-1");
    expect(devIdentity()).toEqual({ tenantId: "tenant-dev-1", userId: "user-dev-1" });
  });

  it("devIdentity throws when a value is missing", () => {
    vi.stubEnv("CMP_DEV_TENANT_ID", "tenant-dev-1");
    expect(() => devIdentity()).toThrow(/CMP_DEV_USER_ID/);
  });

  it("testIdentity reads CMP_TEST_TENANT_ID / CMP_TEST_USER_ID, never the dev names", () => {
    vi.stubEnv("CMP_DEV_TENANT_ID", "should-not-be-read");
    vi.stubEnv("CMP_TEST_TENANT_ID", "tenant-test-1");
    vi.stubEnv("CMP_TEST_USER_ID", "user-test-1");
    expect(testIdentity()).toEqual({ tenantId: "tenant-test-1", userId: "user-test-1" });
  });
});

function stubCompleteAuth0Env() {
  vi.stubEnv("AUTH0_DOMAIN", "tenant.us.auth0.com");
  vi.stubEnv("AUTH0_CLIENT_ID", "client-id");
  vi.stubEnv("AUTH0_CLIENT_SECRET", "client-secret");
  vi.stubEnv("AUTH0_SECRET", "0123456789abcdef0123456789abcdef");
  vi.stubEnv("APP_BASE_URL", "https://cmp.example.com");
  vi.stubEnv("CMP_API_AUDIENCE", "https://api.cmp.example.com");
}

describe("checkAuthStartupInvariant", () => {
  it("throws under NODE_ENV=production, real mode, with Auth0 config missing", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(() => checkAuthStartupInvariant("real")).toThrow(/AUTH0_DOMAIN/);
  });

  it("names every missing variable, not just the first", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("AUTH0_DOMAIN", "tenant.us.auth0.com");
    try {
      checkAuthStartupInvariant("real");
      throw new Error("expected checkAuthStartupInvariant to throw");
    } catch (err) {
      const message = (err as Error).message;
      expect(message).not.toMatch(/AUTH0_DOMAIN/);
      expect(message).toMatch(/AUTH0_CLIENT_ID/);
      expect(message).toMatch(/CMP_API_AUDIENCE/);
    }
  });

  it("does not throw under NODE_ENV=production, real mode, with complete Auth0 config", () => {
    vi.stubEnv("NODE_ENV", "production");
    stubCompleteAuth0Env();
    expect(() => checkAuthStartupInvariant("real")).not.toThrow();
  });

  it("does not throw for dev mode under production, regardless of Auth0 config", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(() => checkAuthStartupInvariant("dev")).not.toThrow();
  });

  it("does not throw for test mode under production, regardless of Auth0 config", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(() => checkAuthStartupInvariant("test")).not.toThrow();
  });

  it("does not throw for real mode outside production, even with Auth0 config missing", () => {
    vi.stubEnv("NODE_ENV", "development");
    expect(() => checkAuthStartupInvariant("real")).not.toThrow();
  });
});
