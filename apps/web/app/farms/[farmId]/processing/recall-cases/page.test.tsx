import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { withQueryClient } from "@/lib/test-utils";

import RecallCasesPage from "./page";

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

function recallCaseDetail(overrides: Record<string, unknown> = {}) {
  return {
    recall_case_id: "rc-1", code: "RC-001", crop_batch_id: null, harvested_produce_lot_id: null,
    graded_produce_lot_id: null, finished_goods_lot_id: "fg-1", reason_code: "contamination",
    reason_text: "suspected contamination", effective_time: "2026-01-10T09:00:00Z",
    recorded_time: "2026-01-10T09:00:00Z", actor_user_id: "user-1", is_open: true, closure: null,
    frozen_scope: {}, live_state: {},
    ...overrides,
  };
}

function stubFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";

      if (url.includes("/recall-cases") && method === "POST") {
        if (overrides.openError) return jsonResponse({ detail: "conflict" }, 409);
        return jsonResponse(overrides.openResult ?? recallCaseDetail(), 201);
      }
      if (url.includes("/recall-cases")) {
        return jsonResponse(overrides.cases ?? []);
      }
      if (url.includes("/finished-goods-lots")) {
        return jsonResponse(overrides.lots ?? [FG_LOT]);
      }
      if (url.includes("/graded-produce-lots")) {
        return jsonResponse([]);
      }
      if (url.includes("/harvested-produce-lots")) {
        return jsonResponse([]);
      }
      return jsonResponse([]);
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RecallCasesPage", () => {
  it("opens a Recall Case against a Finished Goods Lot end to end", async () => {
    stubFetch();
    render(withQueryClient(<RecallCasesPage />));

    fireEvent.click(screen.getByRole("button", { name: /open recall case/i }));
    await waitFor(() => expect(screen.getByLabelText(/recall code/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/recall code/i), { target: { value: "RC-001" } });
    await waitFor(() => expect(screen.getByLabelText(/finished goods lot$/i)).toBeInTheDocument());
    fireEvent.focus(screen.getByLabelText(/finished goods lot$/i));
    await waitFor(() => expect(screen.getByText("FG-001")).toBeInTheDocument());
    fireEvent.click(screen.getByText("FG-001"));

    fireEvent.change(screen.getByLabelText(/reason code/i), { target: { value: "contamination" } });
    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "suspected contamination" } });

    fireEvent.click(screen.getByRole("button", { name: /^open recall case$/i, hidden: false }));

    await waitFor(() => expect(screen.queryByLabelText(/recall code/i)).not.toBeInTheDocument());
  });

  it("shows an empty state when no Recall Case exists yet", async () => {
    stubFetch();
    render(withQueryClient(<RecallCasesPage />));
    await waitFor(() => expect(screen.getByText(/no recall cases yet/i)).toBeInTheDocument());
  });

  it("lists an existing Recall Case with its open/closed status", async () => {
    stubFetch({ cases: [{ recall_case_id: "rc-1", code: "RC-001", crop_batch_id: null, harvested_produce_lot_id: null, graded_produce_lot_id: null, finished_goods_lot_id: "fg-1", reason_code: "contamination", reason_text: "suspected contamination", effective_time: "2026-01-10T09:00:00Z", is_open: true }] });
    render(withQueryClient(<RecallCasesPage />));
    await waitFor(() => expect(screen.getByText("RC-001")).toBeInTheDocument());
    expect(screen.getByText("Open")).toBeInTheDocument();
  });
});
