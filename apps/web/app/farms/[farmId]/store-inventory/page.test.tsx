import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  usePathname: () => "/farms/farm-1/store-inventory",
}));

import { withQueryClient } from "@/lib/test-utils";

import StoreInventoryOverviewPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const FARM = { id: "farm-1", tenant_id: "t", code: "F1", name: "Main Farm", country_code: "AE", city_region: null, timezone: "Asia/Dubai", status: "active" };
const RECEIPT = {
  id: "gr-1", tenant_id: "t", farm_id: "farm-1", code: "GR-F1-20260907-001", received_at: "2026-09-07T08:00:00Z",
  recorded_at: "2026-09-07T08:00:00Z", received_by_user_id: "u1", supplier_name: null, external_system: null,
  external_document_id: null, notes: null,
};
const QUEUE_ROW = {
  inventory_quantity_cohort_id: "coh-1", inventory_item_id: "item-1", item_name: "Calcium Nitrate",
  base_uom_id: "uom-1", inventory_lot_id: "lot-1", manufacturer_lot_reference: "LOT-1", expiry_date: null,
  received_at_farm_id: "farm-1", source_goods_receipt_line_id: "line-1", receipt_code: "GR-F1-20260907-001",
  receipt_received_at: "2026-09-07T08:00:00Z", balance: "500.000", current_state: "RECEIVED_QUARANTINED",
  last_actor_user_id: null, last_effective_time: null,
};
const NOT_PUT_AWAY_ROW = {
  inventory_quantity_cohort_id: "coh-2", inventory_item_id: "item-2", item_name: "Perlite",
  base_uom_id: "uom-1", inventory_lot_id: null, manufacturer_lot_reference: null,
  received_at_farm_id: "farm-1", receipt_code: "GR-F1-20260906-002", receipt_received_at: "2026-09-06T08:00:00Z",
  not_put_away_quantity: "12.000",
};

function stubFetch(overrides: Record<string, unknown> = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/farms/farm-1/goods-receipts")) return jsonResponse(overrides.receipts ?? [RECEIPT]);
    if (url.endsWith("/quality-work-queue")) return jsonResponse(overrides.queue ?? [QUEUE_ROW]);
    if (url.includes("/inventory-not-put-away-queue")) return jsonResponse(overrides.notPutAway ?? [NOT_PUT_AWAY_ROW]);
    if (url.endsWith("/farms/farm-1")) return jsonResponse(FARM);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StoreInventoryOverviewPage (PILOT-UX-005 Store Operations workbench)", () => {
  it("shows a unified Action Required queue with both Quality and Putaway rows, plus recent receipts", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate — Lot LOT-1")).toBeInTheDocument());

    expect(screen.getByText("Quality")).toBeInTheDocument();
    expect(screen.getByText("Quarantined")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute(
      "href", "/farms/farm-1/store-inventory/quality",
    );

    expect(screen.getByText("Putaway")).toBeInTheDocument();
    expect(screen.getByText("Awaiting putaway")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Put away" })).toHaveAttribute(
      "href", "/farms/farm-1/store-inventory/putaway",
    );

    // Recent Goods Receipts is a secondary, compact list, not a large card.
    expect(screen.getAllByText("GR-F1-20260907-001").length).toBeGreaterThan(0);
  });

  it("never invents a readiness score, current-location, or availability claim", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText("Quality")).toBeInTheDocument());
    expect(screen.queryByText(/ready/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/current location/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/current store/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/available/i)).not.toBeInTheDocument();
  });

  it("never fabricates a Lot suffix for a row with no manufacturer_lot_reference", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText("Perlite")).toBeInTheDocument());
    expect(screen.queryByText(/Perlite — Lot/)).not.toBeInTheDocument();
  });

  it("shows a nothing-needs-action message only when both queues are empty", async () => {
    stubFetch({ queue: [], notPutAway: [] });
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() =>
      expect(screen.getByText(/nothing currently needs quality or putaway action/i)).toBeInTheDocument(),
    );
  });

  it("shows only the Putaway row when the Quality queue is empty", async () => {
    stubFetch({ queue: [] });
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText("Perlite")).toBeInTheDocument());
    expect(screen.queryByText("Quarantined")).not.toBeInTheDocument();
    expect(screen.queryByText(/nothing currently needs/i)).not.toBeInTheDocument();
  });

  it("shows only the Quality row when the Putaway queue is empty", async () => {
    stubFetch({ notPutAway: [] });
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate — Lot LOT-1")).toBeInTheDocument());
    expect(screen.queryByText("Awaiting putaway")).not.toBeInTheDocument();
    expect(screen.queryByText(/nothing currently needs/i)).not.toBeInTheDocument();
  });

  it("exposes Receive Goods (primary) and Issue Stock (secondary) as header actions, not sidebar destinations", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText("Store Operations")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Receive Goods" })).toHaveAttribute(
      "href", "/farms/farm-1/store-inventory/receive-goods",
    );
    expect(screen.getByRole("link", { name: "Issue Stock" })).toHaveAttribute(
      "href", "/farms/farm-1/store-inventory/issue",
    );
  });

  it("renders the Operations/Inventory StoreSubNav with Operations active, replacing the removed left sidebar", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryOverviewPage />));
    const nav = await screen.findByRole("navigation", { name: "Store & Inventory" });
    expect(within(nav).getByRole("link", { name: "Operations" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Inventory" })).toHaveAttribute(
      "href", "/farms/farm-1/store-inventory/inventory",
    );
  });
});
