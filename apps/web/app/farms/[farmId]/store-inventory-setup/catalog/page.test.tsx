import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import CatalogWorkspacePage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CATEGORY = { id: "cat-1", tenant_id: "t", code: "SEED", name: "Seed", status: "active", created_at: "2026-09-01T00:00:00Z" };
const ITEM = {
  id: "item-1", tenant_id: "t", code: "MAMUTIK-SEED", name: "Mamutik Seed", inventory_category_id: "cat-1",
  base_uom_id: "uom-1", lot_tracking_required: false, expiry_tracking_required: false, qc_release_required: false,
  status: "active", created_at: "2026-09-01T00:00:00Z",
};
const UOM = { id: "uom-1", code: "kg", name: "Kilogram", quantity_kind: "mass", conversion_family: "MASS" };

function stubFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/inventory-categories")) return jsonResponse([CATEGORY]);
    if (url.endsWith("/uoms")) return jsonResponse([UOM]);
    if (url.endsWith("/inventory-items")) return jsonResponse([ITEM]);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CatalogWorkspacePage", () => {
  it("renders the tenant-wide catalog with a Shared-across scope label, unfiltered by farm", async () => {
    stubFetch();
    render(withQueryClient(<CatalogWorkspacePage />));
    await waitFor(() => expect(screen.getByText("MAMUTIK-SEED")).toBeInTheDocument());
    expect(screen.getByText("Shared across Test Tenant")).toBeInTheDocument();
  });
});
