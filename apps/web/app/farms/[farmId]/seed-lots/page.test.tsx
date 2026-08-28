import { render, screen, waitFor } from "@testing-library/react";
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
