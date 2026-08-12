// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/server/session", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server/session")>("@/lib/server/session");
  return { ...actual, getCmpApiAccessToken: vi.fn() };
});

import { getCmpApiAccessToken, SessionExpiredError } from "@/lib/server/session";
import { POST } from "./route";

const mockGetCmpApiAccessToken = vi.mocked(getCmpApiAccessToken);

let fetchMock: ReturnType<typeof vi.fn>;

const RESET_ENV_KEYS: string[] = ["NODE_ENV", "CMP_DEV_AUTH_BYPASS"];

beforeEach(() => {
  for (const key of RESET_ENV_KEYS) delete process.env[key];
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

function callSelect(body: unknown, opts: { origin?: string | null } = {}) {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.origin !== undefined && opts.origin !== null) headers.origin = opts.origin;
  const request = new NextRequest("http://localhost/api/tenant/select", {
    method: "POST",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return POST(request);
}

const authMeBody = (memberships: Array<{ tenant_id: string; tenant_code: string; tenant_name: string; role_code: string }>) => ({
  user: { id: "user-1", email: "person@example.com", display_name: "Person" },
  memberships,
});

const TENANT_A = "11111111-1111-1111-1111-111111111111";
const TENANT_B = "22222222-2222-2222-2222-222222222222";

describe("POST /api/tenant/select", () => {
  it("cross-origin request is rejected (403), before any auth/backend work happens", async () => {
    const response = await callSelect({ tenant_id: TENANT_A }, { origin: "https://evil.example" });
    expect(response.status).toBe(403);
    expect(mockGetCmpApiAccessToken).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("missing body -> 400", async () => {
    const request = new NextRequest("http://localhost/api/tenant/select", { method: "POST" });
    const response = await POST(request);
    expect(response.status).toBe(400);
  });

  it("missing tenant_id -> 400", async () => {
    const response = await callSelect({});
    expect(response.status).toBe(400);
  });

  it("malformed UUID -> 400", async () => {
    const response = await callSelect({ tenant_id: "not-a-uuid" });
    expect(response.status).toBe(400);
  });

  it("token retrieval fails (covers 'no session at all' and 'session present but unusable' alike) -> 401, no backend call", async () => {
    mockGetCmpApiAccessToken.mockRejectedValue(new SessionExpiredError(new Error("x")));
    const response = await callSelect({ tenant_id: TENANT_A });
    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("target tenant absent from a FRESH /auth/me membership list -> 403, cookie untouched", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockResolvedValue(
      jsonResponse(authMeBody([{ tenant_id: TENANT_B, tenant_code: "B", tenant_name: "Tenant B", role_code: "tenant_admin" }])),
    );

    const response = await callSelect({ tenant_id: TENANT_A }); // requesting A, only B is in the fresh list

    expect(response.status).toBe(403);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("a tenant present only in stale client state (not in the fresh /auth/me) is rejected -- fresh verification is mandatory", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    // Fresh /auth/me no longer contains TENANT_A (e.g. membership revoked
    // since the client last saw it) -- must reject even though the client
    // is asking for a tenant id that "looks like" a real UUID it once had.
    fetchMock.mockResolvedValue(jsonResponse(authMeBody([])));

    const response = await callSelect({ tenant_id: TENANT_A });

    expect(response.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1); // proves it actually re-fetched, not reused any cache
  });

  it("valid membership -> 200 and cookie set to the requested tenant", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockResolvedValue(
      jsonResponse(
        authMeBody([
          { tenant_id: TENANT_A, tenant_code: "A", tenant_name: "Tenant A", role_code: "tenant_admin" },
          { tenant_id: TENANT_B, tenant_code: "B", tenant_name: "Tenant B", role_code: "read_only" },
        ]),
      ),
    );

    const response = await callSelect({ tenant_id: TENANT_B });

    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toEqual({
      status: "authenticated",
      user: { id: "user-1", email: "person@example.com", displayName: "Person" },
      memberships: [
        { tenantId: TENANT_A, tenantCode: "A", tenantName: "Tenant A", roleCode: "tenant_admin" },
        { tenantId: TENANT_B, tenantCode: "B", tenantName: "Tenant B", roleCode: "read_only" },
      ],
      selectedTenantId: TENANT_B,
    });
    expect(response.headers.get("set-cookie") ?? "").toMatch(new RegExp(`cmp_tenant_id=${TENANT_B}`));
  });

  it("backend /auth/me failure does not mutate the cookie", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await callSelect({ tenant_id: TENANT_A });

    expect(response.status).toBe(502);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("does not leak whether an inaccessible tenant exists at all (generic 403 body)", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok");
    fetchMock.mockResolvedValue(jsonResponse(authMeBody([])));

    const response = await callSelect({ tenant_id: TENANT_A });
    const body = await response.json();

    expect(body).toEqual({ error: "tenant_not_accessible" });
  });
});
