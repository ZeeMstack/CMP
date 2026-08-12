// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/server/session", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server/session")>("@/lib/server/session");
  return { ...actual, getCmpApiAccessToken: vi.fn() };
});

import { getCmpApiAccessToken, SessionExpiredError } from "@/lib/server/session";
import { resolveIdentityForAuthMe, resolveIdentityForTenantScopedCall } from "@/lib/server/upstream-identity";

const mockGetCmpApiAccessToken = vi.mocked(getCmpApiAccessToken);

beforeEach(() => {
  delete process.env.CMP_DEV_TENANT_ID;
  delete process.env.CMP_DEV_USER_ID;
  delete process.env.CMP_TEST_TENANT_ID;
  delete process.env.CMP_TEST_USER_ID;
  mockGetCmpApiAccessToken.mockReset();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("resolveIdentityForAuthMe", () => {
  it("real: attempts getCmpApiAccessToken() directly, with no separate getSession precheck -- module no longer exports getAuthenticatedSession", async () => {
    // @/lib/server/session no longer exports getAuthenticatedSession at
    // all (AUTH-001C.2 removed it as dead code) -- this import-shape
    // assertion fails at compile/type time if it is ever reintroduced,
    // and this test documents why: getCmpApiAccessToken() alone is the
    // authoritative real-auth check now.
    const sessionModule = await import("@/lib/server/session");
    expect("getAuthenticatedSession" in sessionModule).toBe(false);

    mockGetCmpApiAccessToken.mockResolvedValue("tok-123");
    const result = await resolveIdentityForAuthMe("real");
    expect(result).toEqual({ ok: true, headers: { Authorization: "Bearer tok-123" } });
    expect(mockGetCmpApiAccessToken).toHaveBeenCalledWith();
    expect(mockGetCmpApiAccessToken).toHaveBeenCalledTimes(1);
  });

  it("real: token retrieval failure -> stable 401 session_expired (covers both 'no session at all' and 'session present but token failed', since there is no longer a way to distinguish them)", async () => {
    mockGetCmpApiAccessToken.mockRejectedValue(new SessionExpiredError(new Error("x")));
    const result = await resolveIdentityForAuthMe("real");
    expect(result).toEqual({ ok: false, error: { status: 401, body: { error: "session_expired" } } });
  });

  it("real: never surfaces the underlying SDK/provider error text", async () => {
    mockGetCmpApiAccessToken.mockRejectedValue(
      new SessionExpiredError(new Error("super-secret-vendor-diagnostic-detail")),
    );
    const result = await resolveIdentityForAuthMe("real");
    expect(JSON.stringify(result)).not.toMatch(/super-secret-vendor-diagnostic-detail/);
  });

  it("dev: sends only X-Dev-User-Id, never X-Dev-Tenant-Id, and never calls Auth0 token acquisition", async () => {
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-bootstrap-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    const result = await resolveIdentityForAuthMe("dev");
    expect(result).toEqual({ ok: true, headers: { "X-Dev-User-Id": "dev-user-1" } });
    expect(mockGetCmpApiAccessToken).not.toHaveBeenCalled();
  });

  it("test: sends only X-Dev-User-Id, sourced from CMP_TEST_USER_ID, and never calls Auth0 token acquisition", async () => {
    vi.stubEnv("CMP_TEST_TENANT_ID", "test-bootstrap-tenant");
    vi.stubEnv("CMP_TEST_USER_ID", "test-user-1");
    const result = await resolveIdentityForAuthMe("test");
    expect(result).toEqual({ ok: true, headers: { "X-Dev-User-Id": "test-user-1" } });
    expect(mockGetCmpApiAccessToken).not.toHaveBeenCalled();
  });

  it("dev: incomplete config -> 500 auth_configuration_error, not thrown, and never calls Auth0 token acquisition", async () => {
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1"); // CMP_DEV_TENANT_ID deliberately missing
    const result = await resolveIdentityForAuthMe("dev");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.status).toBe(500);
    expect(mockGetCmpApiAccessToken).not.toHaveBeenCalled();
  });
});

describe("resolveIdentityForTenantScopedCall", () => {
  it("real: selected tenant -> X-CMP-Tenant-Id attached alongside Authorization, via a direct getCmpApiAccessToken() attempt", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok-123");
    const result = await resolveIdentityForTenantScopedCall("real", "tenant-abc");
    expect(result).toEqual({
      ok: true,
      headers: { Authorization: "Bearer tok-123", "X-CMP-Tenant-Id": "tenant-abc" },
    });
    expect(mockGetCmpApiAccessToken).toHaveBeenCalledWith();
  });

  it("real: no selected tenant -> Authorization only, no fabricated tenant header", async () => {
    mockGetCmpApiAccessToken.mockResolvedValue("tok-123");
    const result = await resolveIdentityForTenantScopedCall("real", null);
    expect(result).toEqual({ ok: true, headers: { Authorization: "Bearer tok-123" } });
  });

  it("real: token retrieval failure -> stable 401 session_expired regardless of selected tenant", async () => {
    mockGetCmpApiAccessToken.mockRejectedValue(new SessionExpiredError(new Error("x")));
    const result = await resolveIdentityForTenantScopedCall("real", "tenant-abc");
    expect(result).toEqual({ ok: false, error: { status: 401, body: { error: "session_expired" } } });
  });

  it("dev: selected tenant becomes X-Dev-Tenant-Id; configured user remains X-Dev-User-Id; Auth0 token acquisition never called", async () => {
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-bootstrap-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    const result = await resolveIdentityForTenantScopedCall("dev", "selected-tenant-xyz");
    expect(result).toEqual({
      ok: true,
      headers: { "X-Dev-Tenant-Id": "selected-tenant-xyz", "X-Dev-User-Id": "dev-user-1" },
    });
    expect(mockGetCmpApiAccessToken).not.toHaveBeenCalled();
  });

  it("dev: no selected tenant -> stable 400 tenant_selection_required, never falls back to the configured bootstrap tenant", async () => {
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-bootstrap-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    const result = await resolveIdentityForTenantScopedCall("dev", null);
    expect(result).toEqual({ ok: false, error: { status: 400, body: { error: "tenant_selection_required" } } });
  });

  it("test: selected tenant becomes X-Dev-Tenant-Id; configured user remains X-Dev-User-Id", async () => {
    vi.stubEnv("CMP_TEST_TENANT_ID", "test-bootstrap-tenant");
    vi.stubEnv("CMP_TEST_USER_ID", "test-user-1");
    const result = await resolveIdentityForTenantScopedCall("test", "selected-tenant-xyz");
    expect(result).toEqual({
      ok: true,
      headers: { "X-Dev-Tenant-Id": "selected-tenant-xyz", "X-Dev-User-Id": "test-user-1" },
    });
  });

  it("test: no selected tenant -> stable 400, never uses CMP_TEST_TENANT_ID as an operational selection", async () => {
    vi.stubEnv("CMP_TEST_TENANT_ID", "test-bootstrap-tenant");
    vi.stubEnv("CMP_TEST_USER_ID", "test-user-1");
    const result = await resolveIdentityForTenantScopedCall("test", null);
    expect(result).toEqual({ ok: false, error: { status: 400, body: { error: "tenant_selection_required" } } });
  });

  it("dev/test paths never produce an X-CMP-Tenant-Id header", async () => {
    vi.stubEnv("CMP_DEV_TENANT_ID", "dev-bootstrap-tenant");
    vi.stubEnv("CMP_DEV_USER_ID", "dev-user-1");
    const result = await resolveIdentityForTenantScopedCall("dev", "selected-tenant-xyz");
    expect(result.ok && "X-CMP-Tenant-Id" in result.headers).toBe(false);
  });
});
