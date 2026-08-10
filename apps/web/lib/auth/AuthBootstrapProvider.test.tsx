import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/fetchAuthBootstrap", () => ({
  fetchAuthBootstrap: vi.fn(),
  selectTenant: vi.fn(),
}));
vi.mock("@/lib/api/client", () => ({ listFarms: vi.fn() }));

import { listFarms } from "@/lib/api/client";
import { AuthBootstrapProvider, useAuthBootstrap } from "@/lib/auth/AuthBootstrapProvider";
import { selectTenant as postSelectTenant } from "@/lib/auth/fetchAuthBootstrap";
import type { AuthBootstrap } from "@/lib/auth/types";
import { useFarms } from "@/lib/query/hooks";
import { queryKeys } from "@/lib/query/keys";

const TENANT_A = "11111111-1111-1111-1111-111111111111";
const TENANT_B = "22222222-2222-2222-2222-222222222222";

const bootstrapWithSelection = (selectedTenantId: string): AuthBootstrap => ({
  status: "authenticated",
  user: { id: "u1", email: "a@example.com", displayName: "A" },
  memberships: [
    { tenantId: TENANT_A, tenantCode: "A", tenantName: "Alpha Tenant", roleCode: "tenant_admin" },
    { tenantId: TENANT_B, tenantCode: "B", tenantName: "Beta Tenant", roleCode: "tenant_admin" },
  ],
  selectedTenantId,
});

function makeWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthBootstrapProvider>{children}</AuthBootstrapProvider>
      </QueryClientProvider>
    );
  };
}

beforeEach(() => {
  vi.mocked(listFarms).mockReset();
  vi.mocked(postSelectTenant).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("tenant switch: cache-flash regression", () => {
  it("removes Tenant A's cached data before Tenant B data ever renders, and Tenant B queries resolve under B-prefixed keys", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    // Simulates a user who has been browsing Tenant A: bootstrap already
    // resolved to A, and A's farms are already cached.
    queryClient.setQueryData(queryKeys.authBootstrap(), bootstrapWithSelection(TENANT_A));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    queryClient.setQueryData(queryKeys.farms(TENANT_A), [{ id: "farm-alpha", name: "Alpha Farm", code: "ALPHA" }] as any);

    vi.mocked(listFarms).mockResolvedValue([
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      { id: "farm-beta", name: "Beta Farm", code: "BETA" } as any,
    ]);
    vi.mocked(postSelectTenant).mockResolvedValue({ ok: true, bootstrap: bootstrapWithSelection(TENANT_B) });

    const { result } = renderHook(() => ({ auth: useAuthBootstrap(), farms: useFarms() }), {
      wrapper: makeWrapper(queryClient),
    });

    // Sanity: Tenant A's cached farm is visible before any switch happens.
    await waitFor(() => expect(result.current.farms.data?.[0]?.name).toBe("Alpha Farm"));
    expect(result.current.auth.selectedTenant?.tenantId).toBe(TENANT_A);

    await act(async () => {
      await result.current.auth.selectTenant(TENANT_B);
    });

    // The switch clears the ENTIRE cache (belt-and-braces) -- Tenant A's
    // farms entry must be gone immediately, not just stale.
    expect(queryClient.getQueryData(queryKeys.farms(TENANT_A))).toBeUndefined();

    await waitFor(() => expect(result.current.auth.bootstrap?.selectedTenantId).toBe(TENANT_B));

    // The critical assertion: at no point after the switch does the
    // re-rendered farms query ever show Tenant A's farm -- it is either
    // absent (loading under the new B-prefixed key) or already Beta's data.
    expect(result.current.farms.data?.some((f) => f.name === "Alpha Farm")).toBeFalsy();

    await waitFor(() => expect(result.current.farms.data?.[0]?.name).toBe("Beta Farm"));
    expect(listFarms).toHaveBeenCalled();
  });

  it("a failed selection attempt still clears stale data and does not leave the app on Tenant A's cache", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient.setQueryData(queryKeys.authBootstrap(), bootstrapWithSelection(TENANT_A));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    queryClient.setQueryData(queryKeys.farms(TENANT_A), [{ id: "farm-alpha", name: "Alpha Farm", code: "ALPHA" }] as any);

    vi.mocked(postSelectTenant).mockResolvedValue({ ok: false, status: 403 });
    // Reseed path: after a failed switch, the provider refetches bootstrap.
    const { fetchAuthBootstrap } = await import("@/lib/auth/fetchAuthBootstrap");
    vi.mocked(fetchAuthBootstrap).mockResolvedValue(bootstrapWithSelection(TENANT_A));

    const { result } = renderHook(() => ({ auth: useAuthBootstrap() }), { wrapper: makeWrapper(queryClient) });

    await act(async () => {
      const outcome = await result.current.auth.selectTenant(TENANT_B);
      expect(outcome.ok).toBe(false);
    });

    // Cache was cleared regardless of outcome -- the stale Alpha Farm
    // entry must not survive a failed switch attempt either.
    expect(queryClient.getQueryData(queryKeys.farms(TENANT_A))).toBeUndefined();
  });
});
