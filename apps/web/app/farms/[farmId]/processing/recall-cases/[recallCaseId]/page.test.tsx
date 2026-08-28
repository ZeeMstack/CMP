import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import RecallCaseDetailPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ farmId: "farm-1", recallCaseId: "rc-1" }),
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const FG_LOT = {
  id: "fg-1", tenant_id: "t", farm_id: "farm-1", code: "FG-001", crop: { id: "crop-1", code: "LET", common_name: "Lettuce" },
  variety: null, packing_event_id: "pe-1", source_graded_produce_lot_ids: ["gpl-1"], net_packed_weight_kg: "100.000",
  package_count: 10, effective_time: "2026-01-10T08:00:00Z", recorded_time: "2026-01-10T08:05:00Z",
};

function recallCaseDetail(overrides: Record<string, unknown> = {}) {
  return {
    recall_case_id: "rc-1", code: "RC-001", crop_batch_id: null, harvested_produce_lot_id: null,
    graded_produce_lot_id: null, finished_goods_lot_id: "fg-1", reason_code: "contamination",
    reason_text: "suspected contamination", effective_time: "2026-01-10T09:00:00Z",
    recorded_time: "2026-01-10T09:00:00Z", actor_user_id: "user-1", is_open: true, closure: null,
    frozen_scope: {
      crop_batch_ids: [], harvested_produce_lot_ids: [], graded_produce_lot_ids: [], finished_goods_lot_ids: ["fg-1"],
    },
    live_state: { finished_goods_lots: [], storage: [], dispatches: [] },
    ...overrides,
  };
}

function stubFetch(overrides: Record<string, unknown> = {}) {
  let current = (overrides.detail as ReturnType<typeof recallCaseDetail>) ?? recallCaseDetail();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.includes("/recall-cases/rc-1/close") && method === "POST") {
        current = recallCaseDetail({
          is_open: false,
          closure: { id: "cl-1", effective_time: "2026-01-11T09:00:00Z", recorded_time: "2026-01-11T09:00:00Z", actor_user_id: "user-1", close_reason: "resolved" },
        });
        return jsonResponse(current);
      }
      if (url.includes("/recall-cases/rc-1")) {
        return jsonResponse(current);
      }
      if (url.includes("/finished-goods-lots")) {
        return jsonResponse([FG_LOT]);
      }
      if (url.includes("/locations/tree")) {
        return jsonResponse([]);
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RecallCaseDetailPage", () => {
  it("closes an open Recall Case", async () => {
    stubFetch();
    render(withQueryClient(<RecallCaseDetailPage />));

    await waitFor(() => expect(screen.getByText("Open")).toBeInTheDocument());

    // UI-OPT-001: raw JSON is gone -- both scope sections render real
    // structured facts, and the Finished Goods Lot scope id resolves to its
    // real code rather than showing the raw uuid.
    expect(document.querySelector("pre")).not.toBeInTheDocument();
    expect(screen.getByText("Contained at time of opening")).toBeInTheDocument();
    expect(screen.getByText("Currently affected")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("FG-001").length).toBeGreaterThan(0));

    fireEvent.change(screen.getByLabelText(/close reason/i), { target: { value: "resolved" } });
    fireEvent.click(screen.getByRole("button", { name: /^close recall case$/i }));

    await waitFor(() => expect(screen.getByText("Closed")).toBeInTheDocument());
  });

  it("hides the close form for an already-closed Recall Case", async () => {
    stubFetch({
      detail: recallCaseDetail({
        is_open: false,
        closure: { id: "cl-1", effective_time: "2026-01-11T09:00:00Z", recorded_time: "2026-01-11T09:00:00Z", actor_user_id: "user-1", close_reason: "resolved" },
      }),
    });
    render(withQueryClient(<RecallCaseDetailPage />));

    await waitFor(() => expect(screen.getByText("Closed")).toBeInTheDocument());
    expect(screen.queryByLabelText(/close reason/i)).not.toBeInTheDocument();
  });
});
