import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import StoreInventoryInventoryPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const ITEM = {
  id: "item-1", tenant_id: "t", code: "CALCIUM-NITRATE", name: "Calcium Nitrate", inventory_category_id: "cat-1",
  base_uom_id: "uom-1", lot_tracking_required: true, expiry_tracking_required: false, qc_release_required: true,
  status: "active", created_at: "2026-09-01T00:00:00Z",
};

function stubFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/inventory-items?") || url.endsWith("/inventory-items")) return jsonResponse([ITEM]);
    if (url.endsWith("/existence")) return jsonResponse({ inventory_item_id: "item-1", existing_quantity: "500.000" });
    if (url.endsWith("/usable-existence")) return jsonResponse({ inventory_item_id: "item-1", usable_quantity: "450.000" });
    if (url.endsWith("/provenance")) return jsonResponse([]);
    if (url.includes("/storage-breakdown")) {
      return jsonResponse({ inventory_item_id: "item-1", not_put_away_quantity: "120.000", bins: [] });
    }
    if (url.includes("/locations/tree")) return jsonResponse([]);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StoreInventoryInventoryPage", () => {
  it("shows Exists, Usable, and Not put away quantities, company-wide, never labeled Available", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryInventoryPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.getByText("500.000")).toBeInTheDocument();
    expect(screen.getByText("450.000")).toBeInTheDocument();
    expect(screen.getAllByText(/usable/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/^available$/i)).not.toBeInTheDocument();
    expect(screen.getByText("Not put away")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("120.000")).toBeInTheDocument());
  });
});
