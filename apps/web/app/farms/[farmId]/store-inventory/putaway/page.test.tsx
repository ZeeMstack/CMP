import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

import { withQueryClient } from "@/lib/test-utils";

import StoreInventoryPutawayPage from "./page";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
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

  it("A3: a network failure on Confirm shows an unresolved-result state (not 'Putaway failed'), and Retry resends the exact frozen payload", async () => {
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

    // Unresolved-result state, never a definitive "failed" message.
    await waitFor(() => expect(screen.getByText(/result not confirmed/i)).toBeInTheDocument());
    expect(screen.queryByText(/putaway failed/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /confirm putaway/i })).not.toBeInTheDocument();

    // The frozen submitted values are displayed (not a live editable
    // field), and Cancel is disabled for the whole uncertain state.
    expect(screen.getByText("Main Store / Bin 01")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.queryByLabelText(/quantity/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1].client_command_id).toBe(posts[0].client_command_id);
    expect(posts[1]).toEqual(posts[0]);
  });
});
