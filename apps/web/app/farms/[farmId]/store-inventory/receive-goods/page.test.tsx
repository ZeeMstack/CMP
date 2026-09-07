import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import ReceiveGoodsPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const FARM = { id: "farm-1", tenant_id: "t", code: "F1", name: "Main Farm", country_code: "AE", city_region: null, timezone: "Asia/Dubai", status: "active" };
const DIRECT_ITEM = {
  id: "item-direct", tenant_id: "t", code: "HAIRNETS", name: "Hairnets", inventory_category_id: "cat-1",
  base_uom_id: "uom-ea", lot_tracking_required: false, expiry_tracking_required: false, qc_release_required: false,
  status: "active", created_at: "2026-09-01T00:00:00Z",
};
const LOT_ITEM = {
  id: "item-lot", tenant_id: "t", code: "CALCIUM-NITRATE", name: "Calcium Nitrate", inventory_category_id: "cat-1",
  base_uom_id: "uom-kg", lot_tracking_required: true, expiry_tracking_required: true, qc_release_required: true,
  status: "active", created_at: "2026-09-01T00:00:00Z",
};
const UOMS = [
  { id: "uom-ea", code: "EA", name: "Each", quantity_kind: "count", conversion_family: null },
  { id: "uom-kg", code: "kg", name: "Kilogram", quantity_kind: "mass", conversion_family: "MASS" },
];
const PACKAGING = [
  { id: "pkg-1", tenant_id: "t", inventory_item_id: "item-lot", code: "BAG-25KG", display_name: "25kg Bag", package_quantity: "25.000", status: "active", created_at: "2026-09-01T00:00:00Z" },
];

function stubFetch(postHandler?: (url: string, body: unknown) => Response) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      const body = init.body ? JSON.parse(String(init.body)) : {};
      if (postHandler) return postHandler(url, body);
      return jsonResponse({});
    }
    if (url.includes("/inventory-items")) return jsonResponse([DIRECT_ITEM, LOT_ITEM]);
    if (url.endsWith("/uoms")) return jsonResponse(UOMS);
    if (url.includes("/inventory-item-packaging")) return jsonResponse(PACKAGING);
    if (url.includes("/seed-profile")) return jsonResponse(null);
    if (url.endsWith("/farms/farm-1")) return jsonResponse(FARM);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ReceiveGoodsPage", () => {
  it("renders a single starting line with no server Draft call on mount", async () => {
    stubFetch();
    render(withQueryClient(<ReceiveGoodsPage />));
    await waitFor(() => expect(screen.getByText("Line 1")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Record Receipt" })).toBeInTheDocument();
    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    expect(fetchMock.mock.calls.some((call: unknown[]) => (call[1] as RequestInit | undefined)?.method === "POST")).toBe(false);
  });

  it("blocks submission and shows an error when no item is selected on the only line", async () => {
    stubFetch();
    render(withQueryClient(<ReceiveGoodsPage />));
    await waitFor(() => expect(screen.getByText("Line 1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Record Receipt" }));
    expect(await screen.findByText("Select an item")).toBeInTheDocument();
  });

  it("supports the direct-quantity entry path and submits successfully", async () => {
    let posted: unknown = null;
    stubFetch((url, body) => {
      if (url.endsWith("/goods-receipts")) {
        posted = body;
        return jsonResponse({
          id: "gr-1", tenant_id: "t", farm_id: "farm-1", code: "GR-F1-20260907-001",
          received_at: "2026-09-07T08:00:00Z", recorded_at: "2026-09-07T08:00:00Z", received_by_user_id: "u1",
          supplier_name: null, external_system: null, external_document_id: null, notes: null,
        });
      }
      return jsonResponse({});
    });
    render(withQueryClient(<ReceiveGoodsPage />));
    await waitFor(() => expect(screen.getByText("Line 1")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Hairnets")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Inventory Item"), { target: { value: "item-direct" } });
    await waitFor(() => expect(screen.getByLabelText("Quantity")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("Unit"), { target: { value: "uom-ea" } });

    fireEvent.click(screen.getByRole("button", { name: "Record Receipt" }));

    await waitFor(() => expect(screen.getByText("Receipt recorded")).toBeInTheDocument());
    expect(posted).not.toBeNull();
    const line = (posted as { lines: Record<string, unknown>[] }).lines[0];
    expect(line.inventory_item_id).toBe("item-direct");
    expect(line.entered_quantity).toBe(100);
    expect(line.entered_uom_id).toBe("uom-ea");
    expect(line.packaging_id).toBeNull();
  });

  it("shows manufacturer/lot/expiry fields only for a lot-tracked item, and a packaging normalized preview", async () => {
    stubFetch();
    render(withQueryClient(<ReceiveGoodsPage />));
    await waitFor(() => expect(screen.getByText("Line 1")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Inventory Item"), { target: { value: "item-lot" } });
    await waitFor(() => expect(screen.getByLabelText("Manufacturer")).toBeInTheDocument());
    expect(screen.getByLabelText(/Expiry Date \(required\)/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Packaging"));
    fireEvent.change(screen.getByLabelText("Packaging Option"), { target: { value: "pkg-1" } });
    fireEvent.change(screen.getByLabelText("Number of packages"), { target: { value: "4" } });

    await waitFor(() => expect(screen.getByText(/Normalized quantity: 100.000 kg/)).toBeInTheDocument());
  });

  it("does not show manufacturer/lot fields for a non-lot-tracked item", async () => {
    stubFetch();
    render(withQueryClient(<ReceiveGoodsPage />));
    await waitFor(() => expect(screen.getByText("Line 1")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Hairnets")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Inventory Item"), { target: { value: "item-direct" } });
    await waitFor(() => expect(screen.getByLabelText("Quantity")).toBeInTheDocument());
    expect(screen.queryByLabelText("Manufacturer")).not.toBeInTheDocument();
  });
});
