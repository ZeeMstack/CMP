// @vitest-environment node
import { NextRequest, NextResponse } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/server/session", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server/session")>("@/lib/server/session");
  return { ...actual, getAuthenticatedSession: vi.fn(), getCmpApiAccessToken: vi.fn() };
});

import { getAuthenticatedSession, getCmpApiAccessToken, SessionExpiredError } from "@/lib/server/session";
import { resolveIdentityForAuthMe, resolveIdentityForTenantScopedCall } from "@/lib/server/upstream-identity";

const mockGetAuthenticatedSession = vi.mocked(getAuthenticatedSession);
const mockGetCmpApiAccessToken = vi.mocked(getCmpApiAccessToken);

const request = new NextRequest("http://localhost/");
const cookieCarrier = new NextResponse();

beforeEach(() => {
  delete process.env.CMP_DEV_TENANT_ID;
  delete process.env.CMP_DEV_USER_ID;
  delete process.env.CMP_TEST_TENANT_ID;
  delete process.env.CMP_TEST_USER_ID;
  mockGetAuthenticatedSession.mockReset();
  mockGetCmpApiAccessToken.mockReset();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("resolveIdentityForAuthMe", () => {
  it("real: no session -> 401 unauthenticated", async () => {
    mockGetAuthenticatedSession.mockResolvedValue(null);
    const result = await resolveIdentityForAuthMe(request, cookieCarrier, "real");
    expect(result).toEqual({ ok: false, error: { status: 401, body: { error: "unauthenticated" } } });
  });

  it("real: valid session -> Authorization header only", async () => {
    mockGetAuthenticatedSession.mockResolvedValue({} as never);
    mockGetCmpApiAccessToken.mockResolvedValue("tok-123");
    const result = await resolveIdentityForAuthMe(request, cookieCarrier, "real");
    expect(result).toEqual({ ok: true, headers: { Authorization: "Bearer tok-123" } });
  });

  it("real: token retrieval failure -> 401 session_expired", async () => {
    mockGetAuthenticatedSession.mockResolvedValue({} as never);
    mockGetCmpApiAccessToken.mockRejectedValue(new SessionExpiredError(new Error("x")));
    const result = await resolveIdentityForAuthMe(request, cookieCarrier, "real");
    expect(result).toEqual({ ok: false, error: { status: 401, body: { error: "session_expired" } } });
  });

  it("dev: sends only X-Dev-User-Id, never X-Dev-Tenant-Id", async () => {
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-bootstrap-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    const result = await resolveIdentityForAuthMe(request, cookieCarrier, "dev");
    expect(result).toEqual({ ok: true, headers: { "X-Dev-User-Id": "dev-user-1" } });
  });

  it("test: sends only X-Dev-User-Id, sourced from CMP_TEST_USER_ID", async () => {
    vi.stubEnv("CMP_TEST_TENANT_ID", "test-bootstrap-tenant");
    vi.stubEnv("CMP_TEST_USER_ID", "test-user-1");
    const result = await resolveIdentityForAuthMe(request, cookieCarrier, "test");
    expect(result).toEqual({ ok: true, headers: { "X-Dev-User-Id": "test-user-1" } });
  });

  it("dev: incomplete config -> 500 auth_configuration_error, not thrown", async () => {
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1"); // CMP_DEV_TENANT_ID deliberately missing
    const result = await resolveIdentityForAuthMe(request, cookieCarrier, "dev");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.status).toBe(500);
  });
});

describe("resolveIdentityForTenantScopedCall", () => {
  it("real: selected tenant -> X-CMP-Tenant-Id attached alongside Authorization", async () => {
    mockGetAuthenticatedSession.mockResolvedValue({} as never);
    mockGetCmpApiAccessToken.mockResolvedValue("tok-123");
    const result = await resolveIdentityForTenantScopedCall(request, cookieCarrier, "real", "tenant-abc");
    expect(result).toEqual({
      ok: true,
      headers: { Authorization: "Bearer tok-123", "X-CMP-Tenant-Id": "tenant-abc" },
    });
  });

  it("real: no selected tenant -> Authorization only, no fabricated tenant header", async () => {
    mockGetAuthenticatedSession.mockResolvedValue({} as never);
    mockGetCmpApiAccessToken.mockResolvedValue("tok-123");
    const result = await resolveIdentityForTenantScopedCall(request, cookieCarrier, "real", null);
    expect(result).toEqual({ ok: true, headers: { Authorization: "Bearer tok-123" } });
  });

  it("real: no session -> 401 unauthenticated regardless of selected tenant", async () => {
    mockGetAuthenticatedSession.mockResolvedValue(null);
    const result = await resolveIdentityForTenantScopedCall(request, cookieCarrier, "real", "tenant-abc");
    expect(result).toEqual({ ok: false, error: { status: 401, body: { error: "unauthenticated" } } });
  });

  it("dev: selected tenant becomes X-Dev-Tenant-Id; configured user remains X-Dev-User-Id", async () => {
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-bootstrap-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    const result = await resolveIdentityForTenantScopedCall(request, cookieCarrier, "dev", "selected-tenant-xyz");
    expect(result).toEqual({
      ok: true,
      headers: { "X-Dev-Tenant-Id": "selected-tenant-xyz", "X-Dev-User-Id": "dev-user-1" },
    });
  });

  it("dev: no selected tenant -> stable 400 tenant_selection_required, never falls back to the configured bootstrap tenant", async () => {
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-bootstrap-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    const result = await resolveIdentityForTenantScopedCall(request, cookieCarrier, "dev", null);
    expect(result).toEqual({ ok: false, error: { status: 400, body: { error: "tenant_selection_required" } } });
  });

  it("test: selected tenant becomes X-Dev-Tenant-Id; configured user remains X-Dev-User-Id", async () => {
    vi.stubEnv("CMP_TEST_TENANT_ID", "test-bootstrap-tenant");
    vi.stubEnv("CMP_TEST_USER_ID", "test-user-1");
    const result = await resolveIdentityForTenantScopedCall(request, cookieCarrier, "test", "selected-tenant-xyz");
    expect(result).toEqual({
      ok: true,
      headers: { "X-Dev-Tenant-Id": "selected-tenant-xyz", "X-Dev-User-Id": "test-user-1" },
    });
  });

  it("test: no selected tenant -> stable 400, never uses CMP_TEST_TENANT_ID as an operational selection", async () => {
    vi.stubEnv("CMP_TEST_TENANT_ID", "test-bootstrap-tenant");
    vi.stubEnv("CMP_TEST_USER_ID", "test-user-1");
    const result = await resolveIdentityForTenantScopedCall(request, cookieCarrier, "test", null);
    expect(result).toEqual({ ok: false, error: { status: 400, body: { error: "tenant_selection_required" } } });
  });

  it("dev/test paths never produce an X-CMP-Tenant-Id header", async () => {
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-bootstrap-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    const result = await resolveIdentityForTenantScopedCall(request, cookieCarrier, "dev", "selected-tenant-xyz");
    expect(result.ok && "X-CMP-Tenant-Id" in result.headers).toBe(false);
  });
});
