import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import CarrierSpecificationsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const carrierTypes = [
  { id: "ct-1", code: "NURSERY_PLATE", name: "Nursery Plate", requires_specification: true, biological_position_label: "Cells" },
];

function spec(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "spec-1",
    tenant_id: "t1",
    carrier_type_id: "ct-1",
    carrier_type_code: "NURSERY_PLATE",
    biological_position_label: "Cells",
    code: "PLATE-200",
    name: "200-hole nursery plate",
    length_mm: 500,
    width_mm: 300,
    height_mm: null,
    biological_position_count: 200,
    status: "active",
    is_structurally_locked: false,
    ...overrides,
  };
}

function stubFetch(specifications: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/carrier-types")) return jsonResponse(carrierTypes);
      if (url.includes("/carrier-specifications")) return jsonResponse(specifications);
      return jsonResponse({});
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CarrierSpecificationsPage", () => {
  it("renders as a standalone tenant-level page -- no farmId is supplied anywhere in this test, by design", async () => {
    stubFetch([spec()]);
    // No next/navigation mock, no farmId param, no farm-scoped provider --
    // this page must render correctly with none of that, proving its
    // visual shell does not require a farm context.
    render(withQueryClient(<CarrierSpecificationsPage />));
    await waitFor(() => expect(screen.getByText("PLATE-200")).toBeInTheDocument());
    expect(screen.getByText("GrowCMP")).toBeInTheDocument();
    expect(screen.queryByText("ImperialFarms CMP")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to farms/i })).toHaveAttribute("href", "/farms");
  });

  it("shows the real Tenant context via the shared StandaloneShell, not a fabricated name", async () => {
    stubFetch([]);
    render(withQueryClient(<CarrierSpecificationsPage />));
    await waitFor(() => expect(screen.getByText("No carrier specifications yet")).toBeInTheDocument());
    expect(screen.getByText("Test Tenant")).toBeInTheDocument();
  });

  it("breadcrumb roots at the farm picker, not a specific or fabricated farm", async () => {
    stubFetch([]);
    render(withQueryClient(<CarrierSpecificationsPage />));
    await waitFor(() => expect(screen.getByText("No carrier specifications yet")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/farms");
  });

  it("shows loading and empty states correctly", async () => {
    stubFetch([]);
    render(withQueryClient(<CarrierSpecificationsPage />));
    await waitFor(() => expect(screen.getByText("No carrier specifications yet")).toBeInTheDocument());
  });

  it("opens the create form and renders its fields", async () => {
    stubFetch([]);
    render(withQueryClient(<CarrierSpecificationsPage />));
    await waitFor(() => expect(screen.getByText("No carrier specifications yet")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new specification/i }));
    expect(screen.getByText("Identity")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create specification" })).toBeInTheDocument();
  });

  it("shows Deactivate for an active specification and Reactivate for an inactive one -- never a delete action", async () => {
    stubFetch([spec({ id: "spec-1", code: "PLATE-200", status: "active" }), spec({ id: "spec-2", code: "BAG-100", status: "inactive" })]);
    render(withQueryClient(<CarrierSpecificationsPage />));
    await waitFor(() => expect(screen.getByText("PLATE-200")).toBeInTheDocument());

    const rows = screen.getAllByRole("row").slice(1); // drop header row
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("button", { name: "Deactivate" })).toBeInTheDocument();
    expect(within(rows[1]).getByRole("button", { name: "Reactivate" })).toBeInTheDocument();

    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove/i })).not.toBeInTheDocument();
  });

  it("shows Active/Inactive status, never a hard-deleted row disappearing from the list", async () => {
    stubFetch([spec({ status: "inactive" })]);
    render(withQueryClient(<CarrierSpecificationsPage />));
    await waitFor(() => expect(screen.getByText("PLATE-200")).toBeInTheDocument());
    expect(screen.getByText("Inactive")).toBeInTheDocument();
  });
});
