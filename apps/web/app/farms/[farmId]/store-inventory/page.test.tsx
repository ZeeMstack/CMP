import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  usePathname: () => "/farms/farm-1/store-inventory",
}));

import { AuthBootstrapProvider } from "@/lib/auth/AuthBootstrapProvider";
import { queryKeys } from "@/lib/query/keys";
import { DEFAULT_TEST_BOOTSTRAP, TEST_TENANT_ID, withQueryClient } from "@/lib/test-utils";

import StoreInventoryOverviewPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Like `withQueryClient`, but also hands back the `QueryClient` so a test
 * can force a refetch against a mock that starts returning errors, to model
 * a stale-cache-plus-failed-refresh scenario without a second render. */
function renderWithClient(children: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(queryKeys.authBootstrap(), DEFAULT_TEST_BOOTSTRAP);
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <AuthBootstrapProvider>{children}</AuthBootstrapProvider>
    </QueryClientProvider>,
  );
  return { ...utils, queryClient };
}

const FARM = { id: "farm-1", tenant_id: "t", code: "F1", name: "Main Farm", country_code: "AE", city_region: null, timezone: "Asia/Dubai", status: "active" };
const FARM_2 = { id: "farm-2", tenant_id: "t", code: "F2", name: "Second Farm", country_code: "AE", city_region: null, timezone: "Asia/Dubai", status: "active" };
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
    if (url.endsWith("/farms")) return jsonResponse(overrides.farms ?? [FARM, FARM_2]);
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
      "href", "/farms/farm-1/store-inventory/quality?cohortId=coh-1",
    );

    expect(screen.getByText("Putaway")).toBeInTheDocument();
    expect(screen.getByText("Awaiting putaway")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Put away" })).toHaveAttribute(
      "href", "/farms/farm-1/store-inventory/putaway?cohortId=coh-2",
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

  // --- PILOT-BLOCKER-009 R1 -------------------------------------------------

  it("R1.1: Quality fails and Putaway fails (no cache) -- both failures are visible/retryable, never a clean empty state", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/quality-work-queue")) return jsonResponse({ detail: "boom" }, 500);
      if (url.includes("/inventory-not-put-away-queue")) return jsonResponse({ detail: "boom" }, 500);
      if (url.endsWith("/farms/farm-1")) return jsonResponse(FARM);
      return jsonResponse([]);
    }));
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText(/could not load the quality queue/i)).toBeInTheDocument());
    expect(screen.getByText(/could not load the putaway queue/i)).toBeInTheDocument();
    expect(screen.queryByText(/nothing currently needs quality or putaway action/i)).not.toBeInTheDocument();
    // Both are retryable.
    expect(screen.getAllByRole("button", { name: "Retry" }).length).toBeGreaterThanOrEqual(2);
  });

  it("R1.2: Quality succeeds with work and Putaway fails -- Quality rows stay visible, Putaway error is visible, no global safe-empty state", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/quality-work-queue")) return jsonResponse([QUEUE_ROW]);
      if (url.includes("/inventory-not-put-away-queue")) return jsonResponse({ detail: "boom" }, 500);
      if (url.endsWith("/farms/farm-1")) return jsonResponse(FARM);
      return jsonResponse([]);
    }));
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate — Lot LOT-1")).toBeInTheDocument());
    expect(screen.getByText(/could not load the putaway queue/i)).toBeInTheDocument();
    expect(screen.queryByText(/nothing currently needs quality or putaway action/i)).not.toBeInTheDocument();
  });

  it("R1.3: both Quality and Putaway succeed and are genuinely empty -- the clean empty state is allowed", async () => {
    stubFetch({ queue: [], notPutAway: [] });
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() =>
      expect(screen.getByText(/nothing currently needs quality or putaway action/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/could not load/i)).not.toBeInTheDocument();
  });

  it("R1.4: a Recent Receipts read failure shows error/retry, never 'no receipts'", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/farms/farm-1/goods-receipts")) return jsonResponse({ detail: "boom" }, 500);
      if (url.endsWith("/quality-work-queue")) return jsonResponse([]);
      if (url.includes("/inventory-not-put-away-queue")) return jsonResponse([]);
      if (url.endsWith("/farms/farm-1")) return jsonResponse(FARM);
      return jsonResponse([]);
    }));
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText(/could not load recent receipts/i)).toBeInTheDocument());
    expect(screen.queryByText(/no receipts recorded/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("R1.5: cached Quality rows stay visible with a stale indicator when a refresh fails", async () => {
    let queueCallCount = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/quality-work-queue")) {
        queueCallCount += 1;
        if (queueCallCount === 1) return jsonResponse([QUEUE_ROW]);
        return jsonResponse({ detail: "boom" }, 500);
      }
      if (url.includes("/inventory-not-put-away-queue")) return jsonResponse([]);
      if (url.endsWith("/farms/farm-1")) return jsonResponse(FARM);
      return jsonResponse([]);
    }));
    const { queryClient } = renderWithClient(<StoreInventoryOverviewPage />);
    await waitFor(() => expect(screen.getByText("Calcium Nitrate — Lot LOT-1")).toBeInTheDocument());

    await queryClient.refetchQueries({ queryKey: queryKeys.qualityWorkQueue(TEST_TENANT_ID) });

    await waitFor(() => expect(screen.getByText(/could not refresh the quality queue/i)).toBeInTheDocument());
    expect(screen.getByText("Calcium Nitrate — Lot LOT-1")).toBeInTheDocument();
    expect(screen.queryByText(/nothing currently needs quality or putaway action/i)).not.toBeInTheDocument();
  });

  // --- PILOT-BLOCKER-009 R2 -------------------------------------------------

  it("R2.6: Manage Quality remains visible when Action Required has zero Quality rows", async () => {
    stubFetch({ queue: [] });
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText("Store Operations")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Manage Quality" })).toHaveAttribute(
      "href", "/farms/farm-1/store-inventory/quality",
    );
  });

  it("R2.7: a Quality row action carries its stable cohort identifier", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByRole("link", { name: "Review" })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute(
      "href", expect.stringContaining("cohortId=coh-1"),
    );
  });

  // --- PILOT-BLOCKER-009 R6 -------------------------------------------------

  it("R6.12: a row received at a different Farm than the one being viewed routes to its OWN Farm, never the currently-viewed one, and shows that Farm's name", async () => {
    stubFetch({
      queue: [{ ...QUEUE_ROW, received_at_farm_id: "farm-2" }],
      notPutAway: [],
    });
    render(withQueryClient(<StoreInventoryOverviewPage />));
    await waitFor(() => expect(screen.getByText("Second Farm")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute(
      "href", "/farms/farm-2/store-inventory/quality?cohortId=coh-1",
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
