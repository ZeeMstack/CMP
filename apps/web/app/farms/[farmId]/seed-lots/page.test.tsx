import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import SeedLotsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SeedLotsPage", () => {
  it("shows an empty state with a primary 'Add Seed Lot' action when no Seed Lots are registered", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<SeedLotsPage />));

    await waitFor(() => expect(screen.getByText("No Seed Lots registered yet.")).toBeInTheDocument());
    const addLinks = screen.getAllByRole("link", { name: /add seed lot/i });
    expect(addLinks.length).toBeGreaterThan(0);
    expect(addLinks[0]).toHaveAttribute("href", "/farms/farm-1/seed-lots/new");
    // Language makes clear this is traceability, not stock-on-hand.
    expect(screen.getByText(/traceability source, not seed stock on hand/i)).toBeInTheDocument();
    expect(screen.queryByText(/quantity remaining|stock-on-hand|purchase cost/i)).not.toBeInTheDocument();
  });

  it("renders one card per registered Seed Lot from real data, never fabricated", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse([
          {
            id: "lot-1", tenant_id: "t", farm_id: "f", code: "RZ-MAM-2026-001",
            crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
            variety: { id: "var-1", code: "MAM", name: "Mamutik" },
            supplier_name: null, supplier_lot_reference: null, received_date: null, expiry_date: null,
            status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
          },
        ]),
      ),
    );
    render(withQueryClient(<SeedLotsPage />));

    await waitFor(() => expect(screen.getByText("RZ-MAM-2026-001")).toBeInTheDocument());
    expect(screen.getByText(/iceberg lettuce/i)).toBeInTheDocument();
  });

  it("links to Seeding so hiding Seed Lots from the primary nav does not make it unreachable from there", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(withQueryClient(<SeedLotsPage />));

    await waitFor(() => expect(screen.getByText("No Seed Lots registered yet.")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Go to Seeding" })).toHaveAttribute(
      "href",
      "/farms/farm-1/nursery/sowings/new",
    );
  });
});

const TWO_LOTS = [
  {
    id: "lot-1", tenant_id: "t", farm_id: "f", code: "RZ-MAM-2026-001",
    crop: { id: "crop-1", code: "ICE", common_name: "Iceberg Lettuce" },
    variety: { id: "var-1", code: "MAM", name: "Mamutik" },
    supplier_name: "Rijk Zwaan", supplier_lot_reference: null, received_date: null, expiry_date: null,
    status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "lot-2", tenant_id: "t", farm_id: "f", code: "BJ-TOM-2026-002",
    crop: { id: "crop-2", code: "TOM", common_name: "Tomato" },
    variety: { id: "var-2", code: "MON", name: "Money Maker" },
    supplier_name: "Bejo", supplier_lot_reference: null, received_date: null, expiry_date: null,
    status: "active", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  },
];

describe("SeedLotsPage: compact register search and inspector", () => {
  function stubTwoLots() {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/seed-lots/") && url.includes("/crop-batches")) return jsonResponse([]);
      return jsonResponse(TWO_LOTS);
    }));
  }

  it("filters the register by search text across code/crop/variety/supplier", async () => {
    stubTwoLots();
    render(withQueryClient(<SeedLotsPage />));
    await waitFor(() => expect(screen.getByText("RZ-MAM-2026-001")).toBeInTheDocument());
    expect(screen.getByText("BJ-TOM-2026-002")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "tomato" } });
    await waitFor(() => expect(screen.queryByText("RZ-MAM-2026-001")).not.toBeInTheDocument());
    expect(screen.getByText("BJ-TOM-2026-002")).toBeInTheDocument();
  });

  it("selecting a row opens the inspector with a link to the full detail page", async () => {
    stubTwoLots();
    render(withQueryClient(<SeedLotsPage />));
    await waitFor(() => expect(screen.getByText("RZ-MAM-2026-001")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /RZ-MAM-2026-001/ }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Open full detail" })).toHaveAttribute(
      "href",
      "/farms/farm-1/seed-lots/lot-1",
    ));
  });
});
