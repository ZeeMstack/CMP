// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/server/session", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server/session")>("@/lib/server/session");
  return {
    ...actual,
    getCmpApiAccessToken: vi.fn(),
  };
});

import { getCmpApiAccessToken, SessionExpiredError } from "@/lib/server/session";
import * as route from "./route";

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

function callProxy(path: string[], cookieHeader?: string) {
  const request = new NextRequest(`http://localhost/api/${path.join("/")}`, {
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
  });
  return route.GET(request, { params: Promise.resolve({ path }) });
}

function callProxyPost(path: string[], body: unknown, cookieHeader?: string) {
  const request = new NextRequest(`http://localhost/api/${path.join("/")}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(cookieHeader ? { cookie: cookieHeader } : {}) },
    body: JSON.stringify(body),
  });
  return route.POST(request, { params: Promise.resolve({ path }) });
}

const SELECTED_TENANT_COOKIE = "cmp_tenant_id=selected-tenant-abc";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  clearAuthEnv();
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

describe("generic proxy supports exactly GET and POST", () => {
  it("exports GET and POST, and nothing else", () => {
    // FARM-SETUP-001 added POST (Greenhouse setup creation is CMP's first
    // business mutation UX) -- PUT/PATCH/DELETE remain deliberately absent
    // (CMP has no PUT/PATCH/DELETE endpoints anywhere; see
    // AUTHORIZATION_MODEL.md's permission-catalog note). This guard still
    // fails the moment any of those three is added without a deliberate
    // review of this file's own routing/identity assumptions.
    expect(typeof route.GET).toBe("function");
    expect(typeof route.POST).toBe("function");
    expect((route as Record<string, unknown>).PUT).toBeUndefined();
    expect((route as Record<string, unknown>).PATCH).toBeUndefined();
    expect((route as Record<string, unknown>).DELETE).toBeUndefined();
  });
});

describe("proxy target URL safety (FARM-SETUP-001.1 section 11)", () => {
  it("never proxies to an external host even when a path segment decodes to an empty string (protocol-relative host override)", async () => {
    // `new URL("//evil.example/steal", "http://backend.internal:8000")`
    // resolves to `http://evil.example/steal` per the WHATWG URL spec --
    // an empty leading path segment (reachable if a request path segment
    // ever decodes to "") joined with the rest would produce exactly a
    // "//host/..." string. This proves the actual route handler's URL
    // construction is safe against that input shape, not merely that
    // ordinary paths look fine.
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user");
    fetchMock.mockResolvedValue(jsonResponse([]));

    await callProxy(["", "evil.example", "steal"], SELECTED_TENANT_COOKIE);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.hostname).toBe("backend.internal");
    expect(url.hostname).not.toBe("evil.example");
  });

  it("never proxies to an external host for a POST request either", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user");
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }, 201));

    await callProxyPost(["", "evil.example", "steal"], {}, SELECTED_TENANT_COOKIE);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.hostname).toBe("backend.internal");
    expect(url.hostname).not.toBe("evil.example");
  });

  it("a client-supplied Authorization header is never forwarded upstream -- only the server-resolved identity is", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user");
    fetchMock.mockResolvedValue(jsonResponse([]));

    const request = new NextRequest("http://localhost/api/farms", {
      headers: {
        cookie: SELECTED_TENANT_COOKIE,
        Authorization: "Bearer attacker-supplied-token",
        "X-CMP-Tenant-Id": "attacker-tenant",
        "X-Dev-Tenant-Id": "attacker-dev-tenant",
        "X-Dev-User-Id": "attacker-dev-user",
      },
    });
    await route.GET(request, { params: Promise.resolve({ path: ["farms"] }) });

    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    // Dev-bypass mode's own server-resolved identity, not anything the
    // client sent -- proves the outgoing header set is built exclusively
    // server-side (`identity.headers`), never merged with `request.headers`.
    expect(headers["X-Dev-Tenant-Id"]).toBe("selected-tenant-abc");
    expect(headers["X-Dev-User-Id"]).toBe("dev-user");
    expect(headers.Authorization).toBeUndefined();
  });

  it("a client-supplied Authorization header cannot smuggle a bearer token past a POST either", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user");
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }, 201));

    const request = new NextRequest("http://localhost/api/farms/farm-1/farm-setup/greenhouses", {
      method: "POST",
      headers: {
        cookie: SELECTED_TENANT_COOKIE,
        "Content-Type": "application/json",
        Authorization: "Bearer attacker-supplied-token",
      },
      body: JSON.stringify({}),
    });
    await route.POST(request, { params: Promise.resolve({ path: ["farms", "farm-1", "farm-setup", "greenhouses"] }) });

    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(headers["X-Dev-User-Id"]).toBe("dev-user");
  });

  it("stays scoped under the configured backend base URL for an ordinary path -- sanity check", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user");
    fetchMock.mockResolvedValue(jsonResponse([]));

    await callProxy(["farms", "farm-1", "farm-setup", "greenhouses"], SELECTED_TENANT_COOKIE);

    const [url] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.href).toBe("http://backend.internal:8000/farms/farm-1/farm-setup/greenhouses");
  });
});

describe("CSRF / same-origin boundary (FARM-SETUP-001.2 section 6/7)", () => {
  it("rejects a POST carrying a cross-origin Origin header, before ever calling the backend", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user");

    const request = new NextRequest("http://localhost/api/farms/farm-1/farm-setup/greenhouses", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        origin: "https://evil.example",
        cookie: SELECTED_TENANT_COOKIE,
      },
      body: JSON.stringify({}),
    });
    const response = await route.POST(request, { params: Promise.resolve({ path: ["farms", "farm-1", "farm-setup", "greenhouses"] }) });

    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({ error: "cross_origin_rejected" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accepts a POST with a matching same-origin Origin header", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user");
    fetchMock.mockResolvedValue(jsonResponse({ greenhouse_id: "gh-1" }, 201));

    const request = new NextRequest("http://localhost/api/farms/farm-1/farm-setup/greenhouses", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        origin: "http://localhost",
        cookie: SELECTED_TENANT_COOKIE,
      },
      body: JSON.stringify({}),
    });
    const response = await route.POST(request, { params: Promise.resolve({ path: ["farms", "farm-1", "farm-setup", "greenhouses"] }) });

    expect(response.status).toBe(201);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("still accepts a POST with no Origin header at all -- SameSite cookies remain the primary defense", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user");
    fetchMock.mockResolvedValue(jsonResponse({ greenhouse_id: "gh-1" }, 201));

    const response = await callProxyPost(["farms", "farm-1", "farm-setup", "greenhouses"], {}, SELECTED_TENANT_COOKIE);

    expect(response.status).toBe(201);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("GET is not gated on Origin -- only the mutating verb is (matches every other Route Handler's convention)", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user");
    fetchMock.mockResolvedValue(jsonResponse([]));

    const request = new NextRequest("http://localhost/api/farms", {
      headers: { origin: "https://evil.example", cookie: SELECTED_TENANT_COOKIE },
    });
    const response = await route.GET(request, { params: Promise.resolve({ path: ["farms"] }) });

    expect(response.status).toBe(200);
  });
});

describe("POST passthrough (FARM-SETUP-001)", () => {
  it("forwards the request body and Content-Type: application/json to the backend", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user");
    fetchMock.mockResolvedValue(jsonResponse({ greenhouse_id: "gh-1" }, 201));

    const payload = { code: "GH-01", classification: "leafy_greens" };
    const response = await callProxyPost(
      ["farms", "farm-1", "farm-setup", "greenhouses"],
      payload,
      SELECTED_TENANT_COOKIE,
    );

    expect(response.status).toBe(201);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.pathname).toBe("/farms/farm-1/farm-setup/greenhouses");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(payload);
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("reuses the exact same identity resolution as GET -- an auth failure still returns 401 and never calls the backend", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "false");
    // real mode, no session -> getCmpApiAccessToken rejects
    mockGetCmpApiAccessToken.mockRejectedValue(new SessionExpiredError(new Error("x")));

    const response = await callProxyPost(["farms", "farm-1", "farm-setup", "greenhouses"], {});

    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("relays a network failure as 502, matching GET's own network-error handling", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user");
    fetchMock.mockRejectedValue(new Error("boom"));

    const response = await callProxyPost(
      ["farms", "farm-1", "farm-setup", "greenhouses"],
      {},
      SELECTED_TENANT_COOKIE,
    );

    expect(response.status).toBe(502);
  });
});

describe("real mode", () => {
  it("token retrieval fails (covers 'no session at all' and 'session present but unusable' alike, since getCmpApiAccessToken() is the sole real-auth check) -> 401 { error: 'session_expired' }, and never calls the backend", async () => {
    mockGetCmpApiAccessToken.mockRejectedValue(new SessionExpiredError(new Error("x")));

    const response = await callProxy(["farms"]);

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ error: "session_expired" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("attempts getCmpApiAccessToken() directly, with no separate getSession precheck beforehand", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("t");
    fetchMock.mockResolvedValue(jsonResponse([]));

    await callProxy(["farms"]);

    expect(mockGetCmpApiAccessToken).toHaveBeenCalledWith();
    expect(mockGetCmpApiAccessToken).toHaveBeenCalledTimes(1);
  });

  it("on a valid token, forwards Authorization: Bearer <token> to the backend", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("real-access-token-value");
    fetchMock.mockResolvedValue(jsonResponse([{ id: "farm-1" }]));

    await callProxy(["farms"]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer real-access-token-value");
  });

  it("never sends X-Dev-Tenant-Id / X-Dev-User-Id headers", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("t");
    fetchMock.mockResolvedValue(jsonResponse([]));

    await callProxy(["farms"]);

    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Dev-Tenant-Id"]).toBeUndefined();
    expect(headers["X-Dev-User-Id"]).toBeUndefined();
  });

  it("never sends X-CMP-Tenant-Id -- GET /auth/me (unscoped)", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("t");
    fetchMock.mockResolvedValue(jsonResponse({ user: {}, memberships: [] }));

    await callProxy(["auth", "me"]);

    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.pathname).toBe("/auth/me");
    const headers = init.headers as Record<string, string>;
    expect(headers["X-CMP-Tenant-Id"]).toBeUndefined();
  });

  it("never fabricates X-CMP-Tenant-Id for a tenant-scoped path either -- B2 has not shipped yet", async () => {
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
    mockGetCmpApiAccessToken.mockRejectedValue(new SessionExpiredError(new Error("refresh token revoked")));

    const response = await callProxy(["farms"]);

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ error: "session_expired" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not leak the underlying SDK error message into the response body", async () => {
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
    mockGetCmpApiAccessToken.mockRejectedValue(new SessionExpiredError(new Error("x")));

    const response = await callProxy(["farms"]);
    const text = await response.text();

    expect(text).not.toMatch(/sekrit-client-secret-value/);
    expect(text).not.toMatch(/sekrit-session-secret-value/);
  });

  it("preserves the backend's status code and body verbatim", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("t");
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Farm not found" }, 404));

    const response = await callProxy(["farms", "unknown-id"]);

    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toEqual({ detail: "Farm not found" });
  });

  it("returns 502 network_error when the backend is unreachable, without leaking the low-level error", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("t");
    fetchMock.mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await callProxy(["farms"]);

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({ error: "network_error", detail: "Could not reach the backend" });
  });

  it("ignores the removed CMP_PILOT_* variables entirely -- they have no effect on the outcome", async () => {
    vi.stubEnv("CMP_PILOT_TENANT_ID", "some-old-pilot-tenant");
    vi.stubEnv("CMP_PILOT_USER_ID", "some-old-pilot-user");
    mockGetCmpApiAccessToken.mockRejectedValue(new SessionExpiredError(new Error("x")));

    const response = await callProxy(["farms"]);

    // Still 401 -- pilot vars being set does not somehow authenticate the request.
    expect(response.status).toBe(401);
  });
});

describe("platform-scoped calls (PILOT-SETUP-001B3)", () => {
  it("dev bypass: /platform/tenants works with no tenant selected, and sends no X-Dev-Tenant-Id", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant-1");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    fetchMock.mockResolvedValue(jsonResponse([]));

    const response = await callProxy(["platform", "tenants"]); // no cookie, no tenant selected

    expect(response.status).toBe(200);
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Dev-User-Id"]).toBe("dev-user-1");
    expect(headers["X-Dev-Tenant-Id"]).toBeUndefined();
  });

  it("dev bypass: a platform-scoped POST also never requires a selected tenant", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant-1");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    fetchMock.mockResolvedValue(jsonResponse({ tenant: { id: "t1" } }, 201));

    const response = await callProxyPost(["platform", "tenants"], {}); // no cookie

    expect(response.status).toBe(201);
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Dev-Tenant-Id"]).toBeUndefined();
  });

  it("real mode: never sends X-CMP-Tenant-Id for GET /platform/tenants, even when a tenant is selected", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("t");
    fetchMock.mockResolvedValue(jsonResponse([]));

    await callProxy(["platform", "tenants"], SELECTED_TENANT_COOKIE);

    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(url.pathname).toBe("/platform/tenants");
    const headers = init.headers as Record<string, string>;
    expect(headers["X-CMP-Tenant-Id"]).toBeUndefined();
    expect(headers.Authorization).toBe("Bearer t");
  });

  it("real mode: GET /platform/tenants/{id} is also tenant-unscoped", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("t");
    fetchMock.mockResolvedValue(jsonResponse({ id: "tenant-1" }));

    await callProxy(["platform", "tenants", "tenant-1"], SELECTED_TENANT_COOKIE);

    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-CMP-Tenant-Id"]).toBeUndefined();
  });
});

describe("dev bypass mode", () => {
  it("forwards only X-Dev-Tenant-Id / X-Dev-User-Id for a selected-tenant call, and no Authorization header", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant-1");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    fetchMock.mockResolvedValue(jsonResponse([]));

    await callProxy(["farms"], SELECTED_TENANT_COOKIE);

    expect(mockGetCmpApiAccessToken).not.toHaveBeenCalled();
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Dev-User-Id"]).toBe("dev-user-1");
    expect(headers.Authorization).toBeUndefined();
  });

  it("uses the SELECTED tenant (cookie), not the configured bootstrap tenant, as X-Dev-Tenant-Id", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-bootstrap-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    fetchMock.mockResolvedValue(jsonResponse([]));

    await callProxy(["farms"], SELECTED_TENANT_COOKIE);

    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Dev-Tenant-Id"]).toBe("selected-tenant-abc");
    expect(headers["X-Dev-Tenant-Id"]).not.toBe("dev-bootstrap-tenant");
  });

  it("returns a stable 400 tenant_selection_required when no tenant is selected, without ever calling the backend", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant-1");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");

    const response = await callProxy(["farms"]); // no cookie

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ error: "tenant_selection_required" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("GET /auth/me still works with no tenant selected -- unscoped", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-tenant-1");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    fetchMock.mockResolvedValue(jsonResponse({ user: {}, memberships: [] }));

    const response = await callProxy(["auth", "me"]); // no cookie

    expect(response.status).toBe(200);
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Dev-User-Id"]).toBe("dev-user-1");
    expect(headers["X-Dev-Tenant-Id"]).toBeUndefined();
  });

  it("fails closed (500) when CMP_DEV_TENANT_ID/CMP_DEV_USER_ID are not both set, even for the unscoped /auth/me call", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    // Deliberately missing CMP_DEV_TENANT_ID / CMP_DEV_USER_ID.

    const response = await callProxy(["auth", "me"]);

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
    expect(mockGetCmpApiAccessToken).not.toHaveBeenCalled();
  });
});

describe("test bypass mode", () => {
  it("forwards X-Dev-User-Id from CMP_TEST_USER_ID and the SELECTED tenant as X-Dev-Tenant-Id, under production NODE_ENV", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("CMP_TEST_AUTH_BYPASS", "playwright-e2e-only");
    vi.stubEnv("CMP_TEST_TENANT_ID", "test-bootstrap-tenant");
    vi.stubEnv("CMP_TEST_USER_ID", "test-user-1");
    fetchMock.mockResolvedValue(jsonResponse([]));

    const response = await callProxy(["farms"], SELECTED_TENANT_COOKIE);

    expect(response.status).toBe(200);
    const [, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-Dev-Tenant-Id"]).toBe("selected-tenant-abc");
    expect(headers["X-Dev-User-Id"]).toBe("test-user-1");
    expect(headers.Authorization).toBeUndefined();
  });

  it("returns 400 tenant_selection_required with no selected tenant, never falling back to CMP_TEST_TENANT_ID", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("CMP_TEST_AUTH_BYPASS", "playwright-e2e-only");
    vi.stubEnv("CMP_TEST_TENANT_ID", "test-bootstrap-tenant");
    vi.stubEnv("CMP_TEST_USER_ID", "test-user-1");

    const response = await callProxy(["farms"]); // no cookie

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ error: "tenant_selection_required" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not activate merely because NODE_ENV=production and CMP_DEV_AUTH_BYPASS is unset -- requires the exact sentinel", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("CMP_TEST_AUTH_BYPASS", "not-the-real-sentinel");
    mockGetCmpApiAccessToken.mockRejectedValue(new SessionExpiredError(new Error("x")));

    const response = await callProxy(["farms"]);

    // Falls through to real mode, which correctly 401s with no usable
    // token -- proving an arbitrary truthy value cannot enable the bypass.
    expect(response.status).toBe(401);
  });
});
