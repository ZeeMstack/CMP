// @vitest-environment node
import { NextRequest, NextResponse } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyTenantCookieAction,
  readSelectedTenantId,
  TENANT_COOKIE_NAME,
  tenantCookieSecureFlag,
} from "@/lib/server/tenant-selection";

const RESET_ENV_KEYS: string[] = ["NODE_ENV"];

beforeEach(() => {
  for (const key of RESET_ENV_KEYS) delete process.env[key];
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("tenantCookieSecureFlag", () => {
  it("real mode + NODE_ENV=production -> true", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(tenantCookieSecureFlag("real")).toBe(true);
  });

  it("real mode + NODE_ENV=development -> false (local HTTP)", () => {
    vi.stubEnv("NODE_ENV", "development");
    expect(tenantCookieSecureFlag("real")).toBe(false);
  });

  it("dev mode -> always false, even under NODE_ENV=production", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(tenantCookieSecureFlag("dev")).toBe(false);
  });

  it("test mode -> always false, even under NODE_ENV=production (Playwright's next start)", () => {
    vi.stubEnv("NODE_ENV", "production");
    expect(tenantCookieSecureFlag("test")).toBe(false);
  });
});

describe("readSelectedTenantId", () => {
  it("reads the cmp_tenant_id cookie value", () => {
    const request = new NextRequest("http://localhost/", { headers: { cookie: `${TENANT_COOKIE_NAME}=tenant-xyz` } });
    expect(readSelectedTenantId(request)).toBe("tenant-xyz");
  });

  it("returns null when the cookie is absent", () => {
    const request = new NextRequest("http://localhost/");
    expect(readSelectedTenantId(request)).toBeNull();
  });
});

describe("applyTenantCookieAction", () => {
  it("'set' writes an HttpOnly, SameSite=Lax, Path=/ cookie with no Domain", () => {
    vi.stubEnv("NODE_ENV", "development");
    const response = new NextResponse();
    applyTenantCookieAction(response, { kind: "set", tenantId: "tenant-xyz" }, "real");

    const cookie = response.cookies.get(TENANT_COOKIE_NAME);
    expect(cookie?.value).toBe("tenant-xyz");
    const setCookieHeader = response.headers.get("set-cookie") ?? "";
    expect(setCookieHeader).toMatch(/HttpOnly/i);
    expect(setCookieHeader).toMatch(/SameSite=Lax/i);
    expect(setCookieHeader).toMatch(/Path=\//i);
    expect(setCookieHeader).not.toMatch(/Domain=/i);
  });

  it("'set' includes Secure under real+production", () => {
    vi.stubEnv("NODE_ENV", "production");
    const response = new NextResponse();
    applyTenantCookieAction(response, { kind: "set", tenantId: "t" }, "real");
    expect(response.headers.get("set-cookie") ?? "").toMatch(/Secure/i);
  });

  it("'set' omits Secure under dev mode", () => {
    vi.stubEnv("NODE_ENV", "production"); // even if somehow production, dev mode still wins
    const response = new NextResponse();
    applyTenantCookieAction(response, { kind: "set", tenantId: "t" }, "dev");
    expect(response.headers.get("set-cookie") ?? "").not.toMatch(/Secure/i);
  });

  it("'set' omits Secure under test mode", () => {
    vi.stubEnv("NODE_ENV", "production");
    const response = new NextResponse();
    applyTenantCookieAction(response, { kind: "set", tenantId: "t" }, "test");
    expect(response.headers.get("set-cookie") ?? "").not.toMatch(/Secure/i);
  });

  it("'clear' expires the cookie (maxAge 0)", () => {
    vi.stubEnv("NODE_ENV", "development");
    const response = new NextResponse();
    applyTenantCookieAction(response, { kind: "clear" }, "real");
    const setCookieHeader = response.headers.get("set-cookie") ?? "";
    expect(setCookieHeader).toMatch(/Max-Age=0/i);
  });

  it("'none' does not set any cookie header", () => {
    const response = new NextResponse();
    applyTenantCookieAction(response, { kind: "none" }, "real");
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("never carries a user id, role, or token value -- only the tenant id", () => {
    vi.stubEnv("NODE_ENV", "development");
    const response = new NextResponse();
    applyTenantCookieAction(response, { kind: "set", tenantId: "tenant-xyz" }, "real");
    const cookie = response.cookies.get(TENANT_COOKIE_NAME);
    expect(cookie?.value).toBe("tenant-xyz");
    expect(cookie?.value).not.toMatch(/role|token|user/i);
  });
});
