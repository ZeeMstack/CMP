import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "tenant-abc" }),
}));

import { withQueryClient } from "@/lib/test-utils";
import PlatformTenantDetailPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PlatformTenantDetailPage", () => {
  it("renders code/name/status metadata once loaded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ id: "tenant-abc", code: "ACME", name: "Acme Farms", status: "active" })),
    );
    render(withQueryClient(<PlatformTenantDetailPage />));

    await waitFor(() => expect(screen.getAllByText("Acme Farms").length).toBeGreaterThan(0));
    expect(screen.getAllByText("ACME").length).toBeGreaterThan(0);
    expect(screen.getByText("active")).toBeInTheDocument();
  });

  it("never fabricates farm count, admin, or other operational stats -- only Code/Name/Status render", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ id: "tenant-abc", code: "ACME", name: "Acme Farms", status: "active" })),
    );
    const { container } = render(withQueryClient(<PlatformTenantDetailPage />));

    await waitFor(() => expect(screen.getAllByText("Acme Farms").length).toBeGreaterThan(0));
    const fieldLabels = Array.from(container.querySelectorAll("dt")).map((el) => el.textContent);
    expect(fieldLabels).toEqual(["Code", "Name", "Status"]);
  });

  it("shows a not-found state for an unknown Tenant (404)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "Tenant not found" }, 404)));
    render(withQueryClient(<PlatformTenantDetailPage />));

    await waitFor(() => expect(screen.getByText("Not found")).toBeInTheDocument());
    expect(screen.getByText("Tenant not found")).toBeInTheDocument();
  });

  it("shows a platform-access-denied state on 403", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "Platform administrator authority required" }, 403)),
    );
    render(withQueryClient(<PlatformTenantDetailPage />));

    await waitFor(() => expect(screen.getByText("Access denied")).toBeInTheDocument());
    expect(screen.getByText("You do not have platform administrator access.")).toBeInTheDocument();
  });
});
