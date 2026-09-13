import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

type PostHandler = (url: string, body: Record<string, unknown>) => Response;

function stubFetch(
  opts: { provenance?: unknown[]; cohortBuckets?: unknown[]; postHandler?: PostHandler } = {},
) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      const body = init.body ? JSON.parse(String(init.body)) : {};
      if (opts.postHandler) return opts.postHandler(url, body);
      return jsonResponse({});
    }
    if (url.includes("/inventory-items?") || url.endsWith("/inventory-items")) return jsonResponse([ITEM]);
    if (url.endsWith("/existence")) return jsonResponse({ inventory_item_id: "item-1", existing_quantity: "500.000" });
    if (url.endsWith("/usable-existence")) return jsonResponse({ inventory_item_id: "item-1", usable_quantity: "450.000" });
    if (url.endsWith("/provenance")) return jsonResponse(opts.provenance ?? []);
    if (url.includes("/availability")) {
      return jsonResponse({
        inventory_item_id: "item-1", farm_id: "farm-1", in_store_quantity: "400.000", reserved_quantity: "70.000",
        issued_to_operations_quantity: "30.000", available_to_issue_quantity: "330.000",
      });
    }
    if (url.includes("/inventory-quantity-cohorts/") && url.includes("/storage-breakdown")) {
      return jsonResponse({ inventory_quantity_cohort_id: "cohort-1", buckets: opts.cohortBuckets ?? [] });
    }
    if (url.includes("/storage-breakdown")) {
      return jsonResponse({ inventory_item_id: "item-1", not_put_away_quantity: "120.000", bins: [] });
    }
    if (url.includes("/locations/tree")) return jsonResponse([]);
    if (url.endsWith("/uoms")) return jsonResponse([{ id: "uom-1", code: "kg", name: "Kilogram", quantity_kind: "mass", conversion_family: "mass" }]);
    return jsonResponse([]);
  });
  vi.stubGlobal("fetch", fetchMock);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StoreInventoryInventoryPage", () => {
  it("shows Available to issue / In store / Reserved by default (this Farm), never labeled just Available", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryInventoryPage />));
    await waitFor(() => expect(screen.getAllByText("Calcium Nitrate")[0]).toBeInTheDocument());
    expect(screen.getByText("Available to issue")).toBeInTheDocument();
    expect(screen.getByText("In store")).toBeInTheDocument();
    expect(screen.getByText("Reserved")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("330.000 kg")).toBeInTheDocument());
    expect(screen.getByText("400.000 kg")).toBeInTheDocument();
    expect(screen.getByText("70.000 kg")).toBeInTheDocument();
    expect(screen.queryByText(/^available$/i)).not.toBeInTheDocument();
  });

  it("keeps company-wide Exists/Usable in a separate, collapsed-by-default section", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryInventoryPage />));
    await waitFor(() => expect(screen.getAllByText("Calcium Nitrate")[0]).toBeInTheDocument());

    // Not fetched/shown until the operator opens the section.
    expect(screen.queryByText("500.000 kg")).not.toBeInTheDocument();
    expect(screen.queryByText("450.000 kg")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Company-wide totals \(all Farms\)/ }));
    await waitFor(() => expect(screen.getByText("500.000 kg")).toBeInTheDocument());
    expect(screen.getByText("450.000 kg")).toBeInTheDocument();
  });

  it("shows Issued to operations / Not put away only inside the selected-stock detail panel", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryInventoryPage />));
    await waitFor(() => expect(screen.getAllByText("Calcium Nitrate")[0]).toBeInTheDocument());

    expect(screen.queryByText(/not put away/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show detail" }));

    await waitFor(() => expect(screen.getByText(/Issued to operations \(this Farm\)/)).toBeInTheDocument());
    expect(screen.getByText(/Not put away \(company-wide\)/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("120.000 kg")).toBeInTheDocument());
  });

  it("records a compact Scrap against a Store Bin bucket", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    stubFetch({
      provenance: [{ inventory_quantity_cohort_id: "cohort-1", balance: "20.000", received_at_farm_id: "farm-1" }],
      cohortBuckets: [{ location_id: "bin-1", label: "Bin 01", balance: "20.000" }],
      postHandler: (url, body) => {
        if (url.includes("/inventory-scraps")) {
          capturedBody = body;
          return jsonResponse({
            id: "evt-1", event_kind: "scrap", source_kind: "store_bin", issue_line_id: null,
            inventory_quantity_cohort_id: "cohort-1", source_location_id: "bin-1", destination_location_id: null,
            quantity_base: body.quantity, reason: body.reason, effective_time: "2026-09-01T00:00:00Z",
            recorded_time: "2026-09-01T00:00:00Z", actor_user_id: "u1",
          }, 201);
        }
        return jsonResponse({});
      },
    });
    render(withQueryClient(<StoreInventoryInventoryPage />));
    await waitFor(() => expect(screen.getAllByText("Calcium Nitrate")[0]).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Show detail" }));
    await waitFor(() => expect(screen.getByText(/Bin 01/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Scrap" }));
    await waitFor(() => expect(screen.getByPlaceholderText(/damaged packaging/i)).toBeInTheDocument());

    fireEvent.change(screen.getAllByRole("spinbutton")[0], { target: { value: "2" } });
    fireEvent.change(screen.getByPlaceholderText(/damaged packaging/i), { target: { value: "torn bag" } });
    fireEvent.click(screen.getByRole("button", { name: /record scrap/i }));

    await waitFor(() => expect(capturedBody).not.toBeNull());
    expect(capturedBody).toMatchObject({
      source_kind: "store_bin", inventory_quantity_cohort_id: "cohort-1", source_location_id: "bin-1",
      quantity: "2", reason: "torn bag",
    });
  });

  it("PILOT-BLOCKER-008 A5: a network failure on Confirm move shows an unresolved-result state, and Retry resends the exact frozen payload", async () => {
    const posts: Array<Record<string, unknown>> = [];
    let callCount = 0;
    const locationsTree = [
      {
        id: "store-1", code: "MAIN-STORE", name: "Main Store", location_type_id: "lt-store",
        location_type_code: "store", status: "active", occupiable: false, capacity: null,
        children: [
          { id: "bin-1", code: "BIN-01", name: "Bin 01", location_type_id: "lt-bin", location_type_code: "store_bin", status: "active", occupiable: false, capacity: null, children: [] },
          { id: "bin-2", code: "BIN-02", name: "Bin 02", location_type_id: "lt-bin", location_type_code: "store_bin", status: "active", occupiable: false, capacity: null, children: [] },
        ],
      },
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST" && url.includes("/inventory-storage-transfers")) {
        callCount += 1;
        const body = init.body ? JSON.parse(String(init.body)) : {};
        posts.push(body);
        if (callCount === 1) throw new TypeError("Failed to fetch");
        return jsonResponse({
          id: "mv-1", tenant_id: "t", farm_id: "farm-1", inventory_quantity_cohort_id: "cohort-1",
          movement_kind: "transfer", source_location_id: "bin-1", destination_location_id: "bin-2",
          moved_quantity_base: "2.000", effective_time: "2026-09-01T00:00:00Z",
          recorded_time: "2026-09-01T00:00:00Z", actor_user_id: "u1", client_command_id: "cc-1", note: null,
        }, 201);
      }
      if (url.includes("/inventory-items?") || url.endsWith("/inventory-items")) return jsonResponse([ITEM]);
      if (url.endsWith("/existence")) return jsonResponse({ inventory_item_id: "item-1", existing_quantity: "500.000" });
      if (url.endsWith("/usable-existence")) return jsonResponse({ inventory_item_id: "item-1", usable_quantity: "450.000" });
      if (url.endsWith("/provenance")) {
        return jsonResponse([{ inventory_quantity_cohort_id: "cohort-1", balance: "20.000", received_at_farm_id: "farm-1" }]);
      }
      if (url.includes("/availability")) {
        return jsonResponse({
          inventory_item_id: "item-1", farm_id: "farm-1", in_store_quantity: "400.000", reserved_quantity: "70.000",
          issued_to_operations_quantity: "30.000", available_to_issue_quantity: "330.000",
        });
      }
      if (url.includes("/inventory-quantity-cohorts/") && url.includes("/storage-breakdown")) {
        return jsonResponse({ inventory_quantity_cohort_id: "cohort-1", buckets: [{ location_id: "bin-1", label: "Bin 01", balance: "20.000" }] });
      }
      if (url.includes("/storage-breakdown")) {
        return jsonResponse({ inventory_item_id: "item-1", not_put_away_quantity: "0.000", bins: [] });
      }
      if (url.includes("/locations/tree")) return jsonResponse(locationsTree);
      if (url.endsWith("/uoms")) return jsonResponse([{ id: "uom-1", code: "kg", name: "Kilogram", quantity_kind: "mass", conversion_family: "mass" }]);
      return jsonResponse([]);
    }));

    render(withQueryClient(<StoreInventoryInventoryPage />));
    await waitFor(() => expect(screen.getAllByText("Calcium Nitrate")[0]).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Show detail" }));
    await waitFor(() => expect(screen.getByText(/Bin 01/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Move stock" }));
    await waitFor(() => expect(screen.getByText(/Main Store \/ Bin 02/)).toBeInTheDocument());
    fireEvent.change(screen.getAllByRole("spinbutton")[0], { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm move/i }));

    await waitFor(() => expect(screen.getByText(/result not confirmed/i)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /confirm move/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    // Frozen submitted values are displayed, not live editable controls.
    expect(screen.getByText("Bin 01")).toBeInTheDocument();
    expect(screen.getByText(/Main Store \/ Bin 02/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1].client_command_id).toBe(posts[0].client_command_id);
    expect(posts[1]).toEqual(posts[0]);
  });

  it("PILOT-UX-003: a failed Farm-availability read shows Unavailable, never a fabricated zero", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/inventory-items?") || url.endsWith("/inventory-items")) return jsonResponse([ITEM]);
        if (url.includes("/availability")) return jsonResponse({ detail: "server_error" }, 500);
        if (url.endsWith("/uoms")) return jsonResponse([{ id: "uom-1", code: "kg", name: "Kilogram", quantity_kind: "mass", conversion_family: "mass" }]);
        return jsonResponse([]);
      }),
    );
    render(withQueryClient(<StoreInventoryInventoryPage />));
    await waitFor(() => expect(screen.getAllByText("Calcium Nitrate")[0]).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0));
    expect(screen.queryByText("0 kg")).not.toBeInTheDocument();
  });

  it("PILOT-UX-003: cohort/bin detail is only requested for the selected Item, not eagerly for the whole list", async () => {
    let provenanceCalls = 0;
    stubFetch();
    const baseFetch = (global.fetch as unknown) as typeof fetch;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/provenance")) provenanceCalls += 1;
        return baseFetch(input, init);
      }),
    );
    render(withQueryClient(<StoreInventoryInventoryPage />));
    await waitFor(() => expect(screen.getAllByText("Calcium Nitrate")[0]).toBeInTheDocument());
    expect(provenanceCalls).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: "Show detail" }));
    await waitFor(() => expect(provenanceCalls).toBeGreaterThan(0));
  });
});
