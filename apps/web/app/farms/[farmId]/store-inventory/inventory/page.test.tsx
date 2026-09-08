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
  it("shows Exists, Usable, and Available to issue quantities, never labeled just Available", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryInventoryPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());
    expect(screen.getByText("500.000 kg")).toBeInTheDocument();
    expect(screen.getByText("450.000 kg")).toBeInTheDocument();
    expect(screen.getByText("Available to issue")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("330.000 kg")).toBeInTheDocument());
    expect(screen.queryByText(/^available$/i)).not.toBeInTheDocument();
  });

  it("shows In Store / Reserved / Issued to operations / Not put away only inside expanded detail", async () => {
    stubFetch();
    render(withQueryClient(<StoreInventoryInventoryPage />));
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());

    expect(screen.queryByText(/not put away/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show detail" }));

    await waitFor(() => expect(screen.getByText(/In Store \(this Farm\)/)).toBeInTheDocument());
    expect(screen.getByText(/Reserved \(this Farm\)/)).toBeInTheDocument();
    expect(screen.getByText(/Issued to operations \(this Farm\)/)).toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByText("Calcium Nitrate")).toBeInTheDocument());

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
});
