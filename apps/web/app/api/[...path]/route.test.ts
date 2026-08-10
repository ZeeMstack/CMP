// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/server/session", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server/session")>("@/lib/server/session");
  return {
    ...actual,
    getAuthenticatedSession: vi.fn(),
    getCmpApiAccessToken: vi.fn(),
  };
});

import { getAuthenticatedSession, getCmpApiAccessToken, SessionExpiredError } from "@/lib/server/session";
import * as route from "./route";

const mockGetAuthenticatedSession = vi.mocked(getAuthenticatedSession);
const mockGetCmpApiAccessToken = vi.mocked(getCmpApiAccessToken);

const ENV_KEYS = [
  "NODE_ENV",
  "CMP_API_BASE_URL",
  "CMP_DEV_AUTH_BYPASS",
  "CMP_TEST_AUTH_BYPASS",
  "CMP_DEV_TENANT_ID",
  "CMP_DEV_USER_ID",
  "CMP_TEST_TENANT_ID",
  "CMP_TEST_USER_ID",
  "CMP_PILOT_TENANT_ID",
  "CMP_PILOT_USER_ID",
] as const;

function clearAuthEnv() {
  for (const key of ENV_KEYS) delete process.env[key];
}

function callProxy(path: string[]) {
  const request = new NextRequest(`http://localhost/api/${path.join("/")}`);
  return route.GET(request, { params: Promise.resolve({ path }) });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  clearAuthEnv();
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("CMP_API_BASE_URL", "http://backend.internal:8000");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  mockGetAuthenticatedSession.mockReset();
  mockGetCmpApiAccessToken.mockReset();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("generic proxy is GET-only", () => {
  it("exports GET and nothing else", () => {
    expect(typeof route.GET).toBe("function");
    expect((route as Record<string, unknown>).POST).toBeUndefined();
    expect((route as Record<string, unknown>).PUT).toBeUndefined();
    expect((route as Record<string, unknown>).PATCH).toBeUndefined();
    expect((route as Record<string, unknown>).DELETE).toBeUndefined();
  });
});

describe("real mode", () => {
  it("returns 401 { error: 'unauthenticated' } when there is no session, and never calls the backend", async () => {
    mockGetAuthenticatedSession.mockResolvedValue(null);

    const response = await callProxy(["farms"]);

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ error: "unauthenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("on a valid session, forwards Authorization: Bearer <token> to the backend", async () => {
    mockGetAuthenticatedSession.mockResolvedValue({ user: { sub: "auth0|x" } } as never);
    mockGetCmpApiAccessToken.mockResolvedValue("real-access-token-value");
    fetchMock.mockResolvedValue(jsonResponse([{ id: "farm-1" }]));

    await callProxy(["farms"]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer real-access-token-value");
  });

  it("never sends X-Dev-Tenant-Id / X-Dev-User-Id headers", async () => {
    mockGetAuthenticatedSession.mockResolvedValue({ user: { sub: "auth0|x" } } as never);
    mockGetCmpApiAccessToken.mockResolvedValue("t");
    fetchMock.mockResolvedValue(jsonResponse([]));

    await callProxy(["farms"]);

    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Dev-Tenant-Id"]).toBeUndefined();
    expect(headers["X-Dev-User-Id"]).toBeUndefined();
  });

  it("never sends X-CMP-Tenant-Id -- GET /auth/me (unscoped)", async () => {
    mockGetAuthenticatedSession.mockResolvedValue({ user: { sub: "auth0|x" } } as never);
    mockGetCmpApiAccessToken.mockResolvedValue("t");
    fetchMock.mockResolvedValue(jsonResponse({ user: {}, memberships: [] }));

    await callProxy(["auth", "me"]);

    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.pathname).toBe("/auth/me");
    const headers = init.headers as Record<string, string>;
    expect(headers["X-CMP-Tenant-Id"]).toBeUndefined();
  });

  it("never fabricates X-CMP-Tenant-Id for a tenant-scoped path either -- B2 has not shipped yet", async () => {
    mockGetAuthenticatedSession.mockResolvedValue({ user: { sub: "auth0|x" } } as never);
    mockGetCmpApiAccessToken.mockResolvedValue("t");
    // Simulates FastAPI's real, expected 400 for a tenant-scoped route
    // called without X-CMP-Tenant-Id -- this proxy must not work around
    // it by inventing a tenant id.
    fetchMock.mockResolvedValue(jsonResponse({ detail: "X-CMP-Tenant-Id is required" }, 400));

    const response = await callProxy(["farms", "some-farm-id", "crop-batches"]);

    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-CMP-Tenant-Id"]).toBeUndefined();
    expect(response.status).toBe(400);
  });

  it("maps a SessionExpiredError from token retrieval to a stable 401 { error: 'session_expired' }", async () => {
    mockGetAuthenticatedSession.mockResolvedValue({ user: { sub: "auth0|x" } } as never);
    mockGetCmpApiAccessToken.mockRejectedValue(new SessionExpiredError(new Error("refresh token revoked")));

    const response = await callProxy(["farms"]);

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ error: "session_expired" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not leak the underlying SDK error message into the response body", async () => {
    mockGetAuthenticatedSession.mockResolvedValue({ user: { sub: "auth0|x" } } as never);
    mockGetCmpApiAccessToken.mockRejectedValue(
      new SessionExpiredError(new Error("super-secret-vendor-diagnostic-detail")),
    );

    const response = await callProxy(["farms"]);
    const text = await response.text();

    expect(text).not.toMatch(/super-secret-vendor-diagnostic-detail/);
  });

  it("never includes a client secret / Auth0 secret value in any response", async () => {
    vi.stubEnv("AUTH0_CLIENT_SECRET", "sekrit-client-secret-value");
    vi.stubEnv("AUTH0_SECRET", "sekrit-session-secret-value");
    mockGetAuthenticatedSession.mockResolvedValue(null);

    const response = await callProxy(["farms"]);
    const text = await response.text();

    expect(text).not.toMatch(/sekrit-client-secret-value/);
    expect(text).not.toMatch(/sekrit-session-secret-value/);
  });

  it("preserves the backend's status code and body verbatim", async () => {
    mockGetAuthenticatedSession.mockResolvedValue({ user: { sub: "auth0|x" } } as never);
    mockGetCmpApiAccessToken.mockResolvedValue("t");
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Farm not found" }, 404));

    const response = await callProxy(["farms", "unknown-id"]);

    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toEqual({ detail: "Farm not found" });
  });

  it("returns 502 network_error when the backend is unreachable, without leaking the low-level error", async () => {
    mockGetAuthenticatedSession.mockResolvedValue({ user: { sub: "auth0|x" } } as never);
    mockGetCmpApiAccessToken.mockResolvedValue("t");
    fetchMock.mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await callProxy(["farms"]);

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({ error: "network_error", detail: "Could not reach the backend" });
  });

  it("ignores the removed CMP_PILOT_* variables entirely -- they have no effect on the outcome", async () => {
    vi.stubEnv("CMP_PILOT_TENANT_ID", "some-old-pilot-tenant");
    vi.stubEnv("CMP_PILOT_USER_ID", "some-old-pilot-user");
    mockGetAuthenticatedSession.mockResolvedValue(null);

    const response = await callProxy(["farms"]);

    // Still 401 -- pilot vars being set does not somehow authenticate the request.
    expect(response.status).toBe(401);
  });
});

describe("dev bypass mode", () => {
  it("forwards only X-Dev-Tenant-Id / X-Dev-User-Id, and no Authorization header", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant-1");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    fetchMock.mockResolvedValue(jsonResponse([]));

    await callProxy(["farms"]);

    expect(mockGetAuthenticatedSession).not.toHaveBeenCalled();
    expect(mockGetCmpApiAccessToken).not.toHaveBeenCalled();
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Dev-Tenant-Id"]).toBe("dev-tenant-1");
    expect(headers["X-Dev-User-Id"]).toBe("dev-user-1");
    expect(headers.Authorization).toBeUndefined();
  });

  it("fails closed (500) when CMP_DEV_TENANT_ID/CMP_DEV_USER_ID are not both set", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    // Deliberately missing CMP_DEV_TENANT_ID / CMP_DEV_USER_ID.

    const response = await callProxy(["farms"]);

    expect(response.status).toBe(500);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed (500) under NODE_ENV=production, and never falls back to real or test mode", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant-1");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");

    const response = await callProxy(["farms"]);

    expect(response.status).toBe(500);
    const body = await response.json();
    expect(body.error).toBe("auth_configuration_error");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(mockGetAuthenticatedSession).not.toHaveBeenCalled();
  });
});

describe("test bypass mode", () => {
  it("forwards only X-Dev-Tenant-Id / X-Dev-User-Id sourced from CMP_TEST_* under production NODE_ENV", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("CMP_TEST_AUTH_BYPASS", "playwright-e2e-only");
    vi.stubEnv("CMP_TEST_TENANT_ID", "test-tenant-1");
    vi.stubEnv("CMP_TEST_USER_ID", "test-user-1");
    fetchMock.mockResolvedValue(jsonResponse([]));

    const response = await callProxy(["farms"]);

    expect(response.status).toBe(200);
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Dev-Tenant-Id"]).toBe("test-tenant-1");
    expect(headers["X-Dev-User-Id"]).toBe("test-user-1");
    expect(headers.Authorization).toBeUndefined();
  });

  it("does not activate merely because NODE_ENV=production and CMP_DEV_AUTH_BYPASS is unset -- requires the exact sentinel", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("CMP_TEST_AUTH_BYPASS", "not-the-real-sentinel");
    mockGetAuthenticatedSession.mockResolvedValue(null);

    const response = await callProxy(["farms"]);

    // Falls through to real mode, which correctly 401s with no session --
    // proving an arbitrary truthy value cannot enable the bypass.
    expect(response.status).toBe(401);
  });
});
