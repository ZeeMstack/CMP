// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "./route";

beforeEach(() => {
  vi.stubEnv("NODE_ENV", "development");
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
