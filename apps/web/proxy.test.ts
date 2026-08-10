// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/server/auth0", () => ({
  getAuth0Client: vi.fn(),
}));

import { getAuth0Client } from "@/lib/server/auth0";
import { proxy } from "./proxy";

const ENV_KEYS = ["NODE_ENV", "CMP_DEV_AUTH_BYPASS", "CMP_TEST_AUTH_BYPASS", "CMP_DEV_TENANT_ID", "CMP_DEV_USER_ID"] as const;

beforeEach(() => {
  for (const key of ENV_KEYS) delete process.env[key];
  vi.stubEnv("NODE_ENV", "development");
  vi.mocked(getAuth0Client).mockReset();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("proxy.ts", () => {
  it("does not construct/call the Auth0 client at all in dev bypass mode", async () => {
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");
    vi.stubEnv("CMP_DEV_TENANT_ID", "t");
    vi.stubEnv("CMP_DEV_USER_ID", "u");

    const response = await proxy(new Request("http://localhost/farms"));

    expect(getAuth0Client).not.toHaveBeenCalled();
    expect(response.status).toBe(200); // NextResponse.next() passthrough
  });

  it("does not construct/call the Auth0 client in test bypass mode", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("CMP_TEST_AUTH_BYPASS", "playwright-e2e-only");

    await proxy(new Request("http://localhost/farms"));

    expect(getAuth0Client).not.toHaveBeenCalled();
  });

  it("delegates to auth0.middleware(request) in real mode", async () => {
    const middleware = vi.fn().mockResolvedValue(new Response(null));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(getAuth0Client).mockReturnValue({ middleware } as any);

    const request = new Request("http://localhost/farms");
    await proxy(request);

    expect(getAuth0Client).toHaveBeenCalledTimes(1);
    expect(middleware).toHaveBeenCalledWith(request);
  });

  it("propagates the fail-closed error rather than falling back to real mode when dev bypass is misconfigured for production", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("CMP_DEV_AUTH_BYPASS", "true");

    await expect(proxy(new Request("http://localhost/farms"))).rejects.toThrow(/production/i);
    expect(getAuth0Client).not.toHaveBeenCalled();
  });
});
