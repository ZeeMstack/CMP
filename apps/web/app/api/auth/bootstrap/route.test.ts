// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/server/session", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server/session")>("@/lib/server/session");
  return { ...actual, getCmpApiAccessToken: vi.fn() };
});

import { getCmpApiAccessToken, SessionExpiredError } from "@/lib/server/session";
import { GET } from "./route";

const mockGetCmpApiAccessToken = vi.mocked(getCmpApiAccessToken);

const ENV_KEYS = [
  "NODE_ENV",
  "CMP_API_BASE_URL",
  "CMP_DEV_AUTH_BYPASS",
  "CMP_TEST_AUTH_BYPASS",
  "CMP_DEV_TENANT_ID",
  "CMP_DEV_USER_ID",
] as const;

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  for (const key of ENV_KEYS) delete process.env[key];
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("CMP_API_BASE_URL", "http://backend.internal:8000");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  mockGetCmpApiAccessToken.mockReset();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function callBootstrap(cookieHeader?: string) {
  const request = new NextRequest("http://localhost/api/auth/bootstrap", {
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
  });
  return GET(request);
}

const authMeBody = (memberships: Array<{ tenant_id: string; tenant_code: string; tenant_name: string; role_code: string }>) => ({
  user: { id: "user-1", email: "person@example.com", display_name: "Person" },
  memberships,
});

describe("GET /api/auth/bootstrap", () => {
  it("real mode, token retrieval fails (covers 'no session at all' and 'session present but unusable' alike, since getCmpApiAccessToken() is the sole real-auth check) -> 401 { status: 'unauthenticated' }, no backend call", async () => {
    mockGetCmpApiAccessToken.mockRejectedValue(new SessionExpiredError(new Error("x")));
    const response = await callBootstrap();
    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({
      status: "unauthenticated",
      user: null,
      memberships: [],
      selectedTenantId: null,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("real mode: attempts getCmpApiAccessToken() directly, with no separate session precheck beforehand", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockResolvedValue(jsonResponse(authMeBody([])));
    await callBootstrap();
    expect(mockGetCmpApiAccessToken).toHaveBeenCalledWith();
    expect(mockGetCmpApiAccessToken).toHaveBeenCalledTimes(1);
  });

  it("backend /auth/me returns 401 -> 401 unauthenticated", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockResolvedValue(jsonResponse({ detail: "no" }, 401));
    const response = await callBootstrap();
    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toMatchObject({ status: "unauthenticated" });
  });

  it("backend /auth/me returns 403 -> 403 { status: 'not_provisioned' }", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockResolvedValue(jsonResponse({ detail: "no" }, 403));
    const response = await callBootstrap();
    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({
      status: "not_provisioned",
      user: null,
      memberships: [],
      selectedTenantId: null,
    });
  });

  it("backend unreachable -> 502 { status: 'error' }", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockRejectedValue(new Error("ECONNREFUSED"));
    const response = await callBootstrap();
    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toMatchObject({ status: "error" });
  });

  it("0 memberships -> authenticated, empty memberships, selectedTenantId null", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockResolvedValue(jsonResponse(authMeBody([])));
    const response = await callBootstrap();
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      status: "authenticated",
      user: { id: "user-1", email: "person@example.com", displayName: "Person" },
      memberships: [],
      selectedTenantId: null,
    });
  });

  it("1 membership -> auto-selected and cookie set", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockResolvedValue(
      jsonResponse(authMeBody([{ tenant_id: "tenant-a", tenant_code: "A", tenant_name: "Tenant A", role_code: "tenant_admin" }])),
    );
    const response = await callBootstrap();
    const body = await response.json();
    expect(body.selectedTenantId).toBe("tenant-a");
    expect(response.headers.get("set-cookie") ?? "").toMatch(/cmp_tenant_id=tenant-a/);
  });

  it("multiple memberships, cookie matches one -> preserved, no cookie rewrite needed", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockResolvedValue(
      jsonResponse(
        authMeBody([
          { tenant_id: "tenant-a", tenant_code: "A", tenant_name: "Tenant A", role_code: "tenant_admin" },
          { tenant_id: "tenant-b", tenant_code: "B", tenant_name: "Tenant B", role_code: "read_only" },
        ]),
      ),
    );
    const response = await callBootstrap("cmp_tenant_id=tenant-b");
    const body = await response.json();
    expect(body.selectedTenantId).toBe("tenant-b");
  });

  it("multiple memberships, stale cookie names a revoked tenant -> selectedTenantId null, cookie cleared", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockResolvedValue(
      jsonResponse(
        authMeBody([
          { tenant_id: "tenant-a", tenant_code: "A", tenant_name: "Tenant A", role_code: "tenant_admin" },
          { tenant_id: "tenant-b", tenant_code: "B", tenant_name: "Tenant B", role_code: "read_only" },
        ]),
      ),
    );
    const response = await callBootstrap("cmp_tenant_id=tenant-that-was-revoked");
    const body = await response.json();
    expect(body.selectedTenantId).toBeNull();
    expect(response.headers.get("set-cookie") ?? "").toMatch(/Max-Age=0/i);
  });

  it("dev mode: resolves via X-Dev-User-Id, Auth0 token acquisition never called", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-bootstrap-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    fetchMock.mockResolvedValue(jsonResponse(authMeBody([])));

    const response = await callBootstrap();

    expect(response.status).toBe(200);
    expect(mockGetCmpApiAccessToken).not.toHaveBeenCalled();
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Dev-User-Id"]).toBe("dev-user-1");
    expect(headers["X-Dev-Tenant-Id"]).toBeUndefined();
  });

  it("never exposes Auth0-shaped fields (sub, tokenSet, etc.) in the response body", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockResolvedValue(jsonResponse(authMeBody([])));
    const response = await callBootstrap();
    const text = await response.text();
    expect(text).not.toMatch(/tokenSet|"sub"|accessToken|refreshToken/);
  });
});
