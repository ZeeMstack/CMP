import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let mockPathname = "/access-denied";
const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useSearchParams: () => new URLSearchParams(""),
  useRouter: () => ({ push: vi.fn(), replace: mockReplace }),
}));

vi.mock("@/lib/auth/fetchAuthBootstrap", () => ({
  fetchAuthBootstrap: vi.fn(),
  selectTenant: vi.fn(),
}));

import { AuthBootstrapProvider } from "@/lib/auth/AuthBootstrapProvider";
import { AuthGate } from "@/lib/auth/AuthGate";
import { fetchAuthBootstrap } from "@/lib/auth/fetchAuthBootstrap";
import AccessDeniedPage from "./page";

/**
 * End-to-end (within Vitest) proof of the Check-again acceptance
 * behavior (AUTH-001B3): renders the REAL /access-denied page inside the
 * REAL AuthGate + AuthBootstrapProvider, clicks the real "Check again"
 * button, and proves the full chain -- refetchBootstrap() actually
 * fires a second fetchAuthBootstrap() call, the provider's state updates
 * to the refreshed result, and AuthGate reacts by navigating away to the
 * correct next destination. A pure route-access.test.ts decision-table
 * assertion alone does not exercise any of this wiring.
 */
function renderAccessDenied() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthBootstrapProvider>
        <AuthGate>
          <AccessDeniedPage />
        </AuthGate>
      </AuthBootstrapProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockPathname = "/access-denied";
  mockReplace.mockReset();
  vi.mocked(fetchAuthBootstrap).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Check-again acceptance behavior", () => {
  it("zero-membership -> Check again -> refetch resolves with one membership -> leaves /access-denied for /farms", async () => {
    vi.mocked(fetchAuthBootstrap)
      .mockResolvedValueOnce({
        status: "authenticated",
        user: { id: "u1", email: "person@example.com", displayName: "Person" },
        memberships: [],
        selectedTenantId: null,
      })
      .mockResolvedValueOnce({
        status: "authenticated",
        user: { id: "u1", email: "person@example.com", displayName: "Person" },
        memberships: [{ tenantId: "t1", tenantCode: "T1", tenantName: "Tenant One", roleCode: "tenant_admin" }],
        selectedTenantId: "t1",
      });

    renderAccessDenied();

    await waitFor(() => expect(screen.getByRole("heading", { name: "Access not provisioned" })).toBeInTheDocument());
    expect(mockReplace).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Check again" }));

    // Proves an explicit second call happened (not the first render's
    // call reused) -- this is the refetch, not a coincidence.
    await waitFor(() => expect(fetchAuthBootstrap).toHaveBeenCalledTimes(2));

    // AuthGate reacts to the newly-ready phase on its own -- the page
    // itself never calls router.replace directly.
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/farms"));
  });

  it("not_provisioned -> Check again -> refetch resolves with multiple unselected memberships -> leaves /access-denied for /select-tenant", async () => {
    vi.mocked(fetchAuthBootstrap)
      .mockResolvedValueOnce({ status: "not_provisioned", user: null, memberships: [], selectedTenantId: null })
      .mockResolvedValueOnce({
        status: "authenticated",
        user: { id: "u1", email: "person@example.com", displayName: "Person" },
        memberships: [
          { tenantId: "t1", tenantCode: "T1", tenantName: "Tenant One", roleCode: "tenant_admin" },
          { tenantId: "t2", tenantCode: "T2", tenantName: "Tenant Two", roleCode: "read_only" },
        ],
        selectedTenantId: null,
      });

    renderAccessDenied();

    await waitFor(() => expect(screen.getByRole("heading", { name: "Access not provisioned" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Check again" }));

    await waitFor(() => expect(fetchAuthBootstrap).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/select-tenant"));
  });

  it("does not poll: fetchAuthBootstrap is called exactly once on mount with no click", async () => {
    vi.mocked(fetchAuthBootstrap).mockResolvedValue({
      status: "authenticated",
      user: { id: "u1", email: "person@example.com", displayName: "Person" },
      memberships: [],
      selectedTenantId: null,
    });

    renderAccessDenied();

    await waitFor(() => expect(screen.getByRole("heading", { name: "Access not provisioned" })).toBeInTheDocument());
    // Give any accidental interval/polling a chance to fire.
    await new Promise((resolve) => setTimeout(resolve, 200));

    expect(fetchAuthBootstrap).toHaveBeenCalledTimes(1);
  });
});
