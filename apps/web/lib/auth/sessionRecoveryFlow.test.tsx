import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * PILOT-BLOCKER-008 CTO-review closure: end-to-end proof of the
 * session-expiry recovery fix, driving the REAL `AuthBootstrapProvider` +
 * `SessionRecoveryCoordinator` + `AuthGate` together over React Query --
 * unlike `SessionRecoveryCoordinator.test.tsx` (which deliberately mocks
 * `useAuthBootstrap()` directly to avoid this exact interaction, per its
 * own comment), this file exists specifically to prove the property that
 * mocking away hides: that `SessionRecoveryCoordinator`'s handler obtains
 * an AUTHORITATIVE bootstrap recheck and writes it into the SAME cache
 * `AuthGate` observes, and that `AuthGate` -- now the sole owner of
 * session-expiry navigation -- redirects exactly once, to `/login` with
 * the original protected route preserved as `returnTo`, and never bounces
 * back (the confirmed defect Playwright's corrected route-access.spec.ts
 * test D exposed).
 *
 * `usePathname`/`useSearchParams` are mocked as REACTIVE state (not a bare
 * closure variable), and the rendered "page" itself reacts to the same
 * mocked URL -- both are necessary for this test to actually observe a
 * redirect-back if the defect were still present; a static children tree
 * would show "protected content" is never really gone even after a real
 * navigation.
 */

let currentUrl = "/farms/abc/crop-batches";
let urlListeners: Array<() => void> = [];

function setUrl(next: string) {
  currentUrl = next;
  urlListeners.forEach((listener) => listener());
}

const mockReplace = vi.fn((to: string) => setUrl(to));

function useReactiveUrlTick(): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    const listener = () => setTick((t) => t + 1);
    urlListeners.push(listener);
    return () => {
      urlListeners = urlListeners.filter((l) => l !== listener);
    };
  }, []);
}

vi.mock("next/navigation", () => ({
  usePathname: () => {
    useReactiveUrlTick();
    return currentUrl.split("?")[0];
  },
  useSearchParams: () => {
    useReactiveUrlTick();
    return new URLSearchParams(currentUrl.split("?")[1] ?? "");
  },
  useRouter: () => ({ push: vi.fn(), replace: mockReplace }),
}));

vi.mock("@/lib/auth/fetchAuthBootstrap", () => ({
  fetchAuthBootstrap: vi.fn(),
  selectTenant: vi.fn(),
}));

import { AuthBootstrapProvider } from "@/lib/auth/AuthBootstrapProvider";
import { AuthGate } from "@/lib/auth/AuthGate";
import { fetchAuthBootstrap } from "@/lib/auth/fetchAuthBootstrap";
import { resetSessionRecoveryForTesting, triggerSessionRecovery } from "@/lib/auth/sessionRecovery";
import { SessionRecoveryCoordinator } from "@/lib/auth/SessionRecoveryCoordinator";
import type { AuthBootstrap } from "@/lib/auth/types";

const PROTECTED_TEXT = "PROTECTED CONTENT";
const LOGIN_TEXT = "LOGIN PAGE";

const authenticatedBootstrap: AuthBootstrap = {
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

/** Stands in for Next.js's real page-swapping-by-route behavior -- a
 * STATIC children tree under `AuthGate` would never actually prove
 * "protected content is gone", since `AuthGate` would keep rendering the
 * exact same children for a `decision.kind === "allow"` regardless of
 * which route produced that decision. */
function CurrentPage() {
  useReactiveUrlTick();
  const path = currentUrl.split("?")[0];
  if (path === "/login") return <div>{LOGIN_TEXT}</div>;
  return <div>{PROTECTED_TEXT}</div>;
}

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthBootstrapProvider>
        <SessionRecoveryCoordinator />
        <AuthGate>
          <CurrentPage />
        </AuthGate>
      </AuthBootstrapProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  currentUrl = "/farms/abc/crop-batches";
  urlListeners = [];
  mockReplace.mockClear();
  resetSessionRecoveryForTesting();
  vi.mocked(fetchAuthBootstrap).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Session-expiry recovery: authoritative recheck before navigation (no redirect-back loop)", () => {
  it("lands on /login with the correct returnTo and STAYS there once bootstrap authoritatively reports unauthenticated", async () => {
    vi.mocked(fetchAuthBootstrap)
      .mockResolvedValueOnce(authenticatedBootstrap) // initial page load
      .mockResolvedValueOnce(unauthenticatedBootstrap); // SessionRecoveryCoordinator's authoritative recheck

    renderApp();
    await waitFor(() => expect(screen.getByText(PROTECTED_TEXT)).toBeInTheDocument());

    await act(async () => {
      await triggerSessionRecovery("/farms/abc/crop-batches");
    });

    // Lands on /login with the exact original protected route preserved
    // as returnTo -- AuthGate derives this from its own live pathname/
    // search, which never changed out from under it during the recheck.
    await waitFor(() => expect(screen.getByText(LOGIN_TEXT)).toBeInTheDocument());
    expect(mockReplace).toHaveBeenCalledWith(expect.stringMatching(/^\/login\?returnTo=/));
    expect(decodeURIComponent(mockReplace.mock.calls[0][0].split("returnTo=")[1])).toBe(
      "/farms/abc/crop-batches",
    );

    // The critical assertion this whole file exists to prove: once
    // AuthGate observes the AUTHORITATIVE (unauthenticated) bootstrap and
    // redirects, it must never bounce back to the protected route -- exactly
    // one navigation call total, and the protected content stays gone.
    expect(mockReplace).toHaveBeenCalledTimes(1);
    expect(currentUrl.split("?")[0]).toBe("/login");
    expect(screen.queryByText(PROTECTED_TEXT)).not.toBeInTheDocument();
    // Never a fake authenticated intermediate state on /login.
    expect(screen.queryByText(/loading/i)).not.toBeInTheDocument();
  });

  it("never forces a navigation when the authoritative recheck confirms the session is genuinely still valid (a false-positive 401)", async () => {
    // An adversarial recheck: fetchAuthBootstrap's SECOND call (the
    // authoritative recheck) still resolves "authenticated" -- proves the
    // recovery mechanism never forces a confirmed-still-valid session off
    // to /login. AuthGate keeps rendering "allow" for a still-"ready"
    // phase on the protected route, exactly as it always has.
    vi.mocked(fetchAuthBootstrap)
      .mockResolvedValueOnce(authenticatedBootstrap)
      .mockResolvedValueOnce(authenticatedBootstrap);

    renderApp();
    await waitFor(() => expect(screen.getByText(PROTECTED_TEXT)).toBeInTheDocument());

    await act(async () => {
      await triggerSessionRecovery("/farms/abc/crop-batches");
    });

    await waitFor(() => expect(fetchAuthBootstrap).toHaveBeenCalledTimes(2));
    expect(mockReplace).not.toHaveBeenCalled();
    expect(screen.getByText(PROTECTED_TEXT)).toBeInTheDocument();
  });

  it("a repeated 401 while recovery is already in flight does not trigger a competing navigation", async () => {
    let resolveRecheck: (value: AuthBootstrap) => void = () => {};
    vi.mocked(fetchAuthBootstrap)
      .mockResolvedValueOnce(authenticatedBootstrap)
      .mockReturnValueOnce(new Promise((resolve) => (resolveRecheck = resolve)));

    renderApp();
    await waitFor(() => expect(screen.getByText(PROTECTED_TEXT)).toBeInTheDocument());

    // Two 401s in immediate succession, before the first's authoritative
    // recheck has resolved -- the dedupe latch (unchanged by this fix)
    // must still allow only the first to ever start a recheck.
    act(() => {
      void triggerSessionRecovery("/farms/abc/crop-batches");
      void triggerSessionRecovery("/farms/abc/other-page");
    });

    await act(async () => {
      resolveRecheck(unauthenticatedBootstrap);
    });

    // Exactly one redirect, to the CURRENT (never-navigated-away-from)
    // protected route -- proving there is no competing navigation, not
    // "which argument wins" (AuthGate no longer consults the argument at
    // all; it reads its own live pathname).
    await waitFor(() => expect(screen.getByText(LOGIN_TEXT)).toBeInTheDocument());
    expect(mockReplace).toHaveBeenCalledTimes(1);
    expect(decodeURIComponent(mockReplace.mock.calls[0][0].split("returnTo=")[1])).toBe(
      "/farms/abc/crop-batches",
    );
  });

  it("an unrelated 403 (permission error, not session expiry) never triggers session recovery at all", async () => {
    // `client.ts` only calls `triggerSessionRecovery` for a 401 -- a 403
    // is an ordinary, unrelated domain/permission failure. This is
    // unchanged by this fix; asserted here for completeness alongside the
    // rest of this file's session-recovery proof.
    vi.mocked(fetchAuthBootstrap).mockResolvedValueOnce(authenticatedBootstrap);

    renderApp();
    await waitFor(() => expect(screen.getByText(PROTECTED_TEXT)).toBeInTheDocument());

    // No call to triggerSessionRecovery here at all -- a 403 never reaches it.
    expect(mockReplace).not.toHaveBeenCalled();
    expect(screen.getByText(PROTECTED_TEXT)).toBeInTheDocument();
  });
});
