import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";
import PlatformTenantsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PlatformTenantsPage", () => {
  it("shows a loading state before the list resolves", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})), // never resolves
    );
    render(withQueryClient(<PlatformTenantsPage />));
    expect(screen.getByRole("status", { name: "Loading tenants" })).toBeInTheDocument();
  });

  it("renders the Tenant list with code/name/status once loaded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse([
          { id: "t1", code: "ACME", name: "Acme Farms", status: "active" },
          { id: "t2", code: "GLOBEX", name: "Globex Farms", status: "suspended" },
        ]),
      ),
    );
    render(withQueryClient(<PlatformTenantsPage />));

    await waitFor(() => expect(screen.getByText("ACME")).toBeInTheDocument());
    expect(screen.getByText("Acme Farms")).toBeInTheDocument();
    expect(screen.getByText("GLOBEX")).toBeInTheDocument();
    expect(screen.getByText("Globex Farms")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "View Tenant" })).toHaveLength(2);
  });

  it("shows an empty state with a Create Tenant action when there are no tenants", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<PlatformTenantsPage />));

    await waitFor(() => expect(screen.getByText("No tenants yet")).toBeInTheDocument());
    const createLinks = screen.getAllByRole("link", { name: "Create Tenant" });
    expect(createLinks.length).toBeGreaterThan(0);
    for (const link of createLinks) expect(link).toHaveAttribute("href", "/admin/tenants/new");
  });

  it("shows a platform-access-denied state, not a generic error, on 403", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "Platform administrator authority required" }, 403)),
    );
    render(withQueryClient(<PlatformTenantsPage />));

    await waitFor(() => expect(screen.getByText("Access denied")).toBeInTheDocument());
    expect(screen.getByText("You do not have platform administrator access.")).toBeInTheDocument();
    expect(screen.queryByText("No tenants yet")).not.toBeInTheDocument();
  });

  it("shows the generic error state (not the platform-access-denied copy) for a non-403 failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "boom" }, 500)));
    render(withQueryClient(<PlatformTenantsPage />));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText("You do not have platform administrator access.")).not.toBeInTheDocument();
  });

  it("links each row's View Tenant action to /admin/tenants/{id}", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse([{ id: "tenant-abc", code: "ACME", name: "Acme Farms", status: "active" }])),
    );
    render(withQueryClient(<PlatformTenantsPage />));

    await waitFor(() => expect(screen.getByRole("link", { name: "View Tenant" })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "View Tenant" })).toHaveAttribute("href", "/admin/tenants/tenant-abc");
  });
});
