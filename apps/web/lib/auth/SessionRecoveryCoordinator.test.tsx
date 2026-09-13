import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const mockUseAuthBootstrap = vi.fn();
vi.mock("@/lib/auth/AuthBootstrapProvider", () => ({
  useAuthBootstrap: () => mockUseAuthBootstrap(),
}));

vi.mock("@/lib/auth/fetchAuthBootstrap", () => ({
  fetchAuthBootstrap: vi.fn(),
  selectTenant: vi.fn(),
}));

import { fetchAuthBootstrap } from "@/lib/auth/fetchAuthBootstrap";
import { resetSessionRecoveryForTesting, triggerSessionRecovery } from "@/lib/auth/sessionRecovery";
import { SessionRecoveryCoordinator } from "@/lib/auth/SessionRecoveryCoordinator";
import type { AuthBootstrap } from "@/lib/auth/types";

/**
 * PILOT-BLOCKER-008 CTO-review closure: `SessionRecoveryCoordinator` no
 * longer owns navigation at all (see its own module docstring) -- that
 * responsibility moved entirely to `AuthGate`, proven end-to-end in
 * `sessionRecoveryFlow.test.tsx` (which drives the real
 * `AuthBootstrapProvider`/`AuthGate` together, exactly the interaction
 * this file's OWN mocked-`useAuthBootstrap()` approach deliberately avoids
 * -- see below). What remains this component's own responsibility, and
 * what this file proves:
 *
 * 1. A triggered recovery performs the authoritative bootstrap recheck
 *    (`fetchAuthBootstrap` called) exactly once per distinct session-
 *    expiry event.
 * 2. The dedupe latch (`sessionRecovery.ts`) is respected: concurrent/
 *    repeated triggers before reauthentication never start a second
 *    recheck.
 * 3. Once a fresh, successfully-authenticated bootstrap is observed
 *    (the dedupe-reset effect, unchanged by this fix), a LATER,
 *    independent 401 can trigger recovery again -- without this, a
 *    session that recovers once could never recover again.
 *
 * `useAuthBootstrap()` is mocked directly (rather than driving a real
 * `AuthBootstrapProvider` through React Query) specifically so this file
 * controls exactly what "the currently observed bootstrap" is at each
 * step, independent of `queryClient.fetchQuery`'s own timing -- that
 * interaction (and the redirect/no-bounce-back property it enables) is
 * `sessionRecoveryFlow.test.tsx`'s job, not this file's.
 */
function bootstrapContext(bootstrap: AuthBootstrap | undefined) {
  return { bootstrap, isLoading: false, selectedTenant: null, selectTenant: vi.fn(), isSwitchingTenant: false, refetchBootstrap: vi.fn() };
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
  resetSessionRecoveryForTesting();
  mockUseAuthBootstrap.mockReset();
  vi.mocked(fetchAuthBootstrap).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SessionRecoveryCoordinator: authoritative recheck + dedupe", () => {
  it("performs exactly one authoritative recheck per session-expiry event, deduping a repeat before reauthentication", async () => {
    vi.mocked(fetchAuthBootstrap).mockResolvedValue(unauthenticatedBootstrap);
    mockUseAuthBootstrap.mockReturnValue(bootstrapContext(readyBootstrap));
    renderCoordinator();

    await act(async () => {
      await triggerSessionRecovery("/farms/abc");
    });
    expect(fetchAuthBootstrap).toHaveBeenCalledTimes(1);

    // Still deduped: a second 401 before reauthentication starts no
    // second recheck.
    await act(async () => {
      await triggerSessionRecovery("/farms/def");
    });
    expect(fetchAuthBootstrap).toHaveBeenCalledTimes(1);
  });

  it("a later independent 401 (after reauthentication) triggers a fresh recheck again", async () => {
    vi.mocked(fetchAuthBootstrap).mockResolvedValue(unauthenticatedBootstrap);
    mockUseAuthBootstrap.mockReturnValue(bootstrapContext(readyBootstrap));
    const { rerender } = renderCoordinator();

    await act(async () => {
      await triggerSessionRecovery("/farms/abc");
    });
    expect(fetchAuthBootstrap).toHaveBeenCalledTimes(1);

    // The session really is gone -- the next bootstrap read reflects it
    // (the dedupe-reset effect's dependency must actually CHANGE away from
    // "authenticated" for its later transition back to be observable).
    mockUseAuthBootstrap.mockReturnValue(bootstrapContext(unauthenticatedBootstrap));
    act(() => {
      rerender(
        <QueryClientProvider client={new QueryClient()}>
          <SessionRecoveryCoordinator />
        </QueryClientProvider>,
      );
    });

    // The user re-authenticates -- a fresh, successful bootstrap arrives,
    // resetting the dedupe latch.
    mockUseAuthBootstrap.mockReturnValue(bootstrapContext(readyBootstrap));
    act(() => {
      rerender(
        <QueryClientProvider client={new QueryClient()}>
          <SessionRecoveryCoordinator />
        </QueryClientProvider>,
      );
    });

    // A later, independent 401 must be able to trigger recovery again --
    // the property that would silently break if the dedupe latch were
    // never reset.
    await act(async () => {
      await triggerSessionRecovery("/farms/new-page");
    });
    expect(fetchAuthBootstrap).toHaveBeenCalledTimes(2);
  });

  it("does not reset the dedupe latch while still unauthenticated (no false reset)", async () => {
    vi.mocked(fetchAuthBootstrap).mockResolvedValue(unauthenticatedBootstrap);
    mockUseAuthBootstrap.mockReturnValue(bootstrapContext(readyBootstrap));
    const { rerender } = renderCoordinator();

    await act(async () => {
      await triggerSessionRecovery("/farms/abc");
    });
    expect(fetchAuthBootstrap).toHaveBeenCalledTimes(1);

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

    await act(async () => {
      await triggerSessionRecovery("/farms/def");
    });
    expect(fetchAuthBootstrap).toHaveBeenCalledTimes(1); // still deduped
  });

  it("a repeated 401 arriving while the recheck is already in flight does not start a competing recheck", async () => {
    // PILOT-BLOCKER-008 CTO-review closure requirement: the dedupe latch
    // is set synchronously in `triggerSessionRecovery` BEFORE the
    // (now-async) handler is invoked, so a second call arriving before the
    // first handler's internal `await` resolves must still be a no-op.
    let resolveRecheck: (value: AuthBootstrap) => void = () => {};
    vi.mocked(fetchAuthBootstrap).mockReturnValueOnce(new Promise((resolve) => (resolveRecheck = resolve)));
    mockUseAuthBootstrap.mockReturnValue(bootstrapContext(readyBootstrap));
    renderCoordinator();

    act(() => {
      void triggerSessionRecovery("/farms/abc");
      void triggerSessionRecovery("/farms/def"); // fires before the first's await resolves
    });

    await act(async () => {
      resolveRecheck(unauthenticatedBootstrap);
    });

    expect(fetchAuthBootstrap).toHaveBeenCalledTimes(1);
  });
});
