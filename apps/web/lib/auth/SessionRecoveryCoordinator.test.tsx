import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: mockReplace }),
}));

const mockUseAuthBootstrap = vi.fn();
vi.mock("@/lib/auth/AuthBootstrapProvider", () => ({
  useAuthBootstrap: () => mockUseAuthBootstrap(),
}));

import { SessionRecoveryCoordinator } from "@/lib/auth/SessionRecoveryCoordinator";
import { resetSessionRecoveryForTesting, triggerSessionRecovery } from "@/lib/auth/sessionRecovery";
import type { AuthBootstrap } from "@/lib/auth/types";

/**
 * Proves the FULL dedupe lifecycle -- not just the pure sessionRecovery.ts
 * module in isolation (see sessionRecovery.test.ts), but that
 * SessionRecoveryCoordinator itself wires a fresh, successfully-
 * authenticated bootstrap to resetSessionRecoveryDedupe(). Without this,
 * a session that recovers once (401 -> /login -> re-authenticate) could
 * never recover again after a later, independent 401.
 *
 * useAuthBootstrap() is mocked directly (rather than driving a real
 * AuthBootstrapProvider through React Query) so this test controls
 * exactly what bootstrap value the coordinator sees at each step,
 * without racing React Query's own background refetch behavior after
 * queryClient.clear() -- that mechanism belongs to
 * AuthBootstrapProvider.test.tsx / tenant-switch tests, not here.
 */
function bootstrapContext(bootstrap: AuthBootstrap | undefined) {
  return {
    bootstrap,
    isLoading: false,
    selectedTenant: null,
    selectTenant: vi.fn(),
    isSwitchingTenant: false,
    refetchBootstrap: vi.fn(),
  };
}

const readyBootstrap: AuthBootstrap = {
  status: "authenticated",
  user: { id: "u1", email: "a@example.com", displayName: "A" },
  memberships: [{ tenantId: "t1", tenantCode: "T1", tenantName: "Tenant One", roleCode: "tenant_admin" }],
  selectedTenantId: "t1",
};

const unauthenticatedBootstrap: AuthBootstrap = {
  status: "unauthenticated",
  user: null,
  memberships: [],
  selectedTenantId: null,
};

function renderCoordinator() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionRecoveryCoordinator />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockReplace.mockReset();
  resetSessionRecoveryForTesting();
  mockUseAuthBootstrap.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SessionRecoveryCoordinator: dedupe reset on reauthentication", () => {
  it("a later independent 401 (after reauthentication) triggers recovery again", () => {
    mockUseAuthBootstrap.mockReturnValue(bootstrapContext(readyBootstrap));
    const { rerender } = renderCoordinator();

    // First session-expiry: recovery fires once.
    act(() => {
      triggerSessionRecovery("/farms/abc");
    });
    expect(mockReplace).toHaveBeenCalledTimes(1);
    expect(mockReplace).toHaveBeenCalledWith(expect.stringContaining("/login?returnTo="));

    // The session really is gone -- the next bootstrap read reflects it.
    mockUseAuthBootstrap.mockReturnValue(bootstrapContext(unauthenticatedBootstrap));
    act(() => {
      rerender(
        <QueryClientProvider client={new QueryClient()}>
          <SessionRecoveryCoordinator />
        </QueryClientProvider>,
      );
    });

    // Still deduped: a second 401 before reauthentication does not fire again.
    act(() => {
      triggerSessionRecovery("/farms/def");
    });
    expect(mockReplace).toHaveBeenCalledTimes(1);

    // The user re-authenticates -- a fresh, successful bootstrap arrives.
    mockUseAuthBootstrap.mockReturnValue(bootstrapContext(readyBootstrap));
    act(() => {
      rerender(
        <QueryClientProvider client={new QueryClient()}>
          <SessionRecoveryCoordinator />
        </QueryClientProvider>,
      );
    });

    // A later, independent 401 must be able to trigger recovery again --
    // this is the property that would silently break if the dedupe latch
    // were never reset.
    act(() => {
      triggerSessionRecovery("/farms/new-page");
    });
    expect(mockReplace).toHaveBeenCalledTimes(2);
    expect(mockReplace).toHaveBeenLastCalledWith(expect.stringContaining(encodeURIComponent("/farms/new-page")));
  });

  it("does not reset the dedupe latch while still unauthenticated (no false reset)", () => {
    mockUseAuthBootstrap.mockReturnValue(bootstrapContext(readyBootstrap));
    const { rerender } = renderCoordinator();

    act(() => {
      triggerSessionRecovery("/farms/abc");
    });
    expect(mockReplace).toHaveBeenCalledTimes(1);

    // Bootstrap settles to unauthenticated (the expected state right
    // after the 401) -- must NOT reset the latch.
    mockUseAuthBootstrap.mockReturnValue(bootstrapContext(unauthenticatedBootstrap));
    act(() => {
      rerender(
        <QueryClientProvider client={new QueryClient()}>
          <SessionRecoveryCoordinator />
        </QueryClientProvider>,
      );
    });

    act(() => {
      triggerSessionRecovery("/farms/def");
    });
    expect(mockReplace).toHaveBeenCalledTimes(1); // still deduped
  });
});
