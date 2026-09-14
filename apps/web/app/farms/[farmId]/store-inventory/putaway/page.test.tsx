import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

let searchParamsValue = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
  usePathname: () => "/farms/farm-1/store-inventory/putaway",
  useSearchParams: () => searchParamsValue,
}));

import { AuthBootstrapProvider } from "@/lib/auth/AuthBootstrapProvider";
import { queryKeys } from "@/lib/query/keys";
import { DEFAULT_TEST_BOOTSTRAP, TEST_TENANT_ID, withQueryClient } from "@/lib/test-utils";

import StoreInventoryPutawayPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Like `withQueryClient`, but also hands back the `QueryClient` so a test
 * can force a refetch (e.g. to model a queue row disappearing mid-recovery)
 * without a second render. */
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

const QUEUE_ENTRY = {
  inventory_quantity_cohort_id: "cohort-1", inventory_item_id: "item-1", item_name: "Calcium Nitrate",
  base_uom_id: "uom-1", inventory_lot_id: null, manufacturer_lot_reference: "LOT-1",
  received_at_farm_id: "farm-1", receipt_code: "GR-0001", receipt_received_at: "2026-09-01T00:00:00Z",
  not_put_away_quantity: "40.000",
};

const BIN_TREE = [
  {
    id: "store-1", code: "MAIN-STORE", name: "Main Store", location_type_id: "lt-store",
    location_type_code: "store", status: "active", occupiable: false, capacity: null,
    children: [
      {
        id: "bin-1", code: "BIN-01", name: "Bin 01", location_type_id: "lt-bin",
        location_type_code: "store_bin", status: "active", occupiable: false, capacity: null, children: [],
      },
    ],
  },
];

function stubFetch(postHandler?: (url: string, body: unknown) => Response) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      const body = init.body ? JSON.parse(String(init.body)) : {};
      if (postHandler) return postHandler(url, body);
      return jsonResponse({});
    }
    if (url.includes("/inventory-not-put-away-queue")) return jsonResponse([QUEUE_ENTRY]);
    if (url.includes("/locations/tree")) return jsonResponse(BIN_TREE);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
}

afterEach(() => {
  vi.unstubAllGlobals();
  searchParamsValue = new URLSearchParams();
});

describe("StoreInventoryPutawayPage", () => {
  it("lists not-put-away entries and submits a putaway against a chosen Bin", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    stubFetch((url, body) => {
      if (url.includes("/inventory-putaways")) {
        capturedBody = body as Record<string, unknown>;
        return jsonResponse({
          id: "mv-1", tenant_id: "t", farm_id: "farm-1", inventory_quantity_cohort_id: "cohort-1",
          movement_kind: "putaway", source_location_id: null, destination_location_id: "bin-1",
          moved_quantity_base: "10.000", effective_time: "2026-09-01T00:00:00Z",
          recorded_time: "2026-09-01T00:00:00Z", actor_user_id: "u1", client_command_id: "cc-1", note: null,
        }, 201);
      }
      return jsonResponse({});
    });
    render(withQueryClient(<StoreInventoryPutawayPage />));

    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.getByText(/40\.000 not put away/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Put away" }));
    await waitFor(() => expect(screen.getByText("Main Store / Bin 01")).toBeInTheDocument());

    const quantityInput = screen.getByLabelText(/quantity/i);
    fireEvent.change(quantityInput, { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm putaway/i }));

    await waitFor(() => expect(capturedBody).not.toBeNull());
    expect(capturedBody).toMatchObject({
      inventory_quantity_cohort_id: "cohort-1", destination_location_id: "bin-1", quantity: "10",
    });
  });

  it("disables Put away when no active Bins are configured for this Farm", async () => {
    stubFetch();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/inventory-not-put-away-queue")) return jsonResponse([QUEUE_ENTRY]);
      if (url.includes("/locations/tree")) return jsonResponse([]);
      return jsonResponse([]);
    }));
    render(withQueryClient(<StoreInventoryPutawayPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Put away" })).toBeDisabled();
  });

  // --- PILOT-BLOCKER-008 A3/A7 --------------------------------------------

  it("A7: a queue load failure never renders as the successful-empty state", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/inventory-not-put-away-queue")) return jsonResponse({ detail: "boom" }, 500);
      if (url.includes("/locations/tree")) return jsonResponse(BIN_TREE);
      return jsonResponse([]);
    }));
    render(withQueryClient(<StoreInventoryPutawayPage />));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText(/nothing is currently awaiting putaway/i)).not.toBeInTheDocument();
  });

  it("A7: a Bin locations load failure never renders as 'no active Bins configured'", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/inventory-not-put-away-queue")) return jsonResponse([QUEUE_ENTRY]);
      if (url.includes("/locations/tree")) return jsonResponse({ detail: "boom" }, 500);
      return jsonResponse([]);
    }));
    render(withQueryClient(<StoreInventoryPutawayPage />));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText(/no active bins are configured/i)).not.toBeInTheDocument();
  });

  it("PILOT-BLOCKER-010: a network failure on Confirm shows an unresolved-result state via the page-level recovery banner (not 'Putaway failed'), and Retry resends the exact frozen payload", async () => {
    const posts: Array<Record<string, unknown>> = [];
    let callCount = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.includes("/inventory-putaways")) {
        callCount += 1;
        const body = init.body ? JSON.parse(String(init.body)) : {};
        posts.push(body);
        if (callCount === 1) throw new TypeError("Failed to fetch");
        return jsonResponse({
          id: "mv-1", tenant_id: "t", farm_id: "farm-1", inventory_quantity_cohort_id: "cohort-1",
          movement_kind: "putaway", source_location_id: null, destination_location_id: "bin-1",
          moved_quantity_base: "10.000", effective_time: "2026-09-01T00:00:00Z",
          recorded_time: "2026-09-01T00:00:00Z", actor_user_id: "u1", client_command_id: "cc-1", note: null,
        }, 201);
      }
      if (url.includes("/inventory-not-put-away-queue")) return jsonResponse([QUEUE_ENTRY]);
      if (url.includes("/locations/tree")) return jsonResponse(BIN_TREE);
      return jsonResponse([]);
    }));
    render(withQueryClient(<StoreInventoryPutawayPage />));

    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Put away" }));
    await waitFor(() => expect(screen.getByText("Main Store / Bin 01")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm putaway/i }));

    // Unresolved-result state, never a definitive "failed" message -- shown
    // via the page-level recovery banner.
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(/result unknown/i);
    expect(screen.queryByText(/putaway failed/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /confirm putaway/i })).not.toBeInTheDocument();

    // The frozen submitted values are shown in the banner, not a live
    // editable field, and there is exactly one Retry -- never two.
    expect(screen.getByRole("alert")).toHaveTextContent(/Main Store \/ Bin 01/);
    expect(screen.getAllByRole("button", { name: "Retry" })).toHaveLength(1);
    expect(screen.queryByLabelText(/quantity/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1].client_command_id).toBe(posts[0].client_command_id);
    expect(posts[1]).toEqual(posts[0]);
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("PILOT-BLOCKER-010: an unresolved Putaway survives its row disappearing from a refetched queue -- recovery remains reachable with the exact same replay identity", async () => {
    const posts: Array<Record<string, unknown>> = [];
    let callCount = 0;
    let queueCallCount = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.includes("/inventory-putaways")) {
        callCount += 1;
        const body = init.body ? JSON.parse(String(init.body)) : {};
        posts.push(body);
        if (callCount === 1) throw new TypeError("Failed to fetch");
        return jsonResponse({
          id: "mv-1", tenant_id: "t", farm_id: "farm-1", inventory_quantity_cohort_id: "cohort-1",
          movement_kind: "putaway", source_location_id: null, destination_location_id: "bin-1",
          moved_quantity_base: "10.000", effective_time: "2026-09-01T00:00:00Z",
          recorded_time: "2026-09-01T00:00:00Z", actor_user_id: "u1", client_command_id: "cc-1", note: null,
        }, 201);
      }
      if (url.includes("/inventory-not-put-away-queue")) {
        queueCallCount += 1;
        // The row disappears from the queue entirely on the next fetch --
        // as if someone else already put it away, or it simply fell out of
        // the company-wide "not put away" set -- while the command is still
        // unresolved.
        return jsonResponse(queueCallCount === 1 ? [QUEUE_ENTRY] : []);
      }
      if (url.includes("/locations/tree")) return jsonResponse(BIN_TREE);
      return jsonResponse([]);
    }));
    const { queryClient } = renderWithClient(<StoreInventoryPutawayPage />);

    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Put away" }));
    await waitFor(() => expect(screen.getByText("Main Store / Bin 01")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm putaway/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    // Force the queue refetch that drops the row.
    await queryClient.refetchQueries({ queryKey: queryKeys.notPutAwayQueue(TEST_TENANT_ID) });
    await waitFor(() => expect(screen.queryByText("Calcium Nitrate")).not.toBeInTheDocument());

    // The frozen command must still be visible/recoverable via the banner.
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/result unknown/i);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1].client_command_id).toBe(posts[0].client_command_id);
    expect(posts[1]).toEqual(posts[0]);
  });

  // --- PILOT-BLOCKER-009 R2 (row-specific continuation) -------------------

  it("carries a valid incoming cohort id by auto-expanding the matching row, never submitting a Putaway automatically", async () => {
    searchParamsValue = new URLSearchParams({ cohortId: "cohort-1" });
    stubFetch();
    render(withQueryClient(<StoreInventoryPutawayPage />));
    await waitFor(() => expect(screen.getByText("Main Store / Bin 01")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /confirm putaway/i })).toBeInTheDocument();
    expect(screen.queryByText(/no longer in the current work queue/i)).not.toBeInTheDocument();
  });

  it("an invalid/stale incoming cohort id expands nothing and shows a concise message instead", async () => {
    searchParamsValue = new URLSearchParams({ cohortId: "cohort-does-not-exist" });
    stubFetch();
    render(withQueryClient(<StoreInventoryPutawayPage />));
    await waitFor(() =>
      expect(screen.getByText(/that putaway item is no longer in the current work queue/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/main store \/ bin 01/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Put away" })).toBeInTheDocument();
  });
});
