import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import StoreInventorySetupOverviewPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const FARM = { id: "farm-1", tenant_id: "t", code: "IMPERIAL", name: "Imperial Farms", status: "active" };

const STORE_TREE = [
  {
    id: "store-1", code: "MAIN-STORE", name: "Main Store", location_type_id: "type-store", location_type_code: "store",
    status: "active", occupiable: false, capacity: null,
    children: [
      {
        id: "area-1", code: "AREA-1", name: "Area 1", location_type_id: "type-area", location_type_code: "store_area",
        status: "active", occupiable: false, capacity: null,
        children: [
          {
            id: "bin-1", code: "BIN-1", name: "Bin 1", location_type_id: "type-bin", location_type_code: "store_bin",
            status: "active", occupiable: true, capacity: null, children: [],
          },
        ],
      },
    ],
  },
];

const CATEGORY = { id: "cat-1", tenant_id: "t", code: "SEED", name: "Seed", status: "active", created_at: "2026-09-01T00:00:00Z" };
const ITEM = {
  id: "item-1", tenant_id: "t", code: "MAMUTIK-SEED", name: "Mamutik Seed", inventory_category_id: "cat-1",
  base_uom_id: "uom-1", lot_tracking_required: false, expiry_tracking_required: false, qc_release_required: false,
  status: "active", created_at: "2026-09-01T00:00:00Z",
};
const UOMS = [{ id: "uom-1", code: "kg", name: "Kilogram", quantity_kind: "mass", conversion_family: "MASS" }];

function stubFetch(overrides: { tree?: unknown[]; categories?: unknown[]; items?: unknown[] } = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/locations/tree")) return jsonResponse(overrides.tree ?? STORE_TREE);
    if (url.endsWith("/inventory-categories")) return jsonResponse(overrides.categories ?? [CATEGORY]);
    if (url.endsWith("/inventory-items")) return jsonResponse(overrides.items ?? [ITEM]);
    if (url.endsWith("/uoms")) return jsonResponse(UOMS);
    if (url.endsWith("/farms/farm-1")) return jsonResponse(FARM);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StoreInventorySetupOverviewPage (Setup Summary)", () => {
  it("shows factual configured counts, never a readiness score", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventorySetupOverviewPage />));
    await waitFor(() => expect(screen.getByText(/1 active Store/)).toBeInTheDocument());
    expect(screen.getByText(/1 Area/)).toBeInTheDocument();
    expect(screen.getByText(/1 Bin/)).toBeInTheDocument();
    expect(screen.getByText("Manage storage")).toBeInTheDocument();
    expect(screen.queryByText(/ready/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("uses correct Farm/Tenant scope labels", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventorySetupOverviewPage />));
    await waitFor(() => expect(screen.getByText("For Imperial Farms")).toBeInTheDocument());
    expect(screen.getByText("Shared across Test Tenant")).toBeInTheDocument();
  });

  it("prompts to create the first Store when none is active", async () => {
    stubFetch({ tree: [] });
    render(withQueryClient(<StoreInventorySetupOverviewPage />));
    await waitFor(() => expect(screen.getByText("No active Store configured")).toBeInTheDocument());
    expect(screen.getByText("Create first Store")).toBeInTheDocument();
  });

  it("prompts to create the first Category when none is active", async () => {
    stubFetch({ categories: [] });
    render(withQueryClient(<StoreInventorySetupOverviewPage />));
    await waitFor(() => expect(screen.getByText("No active Categories")).toBeInTheDocument());
    expect(screen.getByText("Create first Category")).toBeInTheDocument();
  });

  it("prompts to add the first Item when Categories exist but no Items do", async () => {
    stubFetch({ items: [] });
    render(withQueryClient(<StoreInventorySetupOverviewPage />));
    await waitFor(() => expect(screen.getByText("0 Inventory Items")).toBeInTheDocument());
    expect(screen.getByText("Add first Inventory Item")).toBeInTheDocument();
  });
});
