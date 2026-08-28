import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import ColdStoragePage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1" }),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const CROP_LETTUCE = { id: "crop-1", code: "LET", common_name: "Lettuce" };
const FG_LOT = {
  id: "fg-1", tenant_id: "t", farm_id: "farm-1", code: "FG-001", crop: CROP_LETTUCE, variety: null,
  packing_event_id: "pe-1", source_graded_produce_lot_ids: ["gpl-1"], net_packed_weight_kg: "100.000",
  package_count: 10, effective_time: "2026-01-10T08:00:00Z", recorded_time: "2026-01-10T08:05:00Z",
};
const PLACEMENT_UNPLACED = {
  finished_goods_lot_id: "fg-1", finished_goods_lot_code: "FG-001", available_weight_kg: "100.000",
  available_package_count: 10, total_placed_weight_kg: "0", total_placed_package_count: 0,
  unplaced_weight_kg: "100.000", unplaced_package_count: 10, locations: [],
};
const LOCATIONS_TREE = [
  { id: "loc-1", code: "COLD-1", name: "Cold Store 1", location_type_id: "lt-1", status: "active", occupiable: true, capacity: null, children: [] },
];
const MOVEMENT_RESULT = {
  id: "mv-1", tenant_id: "t", farm_id: "farm-1", finished_goods_lot_id: "fg-1", movement_kind: "place",
  source_location_id: null, destination_location_id: "loc-1", moved_weight_kg: "100.000", moved_package_count: 10,
  effective_time: "2026-01-10T09:00:00Z", recorded_time: "2026-01-10T09:00:00Z", actor_user_id: "user-1",
  client_command_id: "cmd-1", note: null,
};

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.includes("/finished-goods-storage-movements") && method === "POST") {
        if (overrides.recordError) return jsonResponse({ detail: "conflict" }, 409);
        return jsonResponse(overrides.movementResult ?? MOVEMENT_RESULT, 201);
      }
      if (url.includes("/storage-movements")) {
        return jsonResponse(overrides.movements ?? []);
      }
      if (url.includes("/placements")) {
        return jsonResponse(overrides.placement ?? PLACEMENT_UNPLACED);
      }
      if (url.includes("/locations/tree")) {
        return jsonResponse(LOCATIONS_TREE);
      }
      if (url.includes("/finished-goods-lots")) {
        return jsonResponse(overrides.lots ?? [FG_LOT]);
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ColdStoragePage", () => {
  it("places a Finished Goods Lot into Cold Storage end to end", async () => {
    stubFetch();
    render(withQueryClient(<ColdStoragePage />));

    await waitFor(() => expect(screen.getByLabelText(/finished goods lot/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/finished goods lot/i));
    await waitFor(() => expect(screen.getByText("FG-001")).toBeInTheDocument());
    fireEvent.click(screen.getByText("FG-001"));

    await waitFor(() => expect(screen.getByRole("heading", { name: /cold storage — fg-001/i })).toBeInTheDocument());
    await waitFor(() => expect(screen.getByLabelText(/destination location/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/destination location/i), { target: { value: "loc-1" } });
    fireEvent.change(screen.getByLabelText(/^weight/i), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText(/package count/i), { target: { value: "10" } });

    fireEvent.click(screen.getByRole("button", { name: /record movement/i }));

    await waitFor(() => expect(screen.getByText("Movement recorded")).toBeInTheDocument());
  });

  it("shows Release/Transfer's source location field only for their own movement kinds", async () => {
    stubFetch();
    render(withQueryClient(<ColdStoragePage />));

    await waitFor(() => expect(screen.getByLabelText(/finished goods lot/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/finished goods lot/i));
    await waitFor(() => expect(screen.getByText("FG-001")).toBeInTheDocument());
    fireEvent.click(screen.getByText("FG-001"));
    await waitFor(() => expect(screen.getByLabelText(/movement/i)).toBeInTheDocument());

    expect(screen.queryByLabelText(/source location/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/destination location/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/movement/i), { target: { value: "release" } });
    expect(screen.getByLabelText(/source location/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/destination location/i)).not.toBeInTheDocument();
  });
});
