import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import DispatchPage from "./page";

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

function dispatchEventResult(overrides: Record<string, unknown> = {}) {
  return {
    id: "disp-1", tenant_id: "t", farm_id: "farm-1", code: "DISP-001",
    lines: [{ id: "dl-1", finished_goods_lot_id: "fg-1", finished_goods_lot_code: "FG-001", dispatched_weight_kg: "100.000", dispatched_package_count: 10, ledger_entry_id: "le-1" }],
    total_dispatched_weight_kg: "100.000", total_dispatched_package_count: 10,
    effective_time: "2026-01-10T09:00:00Z", recorded_time: "2026-01-10T09:00:00Z", actor_user_id: "user-1",
    client_command_id: "cmd-1", external_reference: null, note: null, dispatch_temperature_c: "-18.5",
    ...overrides,
  };
}

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.includes("/dispatches") && method === "POST") {
        if (overrides.recordError) return jsonResponse({ detail: "conflict" }, 409);
        return jsonResponse(overrides.dispatchResult ?? dispatchEventResult(), 201);
      }
      if (url.includes("/dispatches")) {
        return jsonResponse(overrides.events ?? []);
      }
      if (url.includes("/placements")) {
        return jsonResponse(overrides.placement ?? PLACEMENT_UNPLACED);
      }
      if (url.includes("/recall-cases")) {
        return jsonResponse([]);
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

describe("DispatchPage", () => {
  it("records a Dispatch with a required temperature reading end to end", async () => {
    stubFetch();
    render(withQueryClient(<DispatchPage />));

    await waitFor(() => expect(screen.getByText("FG-001")).toBeInTheDocument());
    const row = screen.getByText("FG-001").closest("li") as HTMLElement;
    await waitFor(() => expect(within(row).getByRole("button", { name: /add to dispatch/i })).toBeEnabled());
    fireEvent.click(within(row).getByRole("button", { name: /add to dispatch/i }));

    await waitFor(() => expect(screen.getByText(/Dispatch FG-001/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByLabelText(/dispatched weight/i)).toHaveValue(100));

    fireEvent.change(screen.getByLabelText(/dispatch code/i), { target: { value: "DISP-001" } });
    fireEvent.change(screen.getByLabelText(/dispatch temperature/i), { target: { value: "-18.5" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText("Review before recording")).toBeInTheDocument());
    expect(screen.getByText(/Dispatch temperature: -18.5/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(screen.getByText("Dispatch recorded")).toBeInTheDocument());
  });

  it("blocks Review when the dispatch temperature field is left at an invalid value", async () => {
    stubFetch();
    render(withQueryClient(<DispatchPage />));

    await waitFor(() => expect(screen.getByText("FG-001")).toBeInTheDocument());
    const row = screen.getByText("FG-001").closest("li") as HTMLElement;
    await waitFor(() => expect(within(row).getByRole("button", { name: /add to dispatch/i })).toBeEnabled());
    fireEvent.click(within(row).getByRole("button", { name: /add to dispatch/i }));

    await waitFor(() => expect(screen.getByText(/Dispatch FG-001/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/dispatch code/i), { target: { value: "DISP-001" } });
    fireEvent.change(screen.getByLabelText(/dispatch temperature/i), { target: { value: "999" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(screen.getByText(/outside the supported range/i)).toBeInTheDocument());
    expect(screen.queryByText("Review before recording")).not.toBeInTheDocument();
  });
});
