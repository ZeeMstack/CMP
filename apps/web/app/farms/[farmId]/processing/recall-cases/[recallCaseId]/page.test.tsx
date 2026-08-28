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

function recallCaseDetail(overrides: Record<string, unknown> = {}) {
  return {
    recall_case_id: "rc-1", code: "RC-001", crop_batch_id: null, harvested_produce_lot_id: null,
    graded_produce_lot_id: null, finished_goods_lot_id: "fg-1", reason_code: "contamination",
    reason_text: "suspected contamination", effective_time: "2026-01-10T09:00:00Z",
    recorded_time: "2026-01-10T09:00:00Z", actor_user_id: "user-1", is_open: true, closure: null,
    frozen_scope: { finished_goods_lots: ["fg-1"] }, live_state: { finished_goods_lots: ["fg-1"] },
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
