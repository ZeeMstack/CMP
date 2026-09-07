import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
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

function stubFetch(overrides: Record<string, unknown> = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/farms/farm-1/goods-receipts")) return jsonResponse(overrides.receipts ?? [RECEIPT]);
    if (url.endsWith("/quality-work-queue")) return jsonResponse(overrides.queue ?? [QUEUE_ROW]);
    if (url.endsWith("/farms/farm-1")) return jsonResponse(FARM);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StoreInventoryOverviewPage", () => {
  it("shows a factual summary -- recent receipts and quantities awaiting Quality action", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText("GR-F1-20260907-001")).toBeInTheDocument());
    expect(screen.getByText(/awaiting a/i)).toBeInTheDocument();
  });

  it("never invents a readiness score or custody claim", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText("GR-F1-20260907-001")).toBeInTheDocument());
    expect(screen.queryByText(/ready/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/current location/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/current store/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/available/i)).not.toBeInTheDocument();
  });

  it("shows nothing-awaiting message when the queue is empty", async () => {
    stubFetch({ queue: [] });
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText(/nothing is currently quarantined/i)).toBeInTheDocument());
  });
});
