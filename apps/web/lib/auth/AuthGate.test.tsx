import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let mockPathname = "/farms/abc";
let mockSearch = "";
const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useSearchParams: () => new URLSearchParams(mockSearch),
  useRouter: () => ({ push: vi.fn(), replace: mockReplace }),
}));

vi.mock("@/lib/auth/fetchAuthBootstrap", () => ({
  fetchAuthBootstrap: vi.fn(),
  selectTenant: vi.fn(),
}));

import { AuthBootstrapProvider } from "@/lib/auth/AuthBootstrapProvider";
import { AuthGate } from "@/lib/auth/AuthGate";
import type { AuthBootstrap } from "@/lib/auth/types";
import { fetchAuthBootstrap } from "@/lib/auth/fetchAuthBootstrap";

const PROTECTED_TEXT = "PROTECTED CONTENT MUST NEVER FLASH";

function renderGate() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthBootstrapProvider>
        <AuthGate>
          <div>{PROTECTED_TEXT}</div>
        </AuthGate>
      </AuthBootstrapProvider>
    </QueryClientProvider>,
  );
}

function membership(tenantId: string) {
  return { tenantId, tenantCode: "T", tenantName: `Tenant ${tenantId}`, roleCode: "tenant_admin" };
}

beforeEach(() => {
  mockPathname = "/farms/abc";
  mockSearch = "";
  mockReplace.mockReset();
  vi.mocked(fetchAuthBootstrap).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AuthGate: route-transition flash prevention", () => {
  it("bootstrap loading: shows only a neutral loading state, never protected content", async () => {
    let resolveBootstrap: (value: AuthBootstrap) => void = () => {};
    vi.mocked(fetchAuthBootstrap).mockReturnValue(new Promise((resolve) => (resolveBootstrap = resolve)));

    renderGate();

    expect(screen.queryByText(PROTECTED_TEXT)).not.toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();

    // Cleanup: resolve so the pending promise doesn't leak into other tests.
    resolveBootstrap({ status: "authenticated", user: null, memberships: [membership("t1")], selectedTenantId: "t1" });
  });

  it("unauthenticated on a protected route: protected content never renders, redirects to /login", async () => {
    vi.mocked(fetchAuthBootstrap).mockResolvedValue({
      status: "unauthenticated",
      user: null,
      memberships: [],
      selectedTenantId: null,
    });

    renderGate();

    await waitFor(() => expect(mockReplace).toHaveBeenCalled());

    expect(screen.queryByText(PROTECTED_TEXT)).not.toBeInTheDocument();
    expect(mockReplace).toHaveBeenCalledWith(expect.stringMatching(/^\/login\?returnTo=/));
  });

  it("multiple memberships with no selection: protected content never renders, redirects to /select-tenant", async () => {
    vi.mocked(fetchAuthBootstrap).mockResolvedValue({
      status: "authenticated",
      user: { id: "u1", email: "a@example.com", displayName: "A" },
      memberships: [membership("t1"), membership("t2")],
      selectedTenantId: null,
    });

    renderGate();

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/select-tenant"));

    expect(screen.queryByText(PROTECTED_TEXT)).not.toBeInTheDocument();
  });

  it("zero memberships: protected content never renders, redirects to /access-denied", async () => {
    vi.mocked(fetchAuthBootstrap).mockResolvedValue({
      status: "authenticated",
      user: { id: "u1", email: "a@example.com", displayName: "A" },
      memberships: [],
      selectedTenantId: null,
    });

    renderGate();

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/access-denied"));

    expect(screen.queryByText(PROTECTED_TEXT)).not.toBeInTheDocument();
  });

  it("not_provisioned: protected content never renders, redirects to /access-denied", async () => {
    vi.mocked(fetchAuthBootstrap).mockResolvedValue({
      status: "not_provisioned",
      user: null,
      memberships: [],
      selectedTenantId: null,
    });

    renderGate();

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/access-denied"));

    expect(screen.queryByText(PROTECTED_TEXT)).not.toBeInTheDocument();
  });

  it("bootstrap error: shows an error state, never protected content, never redirects", async () => {
    vi.mocked(fetchAuthBootstrap).mockResolvedValue({
      status: "error",
      user: null,
      memberships: [],
      selectedTenantId: null,
    });

    renderGate();

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    expect(screen.queryByText(PROTECTED_TEXT)).not.toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("ready (authenticated + selected tenant): protected content renders, no redirect", async () => {
    vi.mocked(fetchAuthBootstrap).mockResolvedValue({
      status: "authenticated",
      user: { id: "u1", email: "a@example.com", displayName: "A" },
      memberships: [membership("t1")],
      selectedTenantId: "t1",
    });

    renderGate();

    await waitFor(() => expect(screen.getByText(PROTECTED_TEXT)).toBeInTheDocument());
    expect(mockReplace).not.toHaveBeenCalled();
  });
});
